# SPDX-License-Identifier: Apache-2.0
"""Released-surface in-memory harness used by unit and integration tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast

import pytest

from meridian_storage import Expression, OperationResult, ResourceRef
from meridian_storage.object_common import (
    ByteRange,
    ConditionalConflict,
    FactoryPayloadSource,
    ObjectCatalogSurface,
    ObjectMetadata,
    ObjectNotFound,
    ObjectReference,
    PayloadReference,
    PayloadRegistry,
    iter_payload_chunks,
)
from meridian_storage.plugins.config_artifact import ResourceStore
from meridian_storage.semantics import (
    CatalogName,
    FieldDefinition,
    LogicalType,
    RelationalProfile,
    ResourceNotFound,
    ResourceReference,
    SchemaDocument,
    SchemaReference,
    SemanticKind,
    StructuredCatalogSurface,
)

FINGERPRINT = f"sha256:{'0' * 64}"
NOW = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)


@dataclass(frozen=True)
class FakeSchemaHandle:
    definition: Mapping[str, object]


class FakeRuntime:
    def __init__(self) -> None:
        self.payloads = PayloadRegistry()
        self.structured = StructuredCatalogSurface()
        self.object = ObjectCatalogSurface()
        self.records: dict[str, dict[str, dict[str, Any]]] = {
            "metadata": {},
            "channels": {},
            "provenance": {},
            "orphan-candidates": {},
        }
        self.objects: dict[str, tuple[ObjectMetadata, bytes]] = {}
        self.fail_next_metadata_put = False
        self.transactions = 0
        self.schema_document = _configuration_schema()

    def catalog(self, name: str) -> object:
        return {"structured": self.structured, "object": self.object}[name]

    def schema(
        self,
        catalog: str,
        namespace: str,
        name: str,
        version: str | None = None,
    ) -> FakeSchemaHandle:
        ref = self.schema_document.ref
        if (catalog, namespace, name, version) != (
            ref.catalog.value,
            ref.namespace,
            ref.name,
            ref.version,
        ):
            raise KeyError("schema not found")
        return FakeSchemaHandle(cast(Mapping[str, object], self.schema_document.to_dict()))

    def transaction(
        self, resource: ResourceRef | str | Mapping[str, object]
    ) -> AbstractContextManager[object]:
        ResourceRef.parse(resource)
        self.transactions += 1
        return nullcontext()

    def execute(self, expression: Expression) -> OperationResult:
        if expression.catalog == "structured":
            return self._structured(expression)
        return self._object(expression)

    def _structured(self, expression: Expression) -> OperationResult:
        arguments = cast(Mapping[str, object], expression.arguments)
        raw_resource = arguments["resource"]
        resource = ResourceRef.parse(cast(Mapping[str, object], raw_resource))
        records = self.records[resource.name]
        method = expression.method
        if method == "put":
            data = dict(cast(Mapping[str, Any], arguments["data"]))
            if resource.name == "metadata" and self.fail_next_metadata_put:
                self.fail_next_metadata_put = False
                raise RuntimeError("injected metadata failure")
            key_name = {
                "metadata": "resourceId",
                "channels": "channelVersionId",
                "provenance": "provenanceId",
                "orphan-candidates": "candidateId",
            }[resource.name]
            key = cast(str, data[key_name])
            assert arguments["mode"] == "if_absent"
            assert arguments.get("expectedVersion") is None
            if key in records:
                raise ConditionalConflict("record already exists")
            data["recordVersion"] = 1
            records[key] = data
            stored = data
            return self._result(expression, resource, stored)
        if method == "get":
            where = cast(Mapping[str, object], arguments["where"])
            matches = self._matches(records.values(), where)
            if not matches:
                raise ResourceNotFound("record not found")
            return self._result(expression, resource, matches[0])
        if method == "patch":
            where = cast(Mapping[str, object], arguments["where"])
            matches = self._matches(records.values(), where)
            if not matches:
                raise ResourceNotFound("record not found")
            stored = matches[0]
            expected = arguments.get("expectedVersion")
            if expected is not None and expected != stored["recordVersion"]:
                raise ConditionalConflict("record version did not match")
            stored.update(cast(Mapping[str, object], arguments["changes"]))
            stored["recordVersion"] = cast(int, stored["recordVersion"]) + 1
            return self._result(expression, resource, stored)
        if method == "query":
            where = cast(Mapping[str, object], arguments.get("where", {}))
            matches = self._matches(records.values(), where)
            order_by = cast(list[Mapping[str, object]], arguments.get("orderBy", []))
            for order in reversed(order_by):
                field = cast(str, order["field"])
                reverse = order.get("direction", "asc") == "desc"
                matches.sort(
                    key=lambda item, selected=field: (
                        item.get(selected) is not None,
                        item.get(selected),
                    ),
                    reverse=reverse,
                )
            limit = cast(int, arguments["limit"])
            offset = int(cast(str, arguments.get("cursor", "0")))
            next_offset = offset + limit
            return self._result(
                expression,
                resource,
                {
                    "items": matches[offset:next_offset],
                    "cursor": str(next_offset) if next_offset < len(matches) else None,
                },
            )
        raise AssertionError(f"unsupported structured method {method}")

    def _object(self, expression: Expression) -> OperationResult:
        arguments = cast(Mapping[str, object], expression.arguments)
        resource = ResourceRef.parse(cast(Mapping[str, object], arguments["resource"]))
        method = expression.method
        if method == "put":
            object_id = cast(str, arguments["objectId"])
            if object_id in self.objects:
                raise ConditionalConflict()
            reference = PayloadReference.from_mapping(
                cast(Mapping[str, object], arguments["payload"])
            )
            with self.payloads.open(reference) as stream:
                payload = b"".join(iter_payload_chunks(stream))
            observed = f"sha256:{hashlib.sha256(payload).hexdigest()}"
            if (
                observed != arguments["expectedDigest"]
                or len(payload) != arguments["expectedLength"]
            ):
                raise ValueError("payload identity mismatch")
            exact = ObjectReference(ResourceReference.parse(resource), object_id, observed)
            metadata = ObjectMetadata(
                exact,
                observed,
                len(payload),
                cast(str, arguments["mediaType"]),
                NOW,
                creation_context=cast(Mapping[str, Any], arguments["creationContext"]),
                user_metadata=cast(Mapping[str, str], arguments["userMetadata"]),
                provenance=cast(Mapping[str, Any], arguments["provenance"]),
            )
            self.objects[object_id] = (metadata, payload)
            return self._result(expression, resource, {"metadata": metadata.to_dict()})
        if method in {"stat", "get", "read_range"}:
            reference = ObjectReference(
                ResourceReference.parse(
                    cast(
                        Mapping[str, object],
                        cast(Mapping[str, object], arguments["reference"])["resourceRef"],
                    )
                ),
                cast(str, cast(Mapping[str, object], arguments["reference"])["objectId"]),
                cast(str | None, cast(Mapping[str, object], arguments["reference"]).get("digest")),
            )
            stored = self.objects.get(reference.object_id)
            if stored is None or (
                reference.digest is not None and stored[0].digest != reference.digest
            ):
                raise ObjectNotFound()
            metadata, payload = stored
            if method == "stat":
                return self._result(expression, resource, {"metadata": metadata.to_dict()})
            range_value: dict[str, object] | None = None
            if method == "read_range":
                selected = ByteRange.from_mapping(
                    cast(Mapping[str, object], arguments["range"])
                ).resolve(len(payload))
                payload = payload[selected.start : selected.end + 1]
                range_value = selected.to_dict()
            payload_ref = self.payloads.register(
                FactoryPayloadSource(lambda raw=payload: BytesIO(raw)),
                expected_length=len(payload),
                expected_digest=None if method == "read_range" else metadata.digest,
            )
            data: dict[str, object] = {
                "metadata": metadata.to_dict(),
                "payload": payload_ref.to_dict(),
            }
            if range_value is not None:
                data["range"] = range_value
            return self._result(expression, resource, data)
        if method == "list":
            prefix = cast(str, arguments["prefix"])
            limit = cast(int, arguments["limit"])
            values = [
                metadata.to_dict()
                for object_id, (metadata, _) in sorted(self.objects.items())
                if object_id.startswith(prefix)
            ][:limit]
            return self._result(expression, resource, {"items": values, "cursor": None})
        raise AssertionError(f"unsupported object method {method}")

    @staticmethod
    def _matches(
        records: Any,
        where: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in records
            if all(item.get(field) == value for field, value in where.items())
        ]

    @staticmethod
    def _result(
        expression: Expression,
        resource: ResourceRef,
        data: object,
    ) -> OperationResult:
        return OperationResult(
            data=cast(Any, data),
            catalog=expression.catalog,
            operation_contract=f"meridian.{expression.catalog}.{expression.method}",
            operation_version="1.0.0",
            resources=(resource,),
            request_id="test-request",
            execution_id="test-execution",
            operation_fingerprint=FINGERPRINT,
            registry_fingerprint=FINGERPRINT,
            capability_fingerprint=FINGERPRINT,
        )


def _configuration_schema() -> SchemaDocument:
    return SchemaDocument(
        ref=SchemaReference(
            CatalogName.STRUCTURED,
            "application",
            "service-config",
            "1.0.0",
        ),
        semantic_kind=SemanticKind.RELATIONAL,
        fields=(
            FieldDefinition("endpoint", LogicalType.parse("string")),
            FieldDefinition("replicas", LogicalType.parse("int64")),
        ),
        identity=("endpoint",),
        extensions={
            "org.meridian.profile/v1": RelationalProfile().to_dict(),
        },
    )


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def store(runtime: FakeRuntime) -> ResourceStore:
    return ResourceStore(
        runtime,
        payload_registry=runtime.payloads,
        clock=lambda: NOW,
    )


@pytest.fixture
def schema_ref() -> str:
    return "application.service-config@1.0.0"


@pytest.fixture
def valid_config() -> dict[str, object]:
    return {"endpoint": "https://service.example", "replicas": 3}
