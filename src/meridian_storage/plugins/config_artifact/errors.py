# SPDX-License-Identifier: Apache-2.0
"""Stable, redacted Configuration and Artifact plugin failures."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from meridian_storage import ErrorCategory, MeridianError, SafeCause


class ConfigArtifactErrorCode(StrEnum):
    INVALID_PAYLOAD = "MERIDIAN_CONFIG_ARTIFACT_INVALID_PAYLOAD"
    IDENTITY_CONFLICT = "MERIDIAN_CONFIG_ARTIFACT_IDENTITY_CONFLICT"
    STALE_CHANNEL_POINTER = "MERIDIAN_CONFIG_ARTIFACT_STALE_CHANNEL_POINTER"
    INCOMPATIBLE_PROFILE = "MERIDIAN_CONFIG_ARTIFACT_INCOMPATIBLE_PROFILE"
    RESOURCE_NOT_FOUND = "MERIDIAN_CONFIG_ARTIFACT_RESOURCE_NOT_FOUND"
    MISSING_OBJECT = "MERIDIAN_CONFIG_ARTIFACT_MISSING_OBJECT"
    DIGEST_MISMATCH = "MERIDIAN_CONFIG_ARTIFACT_DIGEST_MISMATCH"
    FORBIDDEN_DELETION = "MERIDIAN_CONFIG_ARTIFACT_FORBIDDEN_DELETION"
    INCOMPLETE_PUBLICATION = "MERIDIAN_CONFIG_ARTIFACT_INCOMPLETE_PUBLICATION"
    INVALID_RESULT = "MERIDIAN_CONFIG_ARTIFACT_INVALID_RESULT"
    SCHEMA_UNAVAILABLE = "MERIDIAN_CONFIG_ARTIFACT_SCHEMA_UNAVAILABLE"


class ConfigArtifactError(MeridianError):
    """Base class for package-owned public failures."""

    def __init__(
        self,
        code: ConfigArtifactErrorCode,
        message: str,
        *,
        category: ErrorCategory,
        **details: Any,
    ) -> None:
        super().__init__(code, message, category=category, **details)


class InvalidPayload(ConfigArtifactError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            ConfigArtifactErrorCode.INVALID_PAYLOAD,
            message,
            category=ErrorCategory.VALIDATION,
            **details,
        )


class IdentityConflict(ConfigArtifactError):
    def __init__(
        self, message: str = "resource identity already has another digest", **details: Any
    ) -> None:
        super().__init__(
            ConfigArtifactErrorCode.IDENTITY_CONFLICT,
            message,
            category=ErrorCategory.CONFLICT,
            **details,
        )


class StaleChannelPointer(ConfigArtifactError):
    def __init__(self, message: str = "channel pointer version is stale", **details: Any) -> None:
        super().__init__(
            ConfigArtifactErrorCode.STALE_CHANNEL_POINTER,
            message,
            category=ErrorCategory.CONFLICT,
            **details,
        )


class IncompatibleProfile(ConfigArtifactError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            ConfigArtifactErrorCode.INCOMPATIBLE_PROFILE,
            message,
            category=ErrorCategory.COMPATIBILITY,
            **details,
        )


class ResourceNotFound(ConfigArtifactError):
    def __init__(self, message: str = "stored resource was not found", **details: Any) -> None:
        super().__init__(
            ConfigArtifactErrorCode.RESOURCE_NOT_FOUND,
            message,
            category=ErrorCategory.NOT_FOUND,
            **details,
        )


class MissingObject(ConfigArtifactError):
    def __init__(
        self, message: str = "published artifact Object is missing", **details: Any
    ) -> None:
        super().__init__(
            ConfigArtifactErrorCode.MISSING_OBJECT,
            message,
            category=ErrorCategory.NOT_FOUND,
            **details,
        )


class ArtifactDigestMismatch(ConfigArtifactError):
    def __init__(
        self, message: str = "artifact digest verification failed", **details: Any
    ) -> None:
        super().__init__(
            ConfigArtifactErrorCode.DIGEST_MISMATCH,
            message,
            category=ErrorCategory.CORRUPTION,
            **details,
        )


class ForbiddenDeletion(ConfigArtifactError):
    def __init__(
        self, message: str = "published resource deletion is forbidden", **details: Any
    ) -> None:
        super().__init__(
            ConfigArtifactErrorCode.FORBIDDEN_DELETION,
            message,
            category=ErrorCategory.CONSTRAINT,
            **details,
        )


class IncompletePublication(ConfigArtifactError):
    def __init__(self, message: str, **details: Any) -> None:
        details.setdefault("retryable", True)
        super().__init__(
            ConfigArtifactErrorCode.INCOMPLETE_PUBLICATION,
            message,
            category=ErrorCategory.TRANSIENT,
            **details,
        )


class InvalidRepositoryResult(ConfigArtifactError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            ConfigArtifactErrorCode.INVALID_RESULT,
            message,
            category=ErrorCategory.CORRUPTION,
            **details,
        )


class SchemaUnavailable(ConfigArtifactError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(
            ConfigArtifactErrorCode.SCHEMA_UNAVAILABLE,
            message,
            category=ErrorCategory.CONFIGURATION,
            **details,
        )


def safe_cause(exc: BaseException) -> SafeCause:
    if isinstance(exc, MeridianError):
        return SafeCause(type=type(exc).__name__, code=exc.code)
    return SafeCause.from_exception(exc)


__all__ = [
    "ArtifactDigestMismatch",
    "ConfigArtifactError",
    "ConfigArtifactErrorCode",
    "ForbiddenDeletion",
    "IdentityConflict",
    "IncompatibleProfile",
    "IncompletePublication",
    "InvalidPayload",
    "InvalidRepositoryResult",
    "MissingObject",
    "ResourceNotFound",
    "SchemaUnavailable",
    "StaleChannelPointer",
    "safe_cause",
]
