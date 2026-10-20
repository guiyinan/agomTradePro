"""Django app-registry identity checks for the extracted simulated models."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import cast

from django.apps import apps
from django.db.models import Model

from apps.simulated_trading import models as public_models
from apps.simulated_trading.infrastructure import models as infrastructure_models

_EXPECTED_REGISTERED_MODEL_NAMES: tuple[str, ...] = (
    "AutomaticTradingInvocationModel",
    "SimulatedAccountRawObservationModel",
    "SimulatedAccountRowSourceModel",
    "SimulatedAccountRowSourceV2Model",
    "SimulatedAccountModel",
    "PositionModel",
    "SimulatedTradeModel",
    "SimulatedOrderReservationModel",
    "FeeConfigModel",
    "DailyInspectionReportModel",
    "DailyInspectionNotificationConfigModel",
    "DailyNetValueModel",
    "RebalanceProposalModel",
    "NotificationHistoryModel",
    "LedgerMigrationMapModel",
    "AccountBenchmarkComponentModel",
    "UnifiedAccountCashFlowModel",
    "AccountPositionValuationSnapshotModel",
)

_MOVED_MODELS: tuple[tuple[str, str], ...] = (
    ("SimulatedAccountModel", "simulated_account"),
    ("PositionModel", "simulated_position"),
    ("SimulatedTradeModel", "simulated_trade"),
)

_ADDITIONAL_MODELS: tuple[tuple[str, str, str], ...] = (
    (
        "AutomaticTradingInvocationModel",
        "simulated_auto_trading_invocation",
        "apps.simulated_trading.infrastructure.automatic_trading_invocation_models",
    ),
    (
        "SimulatedOrderReservationModel",
        "simulated_order_reservation",
        "apps.simulated_trading.infrastructure.order_reservation_models",
    ),
)


def test_simulated_models_keep_one_registered_identity() -> None:
    """Preserve ledger registration order and exact new-model identities."""

    registry_models: tuple[type[Model], ...] = tuple(
        apps.get_app_config("simulated_trading").get_models()
    )
    assert tuple(model.__name__ for model in registry_models) == _EXPECTED_REGISTERED_MODEL_NAMES

    extracted_models: ModuleType = import_module(
        "apps.simulated_trading.infrastructure.simulated_account_trade_models"
    )
    compatibility_modules: tuple[ModuleType, ...] = (
        public_models,
        infrastructure_models,
        extracted_models,
    )

    for model_name, expected_table in _MOVED_MODELS:
        registered_model = cast(type[Model], apps.get_model("simulated_trading", model_name))

        assert all(
            getattr(module, model_name) is registered_model for module in compatibility_modules
        )
        assert registered_model._meta.app_label == "simulated_trading"
        assert registered_model._meta.db_table == expected_table
        assert sum(model is registered_model for model in registry_models) == 1
        assert sum(model.__name__ == model_name for model in registry_models) == 1

    for model_name, expected_table, defining_module_path in _ADDITIONAL_MODELS:
        registered_model = cast(type[Model], apps.get_model("simulated_trading", model_name))
        defining_module = import_module(defining_module_path)
        compatibility_modules: tuple[ModuleType, ...] = (
            public_models,
            infrastructure_models,
            defining_module,
        )

        assert all(
            getattr(module, model_name) is registered_model for module in compatibility_modules
        )
        assert registered_model._meta.app_label == "simulated_trading"
        assert registered_model._meta.db_table == expected_table
        assert sum(model is registered_model for model in registry_models) == 1
        assert sum(model.__name__ == model_name for model in registry_models) == 1

    position_model = cast(type[Model], apps.get_model("simulated_trading", "PositionModel"))
    assert infrastructure_models.SimulatedPositionModel is position_model
    assert public_models.SimulatedPositionModel is position_model
