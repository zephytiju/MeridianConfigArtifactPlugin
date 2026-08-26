# Operations

## Provisioning

Platform IaC must provision and bind the four structured Resources and one object Resource from
`ConfigArtifactSchemaProvider`. The application must not pass database tables, buckets,
repositories, endpoints, or credentials to `ResourceStore`; it passes only logical `ResourceRef`
values. All related Resources must resolve to transaction-compatible structured bindings.

## Payload registry

Create one process-local registry and inject that same instance into both the Object Adapter factory
and `ResourceStore`. Payload references are opaque, bounded, and never network endpoints. The
publisher releases registrations it creates; a caller retains ownership of a pre-registered
reference. Consumer reads release Adapter-created registrations on every exit path.

Resource labels are limited to 64 bounded string pairs. Annotations and provenance attributes are
limited to 64 top-level entries and 262,144 canonical JSON bytes. Domain configuration payload
limits remain the responsibility of their exact published Schema.

## Retry and reconciliation

- Configuration retry: safe when immutable content and metadata match.
- Artifact retry before metadata: stat proves the already-committed Object and resumes metadata.
- Channel retry: re-read the pointer and provide its exact version; stale writes fail closed.
- `IncompletePublication`: retry the same publication identity and content. Also monitor
  `orphan-candidates` and use `discover_orphans()` for bounded scans.
- `MissingObject` or `ArtifactDigestMismatch`: stop consumption and invoke the Platform-owned
  recovery process. The library intentionally offers no Object delete path.

## Evidence

CI runs Python 3.12, 3.13, and 3.14; validates contracts and exact predecessor pins; executes unit,
property, integration, packaging, and conformance tests; enforces at least 90% branch-aware
coverage; runs Bandit and dependency audit; builds twice with a fixed epoch; compares bytes; checks
wheel RECORD hashes and archive boundaries; generates an SPDX SBOM; and attests release artifacts.
