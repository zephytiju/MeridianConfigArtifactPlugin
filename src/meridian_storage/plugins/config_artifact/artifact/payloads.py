# SPDX-License-Identifier: Apache-2.0
"""Bounded payload registration without placing bytes in Core envelopes."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

from meridian_storage.object_common import (
    FactoryPayloadSource,
    PayloadReference,
    PayloadRegistry,
    PayloadSource,
    StreamPayloadSource,
)

from .._canonical import digest
from ..errors import InvalidPayload

ArtifactPayload = bytes | bytearray | memoryview | BinaryIO | PayloadSource | PayloadReference


@dataclass(frozen=True, slots=True)
class RegisteredPayload:
    reference: PayloadReference
    digest: str
    byte_length: int
    owned: bool


def register_payload(
    payload: ArtifactPayload | Callable[[], BinaryIO],
    registry: PayloadRegistry,
    *,
    expected_digest: str | None = None,
    expected_length: int | None = None,
) -> RegisteredPayload:
    """Register a replayable/stream payload and require a complete content identity."""

    if isinstance(payload, bytes | bytearray | memoryview):
        raw = bytes(payload)
        observed_digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        observed_length = len(raw)
        _match_declared(observed_digest, observed_length, expected_digest, expected_length)
        bytes_source = FactoryPayloadSource(lambda: BytesIO(raw))
        reference = registry.register(
            bytes_source,
            expected_digest=observed_digest,
            expected_length=observed_length,
        )
        return RegisteredPayload(reference, observed_digest, observed_length, True)

    if isinstance(payload, PayloadReference):
        selected_digest = expected_digest or payload.expected_digest
        selected_length = (
            expected_length if expected_length is not None else payload.expected_length
        )
        return RegisteredPayload(
            payload,
            _required_digest(selected_digest),
            _required_length(selected_length),
            False,
        )

    selected_digest = _required_digest(expected_digest)
    selected_length = _required_length(expected_length)
    source: PayloadSource
    if isinstance(payload, PayloadSource):
        source = payload
    elif callable(payload):
        source = FactoryPayloadSource(payload)
    elif hasattr(payload, "read"):
        source = StreamPayloadSource(payload)
    else:
        raise TypeError("artifact payload must be bytes, a binary stream, or a PayloadSource")
    reference = registry.register(
        source,
        expected_digest=selected_digest,
        expected_length=selected_length,
    )
    return RegisteredPayload(reference, selected_digest, selected_length, True)


def _required_digest(value: str | None) -> str:
    if value is None:
        raise InvalidPayload("streamed artifact publication requires expected_digest")
    try:
        return digest(value)
    except ValueError as exc:
        raise InvalidPayload("expected_digest must use sha256:<lowercase-hex>") from exc


def _required_length(value: int | None) -> int:
    if value is None:
        raise InvalidPayload("streamed artifact publication requires expected_length")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidPayload("expected_length must be a non-negative integer")
    return value


def _match_declared(
    observed_digest: str,
    observed_length: int,
    expected_digest: str | None,
    expected_length: int | None,
) -> None:
    if expected_digest is not None and _required_digest(expected_digest) != observed_digest:
        raise InvalidPayload("artifact bytes do not match expected_digest")
    if expected_length is not None and _required_length(expected_length) != observed_length:
        raise InvalidPayload("artifact bytes do not match expected_length")


__all__ = ["ArtifactPayload", "RegisteredPayload", "register_payload"]
