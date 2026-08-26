#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify locked contracts, exact released pins, and provider-neutral boundaries."""

from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from importlib import metadata
from inspect import signature
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from meridian_storage import __version__ as core_version
from meridian_storage.object_common import __version__ as object_version
from meridian_storage.plugins.config_artifact import (
    ArtifactConsumer,
    ConfigArtifactErrorCode,
    ConfigArtifactPluginFactory,
    ConfigurationPublisher,
    PublicationReceipt,
    __version__,
)
from meridian_storage.plugins.config_artifact.schemas import ConfigArtifactSchemaProvider
from meridian_storage.query import __version__ as query_version
from meridian_storage.semantics import __version__ as semantics_version
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PINS = {
    "meridian-storage-core": "==1.0.0",
    "meridian-storage-object-common": "==1.0.0",
    "meridian-storage-query": "==1.0.0",
    "meridian-storage-semantics": "==1.0.0",
}
FORBIDDEN_IMPORTS = (
    "boto",
    "botocore",
    "meridian_storage.adapters",
    "meridian_storage.spi.adapters",
    "oci",
    "s3fs",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _distribution_pins() -> dict[str, str]:
    distribution = metadata.distribution("meridian-plugin-config-artifact")
    result: dict[str, str] = {}
    for raw in distribution.requires or ():
        requirement = Requirement(raw)
        if requirement.name in EXPECTED_PINS and requirement.marker is None:
            result[requirement.name] = str(requirement.specifier)
    _require(result == EXPECTED_PINS, f"released Meridian pins differ: {result!r}")
    return result


def _verify_import_boundary() -> int:
    checked = 0
    for path in sorted((ROOT / "src").rglob("*.py")):
        checked += 1
        source = path.read_text(encoding="utf-8")
        _require("NativeQuery" not in source, f"post-V1 NativeQuery appears in {path}")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = (node.module,)
            else:
                continue
            _require(
                not any(
                    name == forbidden or name.startswith(f"{forbidden}.")
                    for name in names
                    for forbidden in FORBIDDEN_IMPORTS
                ),
                f"consumer source imports an Adapter, Engine, or provider SDK: {path}",
            )
    return checked


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    compatibility = _load_json(ROOT / "compatibility.json")
    public = _load_json(ROOT / "contracts/public-api/meridian-config-artifact.v1.json")
    model_paths = sorted((ROOT / "contracts/models").glob("*.schema.json"))
    for path in model_paths:
        Draft202012Validator.check_schema(_load_json(path))

    _require(project["name"] == "meridian-plugin-config-artifact", "name differs")
    _require(project["version"] == __version__ == "1.0.0", "version differs")
    _require(project["license"] == "Apache-2.0", "license differs")
    _require(compatibility["catalogsDefined"] == [], "plugin must define no Catalog")
    _require(
        compatibility["catalogsConsumed"] == ["object", "structured"],
        "plugin must consume only object and structured Catalogs",
    )

    manifest = ConfigArtifactPluginFactory().manifest()
    _require(manifest.plugin_id == public["pluginId"], "plugin id differs")
    _require(manifest.plugin_version == __version__, "plugin version differs")
    _require(manifest.plugin_contract_version == "1.0.0", "plugin contract differs")
    configuration_parameters = signature(ConfigurationPublisher.publish).parameters
    _require("schema" in configuration_parameters, "locked configuration schema argument differs")
    _require(
        "payload_schema" not in configuration_parameters,
        "unapproved configuration argument is exposed",
    )
    _require(hasattr(ConfigurationPublisher, "promote"), "configuration promotion is absent")
    _require(hasattr(ArtifactConsumer, "range_read"), "locked range_read method is absent")
    _require(isinstance(PublicationReceipt.ref, property), "publication ref property is absent")
    bundle = ConfigArtifactSchemaProvider().load()
    _require(bundle.provider_id == public["schemaProviderId"], "schema provider differs")
    _require(len(bundle.resources) == 5 and len(bundle.schemas) == 4, "bundle differs")
    _require(
        {resource.ref.catalog for resource in bundle.resources} == {"object", "structured"},
        "bundle contains an unapproved Catalog",
    )

    versions = {
        "meridian-storage-core": core_version,
        "meridian-storage-object-common": object_version,
        "meridian-storage-query": query_version,
        "meridian-storage-semantics": semantics_version,
    }
    _require(set(versions.values()) == {"1.0.0"}, "released Meridian versions differ")
    _require(
        compatibility["releasedDependencies"] == versions,
        "compatibility ledger versions differ",
    )
    pins = _distribution_pins()
    checked_source_files = _verify_import_boundary()
    _require(len(tuple(ROOT.glob("pyproject.toml"))) == 1, "repository must have one project")
    _require(
        not (ROOT / "src/meridian_storage/__init__.py").exists(),
        "distribution must not own the root PEP 420 namespace",
    )
    _require(
        not (ROOT / "src/meridian_storage/plugins/__init__.py").exists(),
        "distribution must not own the plugins PEP 420 namespace",
    )

    evidence = {
        "formatVersion": "meridian.config-artifact.conformance.v1",
        "package": project["name"],
        "version": __version__,
        "contracts": {
            "models": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in model_paths
            },
            "publicApi": hashlib.sha256(
                (ROOT / "contracts/public-api/meridian-config-artifact.v1.json").read_bytes()
            ).hexdigest(),
        },
        "errors": sorted(item.value for item in ConfigArtifactErrorCode),
        "installedVersions": versions,
        "pins": pins,
        "sourceFilesChecked": checked_source_files,
        "status": "passed",
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    output = {**evidence, "fingerprint": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
