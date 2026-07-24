"""Serialization contracts for dashboard domain and API payloads."""

from datetime import UTC, datetime

import pytest
from rest_framework import serializers

from apps.dashboard.interface.serializers import (
    DashboardAlertModelSerializer,
    DashboardCardModelSerializer,
    DashboardConfigModelSerializer,
    DashboardResponseSerializer,
    DashboardUserConfigModelSerializer,
    MetricCardSerializer,
    RefreshDashboardRequestSerializer,
    ToggleCardCollapseRequestSerializer,
    ToggleCardVisibilityRequestSerializer,
    UpdatePreferencesRequestSerializer,
)


def test_dashboard_response_serializes_nested_empty_and_populated_state() -> None:
    timestamp = datetime(2026, 7, 25, tzinfo=UTC)
    payload = {
        "layout": {
            "layout_id": "primary",
            "name": "Primary",
            "cards": [
                {
                    "card_id": "macro",
                    "card_type": "metrics",
                    "widgets": [
                        {
                            "widget_id": "pmi",
                            "widget_type": "metric",
                            "config": {},
                            "metadata": {"source": "data-center"},
                        }
                    ],
                }
            ],
        },
        "preferences": {
            "user_id": 7,
            "layout_id": "primary",
            "hidden_cards": [],
            "theme": "dark",
        },
        "alerts": [
            {
                "alert_id": "stale",
                "name": "Stale data",
                "severity": "warning",
                "notification_channels": ["terminal"],
            }
        ],
        "metrics": [
            {
                "metric_name": "pmi",
                "value": None,
                "formatted_value": "N/A",
                "timestamp": timestamp,
            }
        ],
        "timestamp": timestamp,
    }

    serializer = DashboardResponseSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["layout"]["cards"][0]["widgets"][0]["widget_id"] == "pmi"
    assert serializer.validated_data["metrics"][0]["value"] is None
    assert serializer.data["timestamp"] == "2026-07-25T08:00:00+08:00"


def test_metric_card_validates_required_fields_and_read_only_output() -> None:
    missing_title = MetricCardSerializer(data={"value": 1.0})
    assert missing_title.is_valid() is False
    assert missing_title.errors["title"][0].code == "required"

    serializer = MetricCardSerializer(
        data={
            "title": "Growth",
            "value": 5.2,
            "formatted_value": "must-not-be-accepted",
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert "formatted_value" not in serializer.validated_data


@pytest.mark.parametrize(
    ("serializer_class", "payload", "expected"),
    [
        (
            UpdatePreferencesRequestSerializer,
            {
                "hidden_cards": ["risk"],
                "collapsed_cards": [],
                "card_order": ["macro", "risk"],
                "theme": "dark",
                "refresh_enabled": False,
                "refresh_interval": 120,
            },
            {"hidden_cards": ["risk"], "refresh_enabled": False},
        ),
        (
            ToggleCardVisibilityRequestSerializer,
            {"card_id": "macro", "is_visible": False},
            {"card_id": "macro", "is_visible": False},
        ),
        (
            ToggleCardCollapseRequestSerializer,
            {"card_id": "macro", "is_collapsed": True},
            {"card_id": "macro", "is_collapsed": True},
        ),
        (
            RefreshDashboardRequestSerializer,
            {"force_refresh": True, "include_widgets": ["pmi"]},
            {"force_refresh": True, "include_widgets": ["pmi"]},
        ),
    ],
)
def test_dashboard_request_serializers_preserve_validated_contract(
    serializer_class: type[serializers.Serializer],
    payload: dict[str, object],
    expected: dict[str, object],
) -> None:
    serializer = serializer_class(data=payload)

    assert serializer.is_valid(), serializer.errors
    for key, value in expected.items():
        assert serializer.validated_data[key] == value


@pytest.mark.parametrize(
    ("serializer_class", "required_field"),
    [
        (ToggleCardVisibilityRequestSerializer, "card_id"),
        (ToggleCardCollapseRequestSerializer, "is_collapsed"),
    ],
)
def test_dashboard_request_serializers_reject_incomplete_mutations(
    serializer_class: type[serializers.Serializer],
    required_field: str,
) -> None:
    serializer = serializer_class(data={})

    assert serializer.is_valid() is False
    assert serializer.errors[required_field][0].code == "required"


def test_model_serializer_contracts_expose_only_declared_fields() -> None:
    config = DashboardConfigModelSerializer()
    user_config = DashboardUserConfigModelSerializer()
    card = DashboardCardModelSerializer()
    alert = DashboardAlertModelSerializer()

    assert set(config.fields) == set(config.Meta.fields)
    assert config.fields["created_at"].read_only is True
    assert user_config.fields["username"].read_only is True
    assert user_config.fields["dashboard_config_name"].allow_null is True
    assert card.fields["updated_at"].read_only is True
    assert alert.fields["severity_display"].read_only is True
    assert alert.fields["trigger_count"].read_only is True
