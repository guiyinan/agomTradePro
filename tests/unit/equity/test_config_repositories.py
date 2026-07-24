from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError

from apps.equity.domain.entities import ScoringWeightConfig
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
