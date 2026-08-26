#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify checked-in release evidence against generated release files."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release_evidence(evidence_path: Path, release_directory: Path) -> dict[str, Any]:
    """Return verification details after validating all evidence-bound artifacts."""
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    source_date_epoch = evidence["sourceDateEpoch"]
    generated_at = datetime.fromtimestamp(source_date_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _require(evidence["generatedAt"] == generated_at, "evidence timestamp differs from epoch")

    expected = evidence["artifacts"]
    _require(isinstance(expected, dict) and expected, "evidence must list release artifacts")
    expected_files = set(expected)
    actual_files = {path.name for path in release_directory.iterdir() if path.name != "SHA256SUMS"}
    _require(actual_files == expected_files, "release files differ from evidence manifest")

    for name, digest in expected.items():
        _require(name == Path(name).name, f"unsafe artifact name in evidence: {name!r}")
        _require(digest == f"sha256:{_sha256(release_directory / name)}", f"hash differs: {name}")

    sbom_names = [name for name in expected if name.endswith(".spdx.json")]
    _require(len(sbom_names) == 1, "evidence must identify exactly one SPDX JSON SBOM")
    sbom = json.loads((release_directory / sbom_names[0]).read_text(encoding="utf-8"))
    _require(sbom["creationInfo"]["created"] == generated_at, "SBOM timestamp differs from epoch")

    distributions = {
        name: digest.removeprefix("sha256:")
        for name, digest in expected.items()
        if name.endswith((".whl", ".tar.gz"))
    }
    _require(len(distributions) == 2, "evidence must identify one wheel and one sdist")
    checksum_lines = (release_directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums = dict(line.split("  ", 1)[::-1] for line in checksum_lines)
    _require(checksums == distributions, "SHA256SUMS differs from distribution evidence")

    return {
        "artifacts": len(expected),
        "generatedAt": generated_at,
        "status": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("release_directory", type=Path)
    arguments = parser.parse_args()
    result = verify_release_evidence(arguments.evidence, arguments.release_directory)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
