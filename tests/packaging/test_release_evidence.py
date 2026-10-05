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


def test_checked_in_evidence_manifests_are_internally_consistent() -> None:
    """Stored-evidence integrity over every checked-in release manifest.

    The evidence file is the integrity record for the RELEASED artifacts:
    its artifact digests are what the released files (wheel, sdist, SPDX
    SBOM) must match — verified against the release at the release
    ceremony and re-verifiable offline with scripts/verify_release_evidence.py
    pointed at the released files. CI does NOT re-derive the bytes:
    regenerating the SBOM or the distributions and comparing them
    byte-for-byte against this record is reproduction, which is
    `jumbo build --pinned`'s job (the JumboIndex record carries the
    artifact sha256 of record), not CI's.
    """
    from datetime import UTC, datetime
    from pathlib import Path

    evidence_dir = Path(__file__).parents[2] / "evidence"
    # The released lineages v1.0.0..v1.1.2; the *-resolution files are
    # resolution captures, not release manifests.
    manifests = sorted(
        path
        for path in evidence_dir.glob("v*.json")
        if "-resolution" not in path.stem
    )
    assert len(manifests) >= 7, "expected the v1.0.0..v1.1.2 release lineages"

    for manifest in manifests:
        if "-resolution" in manifest.stem:
            continue
        evidence = json.loads(manifest.read_text(encoding="utf-8"))
        epoch = evidence["sourceDateEpoch"]
        expected_at = datetime.fromtimestamp(epoch, UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        assert evidence["generatedAt"] == expected_at, manifest.name
        artifacts = evidence["artifacts"]
        assert isinstance(artifacts, dict) and artifacts, manifest.name
        spdx = [name for name in artifacts if name.endswith(".spdx.json")]
        wheels = [name for name in artifacts if name.endswith(".whl")]
        sdists = [name for name in artifacts if name.endswith(".tar.gz")]
        assert len(spdx) == 1, f"{manifest.name}: exactly one SPDX SBOM"
        assert len(wheels) == 1, f"{manifest.name}: exactly one wheel"
        assert len(sdists) == 1, f"{manifest.name}: exactly one sdist"
        for name, digest in artifacts.items():
            assert name == Path(name).name, f"{manifest.name}: unsafe name {name!r}"
            assert digest.startswith("sha256:") and len(digest) == 71, (
                f"{manifest.name}: malformed digest for {name}"
            )
