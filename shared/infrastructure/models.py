"""Compatibility model resolver for legacy shared configuration imports."""

from __future__ import annotations

from django.apps import apps as django_apps

_MODEL_MAP = {
    "AssetConfigModel": ("asset_analysis", "AssetConfigModel"),
    "IndicatorConfigModel": ("macro", "IndicatorConfigModel"),
    "RegimeEligibilityConfigModel": ("regime", "RegimeEligibilityConfigModel"),
    "RiskParameterConfigModel": ("regime", "RiskParameterConfigModel"),
    "FilterParameterConfigModel": ("filter", "FilterParameterConfigModel"),
    "TransactionCostConfigModel": ("account", "TransactionCostConfigModel"),
    "HedgingInstrumentConfigModel": ("hedge", "HedgingInstrumentConfigModel"),
    "StockScreeningRuleConfigModel": ("equity", "StockScreeningRuleConfigModel"),
    "SectorPreferenceConfigModel": ("sector", "SectorPreferenceConfigModel"),
    "FundTypePreferenceConfigModel": ("fund", "FundTypePreferenceConfigModel"),
}

__all__ = list(_MODEL_MAP)


def __getattr__(name: str):
    """Resolve legacy shared configuration models from their owning apps."""

    try:
        app_label, model_name = _MODEL_MAP[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return django_apps.get_model(app_label, model_name)
