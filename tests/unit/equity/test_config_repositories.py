import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError

from apps.equity.application import config as config_module
from apps.equity.application import interface_services
from apps.equity.domain.entities import ScoringWeightConfig
from apps.equity.domain.entities_valuation_repair import DEFAULT_VALUATION_REPAIR_CONFIG
from apps.equity.infrastructure.config_repositories import (
    ScoringWeightConfigRepository,
    ValuationRepairConfigRepository,
)
from apps.equity.infrastructure.models import (
    ScoringWeightConfigModel,
    ValuationRepairConfigModel,
)
from core.exceptions import MissingConfigError

pytestmark = pytest.mark.django_db


def test_scoring_repository_requires_database_backed_active_config() -> None:
    repository = ScoringWeightConfigRepository()

    with pytest.raises(MissingConfigError, match="未配置启用的股票评分权重"):
        repository.get_active_config()


def test_scoring_repository_does_not_mask_database_failures(mocker) -> None:
    repository = ScoringWeightConfigRepository()
    mocker.patch.object(
        ScoringWeightConfigModel._default_manager,
        "get",
        side_effect=OperationalError("database unavailable"),
    )

    with pytest.raises(OperationalError, match="database unavailable"):
        repository.get_active_config()


def test_scoring_repository_switches_active_config_atomically() -> None:
    repository = ScoringWeightConfigRepository()
    repository.save_config(ScoringWeightConfig(name="balanced"))
    repository.save_config(
        ScoringWeightConfig(
            name="growth",
            growth_weight=0.5,
            profitability_weight=0.35,
            valuation_weight=0.15,
        )
    )

    active_rows = ScoringWeightConfigModel._default_manager.filter(is_active=True)
    assert active_rows.count() == 1
    assert active_rows.get().name == "growth"
    assert repository.get_active_config().name == "growth"


def test_database_rejects_multiple_active_scoring_configs() -> None:
    ScoringWeightConfigModel._default_manager.bulk_create(
        [
            ScoringWeightConfigModel(name="first", is_active=True),
        ]
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ScoringWeightConfigModel._default_manager.bulk_create(
            [
                ScoringWeightConfigModel(name="second", is_active=True),
            ]
        )


def test_valuation_repair_repository_activation_switches_single_active_row() -> None:
    repository = ValuationRepairConfigRepository()
    first = repository.create(
        data={"is_active": True, "change_reason": "initial"},
        created_by="tester",
    )
    second = repository.create(
        data={"is_active": False, "change_reason": "replacement"},
        created_by="tester",
    )

    activated = repository.activate(config_id=int(second.pk))

    first.refresh_from_db()
    second.refresh_from_db()
    assert activated is not None
    assert first.is_active is False
    assert second.is_active is True
    assert second.effective_from is not None
    assert second.effective_from <= datetime.now(UTC)
    assert ValuationRepairConfigModel._default_manager.filter(is_active=True).count() == 1


def test_valuation_repair_repository_schema_fallback_sanitizes_error_log(
    mocker,
    caplog,
) -> None:
    """Schema compatibility fallback stays in Infrastructure and hides DB error text."""

    repository = ValuationRepairConfigRepository()
    mocker.patch.object(
        repository,
        "get_active_model",
        side_effect=OperationalError("password=should-not-appear"),
    )

    with caplog.at_level(logging.WARNING):
        assert repository.get_active_model_if_available() is None

    assert "OperationalError" in caplog.text
    assert "should-not-appear" not in caplog.text


def test_runtime_config_discards_wrong_cache_type_before_fallback(monkeypatch) -> None:
    """A poisoned or stale cache object cannot cross into the Domain return contract."""

    cache = SimpleNamespace(
        get=Mock(return_value={"not": "a config"}),
        delete=Mock(),
        set=Mock(),
    )
    repository = SimpleNamespace(get_active_domain_config_if_available=lambda: None)
    monkeypatch.setattr(config_module, "cache", cache)
    monkeypatch.setattr(
        config_module,
        "get_equity_valuation_repair_config_repository",
        lambda: repository,
    )

    result = config_module.get_valuation_repair_config()

    assert isinstance(result, type(DEFAULT_VALUATION_REPAIR_CONFIG))
    cache.delete.assert_called_once_with("equity:valuation_repair_config")
    cache.set.assert_called_once()


@pytest.mark.parametrize("use_cache", [1, "true", None])
def test_runtime_config_rejects_non_boolean_cache_flag(use_cache: object) -> None:
    """Dynamic callers cannot switch cache behavior with truthy non-booleans."""

    with pytest.raises(ValueError, match="use_cache must be a boolean"):
        config_module.get_valuation_repair_config(use_cache=use_cache)


def test_bootstrap_interface_reuses_one_repository_per_batch(monkeypatch) -> None:
    """Bootstrap batches do not rebuild the same repository for every row."""

    repository = SimpleNamespace(upsert_stock_screening_rule=Mock())
    factory = Mock(return_value=repository)
    monkeypatch.setattr(interface_services, "get_equity_bootstrap_config_repository", factory)
    rules = [
        {"regime": "Recovery", "rule_name": "one"},
        {"regime": "Deflation", "rule_name": "two"},
    ]

    interface_services.init_stock_screening_rules(rules=rules)

    factory.assert_called_once_with()
    assert repository.upsert_stock_screening_rule.call_count == 2
