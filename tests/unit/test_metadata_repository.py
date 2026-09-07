# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from meridian_storage import ResourceRef
from meridian_storage.object_common import ConditionalConflict
from meridian_storage.plugins.config_artifact import (
    IdentityConflict,
    IncompletePublication,
    InvalidRepositoryResult,
    ResourceNotFound,
)


@pytest.mark.parametrize("method", ["get_resource", "get_orphan"])
@pytest.mark.parametrize("required", [False, True])
def test_null_get_result_means_missing(store, runtime, monkeypatch, method, required):
    def missing(expression):
        return runtime._result(
            expression, ResourceRef.parse(expression.arguments["resource"]), None
        )

    monkeypatch.setattr(runtime, "execute", missing)
    get = getattr(store.metadata, method)
    if required:
        with pytest.raises(ResourceNotFound):
            get("missing", required=True)
    else:
        assert get("missing", required=False) is None


@pytest.mark.parametrize("method", ["get_resource", "get_orphan"])
@pytest.mark.parametrize("data", [False, 0, "", [], {}, {"values": None}])
def test_optional_get_rejects_malformed_non_null_result(store, runtime, monkeypatch, method, data):
    def malformed(expression):
        return runtime._result(
            expression, ResourceRef.parse(expression.arguments["resource"]), data
        )

    monkeypatch.setattr(runtime, "execute", malformed)
    with pytest.raises(InvalidRepositoryResult):
        getattr(store.metadata, method)("missing", required=False)


def test_orphan_writes_are_idempotent_and_conflicts_are_detected(
    store, runtime, monkeypatch
) -> None:
    runtime.fail_next_metadata_put = True
    with pytest.raises(IncompletePublication):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="orphan",
            version="1",
            payload=b"committed-object",
            actor="builder",
        )
    orphan = store.metadata.list_orphans().items[0]
    real_execute = runtime.execute

    def conflict_on_orphan_put(expression):
        resource = expression.arguments.get("resource", {})
        if (
            expression.catalog == "structured"
            and expression.method == "put"
            and resource.get("name") == "orphan-candidates"
        ):
            raise ConditionalConflict("concurrent orphan recorder")
        return real_execute(expression)

    monkeypatch.setattr(runtime, "execute", conflict_on_orphan_put)
    assert store.metadata.put_orphan(orphan) == orphan
    with pytest.raises(IdentityConflict):
        store.metadata.put_orphan(replace(orphan, byte_length=orphan.byte_length + 1))

    assert store.metadata.get_orphan(orphan.candidate_id) == orphan
    assert store.metadata.get_orphan("missing", required=False) is None
    with pytest.raises(ResourceNotFound):
        store.metadata.get_orphan("missing")


def test_malformed_structured_results_fail_closed(
    store, runtime, schema_ref, valid_config, monkeypatch
) -> None:
    resource = store.configurations.publish(
        namespace="ns",
        kind="service",
        name="malformed",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="publisher",
    ).resource
    real_execute = runtime.execute

    def malformed_data(expression):
        return replace(real_execute(expression), data=[])

    monkeypatch.setattr(runtime, "execute", malformed_data)
    with pytest.raises(InvalidRepositoryResult, match="was not an object"):
        store.metadata.get_resource(resource.resource_id)

    def malformed_page(expression):
        return replace(real_execute(expression), data={"items": "invalid", "cursor": None})

    monkeypatch.setattr(runtime, "execute", malformed_page)
    with pytest.raises(InvalidRepositoryResult, match="page envelope"):
        store.metadata.list_resources(namespace="ns")

    for parser in (
        store.metadata._parse_resource,
        store.metadata._parse_channel,
        store.metadata._parse_orphan,
    ):
        with pytest.raises(InvalidRepositoryResult):
            parser({})


def test_provenance_write_detects_changed_immutable_fields(store, runtime, monkeypatch) -> None:
    real_execute = runtime.execute

    def changed_result(expression):
        result = real_execute(expression)
        return replace(result, data={**result.data, "resourceId": "changed"})

    monkeypatch.setattr(runtime, "execute", changed_result)
    with pytest.raises(InvalidRepositoryResult, match="changed immutable fields"):
        store.metadata.put_provenance(
            {
                "formatVersion": "meridian.config-artifact.provenance-record.v1",
                "provenanceId": "original",
                "resourceId": "original",
                "document": {},
                "createdAt": "2026-01-02T03:04:05.123456Z",
            }
        )


@pytest.mark.parametrize("timestamp", ["2026-01-02T03:04:05.123456Z", "bad", None, 42])
def test_resource_result_structured_update_timestamp(store, timestamp):
    resource = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="timestamp",
        version="1",
        payload=b"content",
        actor="publisher",
    ).resource
    record = {**resource.to_record(), "updatedAt": timestamp}
    if timestamp == "2026-01-02T03:04:05.123456Z":
        assert store.metadata._parse_resource(record) == resource
    else:
        with pytest.raises(InvalidRepositoryResult):
            store.metadata._parse_resource(record)
    with pytest.raises(InvalidRepositoryResult):
        store.metadata._parse_resource({**resource.to_record(), "unknown": "field"})


@pytest.mark.parametrize("timestamp", ["2026-01-02T03:04:05.123456Z", "invalid", None, 42])
def test_channel_and_orphan_adapter_timestamps(store, runtime, timestamp):
    resource = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="timestamps",
        version="1",
        payload=b"x",
        actor="p",
    ).resource
    pointer = store.artifacts.promote(resource.ref, "active", expected_pointer_version=0, actor="p")
    runtime.fail_next_metadata_put = True
    with pytest.raises(IncompletePublication):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="orphan-timestamps",
            version="1",
            payload=b"x",
            actor="p",
        )
    orphan = store.metadata.list_orphans().items[0]
    cases = (
        (store.metadata._parse_channel, pointer, {"createdAt": timestamp}),
        (store.metadata._parse_orphan, orphan, {"createdAt": timestamp, "updatedAt": timestamp}),
    )
    for parse, expected, extra in cases:
        if timestamp == "2026-01-02T03:04:05.123456Z":
            assert parse({**expected.to_record(), **extra}) == expected
        else:
            with pytest.raises(InvalidRepositoryResult):
                parse({**expected.to_record(), **extra})
        with pytest.raises(InvalidRepositoryResult):
            parse({**expected.to_record(), "unrecognized": "field"})


def test_provenance_timestamp_collision_is_rejected(store, runtime, monkeypatch):
    real_execute = runtime.execute
    value = {
        "formatVersion": "meridian.config-artifact.provenance-record.v1",
        "provenanceId": "logical",
        "resourceId": "logical",
        "document": {},
        "createdAt": "2026-01-02T03:04:05.123456Z",
    }

    def collision(expression):
        result = real_execute(expression)
        assert expression.method == "put"
        return replace(result, data={**result.data, "createdAt": "2026-01-02T03:04:06.123456Z"})

    monkeypatch.setattr(runtime, "execute", collision)
    with pytest.raises(InvalidRepositoryResult):
        store.metadata.put_provenance(value)
