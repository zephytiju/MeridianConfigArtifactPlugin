# SPDX-License-Identifier: Apache-2.0
"""Versioned compare-and-set channel pointers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from meridian_storage import ErrorCategory, MeridianError

from .._canonical import channel_name, logical_name, utc_timestamp
from ..errors import IdentityConflict, IncompatibleProfile, StaleChannelPointer
from ..models import (
    ResourceChannelV1,
    ResourceIdentity,
    ResourceProfile,
    ResourceState,
    StoredResourceRef,
    StoredResourceV1,
    channel_version_id,
)
from ..repositories import MetadataRepository


class ChannelRepository:
    """Promote immutable versions through append-only, linearizable pointer rows."""

    def __init__(
        self,
        metadata: MetadataRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._metadata = metadata
        self._clock = clock or (lambda: datetime.now(UTC))

    def get(
        self,
        namespace: str,
        kind: str,
        name: str,
        channel: str,
        *,
        required: bool = True,
    ) -> ResourceChannelV1 | None:
        return self._metadata.latest_channel(
            logical_name(namespace, "namespace"),
            logical_name(kind, "kind"),
            logical_name(name, "name"),
            channel_name(channel),
            required=required,
        )

    def promote(
        self,
        target: StoredResourceV1 | StoredResourceRef | ResourceIdentity,
        channel: str,
        *,
        expected_pointer_version: int,
        actor: str,
        expected_profile: ResourceProfile | None = None,
    ) -> ResourceChannelV1:
        if (
            isinstance(expected_pointer_version, bool)
            or not isinstance(expected_pointer_version, int)
            or expected_pointer_version < 0
        ):
            raise ValueError("expected pointer version must be a non-negative integer")
        resource = (
            target
            if isinstance(target, StoredResourceV1)
            else self._metadata.get_resource(target.resource_id)
        )
        if resource is None:
            raise RuntimeError("required resource lookup returned no value")
        if isinstance(target, StoredResourceRef) and resource.ref != target:
            raise IdentityConflict(
                "channel target reference does not match stored resource",
                resource_ref=target.resource_id,
            )
        if expected_profile is not None and resource.profile is not expected_profile:
            raise IncompatibleProfile(
                f"channel target is not a {expected_profile.value}",
                resource_ref=resource.resource_id,
            )
        if resource.state is not ResourceState.PUBLISHED:
            raise IncompatibleProfile(
                "only a PUBLISHED immutable resource may be promoted",
                resource_ref=resource.resource_id,
            )
        selected_channel = channel_name(channel)
        current = self.get(
            resource.namespace,
            resource.kind,
            resource.name,
            selected_channel,
            required=False,
        )
        observed_version = 0 if current is None else current.pointer_version
        if observed_version != expected_pointer_version:
            raise StaleChannelPointer(
                resource_ref=f"{resource.namespace}:{resource.kind}/{resource.name}#{selected_channel}"
            )
        pointer_version = observed_version + 1
        requested = ResourceChannelV1(
            channel_version_id=channel_version_id(
                resource.namespace,
                resource.kind,
                resource.name,
                selected_channel,
                pointer_version,
            ),
            namespace=resource.namespace,
            kind=resource.kind,
            name=resource.name,
            channel=selected_channel,
            target_resource_id=resource.resource_id,
            pointer_version=pointer_version,
            actor=actor,
            updated_at=utc_timestamp(self._clock()),
        )
        try:
            winner = self._metadata.put_channel(requested)
        except MeridianError as exc:
            if exc.category is ErrorCategory.CONFLICT:
                raise StaleChannelPointer(
                    resource_ref=(
                        f"{resource.namespace}:{resource.kind}/{resource.name}#{selected_channel}"
                    )
                ) from exc
            raise
        if winner.target_resource_id != requested.target_resource_id:
            raise StaleChannelPointer(
                resource_ref=f"{resource.namespace}:{resource.kind}/{resource.name}#{selected_channel}"
            )
        return winner


__all__ = ["ChannelRepository"]
