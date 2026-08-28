# Releasing

1. Confirm `main` is green and the version matches `pyproject.toml`, `_version.py`, the changelog,
   and compatibility ledger.
2. Create the immutable `vX.Y.Z` tag on `main`.
3. The release workflow rebuilds and tests, compares two byte-identical builds, verifies archive
   contents, emits SHA-256 sums and an SPDX 2.3 SBOM, attests provenance, and creates the GitHub
   release.
4. PyPI publication runs only when repository variable `PYPI_TRUSTED_PUBLISHING_ENABLED` is
   `true`, through the configured trusted publisher for the `pypi` GitHub environment.

The approved PyPI project is the existing `meridian-plugin-config-artifact` distribution. CI is
the only publication path. Never upload distributions manually, introduce an API token fallback,
or bypass the trusted-publishing workflow.

Recovery is idempotent: dispatch the release workflow for an existing release tag. Git tags and
published package versions are never replaced.
