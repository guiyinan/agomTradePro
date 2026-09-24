"""Configured source-volume conversion for Tencent's mixed-unit history feed."""

from __future__ import annotations

import json
import math
import re

from core.exceptions import ConfigurationError
from core.integration.runtime_settings import get_runtime_config_value
from shared.numeric import safe_float

TENCENT_HISTORY_VOLUME_KEY = "data_center.tencent.history_volume_multipliers"


def parse_history_volume_rules(raw: object) -> dict[str, float]:
    """Validate explicit prefix.exchange multipliers and a required wildcard rule."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if not isinstance(raw, dict) or "*" not in raw:
        raise ConfigurationError(
            "Tencent history volume units are not configured",
            code="MODEL_MARKET_UNIT_CONFIG_UNAVAILABLE",
        )
    result: dict[str, float] = {}
    for key, value in raw.items():
        multiplier = safe_float(value)
        if (
            not isinstance(key, str)
            or (key != "*" and re.fullmatch(r"\d{1,6}\.(?:SH|SZ|BJ)", key) is None)
            or isinstance(value, bool)
            or multiplier is None
            or not math.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ConfigurationError(
                "Invalid Tencent history volume rule", code="MODEL_MARKET_UNIT_CONFIG_INVALID"
            )
        result[key] = multiplier
    return result


def history_volume_multiplier(asset_code: str) -> float:
    """Use the most specific configured code prefix, without guessing a board's units."""
    rules = parse_history_volume_rules(get_runtime_config_value(TENCENT_HISTORY_VOLUME_KEY))
    code, exchange = asset_code.rsplit(".", 1)
    for key in sorted((key for key in rules if key != "*"), key=len, reverse=True):
        prefix, market = key.split(".", 1)
        if market == exchange and code.startswith(prefix):
            return rules[key]
    return rules["*"]
