# SPDX-License-Identifier: Apache-2.0
"""Composition root for the embeddable Configuration and Artifact plugin."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from meridian_storage import ResourceRef
from meridian_storage.object_common import PayloadRegistry

from ._runtime import MeridianRuntime
from .artifact import ArtifactConsumer, ArtifactPublisher, ArtifactRepository
from .channels import ChannelRepository
from .configuration import (
    ConfigurationConsumer,
    ConfigurationPublisher,
    ConfigurationRepository,
)
from .consumer import ResourceConsumer
from .publisher import ResourcePublisher
from .repositories import MetadataRepository, ObjectRepository
from .schemas import (
    CHANNEL_RESOURCE,
    METADATA_RESOURCE,
    OBJECT_RESOURCE,
    ORPHAN_RESOURCE,
    PROVENANCE_RESOURCE,
)
from .validation import MeridianPayloadValidator, PayloadValidator


class SharedPayloadRegistry(PayloadRegistry):
    """Registry that remains truthy when empty for released Adapter constructors."""

    def __bool__(self) -> bool:
        return True


_DEFAULT_PAYLOADS = SharedPayloadRegistry()


def default_payload_registry() -> PayloadRegistry:
    """Return the process-wide registry applications may share with Object Adapters."""

    return _DEFAULT_PAYLOADS


class ResourceStore:
    """In-process resource API over structured metadata and immutable Objects."""

    def __init__(
        self,
        meridian: MeridianRuntime,
        *,
        metadata_collection: ResourceRef | str = METADATA_RESOURCE,
        channel_collection: ResourceRef | str = CHANNEL_RESOURCE,
        provenance_collection: ResourceRef | str = PROVENANCE_RESOURCE,
        orphan_collection: ResourceRef | str = ORPHAN_RESOURCE,
        object_collection: ResourceRef | str = OBJECT_RESOURCE,
        payload_registry: PayloadRegistry | None = None,
        payload_validator: PayloadValidator | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        metadata_ref = ResourceRef.parse(metadata_collection, catalog="structured")
        channel_ref = ResourceRef.parse(channel_collection, catalog="structured")
        provenance_ref = ResourceRef.parse(provenance_collection, catalog="structured")
        orphan_ref = ResourceRef.parse(orphan_collection, catalog="structured")
        object_ref = ResourceRef.parse(object_collection, catalog="object")
        payloads = default_payload_registry() if payload_registry is None else payload_registry
        metadata = MetadataRepository(
            meridian,
            metadata_resource=metadata_ref,
            channel_resource=channel_ref,
            provenance_resource=provenance_ref,
            orphan_resource=orphan_ref,
        )
        objects = ObjectRepository(meridian, object_resource=object_ref)
        channels = ChannelRepository(metadata, clock=clock)
        validator = (
            MeridianPayloadValidator(meridian) if payload_validator is None else payload_validator
        )
        configuration_publisher = ConfigurationPublisher(
            metadata,
            validator,
            channels,
            clock=clock,
        )
        configuration_consumer = ConfigurationConsumer(metadata, channels)
        artifact_publisher = ArtifactPublisher(
            metadata,
            objects,
            channels,
            payloads,
            clock=clock,
        )
        artifact_consumer = ArtifactConsumer(metadata, objects, channels, payloads)

        self.metadata = metadata
        self.objects = objects
        self.channels = channels
        self.configurations = ConfigurationRepository(
            metadata,
            validator,
            channels,
            clock=clock,
        )
        self.artifacts = ArtifactRepository(
            metadata,
            objects,
            channels,
            payloads,
            clock=clock,
        )
        self.publisher = ResourcePublisher(
            configuration_publisher,
            artifact_publisher,
            channels,
        )
        self.consumer = ResourceConsumer(configuration_consumer, artifact_consumer)
        self.payload_registry = payloads


__all__ = ["ResourceStore", "SharedPayloadRegistry", "default_payload_registry"]
