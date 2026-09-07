# SPDX-License-Identifier: Apache-2.0
"""Standard V1 Schemas, Collections and Object Resource requirements."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, cast

from meridian_storage import ResourceRef
from meridian_storage.object_common import (
    GUARANTEE_BOUNDED_PREFIX_LIST,
    GUARANTEE_CONDITIONAL_CREATE,
    GUARANTEE_DIGEST_SHA256,
    GUARANTEE_DIGEST_VERIFICATION,
    GUARANTEE_METADATA_AFTER_COMMIT,
    GUARANTEE_RANGE_READ,
    GUARANTEE_STREAMING,
    object_requirement,
)
from meridian_storage.registry import (
    CapabilityRequirement,
    NamespaceDefinition,
    ResourceBundle,
    ResourceDefinition,
)
from meridian_storage.semantics import (
    PROFILE_EXTENSION_KEY,
    CatalogName,
    FieldDefinition,
    FrozenJson,
    IndexDefinition,
    LogicalType,
    RelationalProfile,
    SchemaDocument,
    SchemaReference,
    SemanticKind,
    validate_schema,
)

from .._version import __version__

SCHEMA_PROVIDER_ID: Final = "meridian.plugin.config-artifact"
SCHEMA_PROVIDER_CONTRACT_VERSION: Final = "1.0.0"
RESOURCE_NAMESPACE: Final = "resources"

METADATA_RESOURCE: Final = ResourceRef("structured", RESOURCE_NAMESPACE, "metadata")
CHANNEL_RESOURCE: Final = ResourceRef("structured", RESOURCE_NAMESPACE, "channels")
PROVENANCE_RESOURCE: Final = ResourceRef("structured", RESOURCE_NAMESPACE, "provenance")
ORPHAN_RESOURCE: Final = ResourceRef("structured", RESOURCE_NAMESPACE, "orphan-candidates")
OBJECT_RESOURCE: Final = ResourceRef("object", RESOURCE_NAMESPACE, "objects")


def _field(
    name: str,
    logical_type: str | Mapping[str, object],
    *,
    nullable: bool = False,
    mutable: bool = False,
    constraints: Mapping[str, object] | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        name=name,
        logical_type=LogicalType.parse(logical_type),
        nullable=nullable,
        mutable=mutable,
        constraints=cast(Mapping[str, FrozenJson], constraints or {}),
    )


def _schema(
    name: str,
    fields: tuple[FieldDefinition, ...],
    *,
    identity: tuple[str, ...],
    indexes: tuple[IndexDefinition, ...],
    alternate_keys: tuple[tuple[str, ...], ...] = (),
) -> SchemaDocument:
    document = SchemaDocument(
        ref=SchemaReference(CatalogName.STRUCTURED, RESOURCE_NAMESPACE, name, "1.0.0"),
        semantic_kind=SemanticKind.RELATIONAL,
        fields=fields,
        identity=identity,
        indexes=indexes,
        consistency="strong",
        retention_label="config-artifact-metadata",
        extensions=cast(
            Mapping[str, FrozenJson],
            {
                PROFILE_EXTENSION_KEY: RelationalProfile(
                    alternate_keys=alternate_keys,
                ).to_dict()
            },
        ),
        compatibility={"policy": "backward"},
    )
    validate_schema(document)
    return document


def stored_resource_schema() -> SchemaDocument:
    fields = (
        _field("formatVersion", "string", constraints={"maxLength": 128}),
        _field("resourceId", "string", constraints={"maxLength": 256}),
        _field("namespace", "string", constraints={"maxLength": 256}),
        _field("kind", "string", constraints={"maxLength": 256}),
        _field("name", "string", constraints={"maxLength": 256}),
        _field("version", "string", constraints={"maxLength": 256}),
        _field(
            "profile",
            {"kind": "enum", "values": ["configuration", "artifact"]},
        ),
        _field(
            "state",
            {"kind": "enum", "values": ["DRAFT", "PUBLISHED", "DEPRECATED"]},
            mutable=True,
        ),
        _field("mediaType", "string", constraints={"maxLength": 255}),
        _field(
            "digest",
            "string",
            constraints={"pattern": "^sha256:[0-9a-f]{64}$"},
        ),
        _field("byteLength", "int64", constraints={"min": 0}),
        _field("objectRef", "objectRef", nullable=True),
        _field("payload", "json", nullable=True),
        _field("payloadSchema", "json", nullable=True),
        _field("labels", "json"),
        _field("annotations", "json"),
        _field("provenance", "json", nullable=True),
        _field("createdBy", "string", constraints={"maxLength": 512}),
        _field("createdAt", "utcTimestamp"),
        _field("supersedes", "string", nullable=True, constraints={"maxLength": 256}),
        _field("immutable", "boolean"),
        _field("versionOrder", "int64", nullable=True, constraints={"min": 0}),
    )
    return _schema(
        "stored-resource",
        fields,
        identity=("resourceId",),
        alternate_keys=(("namespace", "kind", "name", "version"),),
        indexes=(
            IndexDefinition(
                "identity_lookup",
                "btree",
                ("namespace", "kind", "name", "version"),
                unique=True,
            ),
            IndexDefinition(
                "published_versions",
                "btree",
                ("namespace", "kind", "name", "state", "versionOrder"),
            ),
        ),
    )


def resource_channel_schema() -> SchemaDocument:
    fields = (
        _field("formatVersion", "string", constraints={"maxLength": 128}),
        _field("channelVersionId", "string", constraints={"maxLength": 256}),
        _field("namespace", "string", constraints={"maxLength": 256}),
        _field("kind", "string", constraints={"maxLength": 256}),
        _field("name", "string", constraints={"maxLength": 256}),
        _field("channel", "string", constraints={"maxLength": 128}),
        _field("targetResourceId", "string", constraints={"maxLength": 256}),
        _field("pointerVersion", "int64", constraints={"min": 1}),
        _field("actor", "string", constraints={"maxLength": 512}),
        _field("updatedAt", "utcTimestamp"),
    )
    return _schema(
        "resource-channel",
        fields,
        identity=("channelVersionId",),
        alternate_keys=(("namespace", "kind", "name", "channel", "pointerVersion"),),
        indexes=(
            IndexDefinition(
                "channel_latest",
                "btree",
                ("namespace", "kind", "name", "channel", "pointerVersion"),
                unique=True,
            ),
        ),
    )


def provenance_schema() -> SchemaDocument:
    fields = (
        _field("formatVersion", "string", constraints={"maxLength": 128}),
        _field("provenanceId", "string", constraints={"maxLength": 256}),
        _field("resourceId", "string", constraints={"maxLength": 256}),
        _field("document", "json"),
        _field("createdAt", "utcTimestamp"),
    )
    return _schema(
        "provenance",
        fields,
        identity=("provenanceId",),
        alternate_keys=(("resourceId",),),
        indexes=(IndexDefinition("resource_lookup", "btree", ("resourceId",), unique=True),),
    )


def orphan_candidate_schema() -> SchemaDocument:
    fields = (
        _field("formatVersion", "string", constraints={"maxLength": 128}),
        _field("candidateId", "string", constraints={"maxLength": 256}),
        _field("resourceId", "string", constraints={"maxLength": 256}),
        _field("objectRef", "objectRef"),
        _field(
            "digest",
            "string",
            constraints={"pattern": "^sha256:[0-9a-f]{64}$"},
        ),
        _field("byteLength", "int64", constraints={"min": 0}),
        _field("reason", "string", constraints={"maxLength": 512}),
        _field("discoveredAt", "utcTimestamp"),
        _field(
            "state",
            {"kind": "enum", "values": ["DISCOVERED", "RECORDED", "RESOLVED"]},
            mutable=True,
        ),
    )
    return _schema(
        "orphan-candidate",
        fields,
        identity=("candidateId",),
        indexes=(
            IndexDefinition(
                "orphan_queue",
                "btree",
                ("state", "discoveredAt", "candidateId"),
            ),
        ),
    )


def schema_documents() -> tuple[SchemaDocument, ...]:
    return (
        stored_resource_schema(),
        resource_channel_schema(),
        provenance_schema(),
        orphan_candidate_schema(),
    )


def _structured_requirements(
    *methods: str,
    transactional: bool = True,
) -> tuple[CapabilityRequirement, ...]:
    requirements = [
        CapabilityRequirement(
            f"meridian.structured.{method}", "2.0.0" if method == "put" else "1.0.0"
        )
        for method in methods
    ]
    if transactional:
        requirements.append(
            CapabilityRequirement(
                "meridian.transaction",
                "1.0.0",
                guarantees=("atomic", "no-dirty-reads"),
            )
        )
    return tuple(requirements)


class ConfigArtifactSchemaProvider:
    """Core schema-provider entry point for the canonical ResourceStore layout."""

    provider_id = SCHEMA_PROVIDER_ID
    provider_contract_version = SCHEMA_PROVIDER_CONTRACT_VERSION

    def load(self) -> ResourceBundle:
        documents = schema_documents()
        schemas = tuple(document.to_core_definition() for document in documents)
        schema_by_name = {schema.ref.name: schema.ref for schema in schemas}
        return ResourceBundle(
            provider_id=self.provider_id,
            provider_version=__version__,
            provider_contract_version=self.provider_contract_version,
            namespaces=(
                NamespaceDefinition(
                    "structured",
                    RESOURCE_NAMESPACE,
                    {"owner": "config-artifact"},
                ),
                NamespaceDefinition(
                    "object",
                    RESOURCE_NAMESPACE,
                    {"owner": "config-artifact"},
                ),
            ),
            schemas=schemas,
            resources=(
                ResourceDefinition(
                    METADATA_RESOURCE,
                    profile="relational",
                    schema=schema_by_name["stored-resource"],
                    requirements=_structured_requirements("get", "patch", "put", "query"),
                    required_scope=("tenant",),
                    related_resources=(CHANNEL_RESOURCE, PROVENANCE_RESOURCE, OBJECT_RESOURCE),
                ),
                ResourceDefinition(
                    CHANNEL_RESOURCE,
                    profile="relational",
                    schema=schema_by_name["resource-channel"],
                    requirements=_structured_requirements("get", "put", "query"),
                    required_scope=("tenant",),
                    related_resources=(METADATA_RESOURCE,),
                ),
                ResourceDefinition(
                    PROVENANCE_RESOURCE,
                    profile="relational",
                    schema=schema_by_name["provenance"],
                    requirements=_structured_requirements("get", "put", "query"),
                    required_scope=("tenant",),
                    related_resources=(METADATA_RESOURCE,),
                ),
                ResourceDefinition(
                    ORPHAN_RESOURCE,
                    profile="relational",
                    schema=schema_by_name["orphan-candidate"],
                    requirements=_structured_requirements("get", "patch", "put", "query"),
                    required_scope=("tenant",),
                    related_resources=(METADATA_RESOURCE, OBJECT_RESOURCE),
                ),
                ResourceDefinition(
                    OBJECT_RESOURCE,
                    profile="artifact",
                    requirements=(
                        object_requirement(
                            "put",
                            guarantees=(
                                GUARANTEE_CONDITIONAL_CREATE,
                                GUARANTEE_DIGEST_SHA256,
                                GUARANTEE_METADATA_AFTER_COMMIT,
                                GUARANTEE_STREAMING,
                            ),
                        ),
                        object_requirement(
                            "get",
                            guarantees=(GUARANTEE_DIGEST_VERIFICATION, GUARANTEE_STREAMING),
                        ),
                        object_requirement("stat"),
                        object_requirement(
                            "read_range",
                            guarantees=(GUARANTEE_DIGEST_VERIFICATION, GUARANTEE_RANGE_READ),
                        ),
                        object_requirement("list", guarantees=(GUARANTEE_BOUNDED_PREFIX_LIST,)),
                    ),
                    required_scope=("tenant",),
                    related_resources=(METADATA_RESOURCE, ORPHAN_RESOURCE),
                ),
            ),
            extensions={
                "design.hldRevision": 56,
                "design.catalogRevision": 70,
                "design.configArtifactLldRevision": 44,
                "distribution": "meridian-plugin-config-artifact",
                "catalogs": ["object", "structured"],
            },
        )


__all__ = [
    "CHANNEL_RESOURCE",
    "METADATA_RESOURCE",
    "OBJECT_RESOURCE",
    "ORPHAN_RESOURCE",
    "PROVENANCE_RESOURCE",
    "RESOURCE_NAMESPACE",
    "SCHEMA_PROVIDER_CONTRACT_VERSION",
    "SCHEMA_PROVIDER_ID",
    "ConfigArtifactSchemaProvider",
    "orphan_candidate_schema",
    "provenance_schema",
    "resource_channel_schema",
    "schema_documents",
    "stored_resource_schema",
]
