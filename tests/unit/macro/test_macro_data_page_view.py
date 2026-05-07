"""Tests for the macro data page template controls."""

from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase

from apps.macro.interface.views.page_views import macro_data_view


class MacroDataPageViewTests(TestCase):
    """Verify the macro data page renders the new chart/detail controls."""

    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_macro_data_view_renders_range_controls_and_detail_drawer(self) -> None:
        """The page should expose range presets and a detail drawer entry point."""

        snapshot = {
            "indicator_map": {
                "CN_PMI": {
                    "code": "CN_PMI",
                    "name": "制造业 PMI",
                    "description": "制造业采购经理指数",
                    "latest_value": 50.2,
                    "unit": "指数",
                    "series_semantics": "monthly_flow",
                    "paired_indicator_code": "",
                    "chart_policy": "",
                    "display_priority": 10,
                    "period_type": "M",
                    "refresh_start": "2020-01-01",
                    "has_data": True,
                    "sync_supported": True,
                    "latest_period": "2026-04",
                }
            },
            "selected_indicator": "CN_PMI",
            "history": [
                {
                    "reporting_period": "2026-04-30",
                    "reporting_period_label": "2026-04",
                    "value": 50.2,
                    "period_type": "M",
                }
            ],
            "stats": {
                "total_indicators": 1,
                "synced_indicators": 1,
                "sync_supported_indicators": 1,
                "sync_unsupported_indicators": 0,
                "total_records": 1,
                "latest_date": "2026-04-30",
            },
            "min_date": "2026-04-30",
            "max_date": "2026-04-30",
            "refresh_provider_id": 1,
            "refresh_end_date": "2026-05-04",
            "sync_supported_indicator_count": 1,
            "sync_unsupported_indicator_count": 0,
            "bulk_refresh_indicator_codes": ["CN_PMI"],
        }

        request = self.factory.get("/macro/data/?indicator=CN_PMI")
        request.user = Mock(is_authenticated=True)

        with patch(
            "apps.macro.interface.views.page_views.get_macro_data_page_snapshot",
            return_value=snapshot,
        ):
            response = macro_data_view(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("近36", content)
        self.assertIn("openDataDetailBtn", content)
        self.assertIn("dataDetailDrawer", content)
        self.assertIn("复制当前区间 Markdown", content)
        self.assertIn("indicatorGovernanceNote", content)

    def test_macro_data_view_keeps_same_quarter_color_across_reset_cycles(self) -> None:
        """Quarter-based reset-stack charts should reuse one fixed color per quarter."""

        snapshot = {
            "indicator_map": {
                "CN_GDP": {
                    "code": "CN_GDP",
                    "name": "GDP 国内生产总值累计值",
                    "description": "季度累计值口径",
                    "latest_value": 318466.4,
                    "unit": "亿元",
                    "series_semantics": "cumulative_level",
                    "paired_indicator_code": "CN_GDP_YOY",
                    "chart_policy": "yearly_reset_bar",
                    "chart_reset_frequency": "year",
                    "chart_segment_basis": "period_delta",
                    "display_priority": 20,
                    "period_type": "Q",
                    "refresh_start": "2020-01-01",
                    "has_data": True,
                    "sync_supported": True,
                    "latest_period": "2025-Q1",
                }
            },
            "selected_indicator": "CN_GDP",
            "history": [
                {
                    "reporting_period": "2024-03-31",
                    "reporting_period_label": "2024-Q1",
                    "value": 296299.0,
                    "storage_value": 296299.0,
                    "storage_unit": "亿元",
                    "display_value": 296299.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "Q",
                    "source": "akshare",
                    "published_at": "2024-04-18",
                },
                {
                    "reporting_period": "2025-03-31",
                    "reporting_period_label": "2025-Q1",
                    "value": 318466.4,
                    "storage_value": 318466.4,
                    "storage_unit": "亿元",
                    "display_value": 318466.4,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "Q",
                    "source": "akshare",
                    "published_at": "2025-04-16",
                },
            ],
            "stats": {
                "total_indicators": 1,
                "synced_indicators": 1,
                "sync_supported_indicators": 1,
                "sync_unsupported_indicators": 0,
                "total_records": 2,
                "latest_date": "2025-03-31",
            },
            "min_date": "2024-03-31",
            "max_date": "2025-03-31",
            "refresh_provider_id": 1,
            "refresh_end_date": "2026-05-04",
            "sync_supported_indicator_count": 1,
            "sync_unsupported_indicator_count": 0,
            "bulk_refresh_indicator_codes": ["CN_GDP"],
        }

        request = self.factory.get("/macro/data/?indicator=CN_GDP")
        request.user = Mock(is_authenticated=True)

        with patch(
            "apps.macro.interface.views.page_views.get_macro_data_page_snapshot",
            return_value=snapshot,
        ):
            response = macro_data_view(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Q1: '#2563EB'", content)
        self.assertIn("Q2: '#0F766E'", content)
        self.assertIn("Q3: '#CA8A04'", content)
        self.assertIn("Q4: '#C2410C'", content)
        self.assertIn("return `Q${Math.floor((monthNumber - 1) / 3) + 1}`;", content)
        self.assertIn("return ['Q1', 'Q2', 'Q3', 'Q4'];", content)
        self.assertIn("periodType: String(row.period_type || payload.period_type || ''),", content)
        self.assertIn("const periodType = String(chartPoints?.[0]?.periodType || '').toUpperCase();", content)

    def test_macro_data_view_uses_grouped_visible_range_for_reset_stack_charts(self) -> None:
        """Reset-stack charts should apply range presets on grouped bars, not raw rows."""

        snapshot = {
            "indicator_map": {
                "CN_FIXED_INVESTMENT": {
                    "code": "CN_FIXED_INVESTMENT",
                    "name": "固定资产投资累计值",
                    "description": "月度累计值口径",
                    "latest_value": 52721.0,
                    "unit": "亿元",
                    "series_semantics": "cumulative_level",
                    "paired_indicator_code": "CN_FAI_YOY",
                    "chart_policy": "yearly_reset_bar",
                    "chart_reset_frequency": "year",
                    "chart_segment_basis": "period_delta",
                    "display_priority": 24,
                    "period_type": "M",
                    "refresh_start": "2020-01-01",
                    "has_data": True,
                    "sync_supported": True,
                    "latest_period": "2026-03",
                }
            },
            "selected_indicator": "CN_FIXED_INVESTMENT",
            "history": [
                {
                    "reporting_period": "2025-02-01",
                    "reporting_period_label": "2025-02",
                    "value": 52619.0,
                    "storage_value": 52619.0,
                    "storage_unit": "亿元",
                    "display_value": 52619.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2025-03-15",
                },
                {
                    "reporting_period": "2025-03-01",
                    "reporting_period_label": "2025-03",
                    "value": 103174.0,
                    "storage_value": 103174.0,
                    "storage_unit": "亿元",
                    "display_value": 103174.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2025-04-15",
                },
                {
                    "reporting_period": "2026-02-01",
                    "reporting_period_label": "2026-02",
                    "value": 52721.0,
                    "storage_value": 52721.0,
                    "storage_unit": "亿元",
                    "display_value": 52721.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2026-03-15",
                },
                {
                    "reporting_period": "2026-03-01",
                    "reporting_period_label": "2026-03",
                    "value": 102708.0,
                    "storage_value": 102708.0,
                    "storage_unit": "亿元",
                    "display_value": 102708.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2026-04-15",
                },
            ],
            "stats": {
                "total_indicators": 1,
                "synced_indicators": 1,
                "sync_supported_indicators": 1,
                "sync_unsupported_indicators": 0,
                "total_records": 4,
                "latest_date": "2026-03-01",
            },
            "min_date": "2025-02-01",
            "max_date": "2026-03-01",
            "refresh_provider_id": 1,
            "refresh_end_date": "2026-05-04",
            "sync_supported_indicator_count": 1,
            "sync_unsupported_indicator_count": 0,
            "bulk_refresh_indicator_codes": ["CN_FIXED_INVESTMENT"],
        }

        request = self.factory.get("/macro/data/?indicator=CN_FIXED_INVESTMENT")
        request.user = Mock(is_authenticated=True)

        with patch(
            "apps.macro.interface.views.page_views.get_macro_data_page_snapshot",
            return_value=snapshot,
        ):
            response = macro_data_view(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("function getCurrentChartContext(payload = currentIndicatorPayload)", content)
        self.assertIn("const visiblePointCount = getVisiblePointCount();", content)
        self.assertIn("个周期 / 覆盖", content)
        self.assertIn("chartContext ? chartContext.chartConfig.xAxisData.length : initialPayload.data.length", content)
        self.assertIn("chartContext ? chartContext.chartConfig.xAxisData.length : currentIndicatorPayload.data.length", content)

    def test_macro_data_view_labels_first_monthly_cumulative_segment_as_ytd_span(self) -> None:
        """Monthly cumulative reset-stack charts should explain the first YTD segment."""

        snapshot = {
            "indicator_map": {
                "CN_FIXED_INVESTMENT": {
                    "code": "CN_FIXED_INVESTMENT",
                    "name": "固定资产投资累计值",
                    "description": "月度累计值口径",
                    "latest_value": 52721.0,
                    "unit": "亿元",
                    "series_semantics": "cumulative_level",
                    "paired_indicator_code": "CN_FAI_YOY",
                    "chart_policy": "yearly_reset_bar",
                    "chart_reset_frequency": "year",
                    "chart_segment_basis": "period_delta",
                    "display_priority": 24,
                    "period_type": "M",
                    "refresh_start": "2020-01-01",
                    "has_data": True,
                    "sync_supported": True,
                    "latest_period": "2026-02",
                }
            },
            "selected_indicator": "CN_FIXED_INVESTMENT",
            "history": [
                {
                    "reporting_period": "2025-02-01",
                    "reporting_period_label": "2025-02",
                    "value": 52619.0,
                    "storage_value": 52619.0,
                    "storage_unit": "亿元",
                    "display_value": 52619.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2025-03-15",
                },
                {
                    "reporting_period": "2025-03-01",
                    "reporting_period_label": "2025-03",
                    "value": 103174.0,
                    "storage_value": 103174.0,
                    "storage_unit": "亿元",
                    "display_value": 103174.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2025-04-15",
                },
                {
                    "reporting_period": "2026-02-01",
                    "reporting_period_label": "2026-02",
                    "value": 52721.0,
                    "storage_value": 52721.0,
                    "storage_unit": "亿元",
                    "display_value": 52721.0,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "M",
                    "source": "akshare",
                    "published_at": "2026-03-15",
                },
            ],
            "stats": {
                "total_indicators": 1,
                "synced_indicators": 1,
                "sync_supported_indicators": 1,
                "sync_unsupported_indicators": 0,
                "total_records": 3,
                "latest_date": "2026-02-01",
            },
            "min_date": "2025-02-01",
            "max_date": "2026-02-01",
            "refresh_provider_id": 1,
            "refresh_end_date": "2026-05-04",
            "sync_supported_indicator_count": 1,
            "sync_unsupported_indicator_count": 0,
            "bulk_refresh_indicator_codes": ["CN_FIXED_INVESTMENT"],
        }

        request = self.factory.get("/macro/data/?indicator=CN_FIXED_INVESTMENT")
        request.user = Mock(is_authenticated=True)

        with patch(
            "apps.macro.interface.views.page_views.get_macro_data_page_snapshot",
            return_value=snapshot,
        ):
            response = macro_data_view(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("return `1-${minimumObservedMonth}月累计`;", content)
        self.assertIn("如果官方口径不单独发布 1 月值", content)

    def test_macro_data_view_auto_refreshes_stale_sync_supported_indicator_once(self) -> None:
        """Stale sync-supported indicators should expose one-shot auto-refresh logic."""

        snapshot = {
            "indicator_map": {
                "CN_GDP": {
                    "code": "CN_GDP",
                    "name": "GDP 国内生产总值累计值",
                    "description": "季度累计值口径",
                    "latest_value": 318466.4,
                    "unit": "亿元",
                    "series_semantics": "cumulative_level",
                    "paired_indicator_code": "CN_GDP_YOY",
                    "chart_policy": "yearly_reset_bar",
                    "chart_reset_frequency": "year",
                    "chart_segment_basis": "period_delta",
                    "display_priority": 20,
                    "period_type": "Q",
                    "refresh_start": "2020-01-01",
                    "has_data": True,
                    "sync_supported": True,
                    "latest_period": "2026-Q1",
                }
            },
            "selected_indicator": "CN_GDP",
            "history": [
                {
                    "reporting_period": "2026-03-31",
                    "reporting_period_label": "2026-Q1",
                    "value": 318466.4,
                    "storage_value": 318466.4,
                    "storage_unit": "亿元",
                    "display_value": 318466.4,
                    "display_unit": "亿元",
                    "original_unit": "亿元",
                    "period_type": "Q",
                    "source": "akshare",
                    "published_at": "2026-03-21",
                    "freshness_status": "stale",
                    "decision_grade": "degraded",
                    "age_days": 140,
                }
            ],
            "stats": {
                "total_indicators": 1,
                "synced_indicators": 1,
                "sync_supported_indicators": 1,
                "sync_unsupported_indicators": 0,
                "total_records": 1,
                "latest_date": "2026-03-31",
            },
            "min_date": "2026-03-31",
            "max_date": "2026-03-31",
            "refresh_provider_id": 1,
            "refresh_end_date": "2026-05-04",
            "sync_supported_indicator_count": 1,
            "sync_unsupported_indicator_count": 0,
            "bulk_refresh_indicator_codes": ["CN_GDP"],
        }

        request = self.factory.get("/macro/data/?indicator=CN_GDP")
        request.user = Mock(is_authenticated=True)

        with patch(
            "apps.macro.interface.views.page_views.get_macro_data_page_snapshot",
            return_value=snapshot,
        ):
            response = macro_data_view(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("const autoRefreshAttemptedIndicators = new Set();", content)
        self.assertIn("function shouldAutoRefreshIndicator(code, payload)", content)
        self.assertIn("async function maybeAutoRefreshIndicator(code, payload)", content)
        self.assertIn("检测到当前指标数据已过期，正在自动刷新...", content)
        self.assertIn("skipAutoRefresh = false", content)
        self.assertIn("void maybeAutoRefreshIndicator(initialIndicator, initialPayload);", content)
