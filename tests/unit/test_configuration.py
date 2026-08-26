# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from meridian_storage.object_common import ConditionalConflict
from meridian_storage.plugins.config_artifact import (
    ForbiddenDeletion,
    IdentityConflict,
    InvalidPayload,
    ProvenanceV1,
    ResourceIdentity,
    ResourceNotFound,
    ResourceProfile,
    ResourceState,
    SchemaUnavailable,
    StaleChannelPointer,
)


def test_publish_exact_latest_channel_and_idempotency(store, schema_ref, valid_config) -> None:
    receipt = store.publisher.publish_configuration(
        namespace="payments",
        kind="service",
        name="checkout",
        version="2026.01",
        payload=valid_config,
        schema=schema_ref,
        actor="builder@example.com",
        version_order=1,
        channel="stable",
        expected_pointer_version=0,
    )
    assert receipt.resource.profile is ResourceProfile.CONFIGURATION
    assert receipt.resource.state is ResourceState.PUBLISHED
    assert receipt.resource.object_ref is None
    assert receipt.channel is not None
    assert receipt.channel.pointer_version == 1
    assert not receipt.idempotent

    identity = receipt.resource.identity
    assert receipt.ref == receipt.resource.ref
    assert store.consumer.configurations.exact(identity).resource == receipt.resource
    assert (
        store.consumer.configurations.latest("payments", "service", "checkout").resource
        == receipt.resource
    )
    resolved = store.consumer.configurations.channel("payments", "service", "checkout", "stable")
    assert resolved.pointer_version == 1
    assert store.consumer.configurations.payload(resolved) == valid_config

    retry = store.publisher.publish_configuration(
        namespace="payments",
        kind="service",
        name="checkout",
        version="2026.01",
        payload=valid_config,
        schema=schema_ref,
        actor="another-retry-worker",
        version_order=1,
    )
    assert retry.idempotent
    assert retry.resource.resource_id == identity.resource_id


def test_configuration_conflict_validation_and_schema_failure(
    store, schema_ref, valid_config
) -> None:
    arguments = {
        "namespace": "payments",
        "kind": "service",
        "name": "checkout",
        "version": "v1",
        "payload": valid_config,
        "schema": schema_ref,
        "actor": "publisher",
    }
    store.configurations.publish(**arguments)
    with pytest.raises(IdentityConflict):
        store.configurations.publish(**{**arguments, "payload": {**valid_config, "replicas": 4}})
    with pytest.raises(InvalidPayload):
        store.configurations.publish(**{**arguments, "version": "v2", "payload": {"replicas": 2}})
    with pytest.raises(SchemaUnavailable):
        store.configurations.publish(
            **{**arguments, "version": "v3", "schema": "missing.schema@1.0.0"}
        )


def test_channel_cas_deprecation_listing_and_deletion(store, schema_ref, valid_config) -> None:
    first = store.configurations.publish(
        namespace="ns",
        kind="kind",
        name="name",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="actor",
        version_order=1,
    ).resource
    second = store.configurations.publish(
        namespace="ns",
        kind="kind",
        name="name",
        version="2",
        payload=valid_config,
        schema=schema_ref,
        actor="actor",
        version_order=2,
    ).resource
    with pytest.raises(IdentityConflict):
        store.configurations.promote(
            replace(first.ref, digest=f"sha256:{'0' * 64}"),
            "production",
            expected_pointer_version=0,
            actor="invalid-release",
        )
    pointer = store.configurations.promote(
        first.ref,
        "production",
        expected_pointer_version=0,
        actor="release",
    )
    assert pointer.target_resource_id == first.resource_id
    with pytest.raises(StaleChannelPointer):
        store.publisher.promote(
            second.identity,
            "production",
            expected_pointer_version=0,
            actor="stale-release",
        )
    promoted = store.publisher.promote(
        second.identity,
        "production",
        expected_pointer_version=1,
        actor="release",
    )
    assert promoted.pointer_version == 2

    first_page = store.configurations.list_resources(namespace="ns", name="name", limit=1)
    assert [item.version for item in first_page.items] == ["2"]
    assert first_page.cursor is not None
    second_page = store.configurations.list_resources(
        namespace="ns",
        name="name",
        limit=1,
        cursor=first_page.cursor,
    )
    assert [item.version for item in second_page.items] == ["1"]
    assert second_page.cursor is None
    deprecated = store.configurations.deprecate(first.identity)
    assert deprecated.state is ResourceState.DEPRECATED
    assert store.configurations.deprecate(first.identity).state is ResourceState.DEPRECATED
    with pytest.raises(ForbiddenDeletion):
        store.configurations.delete(ResourceIdentity("ns", "kind", "name", "1"))


