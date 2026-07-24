import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.factor.infrastructure.models import FactorDefinitionModel
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["demo.agomtrade.pro"])
def test_internal_action_executor_uses_allowed_host_for_paginated_api() -> None:
    """Paginated DRF responses build next links and must not use testserver."""

    FactorDefinitionModel._default_manager.bulk_create(
        [
            FactorDefinitionModel(
                code=f"test_factor_{index:02d}",
                name=f"Test Factor {index:02d}",
                category="value",
                description="pagination regression",
                data_source="test",
                data_field=f"field_{index:02d}",
                direction="positive",
                update_frequency="daily",
                is_active=True,
            )
            for index in range(25)
        ]
    )
    user = get_user_model().objects.create_user(
        username="tui_internal_executor_user",
        password="testpass123",
    )

    result = TuiInternalActionExecutor().execute(
        method="GET",
        endpoint="/api/factor/definitions/",
        params={},
        body={},
        user=user,
    )

    assert result["status_code"] == 200
    assert result["payload"]["count"] == 25
    assert result["payload"]["next"].startswith("http://demo.agomtrade.pro")
