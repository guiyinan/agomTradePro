"""Boundary tests for Data Center management commands."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.data_center.management.commands import import_investor_accounts


@pytest.mark.parametrize(
    "command_name",
    ("sync_market_thermometer_inputs", "calculate_market_thermometer"),
)
def test_market_thermometer_commands_reject_invalid_date(command_name: str) -> None:
    """Invalid ISO dates fail as stable command errors."""

    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        call_command(command_name, "--as-of-date", "2026-02-30", stdout=StringIO())


def test_coverage_command_rejects_unbounded_or_non_boolean_options() -> None:
    """Direct call_command callers cannot bypass bounded audit options."""

    with pytest.raises(CommandError, match="sample-size"):
        call_command("audit_on_demand_coverage", sample_size=0, stdout=StringIO())
    with pytest.raises(CommandError, match="hydrate"):
        call_command("audit_on_demand_coverage", hydrate="false", stdout=StringIO())


def test_backfill_command_rejects_non_list_codes() -> None:
    """Programmatic callers must provide a list of code strings."""

    with pytest.raises(CommandError, match="codes must be supplied as text values"):
        call_command("backfill_asset_master", codes="600000.SH", stdout=StringIO())


@pytest.mark.parametrize(
    "command_name",
    ("init_macro_indicator_governance", "normalize_macro_fact_units"),
)
def test_macro_governance_commands_reject_non_text_codes(command_name: str) -> None:
    """Programmatic callers cannot pass dynamic containers as indicator codes."""

    with pytest.raises(CommandError, match="comma-separated text"):
        call_command(command_name, indicator_codes=["CN_PMI"], stdout=StringIO())


def test_import_command_redacts_file_and_parser_error_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CSV paths and parser exception bodies are not disclosed in command errors."""

    missing_path = tmp_path / "secret-token.csv"
    with pytest.raises(CommandError) as missing_error:
        call_command("import_investor_accounts", "--file", str(missing_path))
    assert "secret-token" not in str(missing_error.value)

    csv_path = tmp_path / "investor_accounts.csv"
    csv_path.write_text("reporting_period,value\n2026-05-31,12345\n", encoding="utf-8")

    class _RejectingUseCase:
        def execute(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            raise ValueError("database-password=private")

    monkeypatch.setattr(
        import_investor_accounts,
        "make_import_investor_accounts_use_case",
        lambda: _RejectingUseCase(),
    )
    with pytest.raises(CommandError) as parser_error:
        call_command("import_investor_accounts", "--file", str(csv_path))
    assert "database-password" not in str(parser_error.value)
    assert str(parser_error.value) == "Invalid investor-account CSV."


def test_a_share_sync_redacts_malformed_file_details(tmp_path: Path) -> None:
    """Malformed provider files fail without echoing their contents or paths."""

    json_path = tmp_path / "secret-universe.json"
    json_path.write_text('{"rows": ["token=private"', encoding="utf-8")

    with pytest.raises(CommandError) as error:
        call_command("sync_a_share_universe", "--input-file", str(json_path))

    message = str(error.value)
    assert message == "A-share universe input could not be loaded."
    assert "secret-universe" not in message
    assert "token=private" not in message
