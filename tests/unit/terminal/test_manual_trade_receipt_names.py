"""Factual trade receipts must not hydrate market data to render a security code."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from apps.terminal.application.tui_workbench import TuiMetadataRepository, TuiWorkbenchService


@pytest.mark.parametrize(
    "intent", ["preview_owned_manual_trade_csv", "import_owned_manual_trade_csv"]
)
@pytest.mark.parametrize("known_name", [None, "本地证券"])
def test_manual_trade_grid_uses_canonical_read_only_names(
    monkeypatch: pytest.MonkeyPatch, intent: str, known_name: str | None
) -> None:
    """Unknown local names keep their code and never fall through to hydration."""
    requested: list[list[str]] = []

    def read_only(codes: list[str]) -> dict[str, str]:
        requested.append(codes)
        return {"000001.SZ": known_name} if known_name else {}

    def forbid_hydration(*args: object, **kwargs: object) -> dict[str, str]:
        raise AssertionError("Factual receipt attempted market-data name hydration")

    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench_detail_result_models.resolve_asset_names_read_only",
        read_only,
    )
    monkeypatch.setattr(TuiWorkbenchService, "_resolve_asset_names", forbid_hydration)
    service = TuiWorkbenchService(metadata_repository=Mock(spec=TuiMetadataRepository))
    grid = service._datagrid_model(
        {
            "key": "audit.manual-trade-import",
            "label": "成交回执",
            "intent": intent,
            "view_model": {"columns": [{"key": "asset_code", "label": "证券"}]},
        },
        [{"asset_code": "000001.SZ"}],
        200,
    )
    assert requested and "000001.SZ" in requested[0]
    assert grid["rows"][0]["asset_code"] == (
        f"000001.SZ {known_name}" if known_name else "000001.SZ"
    )


@pytest.mark.parametrize(
    ("canonical_names", "expected_value"),
    [
        ({"000001.SZ": "平安银行"}, "000001.SZ 平安银行"),
        ({}, "000001.SZ"),
    ],
)
def test_nested_detail_asset_codes_use_local_read_only_names_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
    canonical_names: dict[str, str],
    expected_value: str,
) -> None:
    """Use canonical local names in nested details and keep unknown codes intact."""
    requested: list[list[str]] = []

    def read_only(codes: list[str]) -> dict[str, str]:
        requested.append(codes)
        return canonical_names

    def forbid_hydration(_service: TuiWorkbenchService, _codes: list[str]) -> dict[str, str]:
        raise AssertionError("Nested detail rendering attempted market-data hydration")

    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench_detail_result_models.resolve_asset_names_read_only",
        read_only,
    )
    monkeypatch.setattr(TuiWorkbenchService, "_resolve_asset_names", forbid_hydration)
    service = TuiWorkbenchService(metadata_repository=Mock(spec=TuiMetadataRepository))

    fields = service._detail_fields({"task": {"result": {"asset_code": "000001.SZ"}}})
    field_by_key = {field["key"]: field for field in fields}

    assert requested == [["000001", "000001.SZ"]]
    assert field_by_key["task.result.asset_code"]["value"] == expected_value
