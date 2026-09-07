# Changelog

## [1.1.0] - 2026-09-07

- Consume released explicit structured put modes and compatible Object packages.
- Create immutable metadata, provenance, orphan and channel-version rows with `if_absent`.
- Preserve ResourceStore calls, append-only channel CAS, duplicate handling and cleanup.
- Pin PostgreSQL 2.1.1 and OCI 1.0.3 for logical timestamp fidelity and installed runtime discovery.
- Require the same real ResourceStore acceptance through both S3 and OCI.

## [1.0.3] - 2026-09-05

- Treat null structured get results as missing Resources and orphan candidates; malformed non-null results still fail closed.
- Accept the validated structured update timestamp returned alongside immutable Resource values.
- Share Object Common’s default payload registry with installed S3 discovery.
- Add real PostgreSQL/MinIO first-publication, exact-read, idempotency and duplicate-discovery regression gates.


All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning.

## [1.0.2] - 2026-08-28

### Changed

- Continue the existing `meridian-plugin-config-artifact` PyPI distribution identity approved by
  Configuration and Artifact LLD revision 28 while preserving the
  `meridian_storage.plugins.config_artifact` import package and V1 public API.
- Require the configured trusted-publishing workflow as the only PyPI publication path.
- Preserve the immutable GitHub-only `v1.0.1` evidence and verify both predecessor releases before
  producing the corrected distribution.

## [1.0.1] - 2026-08-28

### Changed

- Publish the canonical `meridian-storage-plugin-config-artifact` distribution identity while
  preserving the `meridian_storage.plugins.config_artifact` import package and V1 public API.
- Lock package, plugin, schema-provider, contract, SBOM, and release metadata to Configuration and
  Artifact LLD revision 25.
- Verify both discovery entry points plus deterministic Configuration, Artifact, reference, and
  schema-migration lifecycles locally.

The existing `meridian-plugin-config-artifact` 1.0.0 release remained immutable and did not receive
version 1.0.1.

## [1.0.0] - 2026-08-26

### Added

- Exact-Schema-validated, inline Configuration publication and consumption.
- Immutable Artifact publication over the Meridian Object Catalog.
- Exact, latest, and compare-and-set channel resolution.
- Publisher-only and consumer-only library surfaces.
- Digest verification, idempotent retry, deprecation, and orphan reconciliation.
- Language-neutral contracts, released-package conformance, CI, and reproducible artifacts.

[1.0.0]: https://github.com/zephytiju/MeridianConfigArtifactPlugin/releases/tag/v1.0.0
[1.0.1]: https://github.com/zephytiju/MeridianConfigArtifactPlugin/releases/tag/v1.0.1
[1.0.2]: https://github.com/zephytiju/MeridianConfigArtifactPlugin/releases/tag/v1.0.2
