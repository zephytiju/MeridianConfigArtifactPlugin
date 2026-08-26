# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime

import pytest

from meridian_storage.plugins.config_artifact._canonical import (
    bounded_string,
    canonical_mapping,
    canonical_value,
    channel_name,
    digest,
    logical_name,
    media_type,
    sequence,
    string_mapping,
    utc_timestamp,
)


def test_scalar_validation_and_timestamp_normalization() -> None:
    assert bounded_string("value", "field") == "value"
    assert logical_name("valid/name", "name") == "valid/name"
    assert channel_name("stable-1") == "stable-1"
    assert media_type("application/json") == "application/json"
    assert digest(f"sha256:{'a' * 64}").startswith("sha256:")
    assert utc_timestamp("2026-01-02T03:04:05.123456Z").endswith("Z")
    with pytest.raises(ValueError, match="bounded"):
        bounded_string("", "field")
    with pytest.raises(ValueError, match="logical name"):
        logical_name("invalid name", "name")
    with pytest.raises(ValueError, match="channel"):
        channel_name("bad/channel")
    with pytest.raises(ValueError, match="Internet media"):
        media_type("json")
    with pytest.raises(ValueError, match="sha256"):
        digest("SHA256:bad")
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_timestamp(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="RFC 3339"):
        utc_timestamp("2026-01-01")


def test_canonical_collections_are_detached_bounded_json() -> None:
    value = canonical_mapping({"b": [2, 1], "a": {"ok": True}}, "value")
    assert list(value) == ["a", "b"]
    assert canonical_value({"a": 1}) == {"a": 1}
    assert string_mapping({"b": "2", "a": "1"}, "labels") == {
        "a": "1",
        "b": "2",
    }
    assert sequence([1, 2], "items") == [1, 2]
    with pytest.raises(TypeError, match="mapping"):
        canonical_mapping([], "value")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at most"):
        string_mapping({str(index): "x" for index in range(65)}, "labels")
    with pytest.raises(TypeError, match="array"):
        sequence("not-an-array", "items")
    with pytest.raises(ValueError, match="at most"):
        sequence(list(range(129)), "items")
