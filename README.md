# Meridian Configuration and Artifact Plugin

`meridian-plugin-config-artifact` is the Apache-2.0 licensed Meridian V1 library for
publishing and consuming versioned configuration and built runtime artifacts. It is an embeddable
plugin, never a service or a Catalog.

Configuration payloads remain queryable and mutable through structured database semantics until
publication. A published version stores its validated JSON inline and is immutable. Artifact bytes
are written as immutable Objects; only their logical metadata, provenance, lifecycle state, and
channel pointers are structured records.

## Install

```console
python -m pip install meridian-plugin-config-artifact
```

Python 3.12–3.14, Core 1.0.1, Semantics 2.0.0, Query 1.0.2, and Object Common 1.0.2
are supported. Add `meridian-plugin-config-artifact[s3]` or `[oci]` only to co-install a
released provider; this library never imports either provider or its SDK.

## Compose

Artifact bytes use Object Common's shared process-local default registry. Install the
`s3` extra and start Meridian through installed-component discovery using deployment-owned
bindings and migrations:

```python
from meridian_storage import Meridian
from meridian_storage.plugins.config_artifact import ResourceStore

meridian = Meridian.from_environment()
meridian.start()
store = ResourceStore(meridian)
```

Core rejects duplicate component registration. Do not also inject an `S3AdapterFactory`
when the installed `s3` entry point is present. `default_payload_registry()` remains the
ResourceStore accessor and now returns Object Common's default. Passing this registry
explicitly to ResourceStore is also supported. Custom SPI compositions may share an
explicit `PayloadRegistry` with `S3AdapterFactory(payloads=registry)`; S3 1.0.1 preserves
that exact object even when it is empty.

The target combination is Core 1.0.1, Semantics/PostgreSQL 2.0.0, Query 1.0.2,
Object Common/S3/OCI 1.0.2, and ResourceStore 1.1.0.
The 1.1.0 candidate is not released; combined S3/OCI runtime acceptance is pending.
See `docs/put-mode-validation.md` for compatibility validation.
Regenerate deployment manifest fingerprints after upgrading package versions.

The schema entry point contributes these logical Resources by default:

- `structured:resources.metadata`
- `structured:resources.channels`
- `structured:resources.provenance`
- `structured:resources.orphan-candidates`
- `object:resources.objects`

Platform IaC owns their physical provisioning, binding, identity/ACL, migrations, recovery, and
lifecycle. Constructor arguments accept alternate logical Resource refs; no physical locator is
accepted.

## Publish configuration

```python
receipt = store.publisher.publish_configuration(
    namespace="checkout",
    kind="service",
    name="runtime",
    version="2026.08.26",
    payload={"endpoint": "https://api.example", "replicas": 3},
    schema="application.service-config@1.0.0",
    actor="release-bot",
    version_order=20260826,
    channel="production",
    expected_pointer_version=4,
)
```

The profile-specific surface from the locked LLD is also available directly. Publication receipts
expose their immutable `ref` for a later compare-and-set promotion:

```python
revision = store.configurations.publish(
    namespace="checkout",
    kind="service",
    name="runtime",
    version="2026.08.27",
    payload={"endpoint": "https://api.example", "replicas": 3},
    schema="application.service-config@1.0.0",
    actor="release-bot",
)
store.configurations.promote(
    revision.ref,
    "production",
    expected_pointer_version=5,
    actor="release-bot",
)
```

The exact Schema is resolved through Core and applied locally with Meridian Semantics before any
write. A retry with the same immutable content is idempotent; a different digest or immutable
metadata at the same logical identity raises `IdentityConflict`.

## Publish and consume an artifact

```python
receipt = store.publisher.publish_artifact(
    namespace="recommendations",
    kind="model",
    name="ranker",
    version="v42",
    payload=model_bytes,
    media_type_value="application/vnd.example.model",
    actor="model-builder",
)

resolved = store.consumer.artifacts.exact(receipt.resource.identity)
with store.consumer.artifacts.open(resolved) as stream:
    deploy(stream)
```

Bytes, streams, `PayloadSource` objects, factories, and pre-registered `PayloadReference` values
are supported. Streaming inputs must declare SHA-256 digest and byte length. Full reads are checked
again at the consumer boundary; range reads use the released Object Catalog verification contract.

Artifact publication commits the Object first, then structured metadata and provenance. If the
second phase fails, `IncompletePublication` is raised and an idempotently addressed orphan
candidate is recorded. `discover_orphans()` scans only bounded logical Object prefixes and never
deletes bytes.

## Resolution and lifecycle

Configuration and Artifact consumers each support:

- `exact(ResourceIdentity(...))`
- `latest(namespace, kind, name)` using `version_order`, then creation time
- `channel(namespace, kind, name, channel)`

Channel promotion requires `expected_pointer_version`; concurrent writers cannot silently win.
Published versions may be deprecated but the library forbids deletion. It contains no bootstrap
configuration, provider credentials, Adapter/Engine selection, NativeQuery, endpoint, or physical
storage name.

See [architecture](docs/architecture.md), [operations](docs/operations.md), and the checked-in
[public contract](contracts/public-api/meridian-config-artifact.v1.json).
