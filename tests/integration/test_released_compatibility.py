# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from importlib.metadata import entry_points, version
from pathlib import Path

import pytest

from meridian_storage.adapters.oci import OciDistributionBinding, configured_capability_manifest
from meridian_storage.adapters.s3 import S3Config, s3_capability_manifest
from meridian_storage.object_common import ObjectCatalogSurface
from meridian_storage.plugins.config_artifact import ResourceStore
from meridian_storage.plugins.config_artifact.schemas import ConfigArtifactSchemaProvider
from meridian_storage.semantics import StructuredCatalogSurface
from meridian_storage.spi import capability_violations


@pytest.mark.integration
def test_exact_released_predecessor_versions_and_entry_points(runtime) -> None:
    assert version("meridian-storage-core") == "1.0.1"
    assert version("meridian-storage-semantics") == "2.0.0"
    assert version("meridian-storage-query") == "1.0.2"
    assert version("meridian-storage-object-common") == "1.0.2"
    assert version("meridian-storage-s3") == "1.0.2"
    assert version("meridian-storage-oci") == "1.0.3"
    assert isinstance(runtime.catalog("structured"), StructuredCatalogSurface)
    assert isinstance(runtime.catalog("object"), ObjectCatalogSurface)

    plugins = {item.name: item for item in entry_points(group="meridian_storage.plugins")}
    schemas = {item.name: item for item in entry_points(group="meridian_storage.schemas")}
    assert plugins["config-artifact"].load()().plugin_id == "config-artifact"
    assert schemas["config-artifact"].load()().provider_id == "meridian.plugin.config-artifact"


@pytest.mark.integration
def test_publisher_and_consumer_can_be_composed_as_separate_surfaces(runtime) -> None:
    payloads = runtime.payloads
    publisher_store = ResourceStore(runtime, payload_registry=payloads)
    consumer_store = ResourceStore(runtime, payload_registry=payloads)
    published = publisher_store.publisher.publish_artifact(
        namespace="ns",
        kind="bundle",
        name="separate-process-surface",
        version="1",
        payload=b"artifact",
        actor="publisher",
    )
    resolved = consumer_store.consumer.artifacts.exact(published.resource.identity)
    assert consumer_store.consumer.artifacts.read(resolved) == b"artifact"


@pytest.mark.integration
def test_released_s3_and_oci_manifests_satisfy_plugin_object_requirements() -> None:
    bundle = ConfigArtifactSchemaProvider().load()
    object_resource = next(
        resource for resource in bundle.resources if resource.ref.catalog == "object"
    )
    manifests = (
        s3_capability_manifest(S3Config("conformance-bucket")),
        configured_capability_manifest(
            OciDistributionBinding(
                "object:resources.objects",
                "https://registry.example",
                "meridian/conformance",
                cursor_signing_key=b"meridian-config-artifact-fixture",
            )
        ),
    )
    assert {manifest.descriptor.adapter_id for manifest in manifests} == {
        "s3",
        "oci-distribution",
    }
    assert all(
        not capability_violations(manifest, object_resource.requirements) for manifest in manifests
    )


@pytest.mark.integration
def test_source_never_imports_provider_sdks_or_engine_concepts() -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    text = "\n".join(path.read_text(encoding="utf-8") for path in source.rglob("*.py"))
    forbidden = (
        "import boto3",
        "from boto3",
        "import botocore",
        "from botocore",
        "import oci",
        "from oci",
        "NativeQuery",
        "AdapterConfig",
        "EngineConfig",
    )
    assert not [needle for needle in forbidden if needle in text]
