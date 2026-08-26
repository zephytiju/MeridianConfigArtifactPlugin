# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from meridian_storage.object_common import ObjectReference
from meridian_storage.plugins.config_artifact import (
    OrphanCandidateV1,
    PayloadSchemaRef,
    ProvenanceV1,
    ResourceState,
    StoredResourceV1,
)
from meridian_storage.plugins.config_artifact.models import orphan_candidate_id, parse_items
from meridian_storage.semantics import CatalogName, ResourceReference


def test_stored_resource_rejects_invalid_scalar_and_profile_combinations(
    store, schema_ref, valid_config
) -> None:
    configuration = store.configurations.publish(
        namespace="ns",
        kind="service",
        name="config",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="builder",
    ).resource
    artifact = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="artifact",
        version="1",
        payload=b"artifact",
        actor="builder",
    ).resource

    invalid = (
        ({"resource_id": "wrong"}, ValueError, "resource id"),
        ({"byte_length": True}, TypeError, "byte length"),
        ({"byte_length": -1}, ValueError, "cannot be negative"),
        ({"immutable": False}, ValueError, "must be immutable"),
        ({"immutable": "yes"}, TypeError, "must be boolean"),
        ({"version_order": -1}, ValueError, "version order"),
        ({"record_version": 1.5}, TypeError, "record version"),
        ({"media_type": "json"}, ValueError, "Internet media"),
        ({"created_at": "yesterday"}, ValueError, "RFC 3339"),
        ({"payload": None}, ValueError, "configuration requires"),
        ({"annotations": {str(index): index for index in range(65)}}, ValueError, "at most 64"),
        ({"annotations": {"large": "x" * 262_145}}, ValueError, "canonical JSON bytes"),
        ({"format_version": "bad"}, ValueError, "unsupported stored"),
    )
    for changes, error_type, message in invalid:
        with pytest.raises(error_type, match=message):
            replace(configuration, **changes)

    draft = replace(configuration, state=ResourceState.DRAFT, immutable=False)
    assert draft.state is ResourceState.DRAFT
    with pytest.raises(ValueError, match="draft"):
        replace(configuration, state=ResourceState.DRAFT)
    with pytest.raises(ValueError, match="artifact requires"):
        replace(artifact, payload={"invalid": True})
    wrong_reference = ObjectReference(
        artifact.object_ref.resource_ref,
        artifact.object_ref.object_id,
        f"sha256:{'0' * 64}",
    )
    with pytest.raises(ValueError, match="ObjectRef digest"):
        replace(artifact, object_ref=wrong_reference)


def test_wire_parsers_fail_closed(store, schema_ref, valid_config) -> None:
    resource = store.configurations.publish(
        namespace="ns",
        kind="service",
        name="wire",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="builder",
    ).resource
    record = resource.to_record()
    invalid = (
        ({**record, "payload": []}, "payload"),
        ({**record, "payloadSchema": "bad"}, "SchemaRef"),
        ({**record, "objectRef": "bad"}, "ObjectRef"),
        ({**record, "provenance": "bad"}, "provenance"),
        ({**record, "labels": []}, "labels"),
    )
    for value, message in invalid:
        with pytest.raises(TypeError, match=message):
            StoredResourceV1.from_record(value)
    with pytest.raises(ValueError, match="unknown fields"):
        StoredResourceV1.from_record({**record, "physicalTable": "forbidden"})
    missing = dict(record)
    missing.pop("digest")
    with pytest.raises(ValueError, match="missing fields"):
        StoredResourceV1.from_record(missing)

    with pytest.raises(TypeError, match="objects"):
        ProvenanceV1.from_mapping(
            {"producer": "builder", "producerVersion": "1", "sourceDigests": []}
        )
    with pytest.raises(ValueError, match="unsupported provenance"):
        ProvenanceV1("builder", "1", format_version="bad")
    with pytest.raises(ValueError, match="catalog"):
        PayloadSchemaRef.parse({"catalog": "structured", "namespace": "ns", "name": "schema"})
    with pytest.raises(TypeError, match="array"):
        parse_items("bad")
    assert parse_items([1, 2]) == [1, 2]


def test_channel_and_orphan_defensive_invariants(store) -> None:
    artifact = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="defensive",
        version="1",
        payload=b"artifact",
        actor="builder",
        channel="stable",
        expected_pointer_version=0,
    )
    channel = artifact.channel
    assert channel is not None
    with pytest.raises(ValueError, match="positive integer"):
        replace(channel, pointer_version=0)
    with pytest.raises(ValueError, match="unsupported resource channel"):
        replace(channel, format_version="bad")
    with pytest.raises(ValueError, match="opaque"):
        replace(channel, target_resource_id="not-a-resource-id")
    with pytest.raises(TypeError, match="record version"):
        replace(channel, record_version=True)

    digest = artifact.resource.digest
    reference = artifact.resource.object_ref
    assert reference is not None
    orphan = OrphanCandidateV1(
        candidate_id=orphan_candidate_id(
            artifact.resource.resource_id,
            reference.object_id,
            digest,
        ),
        resource_id=artifact.resource.resource_id,
        object_ref=reference,
        digest=digest,
        byte_length=artifact.resource.byte_length,
        reason="reason",
        discovered_at="2026-01-02T03:04:05.123456Z",
    )
    with pytest.raises(TypeError, match="byte length"):
        replace(orphan, byte_length=True)
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(orphan, byte_length=-1)
    with pytest.raises(ValueError, match="unsupported orphan"):
        replace(orphan, format_version="bad")
    with pytest.raises(ValueError, match="opaque"):
        replace(orphan, resource_id="not-a-resource-id")
    with pytest.raises(TypeError, match="record version"):
        replace(orphan, record_version=True)
    wrong_ref = ObjectReference(
        ResourceReference(CatalogName.OBJECT, "resources", "objects"),
        reference.object_id,
        f"sha256:{'f' * 64}",
    )
    with pytest.raises(ValueError, match="digest"):
        replace(orphan, object_ref=wrong_ref)
    with pytest.raises(TypeError, match="ObjectRef"):
        OrphanCandidateV1.from_record({**orphan.to_record(), "objectRef": "bad"})
