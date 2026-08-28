# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from meridian_storage.object_common import ByteRange
from meridian_storage.plugins.config_artifact import ForbiddenDeletion, ResourceState


@pytest.mark.contract
def test_configuration_resource_lifecycle_is_deterministic(store, schema_ref, valid_config) -> None:
    first = store.configurations.publish(
        namespace="lifecycle",
        kind="configuration",
        name="service",
        version="1",
        payload=valid_config,
        schema=schema_ref,
        actor="publisher",
        version_order=1,
    ).resource
    pointer = store.configurations.promote(
        first.ref,
        "active",
        expected_pointer_version=0,
        actor="publisher",
    )

    resolved = store.configurations.channel("lifecycle", "configuration", "service", "active")
    assert pointer.target_resource_id == first.resource_id
    assert resolved.resource.ref == first.ref
    assert store.configurations.payload(resolved) == valid_config
    assert store.configurations.deprecate(first.identity).state is ResourceState.DEPRECATED
    with pytest.raises(ForbiddenDeletion):
        store.configurations.delete(first.identity)


@pytest.mark.contract
def test_artifact_resource_and_object_reference_lifecycle_is_deterministic(store) -> None:
    payload = b"deterministic-artifact"
    published = store.artifacts.publish(
        namespace="lifecycle",
        kind="artifact",
        name="bundle",
        version="1",
        payload=payload,
        actor="publisher",
    ).resource
    pointer = store.artifacts.promote(
        published.ref,
        "stable",
        expected_pointer_version=0,
        actor="publisher",
    )

    resolved = store.artifacts.channel("lifecycle", "artifact", "bundle", "stable")
    assert published.object_ref is not None
    assert published.object_ref.digest == published.digest
    assert pointer.target_resource_id == published.resource_id
    assert resolved.resource.ref == published.ref
    assert store.artifacts.read(resolved) == payload
    assert store.artifacts.range_read(resolved, ByteRange(0, 4)) == payload[:5]
    assert store.artifacts.deprecate(published.identity).state is ResourceState.DEPRECATED
    with pytest.raises(ForbiddenDeletion):
        store.artifacts.delete(published.identity)
