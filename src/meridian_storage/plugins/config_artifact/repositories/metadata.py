# SPDX-License-Identifier: Apache-2.0
"""Structured Catalog persistence for package-owned public records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import cast

from meridian_storage import ErrorCategory, MeridianError, OperationResult, ResourceRef, SafeCause
from meridian_storage.semantics import JsonValue, StructuredCatalogSurface

from .._canonical import utc_timestamp
from .._runtime import MeridianRuntime
from ..errors import IdentityConflict, InvalidRepositoryResult, ResourceNotFound, safe_cause
from ..models import (
    OrphanCandidateV1,
    OrphanPage,
    OrphanState,
    ResourceChannelV1,
    ResourcePage,
    ResourceState,
    StoredResourceV1,
)
from ..schemas import CHANNEL_RESOURCE, METADATA_RESOURCE, ORPHAN_RESOURCE, PROVENANCE_RESOURCE


def _mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvalidRepositoryResult(f"{description} was not an object")
    if any(not isinstance(key, str) for key in value):
        raise InvalidRepositoryResult(f"{description} contained a non-string key")
    return cast(Mapping[str, object], value)


def _record(result: OperationResult, description: str) -> Mapping[str, object]:
    return _logical_record(_mapping(result.data, description), description)


def _logical_record(value: Mapping[str, object], description: str) -> Mapping[str, object]:
    """Accept both logical values and the released structured Record envelope."""

    if "values" not in value:
        return value
    values = dict(_mapping(value["values"], f"{description} values"))
    record_version = value.get("recordVersion")
    if record_version is not None:
        values["recordVersion"] = record_version
    return values


def _without_record_timestamps(value: Mapping[str, object], *fields: str) -> Mapping[str, object]:
    """Validate adapter timestamps that are not fields of the logical model."""
    for field in fields:
        if field in value:
            utc_timestamp(cast(str, value[field]))
    return {key: item for key, item in value.items() if key not in fields}


def _page(result: OperationResult, description: str) -> tuple[Sequence[object], str | None]:
    data = _mapping(result.data, description)
    items = data.get("items")
    cursor = data.get("cursor")
    if (
        not isinstance(items, Sequence)
        or isinstance(items, str | bytes | bytearray)
        or (cursor is not None and not isinstance(cursor, str))
    ):
        raise InvalidRepositoryResult(f"{description} had an invalid page envelope")
    return items, cursor


def _is_not_found(exc: MeridianError) -> bool:
    return exc.category is ErrorCategory.NOT_FOUND


class MetadataRepository:
    """Typed repository over one caller-supplied structured Resource layout."""

    def __init__(
        self,
        meridian: MeridianRuntime,
        *,
        metadata_resource: ResourceRef = METADATA_RESOURCE,
        channel_resource: ResourceRef = CHANNEL_RESOURCE,
        provenance_resource: ResourceRef = PROVENANCE_RESOURCE,
        orphan_resource: ResourceRef = ORPHAN_RESOURCE,
    ) -> None:
        self._meridian = meridian
        surface = meridian.catalog("structured")
        if not isinstance(surface, StructuredCatalogSurface):
            raise TypeError("structured Catalog did not expose the released V1 surface")
        self._surface = surface
        self.metadata_resource = ResourceRef.parse(metadata_resource, catalog="structured")
        self.channel_resource = ResourceRef.parse(channel_resource, catalog="structured")
        self.provenance_resource = ResourceRef.parse(provenance_resource, catalog="structured")
        self.orphan_resource = ResourceRef.parse(orphan_resource, catalog="structured")

    def transaction(self) -> AbstractContextManager[object]:
        return self._meridian.transaction(self.metadata_resource)

    def get_resource(self, resource_id: str, *, required: bool = True) -> StoredResourceV1 | None:
        expression = self._surface.get(
            resource=self.metadata_resource.to_dict(),
            where={"resourceId": resource_id},
        )
        try:
            result = self._meridian.execute(expression)
        except MeridianError as exc:
            if _is_not_found(exc) and not required:
                return None
            if _is_not_found(exc):
                raise ResourceNotFound(resource_ref=resource_id) from exc
            raise
        if result.data is None:
            if not required:
                return None
            raise ResourceNotFound(resource_ref=resource_id)
        return self._parse_resource(_record(result, "structured resource result"))

    def put_resource(self, resource: StoredResourceV1) -> StoredResourceV1:
        result = self._meridian.execute(
            self._surface.put(
                resource=self.metadata_resource.to_dict(),
                data=resource.to_record(),
                mode="if_absent",
            )
        )
        return self._parse_resource(_record(result, "structured resource put result"))

    def deprecate_resource(self, resource: StoredResourceV1) -> StoredResourceV1:
        if resource.record_version is None:
            raise InvalidRepositoryResult("resource has no recordVersion for conditional patch")
        result = self._meridian.execute(
            self._surface.patch(
                resource=self.metadata_resource.to_dict(),
                where={"resourceId": resource.resource_id},
                changes={"state": ResourceState.DEPRECATED.value},
                expected_version=resource.record_version,
            )
        )
        return self._parse_resource(_record(result, "structured resource patch result"))

    def list_resources(
        self,
        *,
        namespace: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        profile: str | None = None,
        state: ResourceState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ResourcePage:
        candidates: tuple[tuple[str, JsonValue], ...] = (
            ("namespace", namespace),
            ("kind", kind),
            ("name", name),
            ("profile", profile),
            ("state", None if state is None else state.value),
        )
        where = {field: value for field, value in candidates if value is not None}
        result = self._meridian.execute(
            self._surface.query(
                resource=self.metadata_resource.to_dict(),
                where=where,
                order_by=(
                    {"field": "versionOrder", "direction": "desc", "nulls": "last"},
                    {"field": "createdAt", "direction": "desc", "nulls": "last"},
                ),
                limit=limit,
                cursor=cursor,
            )
        )
        items, next_cursor = _page(result, "structured resource query result")
        return ResourcePage(
            tuple(
                self._parse_resource(
                    _logical_record(_mapping(item, "resource page item"), "resource page item")
                )
                for item in items
            ),
            next_cursor,
        )

    def latest_resource(
        self,
        namespace: str,
        kind: str,
        name: str,
        *,
        profile: str | None = None,
    ) -> StoredResourceV1:
        page = self.list_resources(
            namespace=namespace,
            kind=kind,
            name=name,
            profile=profile,
            state=ResourceState.PUBLISHED,
            limit=1,
        )
        if not page.items:
            raise ResourceNotFound(resource_ref=f"{namespace}:{kind}/{name}@latest")
        return page.items[0]

    def put_channel(self, channel: ResourceChannelV1) -> ResourceChannelV1:
        result = self._meridian.execute(
            self._surface.put(
                resource=self.channel_resource.to_dict(),
                data=channel.to_record(),
                mode="if_absent",
            )
        )
        return self._parse_channel(_record(result, "structured channel put result"))

    def latest_channel(
        self,
        namespace: str,
        kind: str,
        name: str,
        channel: str,
        *,
        required: bool = True,
    ) -> ResourceChannelV1 | None:
        result = self._meridian.execute(
            self._surface.query(
                resource=self.channel_resource.to_dict(),
                where={
                    "namespace": namespace,
                    "kind": kind,
                    "name": name,
                    "channel": channel,
                },
                order_by=({"field": "pointerVersion", "direction": "desc", "nulls": "last"},),
                limit=1,
            )
        )
        items, _ = _page(result, "structured channel query result")
        if not items:
            if required:
                raise ResourceNotFound(resource_ref=f"{namespace}:{kind}/{name}#{channel}")
            return None
        return self._parse_channel(
            _logical_record(_mapping(items[0], "channel page item"), "channel page item")
        )

    def put_provenance(self, value: Mapping[str, JsonValue]) -> Mapping[str, object]:
        result = self._meridian.execute(
            self._surface.put(
                resource=self.provenance_resource.to_dict(), data=value, mode="if_absent"
            )
        )
        try:
            stored = _without_record_timestamps(
                _record(result, "structured provenance put result"), "updatedAt"
            )
        except (TypeError, ValueError) as exc:
            raise InvalidRepositoryResult("invalid structured provenance timestamp") from exc
        observed = {key: item for key, item in stored.items() if key != "recordVersion"}
        if observed != dict(value):
            raise InvalidRepositoryResult("structured provenance result changed immutable fields")
        return stored

    def put_orphan(self, orphan: OrphanCandidateV1) -> OrphanCandidateV1:
        try:
            result = self._meridian.execute(
                self._surface.put(
                    resource=self.orphan_resource.to_dict(),
                    data=orphan.to_record(),
                    mode="if_absent",
                )
            )
        except MeridianError as exc:
            if exc.category is ErrorCategory.CONFLICT:
                existing = self.get_orphan(orphan.candidate_id, required=False)
                if existing is not None and _same_orphan_identity(existing, orphan):
                    return existing
                if existing is not None:
                    raise IdentityConflict(
                        "orphan candidate identity already has different metadata",
                        resource_ref=orphan.candidate_id,
                    ) from exc
            raise
        return self._parse_orphan(_record(result, "structured orphan put result"))

    def get_orphan(
        self,
        candidate_id: str,
        *,
        required: bool = True,
    ) -> OrphanCandidateV1 | None:
        expression = self._surface.get(
            resource=self.orphan_resource.to_dict(),
            where={"candidateId": candidate_id},
        )
        try:
            result = self._meridian.execute(expression)
        except MeridianError as exc:
            if _is_not_found(exc) and not required:
                return None
            if _is_not_found(exc):
                raise ResourceNotFound(resource_ref=candidate_id) from exc
            raise
        if result.data is None:
            if not required:
                return None
            raise ResourceNotFound(resource_ref=candidate_id)
        return self._parse_orphan(_record(result, "structured orphan result"))

    def list_orphans(
        self,
        *,
        state: OrphanState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> OrphanPage:
        where: Mapping[str, object] = {} if state is None else {"state": state.value}
        result = self._meridian.execute(
            self._surface.query(
                resource=self.orphan_resource.to_dict(),
                where=where,
                order_by=({"field": "discoveredAt", "direction": "asc", "nulls": "last"},),
                limit=limit,
                cursor=cursor,
            )
        )
        items, next_cursor = _page(result, "structured orphan query result")
        return OrphanPage(
            tuple(
                self._parse_orphan(
                    _logical_record(_mapping(item, "orphan page item"), "orphan page item")
                )
                for item in items
            ),
            next_cursor,
        )

    @staticmethod
    def _parse_resource(value: Mapping[str, object]) -> StoredResourceV1:
        try:
            # PostgreSQL returns the structured record's update timestamp alongside
            # logical values. It is not a field of immutable StoredResourceV1.
            if "updatedAt" in value:
                utc_timestamp(cast(str, value["updatedAt"]))
                value = {key: item for key, item in value.items() if key != "updatedAt"}
            return StoredResourceV1.from_record(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRepositoryResult(
                "structured Resource result violated the V1 contract",
                cause=_safe_cause(exc),
            ) from exc

    @staticmethod
    def _parse_channel(value: Mapping[str, object]) -> ResourceChannelV1:
        try:
            return ResourceChannelV1.from_record(_without_record_timestamps(value, "createdAt"))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRepositoryResult(
                "structured channel result violated the V1 contract",
                cause=_safe_cause(exc),
            ) from exc

    @staticmethod
    def _parse_orphan(value: Mapping[str, object]) -> OrphanCandidateV1:
        try:
            return OrphanCandidateV1.from_record(
                _without_record_timestamps(value, "createdAt", "updatedAt")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRepositoryResult(
                "structured orphan result violated the V1 contract",
                cause=_safe_cause(exc),
            ) from exc


def _safe_cause(exc: BaseException) -> SafeCause:
    return safe_cause(exc)


def _same_orphan_identity(left: OrphanCandidateV1, right: OrphanCandidateV1) -> bool:
    return (
        left.candidate_id,
        left.resource_id,
        left.object_ref,
        left.digest,
        left.byte_length,
    ) == (
        right.candidate_id,
        right.resource_id,
        right.object_ref,
        right.digest,
        right.byte_length,
    )


__all__ = ["MetadataRepository"]
