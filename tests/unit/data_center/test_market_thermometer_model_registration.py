"""Django app-registry identity checks for the extracted thermometer models."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import cast

from django.apps import apps
from django.db.models import Model

from apps.data_center import models as public_models
from apps.data_center.infrastructure import (
    fact_and_operational_models,
)
from apps.data_center.infrastructure import models as infrastructure_models

_MODEL_TABLES: tuple[tuple[str, str], ...] = (
    ("MarketThermometerConfigModel", "data_center_market_thermometer_config"),
    ("MarketThermometerUserOverrideModel", "data_center_market_thermometer_user_override"),
    ("MarketThermometerSnapshotModel", "data_center_market_thermometer_snapshot"),
)


def test_extracted_thermometer_models_keep_one_registered_identity() -> None:
    """All public compatibility paths and Django registration share each model class."""

    # This checks app metadata only; it intentionally does not request database access.
    extracted_models = import_module("apps.data_center.infrastructure.market_thermometer_models")
    compatibility_modules: tuple[ModuleType, ...] = (
        public_models,
        infrastructure_models,
        fact_and_operational_models,
        extracted_models,
    )
    registry_models = tuple(apps.get_app_config("data_center").get_models())

    for model_name, expected_table in _MODEL_TABLES:
        registered_model = cast(type[Model], apps.get_model("data_center", model_name))

        assert all(
            getattr(module, model_name) is registered_model for module in compatibility_modules
        )
        assert registered_model._meta.app_label == "data_center"
        assert registered_model._meta.db_table == expected_table
        assert sum(model is registered_model for model in registry_models) == 1
