from datetime import date
from unittest.mock import Mock

from apps.signal.application.invalidation_checker import (
    InvalidationCheckService,
    _DataCenterMacroRepository,
)
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.signal.domain.invalidation import InvalidationCheckResult


class LegacySignalModelStub:
    """Legacy ORM-like stub used by invalidation checker compatibility tests."""

    def __init__(self) -> None:
        self.id = 123
        self.status = "pending"
        self.asset_code = "000001.SH"

    def save(self) -> None:  # pragma: no cover - should never be called
        raise AssertionError("legacy model save should not be called from application layer")


def test_signal_macro_repository_uses_publication_members(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.signal.application.invalidation_checker.get_published_macro_fact_series",
        lambda code, limit: {
            "rows": [
                {
                    "indicator_code": code,
                    "reporting_period": "2026-06-30",
                    "value": 49.0,
                    "unit": "index",
                },
                {
                    "indicator_code": code,
                    "reporting_period": "2026-07-24",
                    "value": 48.0,
                    "unit": "index",
                },
            ],
            "must_not_use_for_decision": False,
        },
    )

    repository = _DataCenterMacroRepository()

    latest = repository.get_latest_by_code("CN_PMI")
    history = repository.get_history_by_code("CN_PMI")

    assert latest is not None
    assert latest.value == 48.0
    assert history[0].observed_at == date(2026, 7, 24)


def test_legacy_signal_model_path_uses_repository_instead_of_model_save():
    """Application-layer invalidation should delegate persistence to the repository."""

    signal_repository = Mock()
    service = InvalidationCheckService(
        signal_repository=signal_repository,
        macro_repository=Mock(),
    )
    legacy_signal = LegacySignalModelStub()
    result = InvalidationCheckResult(
        is_invalidated=True,
        reason="PMI fell below threshold",
        checked_conditions=[
            {
                "indicator_code": "PMI",
                "actual_value": 49.2,
                "threshold": 50.0,
                "is_met": True,
                "description": "PMI below 50",
            }
        ],
        checked_at="2026-05-01T00:00:00+00:00",
    )

    service._invalidate_signal(legacy_signal, result, current_status="pending")

    signal_repository.persist_invalidation_outcome.assert_called_once()
    kwargs = signal_repository.persist_invalidation_outcome.call_args.kwargs
    assert kwargs["signal_id"] == str(legacy_signal.id)
    assert kwargs["current_status"] == "pending"
    assert kwargs["reason"] == "PMI fell below threshold"
    assert kwargs["details"]["reason"] == "PMI fell below threshold"


def test_notification_formats_checked_condition_mapping() -> None:
    """Notification rendering must consume the domain's mapping-shaped conditions."""

    notification_service = Mock()
    notification_service.send_email.return_value = [Mock(success=True)]
    user_repository = Mock()
    user_repository.get_staff_emails.return_value = ["risk@example.com"]
    service = InvalidationCheckService(
        signal_repository=Mock(),
        user_repository=user_repository,
        notification_service=notification_service,
        macro_repository=Mock(),
    )
    signal = InvestmentSignal(
        id="123",
        asset_code="000001.SH",
        asset_class="equity",
        direction="LONG",
        logic_desc="PMI recovery",
        status=SignalStatus.APPROVED,
    )
    result = InvalidationCheckResult(
        is_invalidated=True,
        reason="PMI fell below threshold",
        checked_conditions=[
            {
                "indicator_code": "PMI",
                "actual_value": 49.2,
                "threshold": 50.0,
                "is_met": True,
            }
        ],
        checked_at="2026-05-01T00:00:00+00:00",
    )

    service._send_invalidation_notification(signal, result)

    notification_service.send_email.assert_called_once()
    call = notification_service.send_email.call_args.kwargs
    assert "Y PMI: 当前值=49.2, 阈值=50.0" in call["body"]
    assert "<strong>PMI</strong>" in call["html_body"]
