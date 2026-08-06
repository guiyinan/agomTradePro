from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from shared.domain.reliability import ReliabilityContract, ReliabilityStatus

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_reliability_contract_ownership.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("reliability_contract_ownership", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("reliability ownership guard cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reliability_status_and_block_reasons_have_one_governed_owner() -> None:
    assert _load_guard().validate() == []


def test_reliability_contract_rejects_unstable_reason_code() -> None:
    with pytest.raises(ValueError, match="stable-code format"):
        ReliabilityContract.blocked(
            status=ReliabilityStatus.FAILED,
            source="test",
            reason_code="Invalid Reason Code",
            reason="invalid code",
        )
