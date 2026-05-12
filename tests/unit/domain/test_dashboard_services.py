"""
Tests for Dashboard Domain Services

Covers DashboardLayoutService, DashboardMetricService,
DashboardChartService, DashboardAlertService, and convenience functions.
No Django/pandas/numpy dependencies.
"""

from datetime import UTC, datetime, timedelta

import pytest

from apps.dashboard.domain.entities import (
    AlertSeverity,
    ChartConfig,
    DashboardLayout,
    WidgetType,
)
from apps.dashboard.domain.services import (
    DashboardAlertService,
    DashboardChartService,
    DashboardLayoutService,
    DashboardMetricService,
    LayoutResolutionResult,
    MetricCalculationResult,
    calculate_dashboard_metric,
    resolve_dashboard_layout,
)
from tests.factories.domain_factories import (
    make_alert_config,
    make_dashboard_card,
    make_dashboard_layout,
    make_dashboard_preferences,
    make_dashboard_widget,
    make_metric_card,
)

# ============================================================
# DashboardLayoutService Tests
# ============================================================


class TestDashboardLayoutServiceResolveLayout:
    """Tests for DashboardLayoutService.resolve_layout."""

    def test_resolve_layout_basic(self) -> None:
        """All visible cards are returned when no preferences are given."""
        layout = make_dashboard_layout(
            cards=[
                make_dashboard_card(card_id="c1"),
                make_dashboard_card(card_id="c2"),
            ]
        )
        service = DashboardLayoutService()
        result = service.resolve_layout(layout)

        assert isinstance(result, LayoutResolutionResult)
        assert len(result.visible_cards) == 2
        assert result.hidden_count == 0
        assert result.total_cards == 2

    def test_resolve_layout_empty_cards(self) -> None:
        """An empty layout yields zero visible cards."""
        layout = DashboardLayout(layout_id="empty", name="Empty", cards=[])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout)

        assert result.visible_cards == []
        assert result.visible_widgets == []
        assert result.hidden_count == 0
        assert result.total_cards == 0

    def test_resolve_layout_hidden_by_preferences(self) -> None:
        """Cards listed in user_preferences.hidden_cards are excluded."""
        layout = make_dashboard_layout(
            cards=[
                make_dashboard_card(card_id="c1"),
                make_dashboard_card(card_id="c2"),
                make_dashboard_card(card_id="c3"),
            ]
        )
        prefs = make_dashboard_preferences(hidden_cards=["c2"])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout, user_preferences=prefs)

        visible_ids = [c.card_id for c in result.visible_cards]
        assert "c2" not in visible_ids
        assert result.hidden_count == 1

    def test_resolve_layout_card_not_visible_flag(self) -> None:
        """Cards with is_visible=False are excluded."""
        layout = make_dashboard_layout(
            cards=[
                make_dashboard_card(card_id="c1", is_visible=False),
                make_dashboard_card(card_id="c2"),
            ]
        )
        service = DashboardLayoutService()
        result = service.resolve_layout(layout)

        assert len(result.visible_cards) == 1
        assert result.visible_cards[0].card_id == "c2"
        assert result.hidden_count == 1

    def test_resolve_layout_card_order_from_preferences(self) -> None:
        """User-specified card_order reorders the visible cards."""
        layout = make_dashboard_layout(
            cards=[
                make_dashboard_card(card_id="c1"),
                make_dashboard_card(card_id="c2"),
                make_dashboard_card(card_id="c3"),
            ]
        )
        prefs = make_dashboard_preferences(card_order=["c3", "c1", "c2"])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout, user_preferences=prefs)

        ids = [c.card_id for c in result.visible_cards]
        assert ids == ["c3", "c1", "c2"]

    def test_resolve_layout_collapsed_card_hides_widgets(self) -> None:
        """Widgets inside collapsed cards are not included in visible_widgets."""
        w1 = make_dashboard_widget(widget_id="w1")
        w2 = make_dashboard_widget(widget_id="w2")
        layout = make_dashboard_layout(
            cards=[
                make_dashboard_card(card_id="c1", widgets=[w1]),
                make_dashboard_card(card_id="c2", widgets=[w2]),
            ]
        )
        prefs = make_dashboard_preferences(collapsed_cards=["c1"])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout, user_preferences=prefs)

        widget_ids = [w.widget_id for w in result.visible_widgets]
        assert "w1" not in widget_ids
        assert "w2" in widget_ids

    def test_resolve_layout_card_collapsed_by_default(self) -> None:
        """A card with is_collapsed=True has its widgets excluded."""
        w1 = make_dashboard_widget(widget_id="w1")
        layout = make_dashboard_layout(
            cards=[make_dashboard_card(card_id="c1", widgets=[w1], is_collapsed=True)]
        )
        service = DashboardLayoutService()
        result = service.resolve_layout(layout)

        assert len(result.visible_cards) == 1
        assert result.visible_widgets == []

    def test_resolve_layout_visibility_conditions_pass(self) -> None:
        """Cards with visibility_conditions pass when context satisfies them."""
        card = make_dashboard_card(
            card_id="c1",
            metadata={"visibility_conditions": {"requires_alpha": True}},
        )
        layout = make_dashboard_layout(cards=[card])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout, context={"has_alpha": True})

        assert len(result.visible_cards) == 1

    def test_resolve_layout_visibility_conditions_fail(self) -> None:
        """Cards with unsatisfied visibility_conditions are hidden."""
        card = make_dashboard_card(
            card_id="c1",
            metadata={"visibility_conditions": {"requires_alpha": True}},
        )
        layout = make_dashboard_layout(cards=[card])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout, context={"has_alpha": False})

        assert len(result.visible_cards) == 0
        assert result.hidden_count == 1

    def test_resolve_layout_metadata_contains_layout_info(self) -> None:
        """The result metadata includes layout_id, columns, and row_height."""
        layout = make_dashboard_layout(layout_id="my-layout", columns=6)
        service = DashboardLayoutService()
        result = service.resolve_layout(layout)

        assert result.layout_metadata["layout_id"] == "my-layout"
        assert result.layout_metadata["columns"] == 6
        assert "resolved_at" in result.layout_metadata

    def test_resolve_layout_missing_preferences_is_none(self) -> None:
        """Passing None for user_preferences does not raise."""
        layout = make_dashboard_layout()
        service = DashboardLayoutService()
        result = service.resolve_layout(layout, user_preferences=None, context=None)

        assert isinstance(result, LayoutResolutionResult)

    def test_resolve_layout_invisible_widget_excluded(self) -> None:
        """Widgets with is_visible=False are not in visible_widgets."""
        w_visible = make_dashboard_widget(widget_id="wv", is_visible=True)
        w_hidden = make_dashboard_widget(widget_id="wh", is_visible=False)
        card = make_dashboard_card(card_id="c1", widgets=[w_visible, w_hidden])
        layout = make_dashboard_layout(cards=[card])
        service = DashboardLayoutService()
        result = service.resolve_layout(layout)

        widget_ids = [w.widget_id for w in result.visible_widgets]
        assert "wv" in widget_ids
        assert "wh" not in widget_ids


