# SPDX-License-Identifier: Apache-2.0
"""Required real-engine gates; invoke explicitly after starting compose.yaml."""

from uuid import uuid4

import pytest
from deployment import compose

from meridian_storage import ConfigurationError, ErrorCode, OperationContext
from meridian_storage.object_common import ByteRange
from meridian_storage.plugins.config_artifact import (
    IdentityConflict,
    ResourceIdentity,
    ResourceNotFound,
    ResourceStore,
    default_payload_registry,
)


@pytest.mark.parametrize("backend", ["s3", "oci"])
@pytest.mark.parametrize("explicit_registry", [False, True])
def test_first_artifact_publication_and_byte_exact_read(explicit_registry, backend):
    runtime = compose(backend=backend)
    registry = default_payload_registry()
    baseline = len(registry)
    try:
        with runtime.context(
            OperationContext(
                tenant="fixture-" + uuid4().hex,
                principal_ref="publisher",
                request_id=uuid4().hex,
                scope={"tenant": "fixture", "application": "artifact-acceptance"},
            )
        ):
            options = {"payload_registry": registry} if explicit_registry else {}
            store = ResourceStore(runtime, **options)
            name = uuid4().hex
            identity = ResourceIdentity("acceptance", "manifest", name, "1")
            assert store.metadata.get_resource(identity.resource_id, required=False) is None
            with pytest.raises(ResourceNotFound):
                store.artifacts.exact(identity)
            payload = bytes(range(256)) * 4096 + b"\x00\xffend"
            arguments = {
                "namespace": "acceptance",
                "kind": "manifest",
                "name": name,
                "version": "1",
                "payload": payload,
                "actor": "publisher",
            }
            receipt = store.artifacts.publish(**arguments)
            assert receipt.object_committed
            assert receipt.metadata_committed
            assert store.artifacts.read(store.artifacts.exact(identity)) == payload
            assert store.artifacts.stat(receipt.resource).digest == receipt.resource.digest
            assert (
                store.artifacts.range_read(receipt.resource, ByteRange(7, 8192)) == payload[7:8193]
            )
            assert store.artifacts.publish(**arguments).idempotent
            fresh = ResourceStore(runtime, **options)
            assert fresh.artifacts.read(fresh.artifacts.exact(identity)) == payload
            with pytest.raises(IdentityConflict):
                store.artifacts.publish(**{**arguments, "payload": b"different"})
            assert len(registry) == baseline
    finally:
        runtime.close()


def test_installed_s3_duplicate_registration_still_fails_closed():
    with pytest.raises(ConfigurationError) as caught:
        compose(duplicate_factory=True)
    assert caught.value.code == ErrorCode.DISCOVERY_DUPLICATE
