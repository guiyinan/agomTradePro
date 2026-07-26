"""Safety contracts for Dashboard Alpha homepage runtime metadata."""

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult
from apps.dashboard.application.alpha_homepage_runtime import AlphaRuntimeMixin


def _scope() -> AlphaPoolScope:
    return AlphaPoolScope(
        pool_type="portfolio",
        market="CN",
        pool_mode="strict_valuation",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 7, 26),
        display_label="Test scope",
    )


def _result(*, staleness_days: object = None, metadata: object = None) -> AlphaResult:
    result = AlphaResult(
        success=False,
        scores=[],
        source="none",
        timestamp="2026-07-26T00:00:00+00:00",
        status="unavailable",
        metadata=metadata if isinstance(metadata, dict) else {},
    )
    dynamic_result = cast(Any, result)
    dynamic_result.staleness_days = staleness_days
    if metadata is not None and not isinstance(metadata, dict):
        dynamic_result.metadata = metadata
    return result


def test_meta_date_normalizes_datetime_to_plain_date() -> None:
    """Datetime metadata cannot leak into date-only subtraction paths."""

    value = datetime(2026, 7, 26, 8, 30, tzinfo=UTC)

    parsed = AlphaRuntimeMixin._parse_meta_date(value)

    assert parsed == date(2026, 7, 26)
    assert type(parsed) is date


@pytest.mark.parametrize("invalid_age", [True, -1, "7", float("nan")])
def test_readiness_ignores_invalid_staleness_values(invalid_age: object) -> None:
    """Malformed provider age metadata cannot mark a result stale or crash rendering."""

    fields = AlphaRuntimeMixin()._build_readiness_fields(
        alpha_result=_result(staleness_days=invalid_age),
        scope=_scope(),
        metadata={},
    )

    assert fields["result_age_days"] is None
    assert fields["is_stale"] is False


def test_build_meta_tolerates_non_mapping_metadata_and_notice() -> None:
    """Dynamic provider metadata is narrowed before nested field access."""

    result = _result(metadata="not-an-object")

    meta = AlphaRuntimeMixin()._build_meta(
        alpha_result=result,
        scope=_scope(),
    )

    assert meta["warning_title"] is None
    assert meta["warning_message"] is None
    assert meta["recommendation_ready"] is False


def test_celery_health_failure_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Broker or credential details never enter the homepage health payload."""

    secret = "redis://user:secret@internal-host/0"

    def fail_health_check():
        raise RuntimeError(secret)

    monkeypatch.setattr(
        "apps.dashboard.application.alpha_homepage_runtime.get_celery_health_checker",
        fail_health_check,
    )

    status = AlphaRuntimeMixin._get_async_refresh_celery_health()

    assert status["reason"] == "health_check_failed"
    assert status["error"] == "Celery health check failed."
    assert secret not in str(status)
