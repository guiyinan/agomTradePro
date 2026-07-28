"""Truthfulness coverage for operational signal diagnostics."""

from __future__ import annotations

import io

import pytest
from django.core.management.base import OutputWrapper

from apps.signal.infrastructure.diagnostic_queries import SignalDiagnosticRepository
from apps.signal.infrastructure.models import InvestmentSignalModel
from core.management.commands.test_data_connections import DataConnectionTester


def _create_signal(*, code: str, status: str) -> None:
    InvestmentSignalModel._default_manager.create(
        asset_code=code,
        asset_class="equity",
        direction="LONG",
        logic_desc="测试信号",
        invalidation_description="价格跌破止损线",
        target_regime="Recovery",
        status=status,
    )


@pytest.mark.django_db
def test_signal_diagnostic_summary_uses_real_statuses_and_marks_regime_unavailable(
    django_assert_num_queries,
) -> None:
    _create_signal(code="000001.SZ", status="pending")
    _create_signal(code="000002.SZ", status="approved")
    _create_signal(code="000003.SZ", status="invalidated")
    _create_signal(code="000004.SZ", status="rejected")
    _create_signal(code="000005.SZ", status="expired")

    with django_assert_num_queries(2):
        summary = SignalDiagnosticRepository().get_signal_summary(recent_limit=2)

    assert summary["total_count"] == 5
    assert summary["active_count"] == 1
    assert summary["invalidated_count"] == 1
    assert summary["closed_count"] == 2
    assert len(summary["recent_signals"]) == 2
    assert summary["regime_match_available"] is False
    assert summary["regime_matched_count"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("recent_limit", [True, 0, -1, 101])
def test_signal_diagnostic_rejects_invalid_limit_before_query(
    recent_limit: int,
    django_assert_num_queries,
) -> None:
    with django_assert_num_queries(0), pytest.raises(ValueError, match="recent_limit"):
        SignalDiagnosticRepository().get_signal_summary(recent_limit=recent_limit)


def test_data_connection_command_reports_regime_evidence_as_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.signal.application.query_services.get_signal_diagnostic_summary",
        lambda: {
            "total_count": 0,
            "active_count": 0,
            "invalidated_count": 0,
            "closed_count": 0,
            "recent_signals": [],
            "regime_match_available": False,
            "regime_matched_count": 0,
        },
    )
    tester = DataConnectionTester(OutputWrapper(io.StringIO()))

    assert tester.test_investment_signals() is True
    regime_result = next(result for result in tester.results if result["test"] == "Regime匹配")
    assert regime_result["status"] == "warning"
    assert "匹配证据不可用" in regime_result["details"]
    assert "暂无与当前Regime匹配" not in regime_result["details"]
