from pathlib import Path

import pytest

import apps.account.infrastructure.models as account_models
from apps.account.infrastructure.models import MacroSizingConfigModel
from apps.account.infrastructure.repositories import MacroSizingConfigRepository


def test_account_api_urls_import_sizing_context_view():
    from apps.account.interface import api_urls

    names = [pattern.name for pattern in api_urls.urlpatterns if getattr(pattern, "name", None)]

    assert "sizing-context" in names


@pytest.mark.django_db
def test_macro_sizing_config_repository_returns_active_config():
    MacroSizingConfigModel.objects.create(
        regime_tiers_json=[{"min_confidence": 0.0, "factor": 0.7}],
        pulse_tiers_json=[{"min_composite": -1.0, "max_composite": 1.0, "factor": 0.8}],
        warning_factor=0.4,
        drawdown_tiers_json=[{"min_drawdown": 0.1, "factor": 0.2}],
        version=3,
        is_active=True,
        description="test",
    )

    config = MacroSizingConfigRepository().get_active_config()

    assert config.version == 3
    assert config.get_regime_factor(0.1) == 0.7
    assert config.get_pulse_factor(0.0, warning=False) == 0.8
    assert config.get_pulse_factor(0.0, warning=True) == 0.4


def test_macro_sizing_admin_marks_json_fields_readonly():
    if not hasattr(account_models, "UserProfile"):
        account_models.UserProfile = type("UserProfile", (), {})

    source = Path("apps/account/infrastructure/admin.py").read_text(encoding="utf-8")

    assert '"regime_tiers_json"' in source
    assert '"pulse_tiers_json"' in source
    assert '"drawdown_tiers_json"' in source
    assert "readonly_fields" in source
