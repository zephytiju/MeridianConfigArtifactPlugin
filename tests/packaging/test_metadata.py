# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re

from importlib.metadata import distribution, metadata, version
from pathlib import Path

import pytest

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


@pytest.mark.packaging
def test_distribution_metadata_and_license_material() -> None:
    name = "meridian-plugin-config-artifact"
    project = metadata(name)
    assert version(name) == "1.1.2"
    assert project["License-Expression"] == "Apache-2.0"
    assert SpecifierSet(project["Requires-Python"]) == SpecifierSet(">=3.12,<3.15")
    # The consumer's own declaration (major-only index resolution) and
    # the resolved record's compatibility: the INSTALLED core is the
    # materialized JumboIndex record (1.3.0), whose published metadata
    # carries ITS producer-era declaration — the compatibility assertion
    # is version-window membership, not specifier-string equality with
    # the consumer's declaration.
    declared = re.search(
        r'"(meridian-storage-core[^"]*)"',
        Path(__file__).parents[2].joinpath("pyproject.toml").read_text(encoding="utf-8"),
    )
    assert declared, "the consumer declares meridian-storage-core"
    consumer = Requirement(declared.group(1))
    assert consumer.specifier == SpecifierSet(">=1,<2")
    installed_core = version("meridian-storage-core")
    assert consumer.specifier.contains(installed_core), installed_core
    assert not consumer.specifier.contains("2.0.0")
    entry_points = {(item.group, item.name, item.value) for item in distribution(name).entry_points}
    assert entry_points == {
        (
            "meridian_storage.plugins",
            "config-artifact",
            "meridian_storage.plugins.config_artifact.plugin:ConfigArtifactPluginFactory",
        ),
        (
            "meridian_storage.schemas",
            "config-artifact",
            "meridian_storage.plugins.config_artifact.schemas:ConfigArtifactSchemaProvider",
        ),
    }
    root = Path(__file__).resolve().parents[2]
    assert "Apache License" in (root / "LICENSE").read_text(encoding="utf-8")
    assert "Meridian" in (root / "NOTICE").read_text(encoding="utf-8")
