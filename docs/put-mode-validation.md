# Put-mode migration validation (1.1.0 candidate)

This candidate is awaiting combined S3/OCI runtime acceptance before publication. The normal released package resolver succeeds; the prior Object dependency blocker is
resolved by ObjectCommon/S3/OCI 1.0.2.

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

## Confirmed PostgreSQL blocker

PostgreSQL 2.0.0 and the latest tested release 2.1.0 append system timestamps as `createdAt` and
`updatedAt` after projecting logical schema fields with those same names. A dictionary result
therefore replaces logical values with system values. Both DML RETURNING and query projection
contain these duplicate aliases. For example, an actual synthetic provenance create sent
`createdAt=2026-09-07T02:32:25.701304Z` and returned
`createdAt=2026-09-07T02:32:25.706010Z`. The immutable-field comparison correctly rejects it;
Artifact publication rolls back metadata and reports incomplete publication after Object commit.

The plugin resolves this through an explicit public `structured.query(select=...)` of all logical
provenance fields inside the existing publication transaction when only the returned timestamp
differs. Every persisted immutable field must still match; missing or different logical values
fail. No requested value is substituted for database evidence. All eleven PostgreSQL/S3 tests
now pass, including forced concurrent
creates and channel CAS (same/different targets), duplicate/create conflict, changed immutable
metadata rejection, exact byte reads, orphan retry/recovery and scope isolation.

The coordinator is also arranging a MeridianPostgreSQLAdapter fidelity fix for declared logical
timestamp values. This plugin workaround consumes only public Catalog calls; no adapter code is
modified. S3/OCI normal ResourceStore interchangeability remains required before completion.

## Existing OCI deployment limitation

OCI 1.0.2 still exports `OciDistributionAdapter` as its adapter entry point, and that constructor
requires a binding. Core discovery instantiates registered adapter classes without arguments.
The normal PostgreSQL/S3 deployment therefore uses the S3 extra in an isolated environment;
installing OCI in that deployment prevents Core startup. No discovery filtering, wheel patch,
source override or substitute factory is used here. Manifest compatibility and the upstream
OCI direct-adapter evidence do not establish ResourceStore runtime interchangeability.

## Review and release status

Code review preserves append-only channel history, scoped identity/digest checks, strict logical
field validation, explicit capabilities, and Object retention. No adapter implementation is
vendored. Required real-engine CI must pass before routine merge/publication. No tag or package
has been published for 1.1.0. The package hash evidence is build evidence only, not acceptance.
