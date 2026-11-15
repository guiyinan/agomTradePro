"""Ordinary-session JSON contracts for the source-bound institutional calendar."""

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.data_center.infrastructure.institutional_calendar_models import (
    InstitutionalCalendarEventModel,
)
from apps.data_center.infrastructure.models import RawPayloadModel
from apps.data_center.institutional_calendar_import import import_nbs_calendar_originals
from tests.support.institutional_calendar_world import retained_originals
from tests.support.runtime_config import configure_critical_runtime

pytestmark = pytest.mark.django_db
PATH = "/api/data-center/institutional-calendar/"


@pytest.fixture
def calendar_client() -> tuple[Client, dict[str, str]]:
    configure_critical_runtime()
    schedule, actual = retained_originals()
    import_nbs_calendar_originals(
        schedule=schedule,
        actual=actual,
        content_title="居民消费价格指数月度报告",
        event_id_prefix="nbs-cpi",
    )
    user = get_user_model().objects.create_user(
        username="calendar-ordinary",
        password="calendar-test-only",
        is_staff=False,
        is_superuser=False,
    )
    client = Client()
    client.force_login(user)
    return client, {
        "date_from": "2026-11-01",
        "date_to": "2026-12-31",
        "known_at": actual.recorded_at.isoformat(),
        "mode": "system_known",
    }


def test_ordinary_user_reads_sources_windows_and_actual_release_without_writes(
    calendar_client: tuple[Client, dict[str, str]],
) -> None:
    client, query = calendar_client
    before = (RawPayloadModel.objects.count(), InstitutionalCalendarEventModel.objects.count())
    response = client.get(PATH, query)
    assert response.status_code == 200
    assert response.headers["Content-Type"].split(";")[0] == "application/json"
    data = response.json()["data"]
    assert data["status"]["must_not_use_for_decision"] is True
    assert "研究未完成" in data["status"]["research_status"]
    assert len(data["windows"]) == 12
    assert {row["row_kind"] for row in data["rows"]} == {"来源与研究边界", "自然日窗口", "官方发布"}
    assert data["rows"][0]["row_kind"] == "来源与研究边界"
    actual = next(row for row in data["events"] if row["revision"] == 2)
    assert actual["evidence_label"] == "已确认"
    assert actual["lifecycle_label"] == "已实际发布"
    assert actual["source_url"].startswith("https://www.stats.gov.cn/")
    assert actual["source_observed_at"] is None
    assert (
        RawPayloadModel.objects.count(),
        InstitutionalCalendarEventModel.objects.count(),
    ) == before
    filtered = client.get(
        PATH, {**query, "lifecycle": "scheduled", "event_type": "nbs_cpi_release"}
    )
    assert filtered.status_code == 200
    assert all(row["lifecycle_label"] == "计划发布" for row in filtered.json()["data"]["events"])


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"mode": "guess"}, 400),
        ({"known_at": "2026-11-01T00:00:00"}, 400),
        ({"date_from": "2026-12-31", "date_to": "2026-11-01"}, 422),
        ({"date_to": "2028-01-01"}, 422),
        ({"db_alias": "production"}, 400),
    ],
)
def test_invalid_or_unsupported_queries_fail_closed(
    calendar_client: tuple[Client, dict[str, str]], change: dict[str, str], expected: int
) -> None:
    client, query = calendar_client
    response = client.get(PATH, {**query, **change})
    assert response.status_code == expected
    assert response.headers["Content-Type"].startswith("application/json")


def test_anonymous_mutation_repeated_keys_and_future_cutoff_are_rejected(
    calendar_client: tuple[Client, dict[str, str]],
) -> None:
    client, query = calendar_client
    assert Client().get(PATH, query).status_code == 403
    assert client.post(PATH, query).status_code == 405
    assert client.get(PATH + "?mode=system_known&mode=market_available").status_code == 400
    response = client.get(
        PATH, {**query, "known_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}
    )
    assert response.status_code == 422