class TestDashboardLayoutServiceCalculateCardPosition:
    """Tests for DashboardLayoutService.calculate_card_position."""

    def test_returns_existing_position(self) -> None:
        """If the card already has a position, return it as-is."""
        card = make_dashboard_card(card_id="c1", position={"row": 2, "col": 3})
        layout = make_dashboard_layout()
        service = DashboardLayoutService()
        pos = service.calculate_card_position(card, layout, [])

        assert pos == {"row": 2, "col": 3}

    def test_finds_first_available_position(self) -> None:
        """With no occupied positions, card is placed at (0, 0)."""
        card = make_dashboard_card(card_id="c1", position=None, size={"width": 4, "height": 3})
        layout = make_dashboard_layout(columns=12)
        service = DashboardLayoutService()
        pos = service.calculate_card_position(card, layout, [])

        assert pos == {"row": 0, "col": 0}

    def test_avoids_occupied_position(self) -> None:
        """Card placement avoids an already occupied region."""
        card = make_dashboard_card(card_id="c1", position=None, size={"width": 4, "height": 3})
        layout = make_dashboard_layout(columns=12)
        occupied = [{"row": 0, "col": 0, "width": 4, "height": 3}]
        service = DashboardLayoutService()
        pos = service.calculate_card_position(card, layout, occupied)

        # Should not overlap with occupied area
        assert pos["col"] >= 4 or pos["row"] >= 3

    def test_default_size_when_card_has_no_size(self) -> None:
        """Uses default width=4, height=3 when card.size is None."""
        card = make_dashboard_card(card_id="c1", position=None, size=None)
        layout = make_dashboard_layout(columns=12)
        service = DashboardLayoutService()
        pos = service.calculate_card_position(card, layout, [])

        assert pos == {"row": 0, "col": 0}

    def test_wraps_to_next_row_when_columns_full(self) -> None:
        """When the entire row is occupied, card is placed on the next row."""
        card = make_dashboard_card(card_id="c1", position=None, size={"width": 4, "height": 1})
        layout = make_dashboard_layout(columns=12)
        occupied = [
            {"row": 0, "col": 0, "width": 4, "height": 1},
            {"row": 0, "col": 4, "width": 4, "height": 1},
            {"row": 0, "col": 8, "width": 4, "height": 1},
        ]
        service = DashboardLayoutService()
        pos = service.calculate_card_position(card, layout, occupied)

        assert pos["row"] >= 1
        assert pos["col"] == 0


