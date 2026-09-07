# Put-mode migration validation (1.1.0)

## Implementation

All four structured put sites explicitly use `if_absent`. Metadata/provenance and orphan rows
retain their existing create lifecycle, duplicate checks and transaction/cleanup boundaries.
Channel initialization is separated from existing-pointer promotion; both retain the existing
append-only CAS sequence using an atomic unique successor-row insertion. Zero is never passed as
a structured `expected_version`. Public schemas, error codes and ResourceStore method signatures
are unchanged. Resource capabilities now require structured put 2.0.0.

The plugin validates and removes only adapter timestamps that are absent from a logical model:
channel `createdAt`, orphan `createdAt`/`updatedAt`, and provenance `updatedAt`. It still rejects
unknown fields, invalid timestamps and changes to declared immutable logical fields.

## Released compatibility

Normal public package resolution uses Core 1.0.1, Semantics 2.0.0, Query/Object Common/S3 1.0.2,
PostgreSQL 2.1.1 and OCI 1.0.3. PostgreSQL preserves declared logical timestamps in mutation and
query results. Provenance compares every returned immutable field directly; no projection fallback
or requested-value substitution remains. OCI implements the installed Core factory contract.

Both adapters are installed together, discovered by Core's normal entry points, and selected by
ordinary deployment placements. Physical and capability fingerprints are required at startup.
The deployment fixture performs adapter preflight to derive the physical pin; it injects no
runtime adapter except in the intentional duplicate-registration rejection test.

## Acceptance

The 21 required real-engine tests run the same ResourceStore paths against PostgreSQL plus S3
and PostgreSQL plus OCI. Engines are pinned disposable PostGIS, MinIO and Distribution 3.1.1.
Coverage includes first publication, exact and range reads, stat, identical retry, different-digest
conflict, concurrent configuration creation, concurrent channel initialization and existing-pointer
CAS with same/different targets, immutable overwrite rejection, provenance, scope isolation and
orphan recovery after Object commit. A fixed historical clock proves logical resource `createdAt`
and channel `updatedAt` round-trip exactly. Shared payload registry usage returns to its baseline.

The deterministic suite has 74 passing tests and 92.09% branch-inclusive coverage. Required CI
also checks Python 3.12–3.14, lint, strict typing, contracts, security, reproducible builds and clean
wheel installation. Release evidence records artifact and SBOM hashes. Publication uses the
existing attested trusted-publishing workflow after review and green required CI.
