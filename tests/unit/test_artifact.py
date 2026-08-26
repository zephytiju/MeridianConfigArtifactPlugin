# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO

import pytest

from meridian_storage.object_common import ByteRange, ConditionalConflict, FactoryPayloadSource
from meridian_storage.plugins.config_artifact import (
    ArtifactDigestMismatch,
    ForbiddenDeletion,
    IdentityConflict,
    IncompatibleProfile,
    IncompletePublication,
    InvalidPayload,
    MissingObject,
    ProvenanceV1,
    ResourceIdentity,
    ResourceProfile,
    ResourceState,
)


def test_artifact_publish_read_range_stat_and_idempotency(store, runtime) -> None:
    payload = b"0123456789-runtime-artifact"
    receipt = store.publisher.publish_artifact(
        namespace="ml",
        kind="model",
        name="ranker",
        version="v1",
        payload=payload,
        actor="builder",
        media_type_value="application/vnd.example.model",
        labels={"stage": "test"},
        version_order=1,
        channel="candidate",
        expected_pointer_version=0,
    )
    assert receipt.resource.profile is ResourceProfile.ARTIFACT
    assert receipt.object_committed
    assert receipt.metadata_committed
    resolved = store.consumer.artifacts.channel("ml", "model", "ranker", "candidate")
    assert store.consumer.artifacts.read(resolved) == payload
    with store.consumer.artifacts.open(resolved) as stream:
        prefix = bytearray(4)
        assert stream.readable()
        assert stream.readinto(prefix) == 4
        assert bytes(prefix) == payload[:4]
    assert stream.closed
    assert store.consumer.artifacts.range_read(resolved, ByteRange(2, 7)) == payload[2:8]
    assert store.consumer.artifacts.stat(resolved).digest == receipt.resource.digest
    assert len(runtime.payloads) == 0

    retry = store.artifacts.publish(
        namespace="ml",
        kind="model",
        name="ranker",
        version="v1",
        payload=payload,
        actor="retry",
        media_type_value="application/vnd.example.model",
        labels={"stage": "test"},
        version_order=1,
    )
    assert retry.idempotent
    assert len(runtime.objects) == 1


def test_streaming_requires_and_verifies_declared_identity(store) -> None:
    payload = b"streamed"
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    receipt = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="app",
        version="1",
        payload=BytesIO(payload),
        expected_digest=digest,
        expected_length=len(payload),
        actor="builder",
    )
    assert store.artifacts.read(receipt.resource) == payload
    with pytest.raises(InvalidPayload, match="expected_digest"):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="app",
            version="2",
            payload=BytesIO(payload),
            actor="builder",
        )
    with pytest.raises(InvalidPayload, match="do not match"):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="app",
            version="3",
            payload=payload,
            expected_digest=f"sha256:{'0' * 64}",
            actor="builder",
        )
    with pytest.raises(InvalidPayload, match="expected_length"):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="app",
            version="4",
            payload=b"x",
            expected_length=True,
            actor="builder",
        )
    with pytest.raises(InvalidPayload, match="lowercase-hex"):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="app",
            version="5",
            payload=BytesIO(payload),
            expected_digest="sha256:not-a-digest",
            expected_length=len(payload),
            actor="builder",
        )


def test_payload_source_and_reference_ownership(store, runtime) -> None:
    payload = b"factory-payload"
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    source = FactoryPayloadSource(lambda: BytesIO(payload))
    first = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="factory",
        version="1",
        payload=source,
        expected_digest=digest,
        expected_length=len(payload),
        actor="builder",
    )
    assert first.resource.byte_length == len(payload)

    reference = runtime.payloads.register(
        FactoryPayloadSource(lambda: BytesIO(payload)),
        expected_digest=digest,
        expected_length=len(payload),
    )
    second = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="reference",
        version="1",
        payload=reference,
        actor="builder",
    )
    assert second.resource.digest == digest
    assert runtime.payloads.release(reference)


def test_artifact_identity_conflict_missing_and_corrupt_object(store, runtime) -> None:
    receipt = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="app",
        version="1",
        payload=b"first",
        actor="builder",
    )
    with pytest.raises(IdentityConflict):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="app",
            version="1",
            payload=b"second",
            actor="builder",
        )

    object_id = receipt.resource.identity.object_id
    metadata, _ = runtime.objects.pop(object_id)
    with pytest.raises(MissingObject):
        store.artifacts.read(receipt.resource)
    runtime.objects[object_id] = (metadata, b"xxxxx")
    with pytest.raises(ArtifactDigestMismatch):
        store.artifacts.read(receipt.resource)


def test_partial_publication_records_and_discovers_orphans(store, runtime) -> None:
    runtime.fail_next_metadata_put = True
    with pytest.raises(IncompletePublication) as raised:
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="partial",
            version="1",
            payload=b"committed-object",
            actor="builder",
        )
    assert raised.value.retryable
    recorded = store.metadata.list_orphans()
    assert len(recorded.items) == 1
    assert recorded.items[0].reason == "metadata-publication-failed"

    recovered = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="partial",
        version="1",
        payload=b"committed-object",
        actor="retry",
    )
    assert recovered.idempotent
    assert recovered.metadata_committed

    runtime.records["metadata"].pop(recovered.resource.resource_id)
    runtime.records["orphan-candidates"].clear()
    discovered = store.artifacts.discover_orphans(record=False)
    assert len(discovered.items) == 1
    persisted = store.artifacts.discover_orphans(record=True)
    assert len(persisted.items) == 1


