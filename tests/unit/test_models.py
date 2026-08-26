# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from meridian_storage.object_common import ObjectReference
from meridian_storage.plugins.config_artifact import (
    ConfigArtifactErrorCode,
    IdentityConflict,
    OrphanCandidateV1,
    OrphanState,
    PayloadSchemaRef,
    ProvenanceV1,
    ResourceChannelV1,
    ResourceIdentity,
    ResourceProfile,
    ResourceState,
    StoredResourceRef,
    StoredResourceV1,
)
from meridian_storage.plugins.config_artifact.models import (
    channel_version_id,
    orphan_candidate_id,
    provenance_record,
)
from meridian_storage.semantics import CatalogName, ResourceReference, canonical_json_bytes

STAMP = "2026-01-02T03:04:05.123456Z"


def test_reference_models_are_deterministic_and_strict() -> None:
    identity = ResourceIdentity("ns", "kind", "name", "v1")
    assert identity == ResourceIdentity("ns", "kind", "name", "v1")
    assert identity.resource_id.startswith("rs_")
    assert identity.object_id == f"artifacts/{identity.resource_id}"
    assert identity.canonical == "ns:kind/name@v1"
    assert identity.to_dict()["version"] == "v1"

    schema = PayloadSchemaRef.parse("structured:app.service@1.2.3")
    assert schema.canonical == "structured:app.service@1.2.3"
    assert PayloadSchemaRef.parse(schema.to_dict()) == schema
    assert PayloadSchemaRef.parse(schema) is schema
    with pytest.raises(ValueError, match="must be"):
        PayloadSchemaRef.parse("missing-version")
    with pytest.raises(ValueError, match="structured Catalog"):
        PayloadSchemaRef("app", "schema", "1.0.0", catalog="object")
    with pytest.raises(ValueError, match="logical name"):
        ResourceIdentity("bad name", "kind", "name", "v1")


def test_configuration_resource_round_trip_and_invariants() -> None:
    identity = ResourceIdentity("ns", "config", "service", "1")
    payload = {"enabled": True, "nested": {"values": [1, 2]}}
    encoded = canonical_json_bytes(payload)
    provenance = ProvenanceV1(
        "builder",
        "1.0.0",
        source_digests={"source": f"sha256:{'1' * 64}"},
        build_id="build-1",
        validation_version="1",
        attributes={"reproducible": True},
    )
    resource = StoredResourceV1(
        resource_id=identity.resource_id,
        namespace=identity.namespace,
        kind=identity.kind,
        name=identity.name,
        version=identity.version,
        profile=ResourceProfile.CONFIGURATION,
        state=ResourceState.PUBLISHED,
        media_type="application/json",
        digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        byte_length=len(encoded),
        created_by="builder",
        created_at=STAMP,
        payload=payload,
        payload_schema=PayloadSchemaRef("app", "service", "1.0.0"),
        labels={"team": "platform"},
        annotations={"ticket": 42},
        provenance=provenance,
        version_order=1,
    )
    restored = StoredResourceV1.from_record({**resource.to_record(), "recordVersion": 7})
    assert restored.ref == resource.ref
    assert restored.record_version == 7
    assert provenance_record(restored)["resourceId"] == identity.resource_id
    assert ProvenanceV1.from_mapping(provenance.to_dict()) == provenance

    with pytest.raises(ValueError, match="digest"):
        StoredResourceV1.from_record({**resource.to_record(), "digest": f"sha256:{'0' * 64}"})
    with pytest.raises(ValueError, match="draft"):
        StoredResourceV1.from_record({**resource.to_record(), "state": "DRAFT", "immutable": True})


def test_artifact_channel_orphan_round_trips() -> None:
    identity = ResourceIdentity("ns", "bundle", "app", "1")
    digest = f"sha256:{'a' * 64}"
    reference = ObjectReference(
        ResourceReference(CatalogName.OBJECT, "resources", "objects"),
        identity.object_id,
        digest,
    )
    resource = StoredResourceV1(
        resource_id=identity.resource_id,
        namespace=identity.namespace,
        kind=identity.kind,
        name=identity.name,
        version=identity.version,
        profile=ResourceProfile.ARTIFACT,
        state=ResourceState.PUBLISHED,
        media_type="application/octet-stream",
        digest=digest,
        byte_length=9,
        created_by="builder",
        created_at=STAMP,
        object_ref=reference,
    )
    assert StoredResourceV1.from_record(resource.to_record()) == resource

    channel = ResourceChannelV1(
        channel_version_id("ns", "bundle", "app", "stable", 1),
        "ns",
        "bundle",
        "app",
        "stable",
        identity.resource_id,
        1,
        "release",
        STAMP,
    )
    assert ResourceChannelV1.from_record(channel.to_record()) == channel
    orphan = OrphanCandidateV1(
        orphan_candidate_id(identity.resource_id, identity.object_id, digest),
        identity.resource_id,
        reference,
        digest,
        9,
        "test-orphan",
        STAMP,
        OrphanState.RECORDED,
    )
    assert OrphanCandidateV1.from_record(orphan.to_record()) == orphan

    with pytest.raises(ValueError, match="channel version id"):
        ResourceChannelV1(
            "ch_bad",
            "ns",
            "bundle",
            "app",
            "stable",
            identity.resource_id,
            1,
            "release",
            STAMP,
        )
    with pytest.raises(ValueError, match="candidate id"):
        OrphanCandidateV1(
            "oc_bad",
            identity.resource_id,
            reference,
            digest,
            9,
            "reason",
            STAMP,
        )


def test_error_envelope_is_stable_and_redacted() -> None:
    error = IdentityConflict(resource_ref="ns:kind/name@1")
    assert error.code == ConfigArtifactErrorCode.IDENTITY_CONFLICT.value
    assert error.to_dict() == {
        "code": ConfigArtifactErrorCode.IDENTITY_CONFLICT.value,
        "category": "CONFLICT",
        "message": "resource identity already has another digest",
        "retryable": False,
        "resourceRef": "ns:kind/name@1",
    }


def test_timestamp_and_provenance_rejections() -> None:
    assert ProvenanceV1("builder", "1").to_dict()["buildId"] is None
    with pytest.raises(ValueError, match="digest"):
        ProvenanceV1("builder", "1", source_digests={"bad": "not-a-digest"})
    with pytest.raises(ValueError, match="unknown or missing"):
        ProvenanceV1.from_mapping({"producer": "x", "producerVersion": "1", "unknown": 1})
    with pytest.raises(ValueError, match="bounded"):
        ResourceIdentity("ns", "kind", "name", "")
    with pytest.raises(ValueError, match="resource id"):
        StoredResourceRef(
            "wrong", "ns", "kind", "name", "1", ResourceProfile.ARTIFACT, f"sha256:{'0' * 64}"
        )
    assert datetime.fromisoformat(STAMP.replace("Z", "+00:00")).tzinfo is UTC
