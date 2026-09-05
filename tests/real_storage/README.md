# Real Artifact acceptance

This deployment fixture provisions only disposable local PostgreSQL and MinIO resources.
It imports released adapter packages and uses the public Meridian/ResourceStore path for
publication and reads. No adapter runtimes or installed wheels are patched.

After the declared package dependencies have been published:

```sh
python -m venv .venv-acceptance
. .venv-acceptance/bin/activate
python -m pip install '.[s3]' meridian-storage-postgresql==1.0.0 pytest==9.0.3 pytest-cov==6.2.1
docker compose -p meridian-artifact-acceptance -f tests/real_storage/compose.yaml up -d --wait
pytest tests/real_storage --no-cov
docker compose -p meridian-artifact-acceptance -f tests/real_storage/compose.yaml down
```

The dedicated CI job is a dependency of the package gate. Both default ResourceStore
construction and explicit use of the shared default registry must publish new bytes,
read them exactly, repeat idempotently, and reject conflicting content. Double registration
of the installed S3 factory must continue to raise `MERIDIAN_DISCOVERY_DUPLICATE`.

Use a dedicated environment with the deployment’s PostgreSQL and S3 adapters. OCI 1.0.1
remains covered by the unchanged direct-adapter suite in the test extra, but its legacy
entry point requires a binding argument and cannot participate in Core discovery.
Installing OCI in this deployment prevents startup; it requires a separate OCI factory fix.
