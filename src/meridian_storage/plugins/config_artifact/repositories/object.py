# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral Object Catalog persistence and payload hand-off."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from meridian_storage import OperationResult, ResourceRef
from meridian_storage.object_common import (
    ByteRange,
    ImmutabilityRequest,
    ObjectCatalogSurface,
    ObjectMetadata,
    ObjectReference,
    PayloadReference,
    parse_object_metadata,
)

from .._runtime import MeridianRuntime
from ..errors import InvalidRepositoryResult, safe_cause
from ..schemas import OBJECT_RESOURCE


@dataclass(frozen=True, slots=True)
class ObjectRead:
    metadata: ObjectMetadata
    payload: PayloadReference
    byte_range: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ObjectPage:
    items: tuple[ObjectMetadata, ...]
    cursor: str | None = None


class ObjectRepository:
    """Exact Object V1 calls without any provider or physical-location knowledge."""

    def __init__(
        self,
        meridian: MeridianRuntime,
        *,
        object_resource: ResourceRef = OBJECT_RESOURCE,
    ) -> None:
        self._meridian = meridian
        surface = meridian.catalog("object")
        if not isinstance(surface, ObjectCatalogSurface):
            raise TypeError("object Catalog did not expose the released V1 surface")
        self._surface = surface
        self.object_resource = ResourceRef.parse(object_resource, catalog="object")

    def put(
        self,
        *,
        object_id: str,
        payload: PayloadReference,
        media_type: str,
        expected_digest: str,
        expected_length: int,
        user_metadata: Mapping[str, str],
        creation_context: Mapping[str, object],
        provenance: Mapping[str, object],
    ) -> ObjectMetadata:
        expression = self._surface.put(
            resource=self.object_resource,
            object_id=object_id,
            payload=payload,
            media_type=media_type,
            expected_digest=expected_digest,
            expected_length=expected_length,
            user_metadata=user_metadata,
            creation_context=creation_context,
            provenance=provenance,
            immutability=ImmutabilityRequest("immutable", publish_once=True),
            create_only=True,
        )
        return self._metadata(self._meridian.execute(expression), "Object put result")

    def stat(self, reference: ObjectReference) -> ObjectMetadata:
        expression = self._surface.stat(resource=self.object_resource, reference=reference)
        return self._metadata(self._meridian.execute(expression), "Object stat result")

    def get(self, reference: ObjectReference) -> ObjectRead:
        expression = self._surface.get(resource=self.object_resource, reference=reference)
        return self._read(self._meridian.execute(expression), "Object get result")

    def read_range(self, reference: ObjectReference, byte_range: ByteRange) -> ObjectRead:
        expression = self._surface.read_range(
            resource=self.object_resource,
            reference=reference,
            byte_range=byte_range,
        )
        return self._read(self._meridian.execute(expression), "Object range result")

    def list(
        self,
        *,
        prefix: str = "",
        limit: int = 100,
        cursor: str | None = None,
    ) -> ObjectPage:
        result = self._meridian.execute(
            self._surface.list(
                resource=self.object_resource,
                prefix=prefix,
                limit=limit,
                cursor=cursor,
                purpose="orphan-reconciliation",
            )
        )
        data = _mapping(result.data, "Object list result")
        items = data.get("items")
        next_cursor = data.get("cursor")
        if not isinstance(items, list | tuple) or (
            next_cursor is not None and not isinstance(next_cursor, str)
        ):
            raise InvalidRepositoryResult("Object list result had an invalid page envelope")
        try:
            parsed = tuple(
                parse_object_metadata(_mapping(item, "Object list item")) for item in items
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRepositoryResult(
                "Object list item violated the V1 contract", cause=safe_cause(exc)
            ) from exc
        return ObjectPage(parsed, next_cursor)

    @staticmethod
    def _metadata(result: OperationResult, description: str) -> ObjectMetadata:
        data = _mapping(result.data, description)
        try:
            return parse_object_metadata(_mapping(data.get("metadata"), f"{description} metadata"))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRepositoryResult(
                f"{description} violated the V1 contract", cause=safe_cause(exc)
            ) from exc

    @classmethod
    def _read(cls, result: OperationResult, description: str) -> ObjectRead:
        data = _mapping(result.data, description)
        metadata = cls._metadata(result, description)
        payload = data.get("payload")
        byte_range = data.get("range")
        try:
            reference = PayloadReference.from_mapping(_mapping(payload, f"{description} payload"))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRepositoryResult(
                f"{description} payload violated the V1 contract", cause=safe_cause(exc)
            ) from exc
        if byte_range is not None and not isinstance(byte_range, Mapping):
            raise InvalidRepositoryResult(f"{description} range was not an object")
        return ObjectRead(metadata, reference, cast(Mapping[str, object] | None, byte_range))


def _mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise InvalidRepositoryResult(f"{description} was not an object")
    return cast(Mapping[str, object], value)


__all__ = ["ObjectPage", "ObjectRead", "ObjectRepository"]
