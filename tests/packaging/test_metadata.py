# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

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
    requirements = project.get_all("Requires-Dist") or []
    core = next(
        Requirement(value)
        for value in requirements
        if Requirement(value).name == "meridian-storage-core"
    )
    assert core.specifier == SpecifierSet(">=1.1.0,<2")
    assert core.specifier.contains("1.2.0")
    assert not core.specifier.contains("2.0.0")
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