def test_invalid_channel_arguments(store, schema_ref, valid_config) -> None:
    common = {
        "namespace": "ns",
        "kind": "kind",
        "name": "name",
        "payload": valid_config,
        "schema": schema_ref,
        "actor": "actor",
    }
    with pytest.raises(ValueError, match="requires channel"):
        store.configurations.publish(
            **common,
            version="1",
            expected_pointer_version=0,
        )
    with pytest.raises(ValueError, match="requires expected"):
        store.configurations.publish(**common, version="2", channel="stable")


def test_missing_resolution_and_invalid_pointer_version(store) -> None:
    with pytest.raises(ResourceNotFound):
        store.consumer.configurations.latest("missing", "kind", "name")
    with pytest.raises(ResourceNotFound):
        store.consumer.configurations.channel("missing", "kind", "name", "stable")
    with pytest.raises(ValueError, match="non-negative"):
        store.channels.promote(
            ResourceIdentity("missing", "kind", "name", "1"),
            "stable",
            expected_pointer_version=-1,
            actor="actor",
        )


def test_released_structured_record_envelopes_are_unwrapped(
    store, runtime, schema_ref, valid_config, monkeypatch
) -> None:
    execute = runtime.execute

    def wrapped_execute(expression):
        result = execute(expression)
        if expression.catalog != "structured":
            return result

        def wrap_record(item):
            values = dict(item)
            record_version = values.pop("recordVersion", None)
            return {
                "collectionRef": expression.arguments["resource"],
                "recordId": next(iter(values.values())),
                "recordVersion": record_version,
                "values": values,
                "createdAt": "2026-01-02T03:04:05.123456Z",
                "updatedAt": "2026-01-02T03:04:05.123456Z",
            }

        if expression.method == "query":
            page = dict(result.data)
            page["items"] = [wrap_record(item) for item in page["items"]]
            return replace(result, data=page)
        return replace(result, data=wrap_record(result.data))

    monkeypatch.setattr(runtime, "execute", wrapped_execute)
    receipt = store.configurations.publish(
        namespace="wire",
        kind="service",
        name="wrapped",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="publisher",
        version_order=1,
    )
    assert store.configurations.exact(receipt.resource.identity).resource == receipt.resource
    assert store.configurations.list_resources(namespace="wire").items == (receipt.resource,)


def test_configuration_and_channel_write_races_fail_deterministically(
    store, schema_ref, valid_config, monkeypatch
) -> None:
    published = store.configurations.publish(
        namespace="race",
        kind="service",
        name="configuration",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="first",
    ).resource
    real_get = store.metadata.get_resource
    hide_first_lookup = True

    def racing_get(resource_id, *, required=True):
        nonlocal hide_first_lookup
        if not required and hide_first_lookup:
            hide_first_lookup = False
            return None
        return real_get(resource_id, required=required)

    def conflict_put(_resource):
        raise ConditionalConflict()

    monkeypatch.setattr(store.metadata, "get_resource", racing_get)
    monkeypatch.setattr(store.metadata, "put_resource", conflict_put)
    retry = store.configurations.publish(
        namespace="race",
        kind="service",
        name="configuration",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="second",
    )
    assert retry.idempotent

    monkeypatch.setattr(store.channels, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store.metadata, "put_channel", conflict_put)
    with pytest.raises(StaleChannelPointer):
        store.configurations.promote(
            published.ref,
            "racing-channel",
            expected_pointer_version=0,
            actor="publisher",
        )


def test_configuration_deprecation_race_and_provenance(
    store, runtime, schema_ref, valid_config, monkeypatch
) -> None:
    provenance = ProvenanceV1("config-builder", "2.0.0", build_id="build-7")
    resource = store.configurations.publish(
        namespace="race",
        kind="service",
        name="deprecation",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="publisher",
        provenance=provenance,
    ).resource
    assert runtime.records["provenance"][resource.resource_id]["document"] == provenance.to_dict()

    winner = replace(resource, state=ResourceState.DEPRECATED, record_version=2)
    lookups = iter((resource, winner))

    def racing_get(_resource_id, *, required=True):
        del required
        return next(lookups)

    def conflict(_resource):
        raise ConditionalConflict("concurrent deprecation")

    monkeypatch.setattr(store.metadata, "get_resource", racing_get)
    monkeypatch.setattr(store.metadata, "deprecate_resource", conflict)
    assert store.configurations.deprecate(resource.identity) == winner
