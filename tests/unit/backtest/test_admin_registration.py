"""Backtest Admin typing and evidence immutability regressions."""

from __future__ import annotations

from django.contrib import admin

from apps.backtest.interface.admin import BacktestResultAdmin, BacktestTradeAdmin
from apps.backtest.models import BacktestResultModel, BacktestTradeModel
from shared.infrastructure.django_admin import TypedModelAdmin


def test_backtest_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery retains one typed owner per Backtest model."""

    expected = {
        BacktestResultModel: BacktestResultAdmin,
        BacktestTradeModel: BacktestTradeAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


def test_backtest_result_and_trade_evidence_are_fully_immutable() -> None:
    """Admin cannot fabricate, alter, or delete backtest evidence."""

    for model in (BacktestResultModel, BacktestTradeModel):
        evidence_admin = admin.site._registry[model]
        assert evidence_admin.has_add_permission(None) is False
        assert evidence_admin.has_change_permission(None) is False
        assert evidence_admin.has_delete_permission(None) is False
        model_fields = {field.name for field in model._meta.fields}
        assert model_fields <= set(evidence_admin.readonly_fields)


def test_backtest_admin_exposes_reproducibility_evidence() -> None:
    """Operators can inspect the PIT and version evidence behind a result."""

    result_admin = admin.site._registry[BacktestResultModel]
    readonly_fields = set(result_admin.readonly_fields)
    assert {
        "trust_status",
        "data_manifest_id",
        "pit_coverage",
        "config_hash",
        "code_commit",
        "engine_version",
        "research_trial_id",
        "decision_snapshot_id",
        "signal_configs",
        "used_signals",
    } <= readonly_fields
