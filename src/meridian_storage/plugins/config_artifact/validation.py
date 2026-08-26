# SPDX-License-Identifier: Apache-2.0
"""Configuration payload validation through released Meridian Schemas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast, runtime_checkable

from meridian_storage import MeridianError
from meridian_storage.semantics import (
    FrozenJson,
    JsonValue,
    SchemaDocument,
    validate_record,
)

from ._runtime import MeridianRuntime
from .errors import InvalidPayload, SchemaUnavailable, safe_cause
from .models import PayloadSchemaRef


@runtime_checkable
class PayloadValidator(Protocol):
    def validate(
        self,
        payload: Mapping[str, object],
        schema: PayloadSchemaRef,
    ) -> Mapping[str, FrozenJson]: ...


class MeridianPayloadValidator:
    """Resolve an exact registry Schema and apply logical validation locally."""

    def __init__(self, meridian: MeridianRuntime) -> None:
        self._meridian = meridian

    def validate(
        self,
        payload: Mapping[str, object],
        schema: PayloadSchemaRef,
    ) -> Mapping[str, FrozenJson]:
        try:
            handle = self._meridian.schema(
                schema.catalog,
                schema.namespace,
                schema.name,
                schema.version,
            )
            document = SchemaDocument.from_definition(
                catalog=schema.catalog,
                namespace=schema.namespace,
                name=schema.name,
                version=schema.version,
                definition=cast(Mapping[str, object], handle.definition),
            )
        except (KeyError, MeridianError, TypeError, ValueError) as exc:
            raise SchemaUnavailable(
                "configuration payload Schema is unavailable or invalid",
                resource_ref=schema.canonical,
                cause=safe_cause(exc),
            ) from exc
        try:
            return validate_record(document, payload)
        except (MeridianError, TypeError, ValueError) as exc:
            raise InvalidPayload(
                "configuration payload does not satisfy its exact Schema",
                resource_ref=schema.canonical,
                cause=safe_cause(exc),
            ) from exc


class CallablePayloadValidator:
    """Explicit adapter for applications that already own a Schema validator."""

    def __init__(self, validator: PayloadValidator) -> None:
        if not isinstance(validator, PayloadValidator):
            raise TypeError("validator must implement PayloadValidator")
        self._validator = validator

    def validate(
        self,
        payload: Mapping[str, object],
        schema: PayloadSchemaRef,
    ) -> Mapping[str, FrozenJson]:
        return self._validator.validate(payload, schema)


def json_payload(value: Mapping[str, FrozenJson]) -> Mapping[str, JsonValue]:
    return cast(Mapping[str, JsonValue], value)


__all__ = ["CallablePayloadValidator", "MeridianPayloadValidator", "PayloadValidator"]
