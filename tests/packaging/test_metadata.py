# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from importlib.metadata import distribution, metadata, version
from pathlib import Path

import pytest

from packaging.specifiers import SpecifierSet


@pytest.mark.packaging
def test_distribution_metadata_and_license_material() -> None:
    name = "meridian-plugin-config-artifact"
    project = metadata(name)
    assert version(name) == "1.1.0"
    assert project["License-Expression"] == "Apache-2.0"
    assert SpecifierSet(project["Requires-Python"]) == SpecifierSet(">=3.12,<3.15")
    requirements = project.get_all("Requires-Dist") or []
    assert "meridian-storage-core==1.0.1" in requirements
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
