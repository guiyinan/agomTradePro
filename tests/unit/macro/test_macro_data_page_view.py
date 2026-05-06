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
