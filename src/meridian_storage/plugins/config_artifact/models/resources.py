# SPDX-License-Identifier: Apache-2.0
"""Immutable stored-resource, channel, provenance and orphan contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from meridian_storage.object_common import ObjectReference, parse_object_reference
from meridian_storage.semantics import JsonValue, canonical_json_bytes

from .._canonical import (
    FrozenJson,
    bounded_string,
    canonical_mapping,
    channel_name,
    digest,
    logical_name,
    media_type,
    string_mapping,
    thaw_json,
    utc_timestamp,
)
from .refs import (
    PayloadSchemaRef,
    ResourceIdentity,
    ResourceProfile,
    ResourceState,
    StoredResourceRef,
    channel_version_id,
    orphan_candidate_id,
    validate_resource_id,
)


@dataclass(frozen=True, slots=True)
class ProvenanceV1:
    producer: str
    producer_version: str
    source_digests: Mapping[str, str] = field(default_factory=dict)
    build_id: str | None = None
    validation_version: str | None = None
    attributes: Mapping[str, FrozenJson] = field(default_factory=dict)
    format_version: str = "meridian.config-artifact.provenance.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "producer", bounded_string(self.producer, "producer", 256))
        object.__setattr__(
            self,
            "producer_version",
            bounded_string(self.producer_version, "producer version", 128),
        )
        sources = string_mapping(self.source_digests, "source digests")
        for value in sources.values():
            digest(value)
        object.__setattr__(self, "source_digests", sources)
        for name in ("build_id", "validation_version"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, bounded_string(value, name.replace("_", " "), 256))
        object.__setattr__(
            self,
            "attributes",
            canonical_mapping(
                cast(Mapping[str, object], self.attributes),
                "provenance attributes",
                maximum_entries=64,
                maximum_bytes=262_144,
            ),
        )
        if self.format_version != "meridian.config-artifact.provenance.v1":
            raise ValueError("unsupported provenance format version")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "producer": self.producer,
            "producerVersion": self.producer_version,
            "sourceDigests": dict(self.source_digests),
            "buildId": self.build_id,
            "validationVersion": self.validation_version,
            "attributes": {key: thaw_json(value) for key, value in self.attributes.items()},
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ProvenanceV1:
        allowed = {
            "formatVersion",
            "producer",
            "producerVersion",
            "sourceDigests",
            "buildId",
            "validationVersion",
            "attributes",
        }
        if {"producer", "producerVersion"} - set(value) or set(value) - allowed:
            raise ValueError("provenance contains unknown or missing fields")
        sources = value.get("sourceDigests", {})
        attributes = value.get("attributes", {})
        if not isinstance(sources, Mapping) or not isinstance(attributes, Mapping):
            raise TypeError("provenance sourceDigests and attributes must be objects")
        return cls(
            producer=cast(str, value["producer"]),
            producer_version=cast(str, value["producerVersion"]),
            source_digests=cast(Mapping[str, str], sources),
            build_id=cast(str | None, value.get("buildId")),
            validation_version=cast(str | None, value.get("validationVersion")),
            attributes=cast(Mapping[str, FrozenJson], attributes),
            format_version=cast(
                str, value.get("formatVersion", "meridian.config-artifact.provenance.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class StoredResourceV1:
    resource_id: str
    namespace: str
    kind: str
    name: str
    version: str
    profile: ResourceProfile
    state: ResourceState
    media_type: str
    digest: str
    byte_length: int
    created_by: str
    created_at: str
    object_ref: ObjectReference | None = None
    payload: Mapping[str, FrozenJson] | None = None
    payload_schema: PayloadSchemaRef | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    annotations: Mapping[str, FrozenJson] = field(default_factory=dict)
    provenance: ProvenanceV1 | None = None
    supersedes: str | None = None
    immutable: bool = True
    version_order: int | None = None
    record_version: str | int | None = field(default=None, compare=False)
    format_version: str = "meridian.config-artifact.stored-resource.v1"

    def __post_init__(self) -> None:
        identity = ResourceIdentity(self.namespace, self.kind, self.name, self.version)
        if self.resource_id != identity.resource_id:
            raise ValueError("resource id does not match its logical identity")
        profile = ResourceProfile(self.profile)
        state = ResourceState(self.state)
        object.__setattr__(self, "namespace", identity.namespace)
        object.__setattr__(self, "kind", identity.kind)
        object.__setattr__(self, "name", identity.name)
        object.__setattr__(self, "version", identity.version)
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "media_type", media_type(self.media_type))
        object.__setattr__(self, "digest", digest(self.digest))
        if isinstance(self.byte_length, bool) or not isinstance(self.byte_length, int):
            raise TypeError("byte length must be an integer")
        if self.byte_length < 0:
            raise ValueError("byte length cannot be negative")
        object.__setattr__(self, "created_by", bounded_string(self.created_by, "actor", 512))
        object.__setattr__(self, "created_at", utc_timestamp(self.created_at))
        object.__setattr__(self, "labels", string_mapping(self.labels, "labels"))
        object.__setattr__(
            self,
            "annotations",
            canonical_mapping(
                cast(Mapping[str, object], self.annotations),
                "annotations",
                maximum_entries=64,
                maximum_bytes=262_144,
            ),
        )
        if self.supersedes is not None:
            object.__setattr__(
                self, "supersedes", bounded_string(self.supersedes, "supersedes", 256)
            )
        if not isinstance(self.immutable, bool):
            raise TypeError("immutable must be boolean")
        if state is ResourceState.DRAFT and self.immutable:
            raise ValueError("draft resources cannot claim immutable publication state")
        if state is not ResourceState.DRAFT and not self.immutable:
            raise ValueError("published and deprecated resources must be immutable")
        if self.version_order is not None and (
            isinstance(self.version_order, bool)
            or not isinstance(self.version_order, int)
            or self.version_order < 0
        ):
            raise ValueError("version order must be a non-negative integer")
        _validate_record_version(self.record_version)
        if profile is ResourceProfile.CONFIGURATION:
            if self.payload is None or self.payload_schema is None or self.object_ref is not None:
                raise ValueError("configuration requires payload and SchemaRef and no ObjectRef")
            normalized_payload = canonical_mapping(
                cast(Mapping[str, object], self.payload), "configuration payload"
            )
            object.__setattr__(self, "payload", normalized_payload)
            object.__setattr__(self, "payload_schema", PayloadSchemaRef.parse(self.payload_schema))
            encoded = _mapping_bytes(normalized_payload)
            observed = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
            if observed != self.digest or len(encoded) != self.byte_length:
                raise ValueError("configuration digest or byte length does not match payload")
        else:
            if (
                self.object_ref is None
                or self.payload is not None
                or self.payload_schema is not None
            ):
                raise ValueError("artifact requires an ObjectRef and no inline payload")
            reference = parse_object_reference(self.object_ref, require_digest=True)
            if reference.digest != self.digest:
                raise ValueError("artifact ObjectRef digest does not match resource digest")
            object.__setattr__(self, "object_ref", reference)
        if self.format_version != "meridian.config-artifact.stored-resource.v1":
            raise ValueError("unsupported stored resource format version")

    @property
    def identity(self) -> ResourceIdentity:
        return ResourceIdentity(self.namespace, self.kind, self.name, self.version)

    @property
    def ref(self) -> StoredResourceRef:
        return StoredResourceRef(
            resource_id=self.resource_id,
            namespace=self.namespace,
            kind=self.kind,
            name=self.name,
            version=self.version,
            profile=self.profile,
            digest=self.digest,
        )

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "resourceId": self.resource_id,
            "namespace": self.namespace,
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
            "profile": self.profile.value,
            "state": self.state.value,
            "mediaType": self.media_type,
            "digest": self.digest,
            "byteLength": self.byte_length,
            "objectRef": None if self.object_ref is None else self.object_ref.to_dict(),
            "payload": (
                None
                if self.payload is None
                else {key: thaw_json(value) for key, value in self.payload.items()}
            ),
            "payloadSchema": (
                None if self.payload_schema is None else self.payload_schema.to_dict()
            ),
            "labels": dict(self.labels),
            "annotations": {key: thaw_json(value) for key, value in self.annotations.items()},
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "createdBy": self.created_by,
            "createdAt": self.created_at,
            "supersedes": self.supersedes,
            "immutable": self.immutable,
            "versionOrder": self.version_order,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> StoredResourceV1:
        required = {
            "formatVersion",
            "resourceId",
            "namespace",
            "kind",
            "name",
            "version",
            "profile",
            "state",
            "mediaType",
            "digest",
            "byteLength",
            "objectRef",
            "payload",
            "payloadSchema",
            "labels",
            "annotations",
            "provenance",
            "createdBy",
            "createdAt",
            "supersedes",
            "immutable",
            "versionOrder",
        }
        _require_record_fields(value, required, allowed=required | {"recordVersion"})
        payload = value.get("payload")
        schema = value.get("payloadSchema")
        object_ref = value.get("objectRef")
        provenance = value.get("provenance")
        if payload is not None and not isinstance(payload, Mapping):
            raise TypeError("stored configuration payload must be an object")
        if schema is not None and not isinstance(schema, Mapping):
            raise TypeError("stored payload SchemaRef must be an object")
        if object_ref is not None and not isinstance(object_ref, Mapping):
            raise TypeError("stored ObjectRef must be an object")
        if provenance is not None and not isinstance(provenance, Mapping):
            raise TypeError("stored provenance must be an object")
        labels = value.get("labels", {})
        annotations = value.get("annotations", {})
        if not isinstance(labels, Mapping) or not isinstance(annotations, Mapping):
            raise TypeError("stored labels and annotations must be objects")
        return cls(
            resource_id=cast(str, value["resourceId"]),
            namespace=cast(str, value["namespace"]),
            kind=cast(str, value["kind"]),
            name=cast(str, value["name"]),
            version=cast(str, value["version"]),
            profile=ResourceProfile(cast(str, value["profile"])),
            state=ResourceState(cast(str, value["state"])),
            media_type=cast(str, value["mediaType"]),
            digest=cast(str, value["digest"]),
            byte_length=cast(int, value["byteLength"]),
            object_ref=(
                None
                if object_ref is None
                else parse_object_reference(object_ref, require_digest=True)
            ),
            payload=cast(Mapping[str, FrozenJson] | None, payload),
            payload_schema=None if schema is None else PayloadSchemaRef.parse(schema),
            labels=cast(Mapping[str, str], labels),
            annotations=cast(Mapping[str, FrozenJson], annotations),
            provenance=None if provenance is None else ProvenanceV1.from_mapping(provenance),
            created_by=cast(str, value["createdBy"]),
            created_at=cast(str, value["createdAt"]),
            supersedes=cast(str | None, value.get("supersedes")),
            immutable=cast(bool, value["immutable"]),
            version_order=cast(int | None, value.get("versionOrder")),
            record_version=cast(str | int | None, value.get("recordVersion")),
            format_version=cast(str, value["formatVersion"]),
        )


@dataclass(frozen=True, slots=True)
class ResourceChannelV1:
    channel_version_id: str
    namespace: str
    kind: str
    name: str
    channel: str
    target_resource_id: str
    pointer_version: int
    actor: str
    updated_at: str
    record_version: str | int | None = field(default=None, compare=False)
    format_version: str = "meridian.config-artifact.resource-channel.v1"

    def __post_init__(self) -> None:
        namespace = logical_name(self.namespace, "namespace")
        kind = logical_name(self.kind, "kind")
        name = logical_name(self.name, "name")
        channel = channel_name(self.channel)
        if (
            isinstance(self.pointer_version, bool)
            or not isinstance(self.pointer_version, int)
            or self.pointer_version < 1
        ):
            raise ValueError("pointer version must be a positive integer")
        expected_id = channel_version_id(namespace, kind, name, channel, self.pointer_version)
        if self.channel_version_id != expected_id:
            raise ValueError("channel version id does not match its logical identity")
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(
            self,
            "target_resource_id",
            validate_resource_id(self.target_resource_id),
        )
        object.__setattr__(self, "actor", bounded_string(self.actor, "actor", 512))
        object.__setattr__(self, "updated_at", utc_timestamp(self.updated_at))
        _validate_record_version(self.record_version)
        if self.format_version != "meridian.config-artifact.resource-channel.v1":
            raise ValueError("unsupported resource channel format version")

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "channelVersionId": self.channel_version_id,
            "namespace": self.namespace,
            "kind": self.kind,
            "name": self.name,
            "channel": self.channel,
            "targetResourceId": self.target_resource_id,
            "pointerVersion": self.pointer_version,
            "actor": self.actor,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> ResourceChannelV1:
        required = {
            "formatVersion",
            "channelVersionId",
            "namespace",
            "kind",
            "name",
            "channel",
            "targetResourceId",
            "pointerVersion",
            "actor",
            "updatedAt",
        }
        _require_record_fields(value, required, allowed=required | {"recordVersion"})
        return cls(
            channel_version_id=cast(str, value["channelVersionId"]),
            namespace=cast(str, value["namespace"]),
            kind=cast(str, value["kind"]),
            name=cast(str, value["name"]),
            channel=cast(str, value["channel"]),
            target_resource_id=cast(str, value["targetResourceId"]),
            pointer_version=cast(int, value["pointerVersion"]),
            actor=cast(str, value["actor"]),
            updated_at=cast(str, value["updatedAt"]),
            record_version=cast(str | int | None, value.get("recordVersion")),
            format_version=cast(str, value["formatVersion"]),
        )


class OrphanState(StrEnum):
    DISCOVERED = "DISCOVERED"
    RECORDED = "RECORDED"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True, slots=True)
class OrphanCandidateV1:
    candidate_id: str
    resource_id: str
    object_ref: ObjectReference
    digest: str
    byte_length: int
    reason: str
    discovered_at: str
    state: OrphanState = OrphanState.RECORDED
    record_version: str | int | None = field(default=None, compare=False)
    format_version: str = "meridian.config-artifact.orphan-candidate.v1"

    def __post_init__(self) -> None:
        resource_id = validate_resource_id(self.resource_id)
        reference = parse_object_reference(self.object_ref, require_digest=True)
        selected_digest = digest(self.digest)
        if reference.digest != selected_digest:
            raise ValueError("orphan ObjectRef digest does not match candidate digest")
        expected_id = orphan_candidate_id(resource_id, reference.object_id, selected_digest)
        if self.candidate_id != expected_id:
            raise ValueError("orphan candidate id does not match its logical identity")
        if isinstance(self.byte_length, bool) or not isinstance(self.byte_length, int):
            raise TypeError("orphan byte length must be an integer")
        if self.byte_length < 0:
            raise ValueError("orphan byte length cannot be negative")
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "object_ref", reference)
        object.__setattr__(self, "digest", selected_digest)
        object.__setattr__(self, "reason", bounded_string(self.reason, "orphan reason", 512))
        object.__setattr__(self, "discovered_at", utc_timestamp(self.discovered_at))
        object.__setattr__(self, "state", OrphanState(self.state))
        _validate_record_version(self.record_version)
        if self.format_version != "meridian.config-artifact.orphan-candidate.v1":
            raise ValueError("unsupported orphan candidate format version")

    def to_record(self) -> dict[str, JsonValue]:
        return {
            "formatVersion": self.format_version,
            "candidateId": self.candidate_id,
            "resourceId": self.resource_id,
            "objectRef": self.object_ref.to_dict(),
            "digest": self.digest,
            "byteLength": self.byte_length,
            "reason": self.reason,
            "discoveredAt": self.discovered_at,
            "state": self.state.value,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> OrphanCandidateV1:
        required = {
            "formatVersion",
            "candidateId",
            "resourceId",
            "objectRef",
            "digest",
            "byteLength",
            "reason",
            "discoveredAt",
            "state",
        }
        _require_record_fields(value, required, allowed=required | {"recordVersion"})
        object_ref = value["objectRef"]
        if not isinstance(object_ref, Mapping):
            raise TypeError("orphan ObjectRef must be an object")
        return cls(
            candidate_id=cast(str, value["candidateId"]),
            resource_id=cast(str, value["resourceId"]),
            object_ref=parse_object_reference(object_ref, require_digest=True),
            digest=cast(str, value["digest"]),
            byte_length=cast(int, value["byteLength"]),
            reason=cast(str, value["reason"]),
            discovered_at=cast(str, value["discoveredAt"]),
            state=OrphanState(cast(str, value["state"])),
            record_version=cast(str | int | None, value.get("recordVersion")),
            format_version=cast(str, value["formatVersion"]),
        )


def _mapping_bytes(value: Mapping[str, FrozenJson]) -> bytes:
    thawed = {key: thaw_json(item) for key, item in value.items()}
    return canonical_json_bytes(cast(JsonValue, thawed))


def provenance_record(resource: StoredResourceV1) -> dict[str, JsonValue] | None:
    if resource.provenance is None:
        return None
    return {
        "formatVersion": "meridian.config-artifact.provenance-record.v1",
        "provenanceId": resource.resource_id,
        "resourceId": resource.resource_id,
        "document": resource.provenance.to_dict(),
        "createdAt": resource.created_at,
    }


def parse_items(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise TypeError("repository items must be an array")
    return value


def _require_record_fields(
    value: Mapping[str, object],
    required: set[str],
    *,
    allowed: set[str],
) -> None:
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing or unknown:
        raise ValueError(
            f"record contains missing fields {sorted(missing)!r} "
            f"or unknown fields {sorted(unknown)!r}"
        )


def _validate_record_version(value: str | int | None) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, str | int)):
        raise TypeError("record version must be a string or integer")


__all__ = [
    "OrphanCandidateV1",
    "OrphanState",
    "ProvenanceV1",
    "ResourceChannelV1",
    "StoredResourceV1",
    "parse_items",
    "provenance_record",
]
