"""Transactional and non-destructive Equity configuration bootstrap contracts."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError

from apps.equity.infrastructure.config_repositories import EquityBootstrapConfigRepository
from apps.equity.infrastructure.models import StockScreeningRuleConfigModel
from apps.equity.management.commands import init_equity_config
from apps.fund.infrastructure.models import FundTypePreferenceConfigModel
from apps.sector.infrastructure.models import SectorPreferenceConfigModel


@pytest.mark.django_db
def test_equity_config_bootstrap_preserves_existing_rows_unless_forced() -> None:
    """Default bootstrap fills missing rows without overwriting governed values."""

    existing = StockScreeningRuleConfigModel._default_manager.create(
        regime="Recovery",
        rule_name="复苏期成长股",
        min_roe=99.0,
    )
    output = StringIO()

    call_command("init_equity_config", force=False, stdout=output)

    existing.refresh_from_db()
    assert existing.min_roe == 99.0
    assert StockScreeningRuleConfigModel._default_manager.count() == 4
    assert SectorPreferenceConfigModel._default_manager.count() == 13
    assert FundTypePreferenceConfigModel._default_manager.count() == 7
    assert "created=23" in output.getvalue()
    assert "preserved=1" in output.getvalue()

    forced_output = StringIO()
    call_command("init_equity_config", force=True, stdout=forced_output)

    existing.refresh_from_db()
    assert existing.min_roe == 15.0
    assert "updated=24" in forced_output.getvalue()


@pytest.mark.django_db(transaction=True)
def test_equity_config_bootstrap_rolls_back_all_categories_on_database_failure(
    monkeypatch,
) -> None:
    """A later category failure cannot leave a partially initialized database."""

    repository = EquityBootstrapConfigRepository()

    def _fail_sector(
        preference: dict[str, object],
        *,
        overwrite: bool = True,
    ) -> str:
        del preference, overwrite
        raise DatabaseError("postgres://secret-host")

    monkeypatch.setattr(repository, "upsert_sector_preference", _fail_sector)
    command = init_equity_config.Command(stdout=StringIO())
    command._get_repository = lambda: repository

    with pytest.raises(CommandError, match="DatabaseError") as exc_info:
        command.handle(force=False)

    assert "secret-host" not in str(exc_info.value)
    assert "配置初始化完成" not in command.stdout.getvalue()
    assert StockScreeningRuleConfigModel._default_manager.count() == 0
    assert SectorPreferenceConfigModel._default_manager.count() == 0
    assert FundTypePreferenceConfigModel._default_manager.count() == 0
