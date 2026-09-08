# Dependency compatibility (1.1.1)

The plugin continues one public distribution and unchanged ResourceStore and Schema contracts.
The 1.1.0 recipe pinned Core 1.0.1 and prevented normal installation with Core 1.1.0.
Version 1.1.1 separates public API requirements from a deployment-selected validation lock.

| Dependency | Runtime bound | Reason |
| --- | --- | --- |
| Core | >=1.1.0,<2 | Released descriptor/configuration provenance semantics and existing v1 runtime/SPI |
| Semantics | >=2.0.1,<3 | Resolvable public closure, structured put operation 2.0.0 and explicit if_absent writes |
| Query | >=1.0.3,<2 | Resolvable Core closure with unchanged expression, cursor and fingerprint contracts |
| Object Common | >=1.0.3,<2 | Resolvable closure and shared immutable Object/payload registry contract |
| S3 extra | >=1.0.4,<2 | Released Core 1.1 support and corrected distribution evidence |
| OCI extra | >=1.1.0,<2 | Released Core factory and Distribution protocol contract |
| PostgreSQL test extra | >=2.2.0,<3 | Released independent server/library selection and logical timestamp preservation |

Upper bounds retain the existing contract major boundaries. They permit dependency resolution;
they do not certify arbitrary future releases. Schema and Operation versions stay unchanged.
No runtime implementation or provider ownership changes are needed. The locked historical
1.1.0 validation remains documented in put-mode-validation.md and immutable release evidence.

`requirements-validation.in` selects the exact public Meridian releases. The generated universal
`requirements-validation.txt` locks their full test dependency closure with SHA-256 hashes.
Install that file with `--require-hashes`, then install this project or wheel normally and run
`pip check`. Never use dependency overrides, sibling source or `--no-deps`.

```sh
uv pip compile pyproject.toml --extra test --extra s3 --extra oci \
  -c requirements-validation.in --generate-hashes --universal -o requirements-validation.txt
python -m pip install --require-hashes -r requirements-validation.txt
python -m pip install '.[test]'
python -m pip check
python scripts/verify_contracts.py
pytest
docker compose -p meridian-artifact-acceptance -f tests/real_storage/compose.yaml up -d --wait
pytest tests/real_storage --no-cov
```

The real-engine suite preserves first Object publication, exact/range integrity, duplicate digest
semantics, concurrent configuration publication, channel initialization and stale/concurrent CAS,
immutable metadata rejection, provenance timestamps, scope isolation and orphan recovery after
Object commit. It uses digest-pinned PostGIS, MinIO and Distribution 3.1.1, both adapters installed
through ordinary discovery, and explicit structured/object Bindings. Other engines, managed cloud
providers and untested library combinations remain unverified.


Validated locally on Python 3.13.3: both the hash-locked Semantics 2.0.1 selection and normal
unconstrained resolution selecting Semantics 2.1.0 passed 74 tests (92.04% coverage), 21 real
storage tests with zero skips, contract verification and `pip check`. The latter exact selected
public URLs/hashes are in `evidence/v1.1.1-current-resolution.json`. CI repeats both combinations
and retains installation reports. These two observations do not expand the compatibility claim
to any untested combination.

Observed fixture engines: PostgreSQL 16.4 with PostGIS 3.4.3, MinIO
RELEASE.2025-04-22T22-12-26Z and Distribution 3.1.1. Images are pinned in compose.yaml;
protocol identifiers (S3 2006-03-01 and Distribution 1.1.1) remain separate from server releases.
