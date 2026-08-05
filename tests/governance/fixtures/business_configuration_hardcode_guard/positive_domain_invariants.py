from enum import Enum


class ScenarioType(Enum):
    HISTORICAL_WINDOW = "historical_window"
    PARAMETRIC_SHOCK = "parametric_shock"


SCENARIO_SCHEMA = {
    "type": "object",
    "properties": {
        "probability": {"type": "number", "minimum": 0, "maximum": 1},
        "scenario_type": {"type": "string"},
    },
}


CURRENCY_UNIT_MULTIPLIERS = {
    "万元": 10_000,
    "亿元": 100_000_000,
    "万亿元": 1_000_000_000_000,
}


def validate_probability_total(total):
    if not 0.99 <= total <= 1.01:
        raise ValueError("probability total must equal one")
