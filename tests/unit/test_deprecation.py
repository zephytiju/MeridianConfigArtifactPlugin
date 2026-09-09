# SPDX-License-Identifier: Apache-2.0
"""Fail-closed validation of predicate patch collections."""

from dataclasses import replace

import pytest

from meridian_storage import ResourceRef
from meridian_storage.plugins.config_artifact import InvalidRepositoryResult, ResourceState


@pytest.fixture
def published(store):
    return store.artifacts.publish(
        namespace="ns", kind="bundle", name="deprecation", version="1", payload=b"x", actor="p"
    ).resource


def envelope(store, resource):
    return {
        "formatVersion": "meridian.record.v1",
        "collectionRef": store.metadata.metadata_resource.to_dict(),
        "recordId": resource.resource_id,
        "recordVersion": 2,
        "values": {**resource.to_record(), "state": "DEPRECATED"},
        "createdAt": "2026-09-09T00:00:00Z",
        "updatedAt": "2026-09-09T00:00:01.123456Z",
    }


@pytest.mark.parametrize("wrapped", [False, True])
def test_deprecation_validates_one_record_and_expected_version(
    store, runtime, published, monkeypatch, wrapped
):
    real_execute = runtime.execute

    def execute(expression):
        assert expression.method == "patch"
        assert expression.arguments["where"] == {"resourceId": published.resource_id}
        assert expression.arguments["expectedVersion"] == published.record_version
        result = real_execute(expression)
        assert len(result.data) == 1
        return replace(result, data=[envelope(store, published)]) if wrapped else result

    monkeypatch.setattr(runtime, "execute", execute)
    updated = store.metadata.deprecate_resource(published)
    assert updated == replace(published, state=ResourceState.DEPRECATED)
    assert updated.record_version == 2


@pytest.mark.parametrize(
    "data", [None, False, 0, "", {}, [], [None], [{}], [{}, {}], {"items": []}]
)
def test_invalid_patch_collection_is_rejected(store, runtime, published, monkeypatch, data):
    real_execute = runtime.execute
    monkeypatch.setattr(
        runtime, "execute", lambda expression: replace(real_execute(expression), data=data)
    )
    with pytest.raises(InvalidRepositoryResult):
        store.metadata.deprecate_resource(published)


@pytest.mark.parametrize(
    "changes",
    [
        {"recordId": "other"},
        {"recordVersion": None},
        {"recordVersion": True},
        {"recordVersion": ""},
        {"recordVersion": -1},
        {"recordVersion": 1},
        {"collectionRef": None},
        {"collectionRef": {"catalog": "structured", "namespace": "other", "name": "metadata"}},
        {"createdAt": "2026-02-29T00:00:00Z"},
        {"updatedAt": None},
        {"formatVersion": "unknown"},
        {"values": None},
        {"unexpected": "field"},
    ],
)
def test_malformed_or_mismatched_record_envelope_fails(
    store, runtime, published, monkeypatch, changes
):
    real_execute = runtime.execute
    record = {**envelope(store, published), **changes}
    monkeypatch.setattr(
        runtime, "execute", lambda expression: replace(real_execute(expression), data=[record])
    )
    with pytest.raises(InvalidRepositoryResult):
        store.metadata.deprecate_resource(published)


@pytest.mark.parametrize("field", ["recordId", "collectionRef", "recordVersion", "updatedAt"])
def test_incomplete_record_envelope_fails(store, runtime, published, monkeypatch, field):
    real_execute = runtime.execute
    record = envelope(store, published)
    record.pop(field)
    monkeypatch.setattr(
        runtime, "execute", lambda expression: replace(real_execute(expression), data=[record])
    )
    with pytest.raises(InvalidRepositoryResult):
        store.metadata.deprecate_resource(published)


@pytest.mark.parametrize(
    "changes", [{"state": "PUBLISHED"}, {"labels": {"changed": "yes"}}, {"createdBy": "other"}]
)
def test_patch_cannot_change_immutable_fields_or_omit_transition(
    store, runtime, published, monkeypatch, changes
):
    real_execute = runtime.execute
    record = {**published.to_record(), "state": "DEPRECATED", "recordVersion": 2, **changes}
    monkeypatch.setattr(
        runtime, "execute", lambda expression: replace(real_execute(expression), data=[record])
    )
    with pytest.raises(InvalidRepositoryResult):
        store.metadata.deprecate_resource(published)


def test_result_scope_and_missing_precondition_fail(store, runtime, published, monkeypatch):
    real_execute = runtime.execute
    with pytest.raises(InvalidRepositoryResult, match="no recordVersion"):
        store.metadata.deprecate_resource(replace(published, record_version=None))
    monkeypatch.setattr(
        runtime,
        "execute",
        lambda expression: replace(
            real_execute(expression), resources=(ResourceRef("structured", "other", "metadata"),)
        ),
    )
    with pytest.raises(InvalidRepositoryResult, match="different scope"):
        store.metadata.deprecate_resource(published)
