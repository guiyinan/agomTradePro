"""Behavior and determinism checks for the generated QMT price-range module."""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from qmt_agent.price_submission_range import (
    ExecutionSide,
    PriceQuoteSource,
    PriceRoundingMode,
    PriceSubmissionRangeDecision,
    PriceSubmissionRangeReason,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeStatus,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
    calculate_price_submission_range,
)
from scripts.build_qmt_price_submission_projection import (
    EXECUTION_DOMAIN_PATH,
    GENERATED_MODULE_PATH,
    PRICE_DOMAIN_PATH,
    REPO_ROOT,
    SCRIPT_PATH,
    ProjectionBuildError,
    check_projection,
    normalize_lf,
    render_projection,
)


def _rule(**changes: object) -> PriceSubmissionRangeRule:
    values: dict[str, object] = {
        "market": "SSE",
        "board": "MAIN",
        "price_tick": Decimal("0.05"),
        "buy_deviation_ratio": Decimal("0.02"),
        "sell_deviation_ratio": Decimal("0.02"),
        "buy_widening_ticks": 10,
        "sell_widening_ticks": 10,
        "minimum_distance_ticks": 1,
        "lower_floor_ticks": 1,
        "rounding_mode": PriceRoundingMode.HALF_UP,
    }
    values.update(changes)
    return PriceSubmissionRangeRule(**values)  # type: ignore[arg-type]


def _quote(state: QuoteValueState, value: str | None = None) -> QuoteValue:
    return QuoteValue(
        state=state,
        value=None if value is None else Decimal(value),
    )


def _calculate(
    *,
    side: ExecutionSide,
    rule: PriceSubmissionRangeRule | None = None,
    ask: QuoteValue | None = None,
    bid: QuoteValue | None = None,
    latest: QuoteValue | None = None,
    previous_close: QuoteValue | None = None,
    stage: PriceSubmissionStage = PriceSubmissionStage.CONTINUOUS,
) -> PriceSubmissionRangeDecision:
    absent = _quote(QuoteValueState.CONFIRMED_ABSENT)
    return calculate_price_submission_range(
        rule or _rule(),
        side=side,
        stage=stage,
        ask=ask or absent,
        bid=bid or absent,
        latest=latest or absent,
        previous_close=previous_close or absent,
    )


def test_generated_module_calculates_buy_and_sell_boundaries() -> None:
    buy = _calculate(
        side=ExecutionSide.BUY,
        ask=_quote(QuoteValueState.PRESENT, "10.00"),
    )
    sell = _calculate(
        side=ExecutionSide.SELL,
        bid=_quote(QuoteValueState.PRESENT, "10.00"),
    )

    assert buy.status is PriceSubmissionRangeStatus.CALCULATED
    assert buy.boundary_price == Decimal("10.50")
    assert sell.status is PriceSubmissionRangeStatus.CALCULATED
    assert sell.boundary_price == Decimal("9.50")


def test_generated_module_blocks_unknown_reference_and_keeps_unknown_reason() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        ask=_quote(QuoteValueState.UNKNOWN),
        bid=_quote(QuoteValueState.PRESENT, "10.00"),
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.REFERENCE_QUOTE_UNKNOWN
    assert decision.reference_source is PriceQuoteSource.ASK


def test_generated_module_calculates_high_precision_decimals_exactly() -> None:
    rule = _rule(
        price_tick=Decimal("0.01"),
        buy_deviation_ratio=Decimal("0.01"),
        buy_widening_ticks=0,
        minimum_distance_ticks=0,
    )
    decision = _calculate(
        side=ExecutionSide.BUY,
        rule=rule,
        ask=_quote(QuoteValueState.PRESENT, "123456789012345678901234567890.00"),
    )

    assert decision.boundary_price == Decimal("124691356902469135690246913568.90")


def test_generated_module_keeps_not_applicable_separate_from_allowed() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        ask=_quote(QuoteValueState.PRESENT, "10.00"),
        stage=PriceSubmissionStage.OPENING_AUCTION,
    )

    assert decision.status is PriceSubmissionRangeStatus.NOT_APPLICABLE
    assert decision.reason_code is PriceSubmissionRangeReason.PRICE_CAGE_NOT_APPLICABLE


