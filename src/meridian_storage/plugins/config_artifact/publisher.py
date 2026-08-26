# SPDX-License-Identifier: Apache-2.0
"""Publisher-only facade for independently deployed build processes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, BinaryIO

from .artifact import ArtifactPayload, ArtifactPublisher
from .channels import ChannelRepository
from .configuration import ConfigurationPublisher
from .models import (
    PayloadSchemaRef,
    PublicationReceipt,
    ResourceChannelV1,
    ResourceIdentity,
    StoredResourceRef,
    StoredResourceV1,
)


class ResourcePublisher:
    """One facade over the distinct configuration and artifact publisher surfaces."""

    def __init__(
        self,
        configuration: ConfigurationPublisher,
        artifacts: ArtifactPublisher,
        channels: ChannelRepository,
    ) -> None:
        self.configuration = configuration
        self.artifacts = artifacts
        self.channels = channels

    def publish_configuration(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        version: str,
        payload: Mapping[str, object],
        schema: PayloadSchemaRef | str | Mapping[str, object],
        actor: str,
        **options: Any,
    ) -> PublicationReceipt:
        return self.configuration.publish(
            namespace=namespace,
            kind=kind,
            name=name,
            version=version,
            payload=payload,
            schema=schema,
            actor=actor,
            **options,
        )

    def publish_artifact(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        version: str,
        payload: ArtifactPayload | Callable[[], BinaryIO],
        actor: str,
        **options: Any,
    ) -> PublicationReceipt:
        return self.artifacts.publish(
            namespace=namespace,
            kind=kind,
            name=name,
            version=version,
            payload=payload,
            actor=actor,
            **options,
        )

    def promote(
        self,
        target: StoredResourceV1 | StoredResourceRef | ResourceIdentity,
        channel: str,
        *,
        expected_pointer_version: int,
        actor: str,
    ) -> ResourceChannelV1:
        return self.channels.promote(
            target,
            channel,
            expected_pointer_version=expected_pointer_version,
            actor=actor,
        )


__all__ = ["ResourcePublisher"]
