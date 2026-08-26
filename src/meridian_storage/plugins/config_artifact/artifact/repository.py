# SPDX-License-Identifier: Apache-2.0
"""Artifact publication, retrieval, verification, and orphan reconciliation."""

from __future__ import annotations

import hashlib
from collections.abc import Buffer, Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from io import RawIOBase
from typing import BinaryIO, cast

from meridian_storage import ErrorCategory, MeridianError
from meridian_storage.object_common import (
    ByteRange,
    ConditionalConflict,
    ImmutableObjectConflict,
    ObjectMetadata,
    ObjectNotFound,
    ObjectReference,
    PayloadReference,
    PayloadRegistry,
    iter_payload_chunks,
)
from meridian_storage.semantics import ResourceReference

from .._canonical import canonical_mapping, media_type, utc_timestamp
from ..channels import ChannelRepository
from ..errors import (
    ArtifactDigestMismatch,
    ForbiddenDeletion,
    IdentityConflict,
    IncompatibleProfile,
    IncompletePublication,
    MissingObject,
    safe_cause,
)
from ..models import (
    OrphanCandidateV1,
    OrphanPage,
    OrphanState,
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
    orphan_candidate_id,
    provenance_record,
)
from ..models.refs import validate_resource_id
from ..repositories import MetadataRepository, ObjectRepository
from .payloads import ArtifactPayload, register_payload


def _same_publication(left: StoredResourceV1, right: StoredResourceV1) -> bool:
    fields = (
        "resource_id",
        "profile",
        "media_type",
        "digest",
        "byte_length",
        "object_ref",
        "labels",
        "annotations",
        "provenance",
        "supersedes",
        "version_order",
    )
    return all(getattr(left, name) == getattr(right, name) for name in fields)


