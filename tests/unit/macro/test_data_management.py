from datetime import date

from apps.macro.application.data_management import ScheduleDataFetchUseCase


class _FakeScheduleRepository:
    def __init__(self, latest_by_code: dict[str, date | None]):
        self.latest_by_code = latest_by_code

    def get_latest_observation_date(self, indicator: str, check_date: date) -> date | None:
        return self.latest_by_code.get(indicator)


def test_schedule_data_fetch_use_case_prefers_runtime_catalog_schedule(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.data_management.get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_GDP_YOY": {
                "schedule_frequency": "quarterly",
                "schedule_day_of_month": 20,
                "schedule_release_months": [1, 4, 7, 10],
            }
        },
    )
    use_case = ScheduleDataFetchUseCase(repository=_FakeScheduleRepository({}))

    schedules = use_case.get_scheduled_indicators()

    assert schedules["CN_GDP_YOY"] == {
        "frequency": "quarterly",
        "day_of_month": 20,
        "release_months": [1, 4, 7, 10],
    }


def test_schedule_data_fetch_use_case_supports_quarterly_due_checks(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.data_management.get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_GDP_YOY": {
                "schedule_frequency": "quarterly",
                "schedule_day_of_month": 20,
                "schedule_release_months": [1, 4, 7, 10],
            }
        },
    )
    repository = _FakeScheduleRepository({"CN_GDP_YOY": date(2025, 12, 31)})
    use_case = ScheduleDataFetchUseCase(repository=repository)

    due_codes = use_case.get_due_indicators(as_of_date=date(2026, 4, 20))

    assert "CN_GDP_YOY" in due_codes


def test_schedule_data_fetch_use_case_no_longer_uses_local_default_tables(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.data_management.get_runtime_macro_index_metadata_map",
        lambda: {},
    )
    use_case = ScheduleDataFetchUseCase(repository=_FakeScheduleRepository({}))

    assert use_case.get_scheduled_indicators() == {}