def test_generated_projection_contains_only_standard_library_imports() -> None:
    tree = ast.parse(GENERATED_MODULE_PATH.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

    assert all(isinstance(node, ast.ImportFrom) for node in imports)
    signatures = {
        (node.module, tuple(alias.name for alias in node.names))
        for node in imports
        if isinstance(node, ast.ImportFrom)
    }
    assert signatures == {
        ("__future__", ("annotations",)),
        ("dataclasses", ("dataclass",)),
        ("decimal", ("Decimal",)),
        ("enum", ("StrEnum",)),
        ("fractions", ("Fraction",)),
    }


def test_projection_is_deterministic_and_embeds_the_combined_source_hash() -> None:
    price_source = PRICE_DOMAIN_PATH.read_text(encoding="utf-8")
    execution_source = EXECUTION_DOMAIN_PATH.read_text(encoding="utf-8")
    generated = render_projection(price_source, execution_source)
    execution_tree = ast.parse(execution_source)
    side_definition = next(
        node
        for node in execution_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionSide"
    )
    side_source = ast.get_source_segment(execution_source, side_definition)
    assert side_source is not None
    expected_hash = hashlib.sha256(
        (normalize_lf(price_source) + normalize_lf(side_source)).encode("utf-8")
    ).hexdigest()

    assert generated.encode("utf-8") == GENERATED_MODULE_PATH.read_bytes()
    assert "# Generated by scripts/build_qmt_price_submission_projection.py" in generated
    assert "# Source: apps/risk_center/domain/price_submission_range.py" in generated
    assert (
        "# Additional source: "
        "apps/risk_center/domain/execution_trading_constraints.py::ExecutionSide"
    ) in generated
    assert f"# Effective source SHA-256: {expected_hash}" in generated
    header = [
        line
        for line in generated.splitlines()
        if line.startswith("# Generated")
        or line.startswith("# Source")
        or line.startswith("# Additional source")
        or line.startswith("# Effective source")
    ]
    assert all("git" not in line.lower() and "timestamp" not in line.lower() for line in header)


def test_renderer_rejects_unexpected_source_imports() -> None:
    price_source = PRICE_DOMAIN_PATH.read_text(encoding="utf-8").replace(
        "from fractions import Fraction",
        "import pandas",
    )
    execution_source = EXECUTION_DOMAIN_PATH.read_text(encoding="utf-8")

    with pytest.raises(ProjectionBuildError, match="unexpected import"):
        render_projection(price_source, execution_source)


def test_renderer_rejects_nested_source_imports() -> None:
    price_source = PRICE_DOMAIN_PATH.read_text(encoding="utf-8").replace(
        "def _validate_token(value: object, field_name: str) -> None:\n",
        "def _validate_token(value: object, field_name: str) -> None:\n    import os\n",
    )
    execution_source = EXECUTION_DOMAIN_PATH.read_text(encoding="utf-8")

    with pytest.raises(ProjectionBuildError, match="nested import"):
        render_projection(price_source, execution_source)


@pytest.mark.parametrize(
    "dynamic_expression",
    [
        "__import__('os')",
        "importlib.import_module('os')",
        "dynamic_loader = __import__",
    ],
)
def test_renderer_rejects_dynamic_import_references(dynamic_expression: str) -> None:
    price_source = PRICE_DOMAIN_PATH.read_text(encoding="utf-8").replace(
        "def _validate_token(value: object, field_name: str) -> None:\n",
        "def _validate_token(value: object, field_name: str) -> None:\n"
        f"    {dynamic_expression}\n",
    )
    execution_source = EXECUTION_DOMAIN_PATH.read_text(encoding="utf-8")

    with pytest.raises(ProjectionBuildError, match="dynamic import"):
        render_projection(price_source, execution_source)


def test_renderer_rejects_unexpected_execution_side_structure() -> None:
    price_source = PRICE_DOMAIN_PATH.read_text(encoding="utf-8")
    execution_source = EXECUTION_DOMAIN_PATH.read_text(encoding="utf-8").replace(
        '    SELL = "SELL"',
        '    HOLD = "HOLD"',
    )

    with pytest.raises(ProjectionBuildError, match="ExecutionSide"):
        render_projection(price_source, execution_source)


def test_check_projection_detects_missing_or_drifted_bytes_without_writing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "price_submission_range.py"
    expected = b"# generated\n"

    assert not check_projection(target, expected)
    assert not target.exists()

    target.write_bytes(b"# generated\r\n")
    before_check = target.read_bytes()
    assert not check_projection(target, expected)
    assert target.read_bytes() == before_check

    target.write_bytes(expected)
    before_check = target.read_bytes()
    assert check_projection(target, expected)
    assert target.read_bytes() == before_check


def test_cli_check_passes_without_modifying_the_generated_projection() -> None:
    before_check = GENERATED_MODULE_PATH.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert GENERATED_MODULE_PATH.read_bytes() == before_check
