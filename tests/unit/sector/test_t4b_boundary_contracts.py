"""Task, compatibility-adapter, and repository contracts for Sector."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from apps.sector.application.tasks import (
    analyze_sector_rotation,
    update_daily_sector_data,
)
from apps.sector.domain.entities import SectorInfo, SectorScore
from apps.sector.infrastructure.adapters.tushare_sector_adapter import (
    TushareSectorAdapter,
)
from apps.sector.infrastructure.repositories import DjangoSectorRepository


def _query(rows: list[dict[str, object]]) -> Mock:
    queryset = Mock()
    queryset.filter.return_value = queryset
    queryset.values.return_value = queryset
    queryset.values_list.return_value = queryset
    queryset.order_by.return_value = queryset
    queryset.first.return_value = rows[0] if rows else None
    queryset.__iter__ = Mock(return_value=iter(rows))
    return queryset


def test_update_daily_task_serializes_success_and_contains_setup_failure() -> None:
    result = SimpleNamespace(success=True, updated_count=12, error=None, error_code=None)
    use_case = Mock()
    use_case.execute.return_value = result

    with (
        patch("apps.sector.application.tasks.get_sector_repository"),
        patch("apps.sector.application.tasks.get_sector_adapter"),
        patch(
            "apps.sector.application.tasks.UpdateSectorDataUseCase",
            return_value=use_case,
        ),
    ):
        payload = update_daily_sector_data.run(level="SW2")

    assert payload == {
        "success": True,
        "updated_count": 12,
        "error": None,
        "error_code": None,
    }
    request = use_case.execute.call_args.args[0]
    assert request.level == "SW2"
    assert date.fromisoformat(request.end_date) == date.today()
    assert (date.fromisoformat(request.end_date) - date.fromisoformat(request.start_date)).days == 7

    with patch(
        "apps.sector.application.tasks.get_sector_repository",
        side_effect=RuntimeError("repository unavailable"),
    ):
        with pytest.raises(RuntimeError, match="repository unavailable"):
            update_daily_sector_data.run()


def test_rotation_task_serializes_scores_and_preserves_business_failure() -> None:
    score = SectorScore(
        sector_code="801010",
        sector_name="Agriculture",
        trade_date=date(2026, 7, 25),
        momentum_score=88.126,
        relative_strength_score=77.234,
        regime_fit_score=66.345,
        total_score=79.876,
        rank=1,
    )
    use_case = Mock()
    use_case.execute.return_value = SimpleNamespace(
        success=True,
        regime="Recovery",
        analysis_date=date(2026, 7, 25),
        top_sectors=[score],
        error=None,
        error_code=None,
        status="available",
        data_source="persisted",
        warning_message=None,
        warning_detail=None,
    )

    with (
        patch("apps.sector.application.tasks.get_sector_repository"),
        patch(
            "apps.sector.application.tasks.AnalyzeSectorRotationUseCase",
            return_value=use_case,
        ),
    ):
        payload = analyze_sector_rotation.run(regime="Recovery")

    assert payload == {
        "success": True,
        "regime": "Recovery",
        "analysis_date": "2026-07-25",
        "top_sectors": [
            {
                "rank": 1,
                "sector_code": "801010",
                "sector_name": "Agriculture",
                "total_score": 79.88,
                "momentum_score": 88.13,
                "rs_score": 77.23,
                "regime_fit_score": 66.34,
            }
        ],
        "error": None,
        "error_code": None,
        "status": "available",
        "data_source": "persisted",
        "warning_message": None,
        "warning_detail": None,
    }
    request = use_case.execute.call_args.args[0]
    assert request.regime == "Recovery"
    assert request.lookback_days == 20
    assert request.top_n == 10

    use_case.execute.return_value = SimpleNamespace(
        success=False,
        regime="Recovery",
        analysis_date=date(2026, 7, 25),
        top_sectors=[],
        error="insufficient data",
        error_code="insufficient_data",
        status="unavailable",
        data_source="none",
        warning_message=None,
        warning_detail=None,
    )
    with (
        patch("apps.sector.application.tasks.get_sector_repository"),
        patch(
            "apps.sector.application.tasks.AnalyzeSectorRotationUseCase",
            return_value=use_case,
        ),
    ):
        failed = analyze_sector_rotation.run()
        assert failed["success"] is False
        assert failed["error"] == "insufficient data"
        assert failed["error_code"] == "insufficient_data"

    with patch(
        "apps.sector.application.tasks.get_sector_repository",
        side_effect=RuntimeError("setup failed"),
    ):
        with pytest.raises(RuntimeError, match="setup failed"):
            analyze_sector_rotation.run()


def test_tushare_compatibility_adapter_delegates_and_normalizes_columns() -> None:
    delegate = Mock()
    delegate.fetch_sw_industry_classify.return_value = pd.DataFrame([{"index_code": "801010"}])
    delegate.fetch_sector_index_daily.return_value = pd.DataFrame(
        [{"trade_date": "20260725", "open": 100.0}]
    )
    delegate.fetch_all_sector_index_daily.return_value = pd.DataFrame(
        [{"sector_code": "801010", "open": 101.0}]
    )
    adapter = TushareSectorAdapter.__new__(TushareSectorAdapter)
    adapter._delegate = delegate

    classify = adapter.fetch_sw_industry_classify(level="L2")
    daily = adapter.fetch_sector_index_daily("801010", "20260701", "20260725")
    all_daily = adapter.fetch_all_sector_index_daily(
        ["801010"],
        "20260701",
        "20260725",
    )

    assert classify.iloc[0]["index_code"] == "801010"
    assert daily.iloc[0]["open_price"] == 100.0
    assert "open" not in daily
    assert all_daily.iloc[0]["open_price"] == 101.0

    delegate.fetch_sector_index_daily.return_value = pd.DataFrame()
    delegate.fetch_all_sector_index_daily.return_value = pd.DataFrame()
    assert adapter.fetch_sector_index_daily("801010", "20260701", "20260725").empty
    assert adapter.fetch_all_sector_index_daily([], "20260701", "20260725").empty


def test_tushare_adapter_constructor_builds_internal_delegate() -> None:
    delegate = Mock()
    with patch(
        "apps.sector.infrastructure.adapters.tushare_sector_adapter." "AKShareSectorAdapter",
        return_value=delegate,
    ) as constructor:
        adapter = TushareSectorAdapter()

    assert adapter._delegate is delegate
    constructor.assert_called_once_with()


def test_tushare_constituents_handle_unknown_empty_and_normalized_sector() -> None:
    adapter = TushareSectorAdapter.__new__(TushareSectorAdapter)
    adapter._delegate = Mock()
    membership_repo = SimpleNamespace(get_members=Mock(return_value=[]))

    with patch(
        "apps.sector.infrastructure.adapters.tushare_sector_adapter.get_sector_membership_repository_port",
        return_value=membership_repo,
    ):
        with pytest.raises(ValueError, match="sector_code_invalid"):
            adapter.fetch_sector_constituents("missing.SI")
        assert adapter.fetch_sector_constituents("801010.SI").empty
        membership_repo.get_members.return_value = [
            SimpleNamespace(
                asset_code="000001.SZ",
                effective_date=date(2020, 1, 1),
                expiry_date=None,
            )
        ]
        result = adapter.fetch_sector_constituents("801010.SI")

    assert result.iloc[0]["con_code"] == "000001.SZ"
    membership_repo.get_members.assert_called_with("801010", as_of=date.today())


def test_repository_builds_deduplicated_stock_sector_map_and_handles_saves() -> None:
    membership_repo = SimpleNamespace(
        list_current=Mock(
            return_value=[
                SimpleNamespace(
                    asset_code="000001.SZ",
                    sector_code="801010",
                    sector_name="Agriculture",
                ),
                SimpleNamespace(
                    asset_code="000001.SZ",
                    sector_code="801010",
                    sector_name="Agriculture",
                ),
                SimpleNamespace(asset_code="", sector_code="801020", sector_name=""),
            ]
        )
    )

    with (
        patch(
            "apps.sector.infrastructure.repositories.get_sector_membership_repository_port",
            return_value=membership_repo,
        ),
        patch(
            "apps.sector.infrastructure.repositories.get_current_publication",
            return_value={"publication_id": "pub-sector"},
        ),
        patch(
            "apps.sector.infrastructure.repositories.get_publication_member_fact_pks",
            return_value=["1", "2"],
        ),
    ):
        assert DjangoSectorRepository().get_stock_sector_name_map() == {
            "000001.SZ": ["Agriculture"]
        }
    membership_repo.list_current.assert_called_once_with(
        as_of=date.today(),
        fact_pks=["1", "2"],
    )

    membership_repo.list_current.return_value = []
    with (
        patch(
            "apps.sector.infrastructure.repositories.get_sector_membership_repository_port",
            return_value=membership_repo,
        ),
        patch(
            "apps.sector.infrastructure.repositories.get_current_publication",
            return_value={"publication_id": "pub-sector"},
        ),
        patch(
            "apps.sector.infrastructure.repositories.get_publication_member_fact_pks",
            return_value=[],
        ),
    ):
        assert DjangoSectorRepository().get_stock_sector_name_map() == {}

    manager = Mock()
    model = SimpleNamespace(_default_manager=manager)
    with patch(
        "apps.sector.infrastructure.repositories.SectorInfoModel",
        model,
    ):
        assert DjangoSectorRepository().save_sector_info(SectorInfo("801010", "Agriculture", "SW1"))
        manager.update_or_create.side_effect = RuntimeError("write failed")
        assert (
            DjangoSectorRepository().save_sector_info(SectorInfo("801010", "Agriculture", "SW1"))
            is False
        )


def test_repository_get_sector_info_maps_active_model_and_missing_state() -> None:
    class _DoesNotExist(Exception):
        pass

    manager = Mock()
    manager.get.return_value = SimpleNamespace(
        sector_code="801010",
        sector_name="Agriculture",
        level="SW1",
        parent_code=None,
    )
    model = SimpleNamespace(
        _default_manager=manager,
        DoesNotExist=_DoesNotExist,
    )

    with patch(
        "apps.sector.infrastructure.repositories.SectorInfoModel",
        model,
    ):
        result = DjangoSectorRepository().get_sector_info("801010")
        manager.get.side_effect = _DoesNotExist
        missing = DjangoSectorRepository().get_sector_info("missing")

    assert result == SectorInfo("801010", "Agriculture", "SW1")
    assert missing is None
