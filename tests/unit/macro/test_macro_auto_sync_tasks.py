"""Tests for metadata-driven macro freshness checks and auto-sync tasks."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.data_center.application.dtos import MacroDataPoint, MacroSeriesResponse, SyncResult
from apps.data_center.domain.entities import IndicatorCatalog
from apps.macro.application.tasks import (
    auto_sync_due_macro_indicators,
    check_data_freshness,
)


class MacroAutoSyncTaskTests(SimpleTestCase):
    """Verify macro freshness checks and auto-sync use catalog metadata."""

    @staticmethod
    def _catalog(
        code: str,
        *,
        period_type: str = "M",
        sync_supported: bool = True,
        source_type: str = "akshare",
    ) -> IndicatorCatalog:
        extra = {}
        if sync_supported:
            extra = {
                "governance_sync_supported": True,
                "governance_sync_source_type": source_type,
            }
        return IndicatorCatalog(
            code=code,
            name_cn=code,
            default_period_type=period_type,
            extra=extra,
        )

    @staticmethod
    def _response(
        code: str,
        *,
        freshness_status: str,
        decision_grade: str,
        latest_reporting_period: date | None,
        age_days: int | None = None,
    ) -> MacroSeriesResponse:
        points = []
        if latest_reporting_period is not None and age_days is not None:
            points = [
                MacroDataPoint(
                    indicator_code=code,
                    reporting_period=latest_reporting_period,
                    value=1.0,
                    unit="亿元",
                    display_value=1.0,
                    display_unit="亿元",
                    original_unit="亿元",
                    source="akshare",
                    quality="official",
                    published_at=latest_reporting_period,
                    age_days=age_days,
                    is_stale=freshness_status == "stale",
                    freshness_status=freshness_status,
                    decision_grade=decision_grade,
                )
            ]
        return MacroSeriesResponse(
            indicator_code=code,
            name_cn=code,
            period_type="Q",
            data=points,
            total=len(points),
            freshness_status=freshness_status,
            decision_grade=decision_grade,
            latest_reporting_period=latest_reporting_period,
            latest_published_at=latest_reporting_period,
            blocked_reason="" if freshness_status == "fresh" else "needs refresh",
        )

    @patch("apps.macro.application.tasks.send_data_freshness_alert.delay")
    @patch("apps.macro.application.tasks.make_query_macro_series_use_case")
    @patch("apps.macro.application.tasks.get_indicator_catalog_repository")
    def test_check_data_freshness_uses_governance_metadata_instead_of_hardcoded_codes(
        self,
        mock_catalog_repo_factory: Mock,
        mock_query_use_case_factory: Mock,
        mock_alert_delay: Mock,
    ) -> None:
        """Freshness checks should scan all governed sync-supported indicators."""

        mock_catalog_repo = Mock()
        mock_catalog_repo.list_active.return_value = [
            self._catalog("CN_GDP", period_type="Q"),
            self._catalog("CN_PMI", period_type="M"),
            self._catalog("CN_LOCAL_ONLY", sync_supported=False),
        ]
        mock_catalog_repo_factory.return_value = mock_catalog_repo

        mock_query_use_case = Mock()
        mock_query_use_case.execute.side_effect = [
            self._response(
                "CN_GDP",
                freshness_status="stale",
                decision_grade="degraded",
                latest_reporting_period=date(2026, 3, 31),
                age_days=140,
            ),
            self._response(
                "CN_PMI",
                freshness_status="missing",
                decision_grade="blocked",
                latest_reporting_period=None,
            ),
        ]
        mock_query_use_case_factory.return_value = mock_query_use_case

        result = check_data_freshness()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["checked_count"], 2)
        self.assertEqual(
            {item["indicator"] for item in result["due_indicators"]},
            {"CN_GDP", "CN_PMI"},
        )
        self.assertEqual(
            [item["indicator"] for item in result["stale_indicators"]],
            ["CN_GDP"],
        )
        mock_alert_delay.assert_called_once()

    @patch("apps.macro.application.tasks.get_active_provider_id_by_source")
    @patch("apps.macro.application.tasks.make_sync_macro_use_case")
    @patch("apps.macro.application.tasks.make_query_macro_series_use_case")
    @patch("apps.macro.application.tasks.get_indicator_catalog_repository")
    def test_auto_sync_due_macro_indicators_only_syncs_due_supported_series(
        self,
        mock_catalog_repo_factory: Mock,
        mock_query_use_case_factory: Mock,
        mock_sync_use_case_factory: Mock,
        mock_provider_id_resolver: Mock,
    ) -> None:
        """Auto-sync should skip fresh indicators and only sync due governed series."""

        mock_catalog_repo = Mock()
        mock_catalog_repo.list_active.return_value = [
            self._catalog("CN_GDP", period_type="Q", source_type="akshare"),
            self._catalog("CN_PMI", period_type="M", source_type="akshare"),
            self._catalog("CN_UNSUPPORTED", sync_supported=False),
        ]
        mock_catalog_repo_factory.return_value = mock_catalog_repo

        mock_query_use_case = Mock()
        mock_query_use_case.execute.side_effect = [
            self._response(
                "CN_GDP",
                freshness_status="stale",
                decision_grade="degraded",
                latest_reporting_period=date(2026, 3, 31),
                age_days=140,
            ),
            self._response(
                "CN_PMI",
                freshness_status="fresh",
                decision_grade="decision_safe",
                latest_reporting_period=date(2026, 4, 30),
                age_days=7,
            ),
        ]
        mock_query_use_case_factory.return_value = mock_query_use_case

        mock_sync_use_case = Mock()
        mock_sync_use_case.execute.return_value = SyncResult(
            domain="macro",
            provider_name="AKShare",
            stored_count=3,
            status="success",
        )
        mock_sync_use_case_factory.return_value = mock_sync_use_case
        mock_provider_id_resolver.return_value = 7

        result = auto_sync_due_macro_indicators()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["synced_indicator_count"], 1)
        self.assertEqual(result["failed_indicator_count"], 0)
        self.assertEqual(len(result["sync_runs"]), 1)
        self.assertEqual(result["sync_runs"][0]["indicator_code"], "CN_GDP")

        request = mock_sync_use_case.execute.call_args.args[0]
        self.assertEqual(request.provider_id, 7)
        self.assertEqual(request.indicator_code, "CN_GDP")
        self.assertEqual(request.start, date(2025, 3, 31))
