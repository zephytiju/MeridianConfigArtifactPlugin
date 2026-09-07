# SPDX-License-Identifier: Apache-2.0
"""Core plugin discovery entry point."""

from __future__ import annotations

from meridian_storage import Meridian
from meridian_storage.spi import PluginManifest

from ._version import __version__
from .store import ResourceStore


class ConfigArtifactPluginFactory:
    @property
    def plugin_id(self) -> str:
        return "config-artifact"

    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id=self.plugin_id,
            plugin_version=__version__,
            plugin_contract_version="1.0.0",
            core_contract="1.x",
            extensions={
                "distribution": "meridian-plugin-config-artifact",
                "profiles": "configuration,artifact",
                "catalogs": "structured,object",
                "design.hldRevision": "56",
                "design.catalogRevision": "70",
                "design.configArtifactLldRevision": "44",
            },
        )

    def create(self, meridian: Meridian) -> ResourceStore:
        return ResourceStore(meridian)


__all__ = ["ConfigArtifactPluginFactory"]