def test_orphaned_logical_object_with_another_digest_is_a_conflict(store, runtime) -> None:
    runtime.fail_next_metadata_put = True
    with pytest.raises(IncompletePublication):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="conflicting-orphan",
            version="1",
            payload=b"first",
            actor="builder",
        )
    with pytest.raises(IdentityConflict):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="conflicting-orphan",
            version="1",
            payload=b"second",
            actor="builder",
        )


def test_concurrent_artifact_metadata_winner_is_idempotent(store, monkeypatch) -> None:
    published = store.artifacts.publish(
        namespace="race",
        kind="bundle",
        name="artifact",
        version="1",
        payload=b"same",
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
    receipt = store.artifacts.publish(
        namespace="race",
        kind="bundle",
        name="artifact",
        version="1",
        payload=b"same",
        actor="second",
    )
    assert receipt.idempotent
    assert receipt.resource == published


def test_artifact_deprecation_and_deletion_prohibition(store) -> None:
    resource = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="app",
        version="1",
        payload=b"bytes",
        actor="builder",
    ).resource
    assert store.artifacts.deprecate(resource.identity).state.value == "DEPRECATED"
    with pytest.raises(ForbiddenDeletion):
        store.artifacts.delete(ResourceIdentity("ns", "bundle", "app", "1"))


def test_artifact_deprecation_race_converges_on_deprecated_winner(store, monkeypatch) -> None:
    resource = store.artifacts.publish(
        namespace="race",
        kind="bundle",
        name="deprecation",
        version="1",
        payload=b"bytes",
        actor="builder",
    ).resource
    winner = replace(resource, state=ResourceState.DEPRECATED, record_version=2)
    lookups = iter((resource, winner))

    def racing_get(_resource_id, *, required=True):
        del required
        return next(lookups)

    def conflict(_resource):
        raise ConditionalConflict("concurrent deprecation")

    monkeypatch.setattr(store.metadata, "get_resource", racing_get)
    monkeypatch.setattr(store.metadata, "deprecate_resource", conflict)
    assert store.artifacts.deprecate(resource.identity) == winner


def test_artifact_provenance_is_persisted(store, runtime) -> None:
    provenance = ProvenanceV1(
        "example-builder",
        "1.2.3",
        build_id="build-42",
        attributes={"reproducible": True},
    )
    resource = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="provenance",
        version="1",
        payload=b"runtime",
        actor="builder",
        provenance=provenance,
    ).resource
    assert runtime.records["provenance"][resource.resource_id]["document"] == provenance.to_dict()


def test_artifact_resolution_and_promotion_failures(store, schema_ref, valid_config) -> None:
    first = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="versions",
        version="1",
        payload=b"one",
        actor="builder",
        version_order=1,
    ).resource
    second = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="versions",
        version="2",
        payload=b"two",
        actor="builder",
        version_order=2,
    ).resource
    assert store.artifacts.exact(first.identity).resource == first
    assert store.artifacts.latest("ns", "bundle", "versions").resource == second
    assert [item.resource_id for item in store.artifacts.list_resources(namespace="ns").items] == [
        second.resource_id,
        first.resource_id,
    ]
    with pytest.raises(ValueError, match="requires channel"):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="versions",
            version="3",
            payload=b"three",
            actor="builder",
            expected_pointer_version=0,
        )
    with pytest.raises(ValueError, match="requires expected"):
        store.artifacts.publish(
            namespace="ns",
            kind="bundle",
            name="versions",
            version="4",
            payload=b"four",
            actor="builder",
            channel="stable",
        )

    configuration = store.configurations.publish(
        namespace="ns",
        kind="service",
        name="config",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="builder",
    ).resource
    with pytest.raises(IncompatibleProfile):
        store.artifacts.exact(configuration.identity)
    with pytest.raises(IncompatibleProfile):
        store.configurations.exact(first.identity)
    with pytest.raises(IncompatibleProfile):
        store.configurations.promote(
            first.ref,
            "invalid-profile",
            expected_pointer_version=0,
            actor="release",
        )
    with pytest.raises(IncompatibleProfile):
        store.artifacts.promote(
            configuration.ref,
            "invalid-profile",
            expected_pointer_version=0,
            actor="release",
        )


def test_artifact_missing_stat_and_short_range_are_detected(store, runtime) -> None:
    resource = store.artifacts.publish(
        namespace="ns",
        kind="bundle",
        name="integrity",
        version="1",
        payload=b"long-enough",
        actor="builder",
    ).resource
    object_id = resource.identity.object_id
    metadata, payload = runtime.objects[object_id]
    runtime.objects.pop(object_id)
    with pytest.raises(MissingObject):
        store.artifacts.stat(resource)
    with pytest.raises(MissingObject):
        store.artifacts.range_read(resource, ByteRange(0, 1))
    runtime.objects[object_id] = (replace(metadata, media_type="application/x-corrupt"), payload)
    with pytest.raises(ArtifactDigestMismatch):
        store.artifacts.stat(resource)
    runtime.objects[object_id] = (metadata, payload[:2])
    with pytest.raises(ArtifactDigestMismatch, match="range length"):
        store.artifacts.range_read(resource, ByteRange(0, 5))
