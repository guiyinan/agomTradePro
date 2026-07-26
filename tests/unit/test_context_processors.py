"""Global template context processor regression tests."""

from types import SimpleNamespace

from core.context_processors import get_alerts, get_market_visuals


def _request(*, authenticated: bool = True):
    return SimpleNamespace(
        user=SimpleNamespace(is_authenticated=authenticated),
        path="/dashboard/",
        COOKIES={},
    )


def test_anonymous_request_skips_all_alert_services(monkeypatch):
    def _unexpected_factory():
        raise AssertionError("anonymous requests must not load alert services")

    monkeypatch.setattr(
        "apps.decision_rhythm.application.global_alert_service."
        "get_decision_rhythm_global_alert_service",
        _unexpected_factory,
    )

    assert get_alerts(_request(authenticated=False)) == {"global_alerts": []}


def test_alert_services_are_reused_once_per_request(monkeypatch):
    factory_calls = {"decision": 0, "alpha": 0}

    class _DecisionService:
        def get_weekly_quota_usage(self):
            return {
                "quota_total": 10,
                "quota_used": 9,
                "quota_remaining": 1,
                "usage_percent": 90.0,
            }

        def count_active_cooldowns(self):
            return 6

        def count_high_priority_pending_requests(self):
            return 1

    class _AlphaService:
        def count_expiring_candidates(self):
            return 1

        def count_expiring_triggers(self):
            return 2

        def count_actionable_candidates(self):
            return 11

    def _decision_factory():
        factory_calls["decision"] += 1
        return _DecisionService()

    def _alpha_factory():
        factory_calls["alpha"] += 1
        return _AlphaService()

    monkeypatch.setattr(
        "apps.decision_rhythm.application.global_alert_service."
        "get_decision_rhythm_global_alert_service",
        _decision_factory,
    )
    monkeypatch.setattr(
        "apps.alpha_trigger.application.global_alert_service."
        "get_alpha_trigger_global_alert_service",
        _alpha_factory,
    )
    monkeypatch.setattr(
        "apps.beta_gate.application.config_summary_service." "get_beta_gate_config_summary_service",
        lambda: SimpleNamespace(get_beta_gate_summary=lambda user: {"status": "configured"}),
    )

    alerts = get_alerts(_request())["global_alerts"]

    assert factory_calls == {"decision": 1, "alpha": 1}
    assert len(alerts) == 6
    assert all(isinstance(alert["dismissible"], bool) for alert in alerts)


def test_invalid_counts_and_non_finite_quota_do_not_create_alerts(monkeypatch):
    decision_service = SimpleNamespace(
        get_weekly_quota_usage=lambda: {
            "quota_remaining": -1,
            "usage_percent": float("nan"),
        },
        count_active_cooldowns=lambda: True,
        count_high_priority_pending_requests=lambda: -1,
    )
    alpha_service = SimpleNamespace(
        count_expiring_candidates=lambda: True,
        count_expiring_triggers=lambda: -2,
        count_actionable_candidates=lambda: float("inf"),
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.global_alert_service."
        "get_decision_rhythm_global_alert_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "apps.alpha_trigger.application.global_alert_service."
        "get_alpha_trigger_global_alert_service",
        lambda: alpha_service,
    )
    monkeypatch.setattr(
        "apps.beta_gate.application.config_summary_service." "get_beta_gate_config_summary_service",
        lambda: SimpleNamespace(get_beta_gate_summary=lambda user: {"status": "configured"}),
    )

    assert get_alerts(_request()) == {"global_alerts": []}


def test_context_failure_logs_only_exception_type(monkeypatch, caplog):
    monkeypatch.setattr(
        "apps.account.application.config_summary_service." "get_account_config_summary_service",
        lambda: (_ for _ in ()).throw(RuntimeError("postgres://user:secret@database")),
    )

    context = get_market_visuals(_request())

    assert context["market_visuals"]["convention"] == "cn_a_share"
    assert "RuntimeError" in caplog.text
    assert "user:secret" not in caplog.text
