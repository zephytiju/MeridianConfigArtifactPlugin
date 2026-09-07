#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify wheel/sdist metadata, archive boundaries, hashes, and licenses."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from packaging.specifiers import SpecifierSet

EXPECTED_PINS = {
    "meridian-storage-core==1.0.1",
    "meridian-storage-object-common==1.0.2",
    "meridian-storage-query==1.0.2",
    "meridian-storage-semantics==2.0.0",
}
DISTRIBUTION = "meridian-plugin-config-artifact"
NORMALIZED_DISTRIBUTION = "meridian_plugin_config_artifact"
VERSION = "1.1.0"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_record(archive: zipfile.ZipFile, record_name: str) -> None:
    rows = csv.reader(io.StringIO(archive.read(record_name).decode()))
    for name, encoded_hash, size in rows:
        if not encoded_hash:
            continue
        algorithm, encoded = encoded_hash.split("=", 1)
        _require(algorithm == "sha256", f"RECORD uses unsupported hash {algorithm!r}")
        content = archive.read(name)
        expected = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        _require(encoded == expected, f"RECORD hash differs for {name}")
        _require(int(size) == len(content), f"RECORD size differs for {name}")


def _verify_wheel(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = tuple(sorted(archive.namelist()))
        dist_info = sorted({name.split("/", 1)[0] for name in names if ".dist-info/" in name})
        _require(
            dist_info == [f"{NORMALIZED_DISTRIBUTION}-{VERSION}.dist-info"],
            "wheel must contain exactly one config-artifact distribution",
        )
        root = dist_info[0]
        required = {
            f"{root}/licenses/LICENSE",
            f"{root}/licenses/NOTICE",
            f"{root}/METADATA",
            f"{root}/RECORD",
            f"{root}/entry_points.txt",
            "meridian_storage/plugins/config_artifact/compatibility.json",
            "meridian_storage/plugins/config_artifact/contracts/public-api/meridian-config-artifact.v1.json",
            "meridian_storage/plugins/config_artifact/py.typed",
        }
        _require(required.issubset(names), "wheel omits required metadata or package data")
        _require(
            not any(name.startswith("meridian_storage/adapters/") for name in names),
            "wheel contains Adapter source",
        )
        metadata_value = BytesParser().parsebytes(archive.read(f"{root}/METADATA"))
        _require(metadata_value["Name"] == DISTRIBUTION, "name differs")
        _require(metadata_value["Version"] == VERSION, "version differs")
        _require(metadata_value["License-Expression"] == "Apache-2.0", "license differs")
        _require(
            SpecifierSet(metadata_value["Requires-Python"]) == SpecifierSet(">=3.12,<3.15"),
            "Python range differs",
        )
        runtime_pins = {
            value
            for value in metadata_value.get_all("Requires-Dist", [])
            if value.startswith("meridian-storage-") and "; extra ==" not in value
        }
        _require(runtime_pins == EXPECTED_PINS, "wheel runtime pins differ")
        _verify_record(archive, f"{root}/RECORD")
    return {"file": path.name, "sha256": _sha256(path), "entries": len(names)}


def _verify_sdist(path: Path) -> dict[str, object]:
    with tarfile.open(path, "r:gz") as archive:
        names = tuple(sorted(member.name for member in archive.getmembers()))
        prefixes = {PurePosixPath(name).parts[0] for name in names}
        _require(
            prefixes == {f"{NORMALIZED_DISTRIBUTION}-{VERSION}"},
            "sdist must contain exactly one project root",
        )
        prefix = next(iter(prefixes))
        required = {
            f"{prefix}/LICENSE",
            f"{prefix}/NOTICE",
            f"{prefix}/README.md",
            f"{prefix}/pyproject.toml",
            f"{prefix}/compatibility.json",
            f"{prefix}/contracts/public-api/meridian-config-artifact.v1.json",
            f"{prefix}/src/meridian_storage/plugins/config_artifact/__init__.py",
        }
        _require(required.issubset(names), "sdist omits required source or license material")
        _require(
            not any("/src/meridian_storage/adapters/" in name for name in names),
            "sdist contains Adapter source",
        )
    return {"file": path.name, "sha256": _sha256(path), "entries": len(names)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    wheels = sorted(arguments.directory.glob("*.whl"))
    sdists = sorted(arguments.directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("expected exactly one wheel and one sdist")
    evidence = {
        "formatVersion": "meridian.config-artifact.artifacts.v1",
        "package": DISTRIBUTION,
        "version": VERSION,
        "artifacts": [_verify_wheel(wheels[0]), _verify_sdist(sdists[0])],
        "status": "passed",
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    output = {**evidence, "fingerprint": f"sha256:{hashlib.sha256(encoded).hexdigest()}"}
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
