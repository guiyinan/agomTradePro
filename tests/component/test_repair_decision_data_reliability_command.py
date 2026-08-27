from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.core.management import CommandError
from kombu.exceptions import OperationalError as KombuOperationalError

from apps.data_center.management.commands import repair_decision_data_reliability as command_module


@pytest.mark.django_db
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
    monkeypatch.setattr(
        command_module,
        "make_system_audited_sync_macro_use_case",
        lambda **_kwargs: SimpleNamespace(execute=lambda _request: None),
    )
    monkeypatch.setattr(
        command_module,
        "make_system_audited_sync_price_use_case",
        lambda **_kwargs: SimpleNamespace(execute=lambda _request: None),
    )
    monkeypatch.setattr(
        command_module,
        "make_system_audited_sync_quote_use_case",
        lambda **_kwargs: SimpleNamespace(execute=lambda _request: None),
    )
    decision_read_recorder = SimpleNamespace(execute=lambda _command: None)
    monkeypatch.setattr(
        command_module,
        "make_publication_decision_read_recorder",
        lambda: decision_read_recorder,
    )
    repair_audit = SimpleNamespace(
        identity_issuer=object(),
        identity_unit_of_work=object(),
        audit_writer=object(),
        clock=object(),
    )
    monkeypatch.setattr(
        command_module,
        "make_repair_run_audit_dependencies",
        lambda: repair_audit,
    )
    monkeypatch.setattr(
        command_module.Command,
        "_resolve_user",
        lambda self, user_id: SimpleNamespace(id=7),
    )
    monkeypatch.setattr(
        command_module.Command,
        "_resolve_default_portfolio_id",
        staticmethod(lambda user, target_date: 135),
    )

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
    assert "macro_sync_use_case" in captured
    assert "price_sync_use_case" in captured
    assert "quote_sync_use_case" in captured
    assert captured["decision_read_recorder"] is decision_read_recorder
    assert captured["data_repair_audit_writer"] is repair_audit.audit_writer
    assert captured["request"].macro_indicator_codes == ["CN_NEW_CREDIT"]
    assert captured["request"].portfolio_id == 135


def test_command_normalizes_and_bounds_code_options() -> None:
    assert command_module._split_codes(
        " 000300.sh,000300.SH, cn_new_credit ",
        (),
        option_name="--asset-codes",
    ) == ["000300.SH", "CN_NEW_CREDIT"]

    with pytest.raises(CommandError, match="non-empty"):
        command_module._split_codes("", (), option_name="--asset-codes")
    with pytest.raises(CommandError, match="invalid code"):
        command_module._split_codes("000300.SH;DROP", (), option_name="--asset-codes")
    with pytest.raises(CommandError, match="at most"):
        command_module._split_codes(
            ",".join(f"CODE_{index}" for index in range(command_module.MAX_REPAIR_CODES + 1)),
            (),
            option_name="--asset-codes",
        )


@pytest.mark.django_db
def test_command_rejects_invalid_scope_and_freshness_options() -> None:
    command = command_module.Command()

    for value in (True, 0, -1):
        with pytest.raises(CommandError, match="positive integer"):
            command._optional_positive_id(value, "--portfolio-id")
    for value in (True, 0, -1.0, float("nan"), float("inf")):
        with pytest.raises(CommandError, match="positive finite"):
            command._positive_finite_float(value, "--quote-max-age-hours")
    with pytest.raises(CommandError, match="Active user not found"):
        command._resolve_user(2_147_483_647)

    with pytest.raises(CommandError, match="cannot be in the future"):
        command.handle(
            target_date=(date.today() + timedelta(days=1)).isoformat(),
            portfolio_id=None,
            user_id=None,
            asset_codes=None,
            macro_indicator_codes=None,
            strict=False,
            quote_max_age_hours=4.0,
            skip_pulse=True,
            skip_alpha=True,
            sync_alpha=False,
        )


def test_alpha_refresher_skips_qlib_rebuild_when_check_passes(monkeypatch):
    calls: list[dict[str, object]] = []
    resolver_calls: list[dict[str, object]] = []

    def fake_call_command(name, **kwargs):
        calls.append({"name": name, **kwargs})

    class FakeResolver:
        def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
            resolver_calls.append(
                {
                    "user_id": user_id,
                    "portfolio_id": portfolio_id,
                    "trade_date": trade_date,
                    "pool_mode": pool_mode,
                }
            )
            return SimpleNamespace(
                portfolio_id=portfolio_id,
                scope=SimpleNamespace(
                    universe_id="portfolio-1-scope",
                    scope_hash="scope",
                    to_dict=lambda: {"scope_hash": "scope"},
                ),
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
    assert resolver_calls[0]["pool_mode"] == "strict_valuation"
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
