# SPDX-License-Identifier: Apache-2.0
"""Consumer-only facade for independently deployed runtime processes."""

from __future__ import annotations

from .artifact import ArtifactConsumer
from .configuration import ConfigurationConsumer


class ResourceConsumer:
    """Expose separate profile consumers without introducing a service boundary."""

    def __init__(
        self,
        configuration: ConfigurationConsumer,
        artifacts: ArtifactConsumer,
    ) -> None:
        self.configurations = configuration
        self.artifacts = artifacts


__all__ = ["ResourceConsumer"]
