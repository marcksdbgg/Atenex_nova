"""Verify orchestrator modules import when turbovec is absent."""

from __future__ import annotations

import importlib
import sys

import pytest

_ORCHESTRATOR_MODULES = (
    "atenex_nova.application.orchestrators.retrieval_orchestrator",
    "atenex_nova.application.orchestrators.ingestion_orchestrator",
)

_MODULES_TO_RELOAD = (
    "atenex_nova.infrastructure.indexes.turboquant_candidate_index",
    *_ORCHESTRATOR_MODULES,
)


@pytest.fixture
def turbovec_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate an environment without turbovec installed."""
    monkeypatch.setitem(sys.modules, "turbovec", None)
    for name in _MODULES_TO_RELOAD:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("module_name", _ORCHESTRATOR_MODULES)
def test_orchestrator_imports_without_turbovec(turbovec_absent: None, module_name: str) -> None:
    importlib.import_module(module_name)
