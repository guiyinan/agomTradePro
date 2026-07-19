"""Contracts for the shared external numeric parser."""

from decimal import Decimal
from pathlib import Path

import pytest

from shared.numeric import safe_float


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1.0), (" 1.25 ", 1.25), (Decimal("2.5"), 2.5)],
)
def test_safe_float_parses_supported_numeric_values(value: object, expected: float) -> None:
    assert safe_float(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", "-", "N/A", "NA", "null", "None", "bad", float("nan"), float("inf")],
)
def test_safe_float_returns_configured_default_for_invalid_values(value: object) -> None:
    assert safe_float(value) is None
    assert safe_float(value, default=0.0) == 0.0


def test_safe_float_supports_explicit_source_formatting_and_scale() -> None:
    assert safe_float("1,234.5%", strip_chars=",%") == 1234.5
    assert safe_float("125", scale=100) == 1.25


def test_safe_float_rejects_zero_scale() -> None:
    with pytest.raises(ValueError, match="scale must be non-zero"):
        safe_float("1", scale=0)


def test_apps_do_not_redefine_safe_float() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    offenders = []
    for path in (repo_root / "apps").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def _safe_float" in text or "def safe_float(" in text:
            offenders.append(path.relative_to(repo_root).as_posix())
    assert offenders == []
