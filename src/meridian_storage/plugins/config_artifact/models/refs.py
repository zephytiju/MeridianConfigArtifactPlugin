# SPDX-License-Identifier: Apache-2.0
"""Logical package-owned resource references."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from urllib.parse import quote

from meridian_storage.semantics import JsonValue

from .._canonical import bounded_string, digest, logical_name

_RESOURCE_ID_NAMESPACE = uuid.UUID("9c554a86-783d-4e78-af85-a3f9e976489a")
_CHANNEL_ID_NAMESPACE = uuid.UUID("12d75351-ea66-45e2-b5c4-53bc97f3fa6f")
_ORPHAN_ID_NAMESPACE = uuid.UUID("7075e49b-9d7f-4134-a879-580c05b2db07")
_RESOURCE_ID_RE = re.compile(r"^rs_[0-9a-f]{32}$")


class ResourceProfile(StrEnum):
    CONFIGURATION = "configuration"
    ARTIFACT = "artifact"


class ResourceState(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True, slots=True, order=True)
class ResourceIdentity:
    namespace: str
    kind: str
    name: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", logical_name(self.namespace, "namespace"))
        object.__setattr__(self, "kind", logical_name(self.kind, "kind"))
        object.__setattr__(self, "name", logical_name(self.name, "name"))
        object.__setattr__(self, "version", bounded_string(self.version, "version", 256))

    @property
    def canonical(self) -> str:
        return (
            f"{_escaped(self.namespace)}:{_escaped(self.kind)}/"
            f"{_escaped(self.name)}@{_escaped(self.version)}"
        )

    @property
    def resource_id(self) -> str:
        return f"rs_{uuid.uuid5(_RESOURCE_ID_NAMESPACE, self.canonical).hex}"

    @property
    def object_id(self) -> str:
        return f"artifacts/{self.resource_id}"

    def to_dict(self) -> dict[str, str]:
        return {
            "namespace": self.namespace,
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True, order=True)
class PayloadSchemaRef:
    namespace: str
    name: str
    version: str
    catalog: str = "structured"

    def __post_init__(self) -> None:
        if self.catalog != "structured":
            raise ValueError("configuration payload Schema must use the structured Catalog")
        object.__setattr__(self, "namespace", logical_name(self.namespace, "schema namespace"))
        object.__setattr__(self, "name", logical_name(self.name, "schema name"))
        object.__setattr__(self, "version", bounded_string(self.version, "schema version", 128))

    @property
    def canonical(self) -> str:
        return f"{self.catalog}:{self.namespace}.{self.name}@{self.version}"

    def to_dict(self) -> dict[str, str]:
        return {
            "catalog": self.catalog,
            "namespace": self.namespace,
            "name": self.name,
            "version": self.version,
        }

    @classmethod
    def parse(cls, value: PayloadSchemaRef | str | Mapping[str, object]) -> PayloadSchemaRef:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            if set(value) != {"catalog", "namespace", "name", "version"}:
                raise ValueError("payload SchemaRef requires catalog, namespace, name and version")
            return cls(
                namespace=cast(str, value["namespace"]),
                name=cast(str, value["name"]),
                version=cast(str, value["version"]),
                catalog=cast(str, value["catalog"]),
            )
        if not isinstance(value, str) or "@" not in value:
            raise ValueError("payload SchemaRef must be '<namespace>.<name>@<version>'")
        address, version = value.rsplit("@", 1)
        catalog = "structured"
        if ":" in address:
            catalog, address = address.split(":", 1)
        if "." not in address:
            raise ValueError("payload SchemaRef must include namespace and name")
        namespace, name = address.rsplit(".", 1)
        return cls(namespace=namespace, name=name, version=version, catalog=catalog)


@dataclass(frozen=True, slots=True, order=True)
class StoredResourceRef:
    resource_id: str
    namespace: str
    kind: str
    name: str
    version: str
    profile: ResourceProfile
    digest: str

    def __post_init__(self) -> None:
        identity = ResourceIdentity(self.namespace, self.kind, self.name, self.version)
        if self.resource_id != identity.resource_id:
            raise ValueError("resource id does not match its logical identity")
        object.__setattr__(self, "namespace", identity.namespace)
        object.__setattr__(self, "kind", identity.kind)
        object.__setattr__(self, "name", identity.name)
        object.__setattr__(self, "version", identity.version)
        object.__setattr__(self, "profile", ResourceProfile(self.profile))
        object.__setattr__(self, "digest", digest(self.digest))

    @property
    def identity(self) -> ResourceIdentity:
        return ResourceIdentity(self.namespace, self.kind, self.name, self.version)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "resourceId": self.resource_id,
            **self.identity.to_dict(),
            "profile": self.profile.value,
            "digest": self.digest,
        }


def channel_version_id(
    namespace: str,
    kind: str,
    name: str,
    channel: str,
    pointer_version: int,
) -> str:
    value = (
        f"{_escaped(namespace)}:{_escaped(kind)}/{_escaped(name)}"
        f"#{_escaped(channel)}@{pointer_version}"
    )
    return f"ch_{uuid.uuid5(_CHANNEL_ID_NAMESPACE, value).hex}"


def orphan_candidate_id(resource_id: str, object_id: str, object_digest: str) -> str:
    value = "|".join(_escaped(item) for item in (resource_id, object_id, object_digest))
    return f"oc_{uuid.uuid5(_ORPHAN_ID_NAMESPACE, value).hex}"


def _escaped(value: str) -> str:
    return quote(value, safe="")


def validate_resource_id(value: object) -> str:
    if not isinstance(value, str) or _RESOURCE_ID_RE.fullmatch(value) is None:
        raise ValueError("resource id must be an opaque rs_<lowercase-hex> identifier")
    return value


__all__ = [
    "PayloadSchemaRef",
    "ResourceIdentity",
    "ResourceProfile",
    "ResourceState",
    "StoredResourceRef",
    "channel_version_id",
    "orphan_candidate_id",
]