# ============================================================
# DashboardMetricService Tests
# ============================================================


class TestDashboardMetricServiceCalculateMetric:
    """Tests for DashboardMetricService.calculate_metric."""

    def test_basic_metric_extraction(self) -> None:
        """Extracts a simple top-level metric from data."""
        service = DashboardMetricService()
        result = service.calculate_metric("total_assets", {"total_assets": 1500000.0})

        assert result.metric_name == "total_assets"
        assert result.value == 1500000.0
        assert result.formatted_value == "1.50M"

    def test_nested_metric_extraction(self) -> None:
        """Supports dot-notation for nested keys."""
        service = DashboardMetricService()
        data = {"portfolio": {"total_value": 250000.0}}
        result = service.calculate_metric("portfolio.total_value", data)

        assert result.value == 250000.0

    def test_missing_metric_returns_none_value(self) -> None:
        """Returns None when the metric key is missing."""
        service = DashboardMetricService()
        result = service.calculate_metric("nonexistent", {"foo": 1})

        assert result.value is None
        assert result.formatted_value == "None"

    def test_trend_up(self) -> None:
        """Trend is 'up' when current > previous."""
        service = DashboardMetricService()
        result = service.calculate_metric(
            "score", {"score": 80.0}, previous_data={"score": 70.0}
        )

        assert result.trend == "up"
        assert result.trend_value == pytest.approx(10.0)

    def test_trend_down(self) -> None:
        """Trend is 'down' when current < previous."""
        service = DashboardMetricService()
        result = service.calculate_metric(
            "score", {"score": 60.0}, previous_data={"score": 70.0}
        )

        assert result.trend == "down"
        assert result.trend_value == pytest.approx(-10.0)

    def test_trend_flat(self) -> None:
        """Trend is 'flat' when current == previous."""
        service = DashboardMetricService()
        result = service.calculate_metric(
            "score", {"score": 70.0}, previous_data={"score": 70.0}
        )

        assert result.trend == "flat"
        assert result.trend_value == pytest.approx(0.0)

    def test_no_trend_without_previous_data(self) -> None:
        """Trend fields are None when previous_data is not provided."""
        service = DashboardMetricService()
        result = service.calculate_metric("score", {"score": 80.0})

        assert result.trend is None
        assert result.trend_value is None

    def test_formatted_value_with_config(self) -> None:
        """Uses MetricCard.get_formatted_value when config is supplied."""
        config = make_metric_card(
            title="ROI", value=12.5, prefix="", suffix="%"
        )
        service = DashboardMetricService()
        result = service.calculate_metric("roi", {"roi": 12.5}, config=config)

        assert "12.5" in result.formatted_value
        assert result.formatted_value.endswith("%")

    def test_format_value_integer(self) -> None:
        """Integers are formatted with comma separators."""
        service = DashboardMetricService()
        result = service.calculate_metric("count", {"count": 42000})

        assert result.formatted_value == "42,000"

    def test_format_value_small_float(self) -> None:
        """Small floats get 2-decimal formatting."""
        service = DashboardMetricService()
        result = service.calculate_metric("rate", {"rate": 3.14})

        assert result.formatted_value == "3.14"

    def test_format_value_thousands(self) -> None:
        """Floats in the thousands range get K suffix."""
        service = DashboardMetricService()
        result = service.calculate_metric("v", {"v": 5500.0})

        assert result.formatted_value == "5.50K"

    def test_severity_from_config(self) -> None:
        """Alert severity is derived from MetricCard thresholds."""
        config = make_metric_card(
            title="CPU", value=95.0,
            threshold_warning=80.0, threshold_critical=90.0,
        )
        service = DashboardMetricService()
        result = service.calculate_metric("cpu", {"cpu": 95.0}, config=config)

        assert result.severity == AlertSeverity.CRITICAL

    def test_severity_none_when_no_config(self) -> None:
        """Severity is None when no config is provided."""
        service = DashboardMetricService()
        result = service.calculate_metric("cpu", {"cpu": 50.0})

        assert result.severity is None

    def test_none_config_uses_default_formatting(self) -> None:
        """When config is None, default formatting is used."""
        service = DashboardMetricService()
        result = service.calculate_metric("x", {"x": "hello"}, config=None)

        assert result.formatted_value == "hello"


