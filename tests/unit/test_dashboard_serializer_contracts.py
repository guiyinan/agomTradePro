"""Boundary tests for Dashboard mutation serializers."""

import pytest

from apps.dashboard.interface.serializers import (
    RefreshDashboardRequestSerializer,
    StrictFieldsSerializer,
    ToggleCardCollapseRequestSerializer,
    ToggleCardVisibilityRequestSerializer,
    UpdatePreferencesRequestSerializer,
)


@pytest.mark.parametrize(
    ("serializer_class", "payload"),
    [
        (
            ToggleCardVisibilityRequestSerializer,
            {"card_id": "macro", "is_visible": True, "typo": False},
        ),
        (
            ToggleCardCollapseRequestSerializer,
            {"card_id": "macro", "is_collapsed": True, "typo": False},
        ),
        (
            RefreshDashboardRequestSerializer,
            {"force_refresh": True, "typo": False},
        ),
        (
            UpdatePreferencesRequestSerializer,
            {"theme": "dark", "typo": False},
        ),
    ],
)
def test_dashboard_mutations_reject_unknown_fields(
    serializer_class: type[StrictFieldsSerializer],
    payload: dict[str, object],
) -> None:
    """Misspelled mutation fields cannot be silently discarded."""

    serializer = serializer_class(data=payload)

    assert serializer.is_valid() is False
    assert "Unknown fields: typo" in str(serializer.errors)


@pytest.mark.parametrize(
    "payload",
    [
        {"hidden_cards": ["macro", "macro"]},
        {"collapsed_cards": ["pulse", "pulse"]},
        {"card_order": ["alpha", "alpha"]},
    ],
)
def test_dashboard_preferences_reject_duplicate_card_ids(
    payload: dict[str, object],
) -> None:
    """Duplicate card IDs cannot create ambiguous layout state."""

    serializer = UpdatePreferencesRequestSerializer(data=payload)

    assert serializer.is_valid() is False
    assert "Duplicate identifiers are not allowed." in str(serializer.errors)


def test_dashboard_refresh_rejects_duplicate_widget_ids() -> None:
    """A widget cannot be refreshed twice in one request."""

    serializer = RefreshDashboardRequestSerializer(data={"include_widgets": ["regime", "regime"]})

    assert serializer.is_valid() is False
    assert "Duplicate identifiers are not allowed." in str(serializer.errors)


@pytest.mark.parametrize("payload", [{}, {"refresh_interval": 0}])
def test_dashboard_preferences_reject_noop_or_nonpositive_interval(
    payload: dict[str, object],
) -> None:
    """No-op writes and nonpositive refresh periods fail at the API boundary."""

    serializer = UpdatePreferencesRequestSerializer(data=payload)

    assert serializer.is_valid() is False


def test_dashboard_preferences_accept_canonical_update() -> None:
    """A valid update preserves ordered, unique card identifiers."""

    serializer = UpdatePreferencesRequestSerializer(
        data={
            "hidden_cards": ["macro"],
            "card_order": ["macro", "alpha"],
            "refresh_interval": 60,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["card_order"] == ["macro", "alpha"]
