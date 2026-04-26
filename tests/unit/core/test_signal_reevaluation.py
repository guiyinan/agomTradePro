from types import SimpleNamespace

from core.integration.signal_reevaluation import reevaluate_signals_for_policy_change


class _FakeSignalRepository:
    pass


class _FakeReevaluateSignalsUseCase:
    def __init__(self, signal_repository):
        assert isinstance(signal_repository, _FakeSignalRepository)

    def execute(self, request):
        assert request.policy_level == 2
        assert request.current_regime == "Recovery"
        assert request.regime_confidence == 0.83
        return SimpleNamespace(total_count=5, rejected_count=2)


def test_signal_reevaluation_bridge_uses_signal_use_case(monkeypatch):
    monkeypatch.setattr(
        "core.integration.signal_reevaluation.get_signal_repository",
        lambda: _FakeSignalRepository(),
    )
    monkeypatch.setattr(
        "core.integration.signal_reevaluation.ReevaluateSignalsUseCase",
        _FakeReevaluateSignalsUseCase,
    )

    result = reevaluate_signals_for_policy_change(
        policy_level=2,
        current_regime="Recovery",
        regime_confidence=0.83,
    )

    assert result.rejected_count == 2
