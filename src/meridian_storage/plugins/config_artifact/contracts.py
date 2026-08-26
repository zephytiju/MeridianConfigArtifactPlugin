# SPDX-License-Identifier: Apache-2.0
"""Load packaged language-neutral contracts and compatibility evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import cast


def public_api_contract() -> Mapping[str, object]:
    return _document("contracts/public-api/meridian-config-artifact.v1.json")


def stored_resource_contract() -> Mapping[str, object]:
    return _document("contracts/models/meridian-stored-resource.v1.schema.json")


def resource_channel_contract() -> Mapping[str, object]:
    return _document("contracts/models/meridian-resource-channel.v1.schema.json")


def provenance_contract() -> Mapping[str, object]:
    return _document("contracts/models/meridian-provenance.v1.schema.json")


def orphan_candidate_contract() -> Mapping[str, object]:
    return _document("contracts/models/meridian-orphan-candidate.v1.schema.json")


def compatibility_document() -> Mapping[str, object]:
    return _document("compatibility.json")


def _document(relative: str) -> Mapping[str, object]:
    packaged = resources.files("meridian_storage.plugins.config_artifact").joinpath(
        *relative.split("/")
    )
    if packaged.is_file():
        return cast(Mapping[str, object], json.loads(packaged.read_text(encoding="utf-8")))
    root = Path(__file__).resolve().parents[4]
    return cast(
        Mapping[str, object],
        json.loads(root.joinpath(relative).read_text(encoding="utf-8")),
    )


__all__ = [
    "compatibility_document",
    "orphan_candidate_contract",
    "provenance_contract",
    "public_api_contract",
    "resource_channel_contract",
    "stored_resource_contract",
]
