# SPDX-License-Identifier: Apache-2.0
"""Canonical, bounded values shared by the plugin's public contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast

from meridian_storage.semantics import JsonValue, canonical_json_bytes

type FrozenJson = (
    None | bool | int | float | str | tuple[FrozenJson, ...] | Mapping[str, FrozenJson]
)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_CHANNEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def bounded_string(value: object, field_name: str, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-empty printable string")
    return value


def logical_name(value: object, field_name: str) -> str:
    selected = bounded_string(value, field_name, 256)
    if _NAME_RE.fullmatch(selected) is None:
        raise ValueError(f"{field_name} is not a valid logical name")
    return selected


def channel_name(value: object) -> str:
    selected = bounded_string(value, "channel", 128)
    if _CHANNEL_RE.fullmatch(selected) is None:
        raise ValueError("channel is not a valid bounded logical name")
    return selected


def digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError("digest must use sha256:<lowercase-hex>")
    return value


def media_type(value: object) -> str:
    selected = bounded_string(value, "media type", 255)
    if "/" not in selected or any(character.isspace() for character in selected):
        raise ValueError("media type must be an Internet media type")
    return selected


def utc_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    selected = bounded_string(value, "timestamp", 64)
    try:
        parsed = datetime.strptime(selected, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError("timestamp must be UTC RFC 3339 with microseconds") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_value(value: object) -> JsonValue:
    """Round-trip through Meridian canonical JSON and return detached JSON data."""

    encoded = canonical_json_bytes(cast(JsonValue, value))
    return cast(JsonValue, json.loads(encoded.decode("utf-8")))


def canonical_mapping(
    value: Mapping[str, object],
    field_name: str,
    *,
    maximum_entries: int | None = None,
    maximum_bytes: int | None = None,
) -> Mapping[str, FrozenJson]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if maximum_entries is not None and len(value) > maximum_entries:
        raise ValueError(f"{field_name} may contain at most {maximum_entries} entries")
    normalized = canonical_value(dict(value))
    if not isinstance(normalized, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    if maximum_bytes is not None and len(canonical_json_bytes(normalized)) > maximum_bytes:
        raise ValueError(f"{field_name} exceeds {maximum_bytes} canonical JSON bytes")
    return cast(Mapping[str, FrozenJson], freeze_json(normalized))


def string_mapping(
    value: Mapping[str, str],
    field_name: str,
    *,
    maximum_entries: int = 64,
) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or len(value) > maximum_entries:
        raise ValueError(f"{field_name} may contain at most {maximum_entries} entries")
    result = {
        bounded_string(key, f"{field_name} key", 128): bounded_string(
            item, f"{field_name} value", 512
        )
        for key, item in value.items()
    }
    return MappingProxyType(dict(sorted(result.items())))


def freeze_json(value: JsonValue) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_json(item) for key, item in sorted(value.items())})
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    return cast(None | bool | int | float | str, value)


def thaw_json(value: FrozenJson) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def sequence(value: object, field_name: str, maximum: int = 128) -> Sequence[object]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an array")
    if len(value) > maximum:
        raise ValueError(f"{field_name} may contain at most {maximum} entries")
    return value


__all__ = [
    "FrozenJson",
    "bounded_string",
    "canonical_mapping",
    "canonical_value",
    "channel_name",
    "digest",
    "freeze_json",
    "logical_name",
    "media_type",
    "sequence",
    "string_mapping",
    "thaw_json",
    "utc_timestamp",
]
