from datetime import date
from unittest.mock import Mock

from django.core.management import call_command

from apps.macro.infrastructure.adapters.base import MacroDataPoint
from apps.macro.management.commands import sync_macro_data as sync_macro_module


def test_sync_macro_command_uses_string_period_types_for_gdp_and_monthly(monkeypatch):
    adapter = Mock()
    adapter.fetch.side_effect = [
        [
            MacroDataPoint(
                code="CN_GDP_YOY",
                value=5.4,
                observed_at=date(2025, 3, 1),
                published_at=date(2025, 4, 18),
                source="akshare",
                unit="%",
                original_unit="%",
            )
        ],
        [
            MacroDataPoint(
                code="CN_PMI",
                value=50.8,
                observed_at=date(2025, 4, 1),
                published_at=date(2025, 4, 30),
                source="akshare",
                unit="指数",
                original_unit="指数",
            )
        ],
    ]

    repository = Mock()

    monkeypatch.setattr(sync_macro_module, "AKShareAdapter", lambda: adapter)
    monkeypatch.setattr(sync_macro_module, "DjangoMacroRepository", lambda: repository)
    monkeypatch.setattr(
        sync_macro_module,
        "get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_GDP_YOY": {
                "default_period_type": "Q",
            },
            "CN_PMI": {
                "default_period_type": "M",
            },
        },
    )

    call_command(
        "sync_macro_data",
        source="akshare",
        indicators=["CN_GDP_YOY", "CN_PMI"],
        years=1,
    )

    assert repository.save_indicator.call_count == 2
    assert repository.save_indicator.call_args_list[0].kwargs["period_type_override"] == "Q"
    assert repository.save_indicator.call_args_list[1].kwargs["period_type_override"] == "M"


def test_sync_macro_command_prefers_runtime_catalog_period_overrides(monkeypatch):
    adapter = Mock()
    adapter.fetch.return_value = [
        MacroDataPoint(
            code="CN_BOND_10Y",
            value=2.31,
            observed_at=date(2025, 4, 30),
            published_at=date(2025, 4, 30),
            source="akshare",
            unit="%",
            original_unit="%",
        )
    ]

    repository = Mock()

    monkeypatch.setattr(sync_macro_module, "AKShareAdapter", lambda: adapter)
    monkeypatch.setattr(sync_macro_module, "DjangoMacroRepository", lambda: repository)
    monkeypatch.setattr(
        sync_macro_module,
        "get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_BOND_10Y": {
                "default_period_type": "D",
                "orm_period_type_override": "10Y",
                "domain_period_type_override": "D",
            }
        },
    )

    call_command(
        "sync_macro_data",
        source="akshare",
        indicators=["CN_BOND_10Y"],
        years=1,
    )

    saved_indicator = repository.save_indicator.call_args.args[0]
    assert saved_indicator.period_type == sync_macro_module.PeriodType.DAY
    assert repository.save_indicator.call_args.kwargs["period_type_override"] == "10Y"
