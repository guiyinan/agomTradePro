"""Regression tests for dashboard preference repository ownership."""

from typing import Any, cast

import pytest
from django.contrib.auth import get_user_model

from apps.dashboard.infrastructure.models import DashboardUserConfigModel
from apps.dashboard.infrastructure.repositories import (
    AlphaRecommendationHistoryRepository,
    DashboardPreferencesRepository,
)


@pytest.mark.django_db
def test_dashboard_preferences_repository_maps_persisted_preferences() -> None:
    """Persisted preferences must be mapped by their owning repository."""

    user = get_user_model()._default_manager.create_user(
        username="dashboard-preferences-user",
        password="test-password",
    )
    user_id = cast(int, user.pk)
    DashboardUserConfigModel._default_manager.create(
        user=user,
        hidden_cards=["risk-card"],
        collapsed_cards=["alpha-card"],
        card_order=["portfolio-card", "risk-card"],
        custom_card_config={"portfolio-card": {"size": "wide"}},
        theme="dark",
        refresh_interval=120,
    )

    preferences = DashboardPreferencesRepository().get_preferences(user_id)

    assert preferences is not None
    assert preferences.user_id == user_id
    assert preferences.hidden_cards == ["risk-card"]
    assert preferences.collapsed_cards == ["alpha-card"]
    assert preferences.card_order == ["portfolio-card", "risk-card"]
    assert preferences.theme == "dark"
    assert preferences.refresh_interval == 120


@pytest.mark.django_db
def test_dashboard_preference_mutations_are_not_owned_by_alpha_history() -> None:
    """Card preference mutations must remain on DashboardPreferencesRepository."""

    user = get_user_model()._default_manager.create_user(
        username="dashboard-card-preferences-user",
        password="test-password",
    )
    user_id = cast(int, user.pk)
    repository = DashboardPreferencesRepository()
    repository.get_or_create_preferences(user_id)

    assert repository.add_hidden_card(user_id, "risk-card") is True
    assert repository.add_collapsed_card(user_id, "alpha-card") is True
    assert (
        repository.update_card_order(
            user_id,
            ["alpha-card", "risk-card"],
        )
        is True
    )

    preferences = repository.get_preferences(user_id)
    assert preferences is not None
    assert preferences.hidden_cards == ["risk-card"]
    assert preferences.collapsed_cards == ["alpha-card"]
    assert preferences.card_order == ["alpha-card", "risk-card"]
    assert not hasattr(
        cast(Any, AlphaRecommendationHistoryRepository),
        "get_or_create_preferences",
    )
