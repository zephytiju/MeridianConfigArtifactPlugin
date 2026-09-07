# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from meridian_storage.object_common import (
    GUARANTEE_CONDITIONAL_CREATE,
    GUARANTEE_DIGEST_VERIFICATION,
)
from meridian_storage.plugins.config_artifact import ConfigArtifactPluginFactory
from meridian_storage.plugins.config_artifact.schemas import (
    ConfigArtifactSchemaProvider,
    schema_documents,
)
from meridian_storage.semantics import validate_schema


def test_schema_bundle_is_complete_and_valid() -> None:
    documents = schema_documents()
    assert {document.ref.name for document in documents} == {
        "stored-resource",
        "resource-channel",
        "provenance",
        "orphan-candidate",
    }
    for document in documents:
        validate_schema(document)
        assert document.ref.version == "1.0.0"
        assert document.fingerprint.startswith("sha256:")
        assert document.compatibility == {"policy": "backward"}

    bundle = ConfigArtifactSchemaProvider().load()
    assert bundle.provider_id == "meridian.plugin.config-artifact"
    assert len(bundle.resources) == 5
    assert len(bundle.schemas) == 4
    assert {resource.ref.catalog for resource in bundle.resources} == {
        "structured",
        "object",
    }
    object_resource = next(item for item in bundle.resources if item.ref.catalog == "object")
    guarantees = {
        guarantee
        for requirement in object_resource.requirements
        for guarantee in requirement.guarantees
    }
    assert GUARANTEE_CONDITIONAL_CREATE in guarantees
    assert GUARANTEE_DIGEST_VERIFICATION in guarantees
    replay = ConfigArtifactSchemaProvider().load()
    assert replay.to_dict() == bundle.to_dict()
    assert replay.fingerprint == bundle.fingerprint
    assert bundle.extensions["distribution"] == "meridian-plugin-config-artifact"
    assert bundle.extensions["design.configArtifactLldRevision"] == 44


def test_plugin_manifest_is_locked_and_provider_neutral() -> None:
    factory = ConfigArtifactPluginFactory()
    manifest = factory.manifest()
    assert factory.plugin_id == "config-artifact"
    assert manifest.plugin_contract_version == "1.0.0"
    assert manifest.core_contract == "1.x"
    assert manifest.extensions["catalogs"] == "structured,object"
    assert manifest.extensions["design.hldRevision"] == "56"
    assert manifest.extensions["design.configArtifactLldRevision"] == "44"
    assert manifest.extensions["distribution"] == "meridian-plugin-config-artifact"
