# SPDX-License-Identifier: Apache-2.0
"""Mode migration acceptance through released Core, PostgreSQL and Object packages."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from deployment import compose

from meridian_storage import ErrorCategory, MeridianError, OperationContext
from meridian_storage.plugins.config_artifact import (
    IdentityConflict,
    IncompletePublication,
    ProvenanceV1,
    ResourceStore,
    StaleChannelPointer,
    default_payload_registry,
)


@contextmanager
def scope(runtime, tenant):
    with runtime.context(
        OperationContext(
            tenant=tenant,
            principal_ref="publisher",
            request_id=uuid4().hex,
            scope={"tenant": tenant, "application": "artifact-acceptance"},
        )
    ):
        yield


@pytest.fixture(params=["s3", "oci"])
def deployed(request):
    runtime = compose(backend=request.param)
    try:
        yield runtime, "fixture-" + uuid4().hex
    finally:
        runtime.close()


def publish(store, name, version="1", **options):
    return store.artifacts.publish(
        namespace="acceptance",
        kind="manifest",
        name=name,
        version=version,
        payload=b"immutable artifact",
        actor="publisher",
        **options,
    ).resource


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("same_target", [True, False])
def test_channel_concurrent_initialization_and_cas(deployed, monkeypatch, initial, same_target):
    runtime, tenant = deployed
    name = uuid4().hex
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        first = publish(store, name)
        second = publish(store, name, "2")
        expected = 0
        if not initial:
            pointer = store.artifacts.promote(
                first.ref, "stable", expected_pointer_version=0, actor="p"
            )
            expected = pointer.pointer_version
    barrier = Barrier(2)

    def contender(target):
        with scope(runtime, tenant):
            own = ResourceStore(runtime)
            real_get = own.channels.get

            def synchronized_get(*args, **kwargs):
                observed = real_get(*args, **kwargs)
                barrier.wait(timeout=15)
                return observed

            monkeypatch.setattr(own.channels, "get", synchronized_get)
            try:
                return own.artifacts.promote(
                    target.ref, "stable", expected_pointer_version=expected, actor="p"
                )
            except StaleChannelPointer as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, (first, first if same_target else second)))
    winners = [r for r in results if not isinstance(r, StaleChannelPointer)]
    assert len(winners) == 1
    assert winners[0].pointer_version == expected + 1
    with scope(runtime, tenant):
        pointer = store.channels.get("acceptance", "manifest", name, "stable")
        assert pointer == winners[0]
        with pytest.raises(StaleChannelPointer):
            store.artifacts.promote(
                first.ref, "stable", expected_pointer_version=expected, actor="stale"
            )
        rows = runtime.execute(
            runtime.catalog("structured").query(
                resource=store.metadata.channel_resource.to_dict(),
                where={"name": name},
                limit=10,
            )
        ).data["items"]
        assert len(rows) == expected + 1


@pytest.mark.parametrize("same_payload", [True, False])
def test_concurrent_configuration_publication_preserves_winner(deployed, monkeypatch, same_payload):
    runtime, tenant = deployed
    name = uuid4().hex
    barrier = Barrier(2)
    # Use a released schema from the installed package as a typed configuration payload.
    payload = {
        "formatVersion": "fixture",
        "channelVersionId": "fixture",
        "namespace": "ns",
        "kind": "kind",
        "name": "name",
        "channel": "active",
        "targetResourceId": "target",
        "pointerVersion": 1,
        "actor": "publisher",
        "updatedAt": "2026-09-07T00:00:00.000000Z",
    }

    def contender(index):
        with scope(runtime, tenant):
            store = ResourceStore(runtime)
            real_put = store.metadata.put_resource

            def synchronized_put(resource):
                barrier.wait(timeout=15)
                return real_put(resource)

            monkeypatch.setattr(store.metadata, "put_resource", synchronized_put)
            try:
                return store.configurations.publish(
                    namespace="acceptance",
                    kind="configuration",
                    name=name,
                    version="1",
                    payload={**payload, "actor": "publisher" if same_payload else str(index)},
                    schema="resources.resource-channel@1.0.0",
                    actor="publisher",
                )
            except IdentityConflict as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, (0, 1)))
    receipts = [r for r in results if not isinstance(r, IdentityConflict)]
    assert len(receipts) == (2 if same_payload else 1)
    if same_payload:
        assert sorted(r.idempotent for r in receipts) == [False, True]
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        winner = receipts[0].resource
        assert store.metadata.get_resource(winner.resource_id) == winner
        # A distinct raw create must conflict even if every value is identical.
        with pytest.raises(MeridianError) as caught:
            store.metadata.put_resource(winner)
        assert caught.value.category is ErrorCategory.CONFLICT
        with pytest.raises(MeridianError):
            store.metadata.put_resource(replace(winner, labels={"attempt": "overwrite"}))
        assert store.metadata.get_resource(winner.resource_id) == winner


def test_provenance_publication_preserves_immutable_fields(deployed):
    runtime, tenant = deployed
    name = uuid4().hex
    with scope(runtime, tenant):
        clock = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
        store = ResourceStore(runtime, clock=lambda: clock)
        resource = publish(store, name, provenance=ProvenanceV1("builder", "1.0.0"))
        assert resource.created_at == "2026-01-02T03:04:05.123456Z"
        assert store.metadata.get_resource(resource.resource_id) == resource
        pointer = store.artifacts.promote(
            resource.ref, "stable", expected_pointer_version=0, actor="publisher"
        )
        assert pointer.updated_at == resource.created_at
        assert store.channels.get("acceptance", "manifest", name, "stable") == pointer
        assert store.artifacts.read(resource) == b"immutable artifact"
        assert publish(store, name, provenance=ProvenanceV1("builder", "1.0.0")) == resource


def test_scope_and_orphan_cleanup(deployed, monkeypatch):
    runtime, tenant = deployed
    registry = default_payload_registry()
    baseline = len(registry)
    name = uuid4().hex
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        resource = publish(store, name)
        real_put = store.metadata.put_resource

        def fail_metadata(_resource):
            raise RuntimeError("injected metadata failure after real Object commit")

        with monkeypatch.context() as patch:
            patch.setattr(store.metadata, "put_resource", fail_metadata)
            with pytest.raises(IncompletePublication):
                publish(store, name, "failed")
        orphans = store.metadata.list_orphans().items
        assert len(orphans) == 1
        orphan = orphans[0]
        assert store.metadata.put_orphan(orphan) == orphan
        with pytest.raises(IdentityConflict):
            store.metadata.put_orphan(replace(orphan, byte_length=orphan.byte_length + 1))
        assert store.metadata.put_resource == real_put
        recovered = publish(store, name, "failed")
        assert store.artifacts.read(recovered) == b"immutable artifact"
        assert len(registry) == baseline
    with scope(runtime, "other-" + tenant):
        assert (
            ResourceStore(runtime).metadata.get_resource(resource.resource_id, required=False)
            is None
        )
