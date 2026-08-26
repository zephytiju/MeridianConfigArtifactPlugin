# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from meridian_storage.plugins.config_artifact import ResourceIdentity

NAMES = st.from_regex(r"[A-Za-z][A-Za-z0-9_.-]{0,31}", fullmatch=True)


@given(NAMES, NAMES, NAMES, NAMES)
def test_resource_identity_is_deterministic_and_collision_resistant_for_inputs(
    namespace: str,
    kind: str,
    name: str,
    version: str,
) -> None:
    identity = ResourceIdentity(namespace, kind, name, version)
    assert identity.resource_id == ResourceIdentity(namespace, kind, name, version).resource_id
    changed = ResourceIdentity(namespace, kind, name, f"{version}-next")
    assert identity.resource_id != changed.resource_id


def test_resource_identity_escapes_canonical_delimiters() -> None:
    namespace_delimiter = ResourceIdentity("alpha:beta", "kind", "name", "1")
    kind_delimiter = ResourceIdentity("alpha", "beta:kind", "name", "1")
    assert namespace_delimiter.canonical != kind_delimiter.canonical
    assert namespace_delimiter.resource_id != kind_delimiter.resource_id
