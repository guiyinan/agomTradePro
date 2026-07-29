"""Agent Runtime repository evidence-boundary tests."""

import pytest

from apps.agent_runtime.infrastructure.repositories import (
    _nonnegative_decimal,
    _nonnegative_int,
    _sanitize_evidence,
)


def test_agent_evidence_is_detached_and_credentials_are_redacted() -> None:
    """Persisted evidence cannot retain caller mutations or nested credentials."""

    source = {
        "token": "raw-token",
        "result": {"dsn": "postgresql://user:secret@database.internal/runtime"},
    }
    sanitized = _sanitize_evidence(source)
    source["result"]["dsn"] = "mutated"

    rendered = str(sanitized)
    assert "raw-token" not in rendered
    assert "secret" not in rendered
    assert "mutated" not in rendered


@pytest.mark.parametrize("value", [True, -1, 1.5, "4"])
def test_agent_token_count_rejects_non_exact_nonnegative_integers(value: object) -> None:
    """Dynamic token accounting fails closed on coercible or invalid values."""

    with pytest.raises(ValueError, match="actual_tokens_invalid"):
        _nonnegative_int(value, field_name="actual_tokens")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, True])
def test_agent_cost_rejects_nonfinite_negative_or_boolean_values(value: object) -> None:
    """Invalid cost evidence never reaches the DecimalField boundary."""

    with pytest.raises(ValueError, match="actual_cost_invalid"):
        _nonnegative_decimal(value, field_name="actual_cost")
