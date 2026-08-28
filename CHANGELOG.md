# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning.

## [1.0.1] - 2026-08-28

### Changed

- Publish the canonical `meridian-storage-plugin-config-artifact` distribution identity while
  preserving the `meridian_storage.plugins.config_artifact` import package and V1 public API.
- Lock package, plugin, schema-provider, contract, SBOM, and release metadata to Configuration and
  Artifact LLD revision 25.
- Verify both discovery entry points plus deterministic Configuration, Artifact, reference, and
  schema-migration lifecycles locally.

The legacy `meridian-plugin-config-artifact` 1.0.0 release remains immutable and is not a supported
installation name for this release line.

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
