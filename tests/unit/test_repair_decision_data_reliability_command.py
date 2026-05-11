from datetime import date
from types import SimpleNamespace

from django.core.management import CommandError
from kombu.exceptions import OperationalError as KombuOperationalError

from apps.data_center.management.commands import repair_decision_data_reliability as command_module


def test_command_builds_repair_use_case_with_unit_rule_repository(monkeypatch):
    captured: dict[str, object] = {}

    class FakeUseCase:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute(self, request):
            captured["request"] = request
            return SimpleNamespace(
                to_dict=lambda: {
                    "must_not_use_for_decision": False,
                    "blocked_reasons": [],
                }
            )

    monkeypatch.setattr(command_module, "RepairDecisionDataReliabilityUseCase", FakeUseCase)
    monkeypatch.setattr(command_module.Command, "_resolve_user", lambda self, user_id: None)

    command_module.Command().handle(
        target_date="2026-05-11",
        portfolio_id=None,
        user_id=None,
        asset_codes="000300.SH",
        macro_indicator_codes="CN_NEW_CREDIT",
        strict=False,
        quote_max_age_hours=4.0,
        skip_pulse=True,
        skip_alpha=True,
        sync_alpha=False,
    )

    assert "indicator_unit_rule_repo" in captured
    assert captured["request"].macro_indicator_codes == ["CN_NEW_CREDIT"]


def test_alpha_refresher_skips_qlib_rebuild_when_check_passes(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_call_command(name, **kwargs):
        calls.append({"name": name, **kwargs})

    class FakeResolver:
        def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
            return SimpleNamespace(
                scope=SimpleNamespace(
                    universe_id="portfolio-1-scope",
                    scope_hash="scope",
                    to_dict=lambda: {"scope_hash": "scope"},
                )
            )

    class FakeTask:
        @staticmethod
        def apply(args=None, kwargs=None):
            return SimpleNamespace(get=lambda: {"ok": True})

    monkeypatch.setattr(command_module, "call_command", fake_call_command)
    monkeypatch.setattr(
        command_module.Command,
        "_sync_scope_quotes",
        staticmethod(lambda codes: {"status": "success", "stored_count": len(codes)}),
    )
    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        FakeResolver,
    )
    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeTask)

    refresher = command_module.Command._build_alpha_refresher(
        SimpleNamespace(id=7),
        sync_alpha=True,
    )
    result = refresher(date(2026, 4, 24), portfolio_id=1)

    assert [call["name"] for call in calls] == ["build_qlib_data"]
    assert calls[0]["check_only"] is True
    assert result["status"] == "completed"
    assert result["universe_id"] == "portfolio-1-scope"


def test_alpha_refresher_rebuilds_qlib_when_check_fails(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_call_command(name, **kwargs):
        calls.append({"name": name, **kwargs})
        if kwargs.get("check_only"):
            raise CommandError("stale")

    class FakeResolver:
        def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
            return SimpleNamespace(
                scope=SimpleNamespace(
                    universe_id="portfolio-1-scope",
                    scope_hash="scope",
                    to_dict=lambda: {"scope_hash": "scope"},
                )
            )

    class FakeTask:
        @staticmethod
        def apply(args=None, kwargs=None):
            return SimpleNamespace(get=lambda: {"ok": True})

    monkeypatch.setattr(command_module, "call_command", fake_call_command)
    monkeypatch.setattr(
        command_module.Command,
        "_sync_scope_quotes",
        staticmethod(lambda codes: {"status": "success", "stored_count": len(codes)}),
    )
    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        FakeResolver,
    )
    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeTask)

    refresher = command_module.Command._build_alpha_refresher(
        SimpleNamespace(id=7),
        sync_alpha=True,
    )
    result = refresher(date(2026, 4, 24), portfolio_id=1)

    assert [call["name"] for call in calls] == ["build_qlib_data", "build_qlib_data"]
    assert calls[0]["check_only"] is True
    assert calls[1].get("check_only") is None
    assert result["status"] == "completed"


def test_alpha_refresher_queues_scoped_inference_by_default(monkeypatch):
    class FakeResolver:
        def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
            return SimpleNamespace(
                scope=SimpleNamespace(
                    universe_id="portfolio-1-scope",
                    scope_hash="scope",
                    to_dict=lambda: {"scope_hash": "scope"},
                )
            )

    class FakeTask:
        @staticmethod
        def apply_async(args=None, kwargs=None):
            return SimpleNamespace(id="task-123")

    monkeypatch.setattr(command_module, "call_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        command_module.Command,
        "_sync_scope_quotes",
        staticmethod(lambda codes: {"status": "success", "stored_count": len(codes)}),
    )
    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        FakeResolver,
    )
    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeTask)

    refresher = command_module.Command._build_alpha_refresher(SimpleNamespace(id=7))
    result = refresher(date(2026, 4, 24), portfolio_id=1)

    assert result["status"] == "queued"
    assert result["task_id"] == "task-123"
    assert result["qlib_result"]["message"] == "Scoped Alpha inference queued."


def test_alpha_refresher_returns_queue_failed_when_broker_unavailable(monkeypatch):
    class FakeResolver:
        def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
            return SimpleNamespace(
                scope=SimpleNamespace(
                    universe_id="portfolio-1-scope",
                    scope_hash="scope",
                    to_dict=lambda: {"scope_hash": "scope"},
                )
            )

    class FakeTask:
        @staticmethod
        def apply_async(args=None, kwargs=None):
            raise KombuOperationalError("redis unavailable")

    monkeypatch.setattr(command_module, "call_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        command_module.Command,
        "_sync_scope_quotes",
        staticmethod(lambda codes: {"status": "success", "stored_count": len(codes)}),
    )
    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        FakeResolver,
    )
    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeTask)

    refresher = command_module.Command._build_alpha_refresher(SimpleNamespace(id=7))
    result = refresher(date(2026, 4, 24), portfolio_id=1)

    assert result["status"] == "queue_failed"
    assert result["task_id"] == ""
    assert "redis unavailable" in result["qlib_result"]["error_message"]
