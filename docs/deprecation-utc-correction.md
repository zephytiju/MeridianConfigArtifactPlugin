# Deprecation and UTC correction (1.1.2)

Install the released correction through normal dependency resolution:

```sh
python -m pip install 'meridian-plugin-config-artifact[s3,oci]==1.1.2' \
  'meridian-storage-postgresql==2.3.1'
python -m pip check
```

This tested selection uses Core 1.1.0, Semantics 2.1.0, Query/Object Common/Projection 1.0.3,
S3 1.0.4 and OCI 1.1.0. The existing hash-locked selection remains a separate compatibility
gate. Neither selection is a universal deployment lock; deployments resolve, validate and pin
their own closure. Runtime dependency bounds, public calls and Schema fingerprints are unchanged.

## Reproduction and correction

With the public 1.1.1 wheel and PostgreSQL 2.3.1, publish a Configuration or Artifact, then
call the corresponding repository's `deprecate(resource.identity)`. PostgreSQL returns an
array containing the changed Record; 1.1.1 expects an object and raises `InvalidRepositoryResult`.
The database update can already have committed despite this exception. After upgrade, re-read
the resource and repeat the same public call: an already deprecated resource returns idempotently.

Version 1.1.2 validates a collection of exactly one matching scoped Record inside the same
metadata transaction as the patch. The returned state must be DEPRECATED, every identity and
immutable field must match, and a changed Record version must be present. Malformed collections,
wrong identity/scope, missing versions or changed immutable data fail with `InvalidRepositoryResult`
and roll back. No adapter shape conversion is needed. Stale conditional updates remain conflicts;
the public repositories preserve their existing convergence on an already deprecated winner.

Publishing with an injected UTC clock at `2026-09-09T00:00:00Z` reproduces the second 1.1.1
failure: PostgreSQL serializes whole seconds without a fraction. The plugin now accepts that
representation and fractional seconds up to microsecond precision, including fresh reads of
legacy rows. Public output remains `2026-09-09T00:00:00.000000Z`. Provenance comparisons use the
same normalization. Invalid dates, missing zones and non-UTC string offsets still fail.

No migration or rewrite is needed. Parsing does not update stored history, canonical payload
bytes, Object bytes, resource identities, digests or physical bindings. Configuration publication
and provenance remain one database transaction; Artifact publication retains its explicit
Object/metadata two-Binding boundary.

## Acceptance evidence

The public 1.1.1 reproduction fails all eight Configuration/Artifact × S3/OCI cases for
deprecation and whole-second publication. The corrected installed package passes 120 tests
(92.37% coverage) and 53 real-engine cases with no skips on PostgreSQL 2.3.1.

`tests/real_storage/test_deprecation.py` covers concurrent and repeated calls, stale versions,
same-identity resources in different tenants, unchanged provenance and Object bytes, malformed
results injected after a real patch, and outer metadata/provenance transaction rollback.
Existing channel CAS, publication, orphan and discovery gates continue to run.

The CI release workflow gates publication on the existing hash-locked suite and the PostgreSQL
2.3.1 real-storage suite, builds identical artifacts twice, verifies their checked-in hashes,
emits an SPDX SBOM and attests the release. Exact wheel/sdist hashes are in `evidence/v1.1.2.json`;
the delivery task records merged commit, CI, PyPI and provenance verification links.
