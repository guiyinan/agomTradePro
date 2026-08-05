# ruff: noqa: F821

from datetime import date


class HistoricalScenarioService:
    SCENARIOS = {
        "legacy_crash": Scenario(
            scenario_id="legacy_crash",
            start_date=date(2015, 6, 12),
            end_date=date(2015, 8, 26),
        ),
        "legacy_pandemic": Scenario(
            scenario_id="legacy_pandemic",
            start_date=date(2020, 1, 14),
            end_date=date(2020, 3, 23),
        ),
        "legacy_trade_war": Scenario(
            scenario_id="legacy_trade_war",
            start_date=date(2018, 1, 2),
            end_date=date(2018, 12, 28),
        ),
    }
