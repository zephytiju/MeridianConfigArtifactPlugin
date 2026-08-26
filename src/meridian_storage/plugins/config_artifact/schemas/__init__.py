# SPDX-License-Identifier: Apache-2.0
"""Packaged standard Schema provider."""

from .provider import (
    CHANNEL_RESOURCE,
    METADATA_RESOURCE,
    OBJECT_RESOURCE,
    ORPHAN_RESOURCE,
    PROVENANCE_RESOURCE,
    RESOURCE_NAMESPACE,
    SCHEMA_PROVIDER_CONTRACT_VERSION,
    SCHEMA_PROVIDER_ID,
    ConfigArtifactSchemaProvider,
    orphan_candidate_schema,
    provenance_schema,
    resource_channel_schema,
    schema_documents,
    stored_resource_schema,
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
