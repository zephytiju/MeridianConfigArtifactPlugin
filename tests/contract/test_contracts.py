# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from meridian_storage.plugins.config_artifact import (
    PayloadSchemaRef,
    ResourceIdentity,
    ResourceProfile,
    ResourceState,
    StoredResourceV1,
    compatibility_document,
    orphan_candidate_contract,
    provenance_contract,
    public_api_contract,
    resource_channel_contract,
    stored_resource_contract,
)
from meridian_storage.semantics import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.contract
def test_packaged_contracts_are_valid_json_schemas() -> None:
    for path in sorted((ROOT / "contracts" / "models").glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(document)
    api = public_api_contract()
    assert api["distribution"] == "meridian-plugin-config-artifact"
    assert api["entryPoints"] == {
        "meridian_storage.plugins": {
            "config-artifact": (
                "meridian_storage.plugins.config_artifact.plugin:ConfigArtifactPluginFactory"
            )
        },
        "meridian_storage.schemas": {
            "config-artifact": (
                "meridian_storage.plugins.config_artifact.schemas:ConfigArtifactSchemaProvider"
            )
        },
    }
    assert api["catalogs"] == {
        "structured": ["get", "patch", "put", "query"],
        "object": ["get", "list", "put", "read_range", "stat"],
    }
    assert api["resolutionModes"] == ["exact", "latest", "channel"]
    assert api["resourceStoreSurfaces"] == [
        "configurations",
        "artifacts",
        "publisher",
        "consumer",
    ]
    assert "range_read" in api["artifactMethods"]
    assert "promote" in api["configurationMethods"]


@pytest.mark.contract
def test_resource_wire_record_validates_against_language_neutral_contract() -> None:
    payload = {"endpoint": "https://example", "replicas": 2}
    encoded = canonical_json_bytes(payload)
    identity = ResourceIdentity("ns", "service", "api", "1")
    resource = StoredResourceV1(
        resource_id=identity.resource_id,
        namespace=identity.namespace,
        kind=identity.kind,
        name=identity.name,
        version=identity.version,
        profile=ResourceProfile.CONFIGURATION,
        state=ResourceState.PUBLISHED,
        media_type="application/json",
        digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        byte_length=len(encoded),
        created_by="builder",
        created_at="2026-01-02T03:04:05.123456Z",
        payload=payload,
        payload_schema=PayloadSchemaRef("application", "service-config", "1.0.0"),
    )
    contract = stored_resource_contract()
    jsonschema.Draft202012Validator(contract).validate(resource.to_record())


@pytest.mark.contract
def test_contracts_and_compatibility_are_packaged() -> None:
    compatibility = compatibility_document()
    assert compatibility["distribution"] == "meridian-plugin-config-artifact"
    assert compatibility["version"] == "1.0.2"
    assert compatibility["lockedDesign"]["configArtifactLldRevision"] == 28
    assert compatibility["releasedDependencies"] == {
        "meridian-storage-core": "1.0.0",
        "meridian-storage-object-common": "1.0.0",
        "meridian-storage-query": "1.0.0",
        "meridian-storage-semantics": "1.0.0",
    }
    assert resource_channel_contract()["title"] == "Meridian Resource Channel V1"
    assert provenance_contract()["title"] == "Meridian Provenance V1"
    assert orphan_candidate_contract()["title"] == "Meridian Orphan Candidate V1"
