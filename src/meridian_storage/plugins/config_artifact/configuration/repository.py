# SPDX-License-Identifier: Apache-2.0
"""Configuration publication and consumption over structured semantics."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast

from meridian_storage import ErrorCategory, MeridianError
from meridian_storage.semantics import FrozenJson, JsonValue, canonical_json_bytes

from .._canonical import canonical_mapping, media_type, thaw_json, utc_timestamp
from ..channels import ChannelRepository
from ..errors import ForbiddenDeletion, IdentityConflict, IncompatibleProfile
from ..models import (
    PayloadSchemaRef,
    ProvenanceV1,
    PublicationReceipt,
    ResolvedResource,
    ResourceChannelV1,
    ResourceIdentity,
    ResourcePage,
    ResourceProfile,
    ResourceState,
    StoredResourceRef,
    StoredResourceV1,
    provenance_record,
)
from ..repositories import MetadataRepository
from ..validation import PayloadValidator


def _payload_bytes(payload: Mapping[str, FrozenJson]) -> bytes:
    value = {key: thaw_json(item) for key, item in payload.items()}
    return canonical_json_bytes(cast(JsonValue, value))


def _same_publication(left: StoredResourceV1, right: StoredResourceV1) -> bool:
    fields = (
        "resource_id",
        "profile",
        "media_type",
        "digest",
        "byte_length",
        "object_ref",
        "payload",
        "payload_schema",
        "labels",
        "annotations",
        "provenance",
        "supersedes",
        "version_order",
    )
    return all(getattr(left, name) == getattr(right, name) for name in fields)


class ConfigurationPublisher:
    """Validate and publish immutable, inline configuration versions."""

    def __init__(
        self,
        metadata: MetadataRepository,
        validator: PayloadValidator,
        channels: ChannelRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._metadata = metadata
        self._validator = validator
        self._channels = channels
        self._clock = clock or (lambda: datetime.now(UTC))

    def publish(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        version: str,
        payload: Mapping[str, object],
        schema: PayloadSchemaRef | str | Mapping[str, object],
        actor: str,
        media_type_value: str = "application/json",
        labels: Mapping[str, str] | None = None,
        annotations: Mapping[str, object] | None = None,
        provenance: ProvenanceV1 | None = None,
        supersedes: str | None = None,
        version_order: int | None = None,
        channel: str | None = None,
        expected_pointer_version: int | None = None,
    ) -> PublicationReceipt:
        identity = ResourceIdentity(namespace, kind, name, version)
        payload_schema = PayloadSchemaRef.parse(schema)
        validated = self._validator.validate(payload, payload_schema)
        normalized = canonical_mapping(cast(Mapping[str, object], validated), "payload")
        encoded = _payload_bytes(normalized)
        candidate = StoredResourceV1(
            resource_id=identity.resource_id,
            namespace=identity.namespace,
            kind=identity.kind,
            name=identity.name,
            version=identity.version,
            profile=ResourceProfile.CONFIGURATION,
            state=ResourceState.PUBLISHED,
            media_type=media_type(media_type_value),
            digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            byte_length=len(encoded),
            payload=normalized,
            payload_schema=payload_schema,
            labels={} if labels is None else labels,
            annotations=canonical_mapping(
                {} if annotations is None else annotations,
                "annotations",
                maximum_entries=64,
                maximum_bytes=262_144,
            ),
            provenance=provenance,
            created_by=actor,
            created_at=utc_timestamp(self._clock()),
            supersedes=supersedes,
            immutable=True,
            version_order=version_order,
        )
        existing = self._metadata.get_resource(identity.resource_id, required=False)
        if existing is not None:
            return self._existing_receipt(
                candidate,
                existing,
                channel,
                expected_pointer_version,
                actor,
            )

        try:
            with self._metadata.transaction():
                stored = self._metadata.put_resource(candidate)
                if not _same_publication(candidate, stored):
                    raise IdentityConflict(resource_ref=identity.canonical)
                record = provenance_record(stored)
                if record is not None:
                    self._metadata.put_provenance(record)
        except MeridianError as exc:
            if exc.category is ErrorCategory.CONFLICT:
                winner = self._metadata.get_resource(identity.resource_id, required=False)
                if winner is not None:
                    return self._existing_receipt(
                        candidate,
                        winner,
                        channel,
                        expected_pointer_version,
                        actor,
                    )
            raise
        promoted = self._promote(stored, channel, expected_pointer_version, actor)
        return PublicationReceipt(
            resource=stored,
            idempotent=False,
            object_committed=False,
            metadata_committed=True,
            channel=promoted,
        )

    def deprecate(self, identity: ResourceIdentity) -> StoredResourceV1:
        resource = self._metadata.get_resource(identity.resource_id)
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        if resource.profile is not ResourceProfile.CONFIGURATION:
            raise IncompatibleProfile(
                "resource is not a configuration", resource_ref=identity.canonical
            )
        if resource.state is ResourceState.DEPRECATED:
            return resource
        try:
            return self._metadata.deprecate_resource(resource)
        except MeridianError as exc:
            if exc.category is ErrorCategory.CONFLICT:
                winner = self._metadata.get_resource(identity.resource_id)
                if winner is not None and winner.state is ResourceState.DEPRECATED:
                    return winner
            raise

    def promote(
        self,
        target: StoredResourceV1 | StoredResourceRef | ResourceIdentity,
        channel: str,
        *,
        expected_pointer_version: int,
        actor: str,
    ) -> ResourceChannelV1:
        return self._channels.promote(
            target,
            channel,
            expected_pointer_version=expected_pointer_version,
            actor=actor,
            expected_profile=ResourceProfile.CONFIGURATION,
        )

    @staticmethod
    def delete(identity: ResourceIdentity) -> None:
        raise ForbiddenDeletion(resource_ref=identity.canonical)

    def _existing_receipt(
        self,
        candidate: StoredResourceV1,
        existing: StoredResourceV1,
        channel: str | None,
        expected_pointer_version: int | None,
        actor: str,
    ) -> PublicationReceipt:
        if not _same_publication(candidate, existing):
            raise IdentityConflict(resource_ref=candidate.identity.canonical)
        promoted = self._promote(existing, channel, expected_pointer_version, actor)
        return PublicationReceipt(
            resource=existing,
            idempotent=True,
            object_committed=False,
            metadata_committed=True,
            channel=promoted,
        )

    def _promote(
        self,
        resource: StoredResourceV1,
        channel: str | None,
        expected_pointer_version: int | None,
        actor: str,
    ) -> ResourceChannelV1 | None:
        if channel is None:
            if expected_pointer_version is not None:
                raise ValueError("expected_pointer_version requires channel")
            return None
        if expected_pointer_version is None:
            raise ValueError("channel promotion requires expected_pointer_version")
        return self.promote(
            resource,
            channel,
            expected_pointer_version=expected_pointer_version,
            actor=actor,
        )


class ConfigurationConsumer:
    """Resolve and return immutable inline configuration payloads."""

    def __init__(self, metadata: MetadataRepository, channels: ChannelRepository) -> None:
        self._metadata = metadata
        self._channels = channels

    def exact(self, identity: ResourceIdentity) -> ResolvedResource:
        resource = self._metadata.get_resource(identity.resource_id)
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        self._require_configuration(resource)
        return ResolvedResource(resource)

    def latest(self, namespace: str, kind: str, name: str) -> ResolvedResource:
        resource = self._metadata.latest_resource(
            namespace,
            kind,
            name,
            profile=ResourceProfile.CONFIGURATION.value,
        )
        self._require_configuration(resource)
        return ResolvedResource(resource)

    def channel(self, namespace: str, kind: str, name: str, channel: str) -> ResolvedResource:
        pointer = self._channels.get(namespace, kind, name, channel)
        if pointer is None:
            raise RuntimeError("required channel lookup returned no value")
        resource = self._metadata.get_resource(pointer.target_resource_id)
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        self._require_configuration(resource)
        return ResolvedResource(resource, pointer)

    def list_resources(
        self,
        *,
        namespace: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        state: ResourceState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResourcePage:
        return self._metadata.list_resources(
            namespace=namespace,
            kind=kind,
            name=name,
            profile=ResourceProfile.CONFIGURATION.value,
            state=state,
            limit=limit,
            cursor=cursor,
        )

    @staticmethod
    def payload(resolved: ResolvedResource | StoredResourceV1) -> Mapping[str, JsonValue]:
        resource = resolved.resource if isinstance(resolved, ResolvedResource) else resolved
        ConfigurationConsumer._require_configuration(resource)
        if resource.payload is None:
            raise IncompatibleProfile(
                "configuration resource has no inline payload",
                resource_ref=resource.resource_id,
            )
        return {key: thaw_json(item) for key, item in resource.payload.items()}

    @staticmethod
    def _require_configuration(resource: StoredResourceV1) -> None:
        if resource.profile is not ResourceProfile.CONFIGURATION:
            raise IncompatibleProfile(
                "resolved resource is not a configuration",
                resource_ref=resource.resource_id,
            )


class ConfigurationRepository(ConfigurationPublisher, ConfigurationConsumer):
    """Combined convenience surface; publisher and consumer classes remain separable."""

    def __init__(
        self,
        metadata: MetadataRepository,
        validator: PayloadValidator,
        channels: ChannelRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        ConfigurationPublisher.__init__(
            self,
            metadata,
            validator,
            channels,
            clock=clock,
        )
        ConfigurationConsumer.__init__(self, metadata, channels)


__all__ = ["ConfigurationConsumer", "ConfigurationPublisher", "ConfigurationRepository"]