class ArtifactPublisher:
    """Publish immutable runtime bytes before their structured metadata record."""

    def __init__(
        self,
        metadata: MetadataRepository,
        objects: ObjectRepository,
        channels: ChannelRepository,
        payloads: PayloadRegistry,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._metadata = metadata
        self._objects = objects
        self._channels = channels
        self._payloads = payloads
        self._clock = clock or (lambda: datetime.now(UTC))

    def publish(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        version: str,
        payload: ArtifactPayload | Callable[[], BinaryIO],
        actor: str,
        media_type_value: str = "application/octet-stream",
        expected_digest: str | None = None,
        expected_length: int | None = None,
        labels: Mapping[str, str] | None = None,
        annotations: Mapping[str, object] | None = None,
        provenance: ProvenanceV1 | None = None,
        supersedes: str | None = None,
        version_order: int | None = None,
        channel: str | None = None,
        expected_pointer_version: int | None = None,
    ) -> PublicationReceipt:
        identity = ResourceIdentity(namespace, kind, name, version)
        selected_media_type = media_type(media_type_value)
        registered = register_payload(
            payload,
            self._payloads,
            expected_digest=expected_digest,
            expected_length=expected_length,
        )
        try:
            existing = self._metadata.get_resource(identity.resource_id, required=False)
            if existing is not None:
                if (
                    existing.profile is not ResourceProfile.ARTIFACT
                    or existing.digest != registered.digest
                    or existing.byte_length != registered.byte_length
                    or existing.media_type != selected_media_type
                ):
                    raise IdentityConflict(resource_ref=identity.canonical)
                candidate = self._candidate(
                    identity,
                    existing.object_ref,
                    registered.digest,
                    registered.byte_length,
                    selected_media_type,
                    actor,
                    labels,
                    annotations,
                    provenance,
                    supersedes,
                    version_order,
                )
                return self._existing_receipt(
                    identity,
                    candidate,
                    existing,
                    channel,
                    expected_pointer_version,
                    actor,
                )

            object_metadata, object_idempotent = self._put_object(
                identity,
                registered.reference,
                registered.digest,
                registered.byte_length,
                selected_media_type,
                actor,
                provenance,
            )
            candidate = self._candidate(
                identity,
                object_metadata.object_ref,
                registered.digest,
                registered.byte_length,
                selected_media_type,
                actor,
                labels,
                annotations,
                provenance,
                supersedes,
                version_order,
            )
            try:
                with self._metadata.transaction():
                    stored = self._metadata.put_resource(candidate)
                    if not _same_publication(candidate, stored):
                        raise IdentityConflict(resource_ref=identity.canonical)
                    record = provenance_record(stored)
                    if record is not None:
                        self._metadata.put_provenance(record)
            except IdentityConflict:
                raise
            except MeridianError as exc:
                if exc.category is ErrorCategory.CONFLICT:
                    winner = self._metadata.get_resource(identity.resource_id, required=False)
                    if winner is not None:
                        return self._existing_receipt(
                            identity,
                            candidate,
                            winner,
                            channel,
                            expected_pointer_version,
                            actor,
                        )
                self._record_orphan(candidate, "metadata-publication-failed")
                raise IncompletePublication(
                    "Object committed but structured metadata publication failed",
                    resource_ref=identity.canonical,
                    cause=safe_cause(exc),
                ) from exc
            except Exception as exc:
                self._record_orphan(candidate, "metadata-publication-failed")
                raise IncompletePublication(
                    "Object committed but structured metadata publication failed",
                    resource_ref=identity.canonical,
                    cause=safe_cause(exc),
                ) from exc
            promoted = self._promote(stored, channel, expected_pointer_version, actor)
            return PublicationReceipt(
                stored,
                idempotent=object_idempotent,
                object_committed=True,
                metadata_committed=True,
                channel=promoted,
                orphan_candidate=None,
            )
        finally:
            if registered.owned:
                self._payloads.release(registered.reference)

    def deprecate(self, identity: ResourceIdentity) -> StoredResourceV1:
        resource = self._metadata.get_resource(identity.resource_id)
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        self._require_artifact(resource)
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
            expected_profile=ResourceProfile.ARTIFACT,
        )

    @staticmethod
    def delete(identity: ResourceIdentity) -> None:
        raise ForbiddenDeletion(resource_ref=identity.canonical)

    def _put_object(
        self,
        identity: ResourceIdentity,
        payload: PayloadReference,
        expected_digest: str,
        expected_length: int,
        selected_media_type: str,
        actor: str,
        provenance: ProvenanceV1 | None,
    ) -> tuple[ObjectMetadata, bool]:
        try:
            metadata = self._objects.put(
                object_id=identity.object_id,
                payload=payload,
                media_type=selected_media_type,
                expected_digest=expected_digest,
                expected_length=expected_length,
                user_metadata={
                    "resourceId": identity.resource_id,
                    "namespace": identity.namespace,
                    "kind": identity.kind,
                    "name": identity.name,
                    "version": identity.version,
                },
                creation_context={"actor": actor, "profile": ResourceProfile.ARTIFACT.value},
                provenance={} if provenance is None else provenance.to_dict(),
            )
            idempotent = False
        except (ConditionalConflict, ImmutableObjectConflict):
            reference = ObjectReference(
                ResourceReference.parse(self._objects.object_resource),
                identity.object_id,
                None,
            )
            metadata = self._objects.stat(reference)
            idempotent = True
        self._verify_object_metadata(
            metadata,
            identity,
            expected_digest,
            expected_length,
            selected_media_type,
        )
        return metadata, idempotent

    def _record_orphan(self, resource: StoredResourceV1, reason: str) -> OrphanCandidateV1:
        if resource.object_ref is None:
            raise IncompatibleProfile(
                "artifact resource has no ObjectRef",
                resource_ref=resource.resource_id,
            )
        candidate = OrphanCandidateV1(
            candidate_id=orphan_candidate_id(
                resource.resource_id,
                resource.object_ref.object_id,
                resource.digest,
            ),
            resource_id=resource.resource_id,
            object_ref=resource.object_ref,
            digest=resource.digest,
            byte_length=resource.byte_length,
            reason=reason,
            discovered_at=utc_timestamp(self._clock()),
            state=OrphanState.RECORDED,
        )
        try:
            return self._metadata.put_orphan(candidate)
        except Exception:
            return candidate

    def _existing_receipt(
        self,
        identity: ResourceIdentity,
        candidate: StoredResourceV1,
        existing: StoredResourceV1,
        channel: str | None,
        expected_pointer_version: int | None,
        actor: str,
    ) -> PublicationReceipt:
        if not _same_publication(candidate, existing):
            raise IdentityConflict(resource_ref=identity.canonical)
        promoted = self._promote(existing, channel, expected_pointer_version, actor)
        return PublicationReceipt(
            existing,
            idempotent=True,
            object_committed=True,
            metadata_committed=True,
            channel=promoted,
        )

    def _candidate(
        self,
        identity: ResourceIdentity,
        object_ref: ObjectReference | None,
        expected_digest: str,
        expected_length: int,
        selected_media_type: str,
        actor: str,
        labels: Mapping[str, str] | None,
        annotations: Mapping[str, object] | None,
        provenance: ProvenanceV1 | None,
        supersedes: str | None,
        version_order: int | None,
    ) -> StoredResourceV1:
        if object_ref is None:
            raise IdentityConflict(
                "stored artifact has no ObjectRef",
                resource_ref=identity.canonical,
            )
        return StoredResourceV1(
            resource_id=identity.resource_id,
            namespace=identity.namespace,
            kind=identity.kind,
            name=identity.name,
            version=identity.version,
            profile=ResourceProfile.ARTIFACT,
            state=ResourceState.PUBLISHED,
            media_type=selected_media_type,
            digest=expected_digest,
            byte_length=expected_length,
            object_ref=object_ref,
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

    def _verify_object_metadata(
        self,
        metadata: ObjectMetadata,
        identity: ResourceIdentity,
        expected_digest: str,
        expected_length: int,
        selected_media_type: str,
    ) -> None:
        if (
            metadata.object_ref.resource_ref
            != ResourceReference.parse(self._objects.object_resource)
            or metadata.object_ref.object_id != identity.object_id
            or metadata.digest != expected_digest
            or metadata.byte_length != expected_length
            or metadata.media_type != selected_media_type
        ):
            raise IdentityConflict(
                "logical artifact Object already has incompatible content",
                resource_ref=identity.canonical,
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

    @staticmethod
    def _require_artifact(resource: StoredResourceV1) -> None:
        if resource.profile is not ResourceProfile.ARTIFACT:
            raise IncompatibleProfile(
                "resource is not an artifact", resource_ref=resource.resource_id
            )


class _VerifyingReader(RawIOBase):
    def __init__(self, stream: BinaryIO, expected_digest: str, expected_length: int) -> None:
        super().__init__()
        self._stream = stream
        self._expected_digest = expected_digest
        self._expected_length = expected_length
        self._hasher = hashlib.sha256()
        self._length = 0
        self._done = False

    def read(self, size: int = -1) -> bytes:
        self._checkClosed()
        raw = self._stream.read(size)
        if not isinstance(raw, bytes | bytearray | memoryview):
            raise TypeError("artifact stream returned non-binary data")
        value = bytes(raw)
        if value:
            self._hasher.update(value)
            self._length += len(value)
        return value

    def readinto(self, buffer: Buffer) -> int:
        target = memoryview(buffer).cast("B")
        value = self.read(len(target))
        target[: len(value)] = value
        return len(value)

    def readable(self) -> bool:
        return True

    def verify(self) -> None:
        if self._done:
            return
        while self.read(1024 * 1024):
            pass
        observed = f"sha256:{self._hasher.hexdigest()}"
        self._done = True
        if self._length != self._expected_length or observed != self._expected_digest:
            raise ArtifactDigestMismatch()


class ArtifactConsumer:
    """Resolve artifact metadata and open provider-neutral verified byte streams."""

    def __init__(
        self,
        metadata: MetadataRepository,
        objects: ObjectRepository,
        channels: ChannelRepository,
        payloads: PayloadRegistry,
    ) -> None:
        self._metadata = metadata
        self._objects = objects
        self._channels = channels
        self._payloads = payloads

    def exact(self, identity: ResourceIdentity) -> ResolvedResource:
        resource = self._metadata.get_resource(identity.resource_id)
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        self._require_artifact(resource)
        return ResolvedResource(resource)

    def latest(self, namespace: str, kind: str, name: str) -> ResolvedResource:
        resource = self._metadata.latest_resource(
            namespace,
            kind,
            name,
            profile=ResourceProfile.ARTIFACT.value,
        )
        self._require_artifact(resource)
        return ResolvedResource(resource)

    def channel(self, namespace: str, kind: str, name: str, channel: str) -> ResolvedResource:
        pointer = self._channels.get(namespace, kind, name, channel)
        if pointer is None:
            raise RuntimeError("required channel lookup returned no value")
        resource = self._metadata.get_resource(pointer.target_resource_id)
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        self._require_artifact(resource)
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
            profile=ResourceProfile.ARTIFACT.value,
            state=state,
            limit=limit,
            cursor=cursor,
        )

    def stat(self, resource: StoredResourceV1 | ResolvedResource) -> ObjectMetadata:
        selected = resource.resource if isinstance(resource, ResolvedResource) else resource
        self._require_artifact(selected)
        if selected.object_ref is None:
            raise IncompatibleProfile(
                "artifact resource has no ObjectRef", resource_ref=selected.resource_id
            )
        try:
            metadata = self._objects.stat(selected.object_ref)
        except (ObjectNotFound, MeridianError) as exc:
            if isinstance(exc, ObjectNotFound) or (
                isinstance(exc, MeridianError) and exc.category is ErrorCategory.NOT_FOUND
            ):
                raise MissingObject(resource_ref=selected.resource_id) from exc
            raise
        self._verify_consumed_metadata(metadata, selected)
        return metadata

    @contextmanager
    def open(self, resource: StoredResourceV1 | ResolvedResource) -> Iterator[BinaryIO]:
        selected = resource.resource if isinstance(resource, ResolvedResource) else resource
        self._require_artifact(selected)
        if selected.object_ref is None:
            raise IncompatibleProfile(
                "artifact resource has no ObjectRef", resource_ref=selected.resource_id
            )
        try:
            result = self._objects.get(selected.object_ref)
        except (ObjectNotFound, MeridianError) as exc:
            if isinstance(exc, ObjectNotFound) or (
                isinstance(exc, MeridianError) and exc.category is ErrorCategory.NOT_FOUND
            ):
                raise MissingObject(resource_ref=selected.resource_id) from exc
            raise
        try:
            self._verify_consumed_metadata(result.metadata, selected)
        except ArtifactDigestMismatch:
            self._payloads.release(result.payload)
            raise
        try:
            with self._payloads.open(result.payload) as stream:
                reader = _VerifyingReader(stream, selected.digest, selected.byte_length)
                try:
                    yield cast(BinaryIO, reader)
                    reader.verify()
                finally:
                    reader.close()
        finally:
            self._payloads.release(result.payload)

    def read(self, resource: StoredResourceV1 | ResolvedResource) -> bytes:
        with self.open(resource) as stream:
            return stream.read()

    def range_read(
        self,
        resource: StoredResourceV1 | ResolvedResource,
        byte_range: ByteRange,
    ) -> bytes:
        selected = resource.resource if isinstance(resource, ResolvedResource) else resource
        self._require_artifact(selected)
        if selected.object_ref is None:
            raise IncompatibleProfile(
                "artifact resource has no ObjectRef", resource_ref=selected.resource_id
            )
        try:
            result = self._objects.read_range(selected.object_ref, byte_range)
        except (ObjectNotFound, MeridianError) as exc:
            if isinstance(exc, ObjectNotFound) or (
                isinstance(exc, MeridianError) and exc.category is ErrorCategory.NOT_FOUND
            ):
                raise MissingObject(resource_ref=selected.resource_id) from exc
            raise
        try:
            self._verify_consumed_metadata(result.metadata, selected)
        except ArtifactDigestMismatch:
            self._payloads.release(result.payload)
            raise
        resolved = byte_range.resolve(selected.byte_length)
        try:
            with self._payloads.open(result.payload) as stream:
                chunks = tuple(iter_payload_chunks(stream))
            value = b"".join(chunks)
        finally:
            self._payloads.release(result.payload)
        if len(value) != resolved.length:
            raise ArtifactDigestMismatch("artifact range length verification failed")
        return value

    def discover_orphans(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        record: bool = True,
    ) -> OrphanPage:
        page = self._objects.list(prefix="artifacts/", limit=limit, cursor=cursor)
        candidates: list[OrphanCandidateV1] = []
        for item in page.items:
            resource_id = item.user_metadata.get("resourceId")
            if resource_id is None:
                continue
            try:
                validate_resource_id(resource_id)
            except ValueError:
                continue
            if item.object_ref.object_id != f"artifacts/{resource_id}":
                continue
            if self._metadata.get_resource(resource_id, required=False) is not None:
                continue
            reference = ObjectReference(
                item.object_ref.resource_ref,
                item.object_ref.object_id,
                item.digest,
            )
            candidate = OrphanCandidateV1(
                candidate_id=orphan_candidate_id(resource_id, reference.object_id, item.digest),
                resource_id=resource_id,
                object_ref=reference,
                digest=item.digest,
                byte_length=item.byte_length,
                reason="object-without-structured-metadata",
                discovered_at=utc_timestamp(datetime.now(UTC)),
                state=OrphanState.DISCOVERED,
            )
            candidates.append(self._metadata.put_orphan(candidate) if record else candidate)
        return OrphanPage(tuple(candidates), page.cursor)

    @staticmethod
    def _require_artifact(resource: StoredResourceV1) -> None:
        ArtifactPublisher._require_artifact(resource)

    @staticmethod
    def _verify_consumed_metadata(
        metadata: ObjectMetadata,
        resource: StoredResourceV1,
    ) -> None:
        if (
            resource.object_ref is None
            or metadata.object_ref != resource.object_ref
            or metadata.digest != resource.digest
            or metadata.byte_length != resource.byte_length
            or metadata.media_type != resource.media_type
        ):
            raise ArtifactDigestMismatch(resource_ref=resource.resource_id)


class ArtifactRepository(ArtifactPublisher, ArtifactConsumer):
    """Combined convenience surface; publisher and consumer classes remain separable."""

    def __init__(
        self,
        metadata: MetadataRepository,
        objects: ObjectRepository,
        channels: ChannelRepository,
        payloads: PayloadRegistry,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        ArtifactPublisher.__init__(
            self,
            metadata,
            objects,
            channels,
            payloads,
            clock=clock,
        )
        ArtifactConsumer.__init__(self, metadata, objects, channels, payloads)


__all__ = ["ArtifactConsumer", "ArtifactPublisher", "ArtifactRepository"]
