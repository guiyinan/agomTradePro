"""Shared fixtures for API contract and edge tests."""

from collections.abc import Iterator

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def active_decision_runtime(db: object) -> None:
    """Run API contracts under an explicitly admitted decision runtime."""

    from apps.config_center.infrastructure.decision_runtime_models import (
        DecisionRuntimeStateModel,
    )

    DecisionRuntimeStateModel._default_manager.update_or_create(
        pk=1,
        defaults={
            "status": "active",
            "reason": "",
            "changed_by": "pytest:api-contract",
        },
    )


@pytest.fixture
def api_client() -> APIClient:
    """Return an unauthenticated DRF client for permission contracts."""

    return APIClient()


@pytest.fixture
def auth_user(db: object) -> AbstractBaseUser:
    """Create the ordinary user shared by API edge tests."""

    return get_user_model().objects.create_user(
        username="api_edge_user",
        password="testpass123",
        email="api-edge@example.com",
    )


@pytest.fixture
def authenticated_client(
    api_client: APIClient,
    auth_user: AbstractBaseUser,
) -> Iterator[APIClient]:
    """Authenticate the shared API client and clear credentials afterwards."""

    api_client.force_authenticate(user=auth_user)
    yield api_client
    api_client.force_authenticate(user=None)
