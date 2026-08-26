# SPDX-License-Identifier: Apache-2.0
"""Tests for release-evidence verification."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    release = tmp_path / "release"
    release.mkdir()
    wheel = release / "example-1.0.0-py3-none-any.whl"
    sdist = release / "example-1.0.0.tar.gz"
    sbom = release / "example-1.0.0.spdx.json"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    sbom.write_text(
        json.dumps({"creationInfo": {"created": "2026-08-26T00:00:00Z"}}) + "\n",
        encoding="utf-8",
    )
    artifacts = {path.name: f"sha256:{_sha256(path)}" for path in (wheel, sdist, sbom)}
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "sourceDateEpoch": 1787702400,
                "generatedAt": "2026-08-26T00:00:00Z",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    (release / "SHA256SUMS").write_text(
        f"{_sha256(wheel)}  {wheel.name}\n{_sha256(sdist)}  {sdist.name}\n",
        encoding="utf-8",
    )
    return evidence, release, wheel


def test_release_evidence_matches_files(tmp_path: Path) -> None:
    evidence, release, _ = _release_fixture(tmp_path)

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts" / "verify_release_evidence.py"),
            str(evidence),
            str(release),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "passed"


def test_release_evidence_rejects_tampering(tmp_path: Path) -> None:
    evidence, release, wheel = _release_fixture(tmp_path)
    wheel.write_bytes(b"tampered")

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts" / "verify_release_evidence.py"),
            str(evidence),
            str(release),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "hash differs" in result.stderr