class TestDashboardMetricServiceCalculateChangeRate:
    """Tests for DashboardMetricService.calculate_change_rate."""

    def test_positive_change(self) -> None:
        service = DashboardMetricService()
        rate = service.calculate_change_rate(120.0, 100.0)
        assert rate == pytest.approx(20.0)

    def test_negative_change(self) -> None:
        service = DashboardMetricService()
        rate = service.calculate_change_rate(80.0, 100.0)
        assert rate == pytest.approx(-20.0)

    def test_zero_previous_returns_zero(self) -> None:
        """Division by zero is handled gracefully."""
        service = DashboardMetricService()
        rate = service.calculate_change_rate(100.0, 0.0)
        assert rate == 0.0

    def test_no_change(self) -> None:
        service = DashboardMetricService()
        rate = service.calculate_change_rate(100.0, 100.0)
        assert rate == pytest.approx(0.0)


# ============================================================
# DashboardChartService Tests
# ============================================================


class TestDashboardChartServicePrepareChartData:
    """Tests for DashboardChartService.prepare_chart_data."""

    def test_line_chart_basic(self) -> None:
        """Line chart extracts x values and series data."""
        config = ChartConfig(
            chart_type=WidgetType.LINE_CHART,
            x_axis_label="date",
            y_axis_label="value",
            series=[{"name": "price", "y_key": "close"}],
        )
        raw_data = [
            {"date": "2025-01-01", "close": 100.0},
            {"date": "2025-01-02", "close": 102.0},
        ]
        service = DashboardChartService()
        result = service.prepare_chart_data(config, raw_data)

        assert result["x"] == ["2025-01-01", "2025-01-02"]
        assert result["series"]["price"] == [100.0, 102.0]
        assert result["config"]["title"] is None

    def test_line_chart_empty_data(self) -> None:
        """Line chart with no data returns empty lists."""
        config = ChartConfig(
            chart_type=WidgetType.LINE_CHART,
            series=[{"name": "s1", "y_key": "y"}],
        )
        service = DashboardChartService()
        result = service.prepare_chart_data(config, [])

        assert result["x"] == []
        assert result["series"] == {}

    def test_bar_chart_basic(self) -> None:
        """Bar chart extracts categories and values."""
        config = ChartConfig(
            chart_type=WidgetType.BAR_CHART,
            x_axis_label="sector",
            y_axis_label="weight",
        )
        raw_data = [
            {"sector": "Tech", "weight": 30},
            {"sector": "Finance", "weight": 25},
        ]
        service = DashboardChartService()
        result = service.prepare_chart_data(config, raw_data)

        assert result["categories"] == ["Tech", "Finance"]
        assert result["values"] == [30, 25]

    def test_pie_chart_basic(self) -> None:
        """Pie chart extracts labels and values."""
        config = ChartConfig(chart_type=WidgetType.PIE_CHART, title="Allocation")
        raw_data = [
            {"label": "Equity", "value": 60},
            {"label": "Bond", "value": 40},
        ]
        service = DashboardChartService()
        result = service.prepare_chart_data(config, raw_data)

        assert result["labels"] == ["Equity", "Bond"]
        assert result["values"] == [60, 40]
        assert result["config"]["title"] == "Allocation"

    def test_unknown_chart_type_returns_raw(self) -> None:
        """Unknown chart types return raw data wrapped in a dict."""
        config = ChartConfig(chart_type=WidgetType.HEATMAP)
        raw_data = [{"x": 1, "y": 2, "v": 10}]
        service = DashboardChartService()
        result = service.prepare_chart_data(config, raw_data)

        assert result == {"data": raw_data}

    def test_line_chart_multiple_series(self) -> None:
        """Line chart handles multiple series correctly."""
        config = ChartConfig(
            chart_type=WidgetType.LINE_CHART,
            x_axis_label="date",
            series=[
                {"name": "open", "y_key": "open"},
                {"name": "close", "y_key": "close"},
            ],
        )
        raw_data = [
            {"date": "2025-01-01", "open": 99.0, "close": 100.0},
            {"date": "2025-01-02", "open": 101.0, "close": 102.0},
        ]
        service = DashboardChartService()
        result = service.prepare_chart_data(config, raw_data)

        assert result["series"]["open"] == [99.0, 101.0]
        assert result["series"]["close"] == [100.0, 102.0]

    def test_pie_chart_empty_data(self) -> None:
        """Pie chart with empty data returns empty labels and values."""
        config = ChartConfig(chart_type=WidgetType.PIE_CHART)
        service = DashboardChartService()
        result = service.prepare_chart_data(config, [])

        assert result["labels"] == []
        assert result["values"] == []


