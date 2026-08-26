# SPDX-License-Identifier: Apache-2.0
"""Small public-contract protocols used to keep the plugin runtime-neutral."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Protocol

from meridian_storage import Expression, OperationResult, ResourceRef
from meridian_storage.registry import SchemaHandle


class MeridianRuntime(Protocol):
    """The subset of Core's public ``Meridian`` API consumed by this plugin."""

    def catalog(self, name: str) -> object: ...

    def execute(self, expression: Expression) -> OperationResult: ...

    def transaction(
        self, resource: ResourceRef | str | Mapping[str, object]
    ) -> AbstractContextManager[object]: ...

    def schema(
        self,
        catalog: str,
        namespace: str,
        name: str,
        version: str | None = None,
    ) -> SchemaHandle: ...


__all__ = ["MeridianRuntime"]
