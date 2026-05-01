from unittest.mock import Mock

from apps.signal.application.invalidation_checker import InvalidationCheckService
from apps.signal.domain.invalidation import InvalidationCheckResult


class LegacySignalModelStub:
    """Legacy ORM-like stub used by invalidation checker compatibility tests."""

    def __init__(self) -> None:
        self.id = 123
        self.status = "pending"
        self.asset_code = "000001.SH"

    def save(self) -> None:  # pragma: no cover - should never be called
        raise AssertionError("legacy model save should not be called from application layer")


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