# ============================================================
# DashboardAlertService Tests
# ============================================================


class TestDashboardAlertServiceEvaluateAlerts:
    """Tests for DashboardAlertService.evaluate_alerts."""

    def test_alert_triggered_above_threshold(self) -> None:
        """An alert fires when the metric value meets the threshold."""
        config = make_alert_config(
            alert_id="a1", name="High CPU", metric="cpu",
            threshold=90.0, severity=AlertSeverity.CRITICAL,
        )
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 95.0})

        assert len(alerts) == 1
        assert alerts[0]["alert_id"] == "a1"
        assert alerts[0]["severity"] == "critical"
        assert alerts[0]["value"] == 95.0

    def test_alert_not_triggered_below_threshold(self) -> None:
        """No alert fires when value is below threshold."""
        config = make_alert_config(
            alert_id="a1", metric="cpu", threshold=90.0,
        )
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 50.0})

        assert len(alerts) == 0

    def test_disabled_alert_skipped(self) -> None:
        """Disabled alerts are never evaluated."""
        config = make_alert_config(
            alert_id="a1", metric="cpu", threshold=90.0, is_enabled=False,
        )
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 99.0})

        assert len(alerts) == 0

    def test_cooldown_prevents_duplicate_alert(self) -> None:
        """An alert in cooldown does not fire again."""
        config = make_alert_config(
            alert_id="a1", metric="cpu", threshold=90.0, cooldown=300,
        )
        recent_time = datetime.now(UTC) - timedelta(seconds=60)
        cooldown_state: dict[str, datetime] = {"a1": recent_time}
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 99.0}, cooldown_state)

        assert len(alerts) == 0

    def test_cooldown_expired_allows_alert(self) -> None:
        """An alert fires when cooldown has expired."""
        config = make_alert_config(
            alert_id="a1", metric="cpu", threshold=90.0, cooldown=300,
        )
        old_time = datetime.now(UTC) - timedelta(seconds=600)
        cooldown_state: dict[str, datetime] = {"a1": old_time}
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 99.0}, cooldown_state)

        assert len(alerts) == 1

    def test_cooldown_state_updated_on_trigger(self) -> None:
        """The cooldown_state dict is updated when an alert fires.

        Note: the service uses ``cooldown_state = cooldown_state or {}``,
        so an empty dict is replaced by a new one. We must pass a *non-empty*
        dict (with an expired entry) to verify mutation, or pass a pre-populated
        dict.
        """
        config = make_alert_config(
            alert_id="a1", metric="cpu", threshold=90.0, cooldown=300,
        )
        # Pre-populate with an old, expired entry so the dict is truthy
        old_time = datetime.now(UTC) - timedelta(seconds=600)
        cooldown_state: dict[str, datetime] = {"a1": old_time}
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 99.0}, cooldown_state)

        # The alert should fire (cooldown expired)
        assert len(alerts) == 1
        # The cooldown_state should now contain a fresh timestamp
        assert "a1" in cooldown_state
        assert cooldown_state["a1"] > old_time

    def test_metric_not_in_data_skipped(self) -> None:
        """Alerts for metrics absent from current_data are skipped."""
        config = make_alert_config(alert_id="a1", metric="memory", threshold=80.0)
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 99.0})

        assert len(alerts) == 0

    def test_non_numeric_value_skipped(self) -> None:
        """Non-numeric metric values are gracefully skipped."""
        config = make_alert_config(alert_id="a1", metric="status", threshold=1.0)
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"status": "healthy"})

        assert len(alerts) == 0

    def test_multiple_alerts_evaluated(self) -> None:
        """Multiple alert configs are evaluated independently."""
        configs = [
            make_alert_config(alert_id="a1", metric="cpu", threshold=90.0),
            make_alert_config(alert_id="a2", metric="memory", threshold=80.0),
        ]
        data = {"cpu": 95.0, "memory": 85.0}
        service = DashboardAlertService()
        alerts = service.evaluate_alerts(configs, data)

        assert len(alerts) == 2

    def test_empty_alert_configs(self) -> None:
        """Empty alert config list returns no alerts."""
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([], {"cpu": 99.0})
        assert alerts == []

    def test_none_cooldown_state_defaults_to_empty(self) -> None:
        """Passing None for cooldown_state does not raise."""
        config = make_alert_config(alert_id="a1", metric="cpu", threshold=90.0)
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 95.0}, cooldown_state=None)

        assert len(alerts) == 1

    def test_alert_message_contains_details(self) -> None:
        """Triggered alert message includes metric name, value, and threshold."""
        config = make_alert_config(
            alert_id="a1", name="CPU Alert", metric="cpu", threshold=90.0,
        )
        service = DashboardAlertService()
        alerts = service.evaluate_alerts([config], {"cpu": 95.0})

        msg = alerts[0]["message"]
        assert "cpu" in msg
        assert "95.0" in msg
        assert "90.0" in msg


# ============================================================
# Convenience Function Tests
# ============================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_resolve_dashboard_layout(self) -> None:
        """resolve_dashboard_layout delegates to DashboardLayoutService."""
        layout = make_dashboard_layout(cards=[make_dashboard_card(card_id="c1")])
        result = resolve_dashboard_layout(layout)

        assert isinstance(result, LayoutResolutionResult)
        assert len(result.visible_cards) == 1

    def test_calculate_dashboard_metric(self) -> None:
        """calculate_dashboard_metric delegates to DashboardMetricService."""
        result = calculate_dashboard_metric("score", {"score": 42})

        assert isinstance(result, MetricCalculationResult)
        assert result.value == 42
