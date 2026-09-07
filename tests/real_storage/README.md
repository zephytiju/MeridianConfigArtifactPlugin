# Real Artifact acceptance

This deployment fixture provisions only disposable PostgreSQL, MinIO and Distribution 3.1.1
resources. Both Object adapters are installed together; normal Meridian discovery and deployment
placement select S3 or OCI. ResourceStore uses the same public operations for either backend.
No installed wheel, discovery list or runtime factory is patched.

```sh
python -m venv .venv-acceptance
. .venv-acceptance/bin/activate
python -m pip install '.[s3,oci]' meridian-storage-postgresql==2.1.1 pytest==9.0.3 pytest-cov==6.2.1
docker compose -p meridian-artifact-acceptance -f tests/real_storage/compose.yaml up -d --wait
pytest tests/real_storage --no-cov
docker compose -p meridian-artifact-acceptance -f tests/real_storage/compose.yaml down
```

The required CI job gates packaging and repeats during release. Both default ResourceStore
construction and explicit use of the shared default payload registry publish new bytes, read
exact bytes and ranges, stat, repeat idempotently and reject conflicting content. Intentional
double registration of S3 still raises `MERIDIAN_DISCOVERY_DUPLICATE`.

Mode acceptance forces concurrent observations for identical/different configuration payloads
and same/different channel targets. It verifies direct duplicate-create rejection, immutable
field preservation, historical logical timestamps, provenance publication, scope isolation,
and orphan recovery. Physical and capability fingerprints are required by normal Core startup.
Tests fail on incompatible providers; they are never skipped or replaced with manifest assertions.
