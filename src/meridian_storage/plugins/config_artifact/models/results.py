# SPDX-License-Identifier: Apache-2.0
"""Publisher and consumer result contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .refs import StoredResourceRef
from .resources import OrphanCandidateV1, ResourceChannelV1, StoredResourceV1


@dataclass(frozen=True, slots=True)
class ResourcePage:
    items: tuple[StoredResourceV1, ...]
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class OrphanPage:
    items: tuple[OrphanCandidateV1, ...]
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedResource:
    resource: StoredResourceV1
    channel: ResourceChannelV1 | None = None

    @property
    def pointer_version(self) -> int | None:
        return None if self.channel is None else self.channel.pointer_version


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    resource: StoredResourceV1
    idempotent: bool
    object_committed: bool
    metadata_committed: bool
    channel: ResourceChannelV1 | None = None
    orphan_candidate: OrphanCandidateV1 | None = None

    @property
    def ref(self) -> StoredResourceRef:
        """Return the immutable reference accepted by channel promotion."""

        return self.resource.ref


__all__ = ["OrphanPage", "PublicationReceipt", "ResolvedResource", "ResourcePage"]
