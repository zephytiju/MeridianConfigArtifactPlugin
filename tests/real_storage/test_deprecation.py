# SPDX-License-Identifier: Apache-2.0
"""Deprecation and UTC compatibility through installed public dependencies."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from test_put_modes import deployed as deployed_fixture
from test_put_modes import scope

from meridian_storage import ErrorCategory, MeridianError
from meridian_storage.plugins.config_artifact import (
    InvalidRepositoryResult,
    ProvenanceV1,
    ResourceNotFound,
    ResourceState,
    ResourceStore,
)

deployed = deployed_fixture


def publish_profile(store, profile, name, **options):
    repository = getattr(store, profile)
    payload = b"immutable artifact"
    if profile == "configurations":
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
            "updatedAt": "2026-09-09T00:00:00.000000Z",
        }
        options["schema"] = "resources.resource-channel@1.0.0"
    return repository.publish(
        namespace="acceptance",
        kind="correction",
        name=name,
        version="1",
        payload=payload,
        actor="publisher",
        provenance=ProvenanceV1("builder", "1.0.0"),
        **options,
    ).resource


def provenance_rows(runtime, store, resource):
    return runtime.execute(
        runtime.catalog("structured").query(
            resource=store.metadata.provenance_resource.to_dict(),
            where={"resourceId": resource.resource_id},
            limit=10,
        )
    ).data["items"]


def abort_metadata_transaction(store, profile, original, name):
    with store.metadata.transaction():
        getattr(store, profile).deprecate(original.identity)
        # Configuration and provenance writes share the metadata Binding.
        # Object publication intentionally remains a two-Binding operation.
        publish_profile(store, "configurations", "rolled-back-" + name)
        raise RuntimeError("abort after metadata and provenance writes")


@pytest.mark.parametrize("profile", ["configurations", "artifacts"])
def test_deprecation_real_collection_and_stale_replay(deployed, profile):
    runtime, tenant = deployed
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        original = publish_profile(store, profile, uuid4().hex)
        history = provenance_rows(runtime, store, original)
        assert len(history) == 1
        deprecated = getattr(store, profile).deprecate(original.identity)
        assert deprecated == replace(original, state=ResourceState.DEPRECATED)
        assert deprecated.record_version != original.record_version
        assert getattr(store, profile).deprecate(original.identity) == deprecated
        with pytest.raises(MeridianError) as caught:
            store.metadata.deprecate_resource(original)
        assert caught.value.category is ErrorCategory.CONFLICT
        assert provenance_rows(runtime, store, original) == history
        if profile == "artifacts":
            assert store.artifacts.read(deprecated) == b"immutable artifact"


@pytest.mark.parametrize("profile", ["configurations", "artifacts"])
def test_whole_second_publication_and_legacy_read(deployed, profile):
    runtime, tenant = deployed
    with scope(runtime, tenant):
        store = ResourceStore(runtime, clock=lambda: datetime(2026, 9, 9, tzinfo=UTC))
        original = publish_profile(store, profile, uuid4().hex)
        assert original.created_at == "2026-09-09T00:00:00.000000Z"
        raw = runtime.execute(
            runtime.catalog("structured").get(
                resource=store.metadata.metadata_resource.to_dict(),
                where={"resourceId": original.resource_id},
            )
        ).data
        assert raw["createdAt"] == "2026-09-09T00:00:00Z"
        # The released adapter's whole-second rows are also the legacy-read fixture.
        fresh = ResourceStore(runtime)
        assert fresh.metadata.get_resource(original.resource_id) == original
        assert getattr(fresh, profile).deprecate(original.identity).digest == original.digest
        pointer = getattr(store, profile).promote(
            publish_profile(store, profile, uuid4().hex).ref,
            "active",
            expected_pointer_version=0,
            actor="publisher",
        )
        assert pointer.updated_at == original.created_at
        assert len(provenance_rows(runtime, store, original)) == 1
        if profile == "artifacts":
            assert fresh.artifacts.read(original) == b"immutable artifact"


@pytest.mark.parametrize("profile", ["configurations", "artifacts"])
def test_deprecation_concurrent_calls_are_idempotent(deployed, monkeypatch, profile):
    runtime, tenant = deployed
    with scope(runtime, tenant):
        original = publish_profile(ResourceStore(runtime), profile, uuid4().hex)
    barrier = Barrier(2)

    def contender(_index):
        with scope(runtime, tenant):
            store = ResourceStore(runtime)
            real_deprecate = store.metadata.deprecate_resource

            def synchronized(resource):
                barrier.wait(timeout=15)
                return real_deprecate(resource)

            monkeypatch.setattr(store.metadata, "deprecate_resource", synchronized)
            return getattr(store, profile).deprecate(original.identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(contender, (0, 1))
    assert first == second == replace(original, state=ResourceState.DEPRECATED)
    assert first.record_version == second.record_version
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        assert store.metadata.get_resource(original.resource_id) == first
        assert len(provenance_rows(runtime, store, original)) == 1


@pytest.mark.parametrize("profile", ["configurations", "artifacts"])
@pytest.mark.parametrize("corruption", ["empty", "multiple", "malformed", "mismatch"])
def test_invalid_patch_result_rolls_back_real_transaction(
    deployed, monkeypatch, profile, corruption
):
    runtime, tenant = deployed
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        original = publish_profile(store, profile, uuid4().hex)
        unrelated = publish_profile(store, profile, uuid4().hex)
        before = provenance_rows(runtime, store, original)
        real_execute = runtime.execute

        def corrupted(expression):
            result = real_execute(expression)
            if expression.catalog == "structured" and expression.method == "patch":
                outcomes = {
                    "empty": [],
                    "multiple": [*result.data, *result.data],
                    "malformed": [None],
                    "mismatch": [{**unrelated.to_record(), "recordVersion": 2}],
                }
                return replace(result, data=outcomes[corruption])
            return result

        with monkeypatch.context() as patch:
            patch.setattr(runtime, "execute", corrupted)
            with pytest.raises(InvalidRepositoryResult):
                getattr(store, profile).deprecate(original.identity)
        observed = store.metadata.get_resource(original.resource_id)
        assert observed == original
        assert observed.record_version == original.record_version
        assert store.metadata.get_resource(unrelated.resource_id) == unrelated
        assert provenance_rows(runtime, store, original) == before


@pytest.mark.parametrize("profile", ["configurations", "artifacts"])
def test_deprecation_scope_and_outer_transaction_rollback(deployed, profile):
    runtime, tenant = deployed
    name = uuid4().hex
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        original = publish_profile(store, profile, name)
    with scope(runtime, "other-" + tenant):
        store = ResourceStore(runtime)
        with pytest.raises(ResourceNotFound):
            getattr(store, profile).deprecate(original.identity)
        other = publish_profile(store, profile, name)
    with scope(runtime, tenant):
        store = ResourceStore(runtime)
        history = provenance_rows(runtime, store, original)
        with pytest.raises(RuntimeError, match="abort"):
            abort_metadata_transaction(store, profile, original, name)
        observed = store.metadata.get_resource(original.resource_id)
        assert observed == original
        assert observed.record_version == original.record_version
        assert provenance_rows(runtime, store, original) == history
        assert not store.metadata.list_resources(name="rolled-back-" + name).items
        getattr(store, profile).deprecate(original.identity)
    with scope(runtime, "other-" + tenant):
        observed = ResourceStore(runtime).metadata.get_resource(other.resource_id)
        assert observed == other
        assert observed.record_version == other.record_version
