"""Transport projections preserve scenario version and evidence semantics."""

from datetime import UTC, date, datetime

from apps.risk_center.application.scenario_dtos import ScenarioSummaryDTO
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ScenarioDefinition,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
)
from apps.risk_center.interface.scenario_presenters import present_summary


def test_summary_presenter_keeps_versions_hash_and_source_observation() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    revision = ScenarioRevision(
        revision_id="revision-1",
        scenario_key="historical.crash",
        version=2,
        based_on_version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=HistoricalWindowParameters(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 1),
            source="published-price-bars",
            event_description="stress",
        ),
        assumptions=("published replay",),
        source_type=ScenarioSourceType.HUMAN,
        source_evidence=(
            {
                "publication_id": "publication-1",
                "observed_at": "2020-03-01T00:00:00+00:00",
            },
        ),
        created_by="operator",
        change_reason="review",
        created_at=now,
    )
    payload = present_summary(
        ScenarioSummaryDTO(
            definition=ScenarioDefinition(
                scenario_key="historical.crash",
                name="Crash",
                category="historical",
                owner="risk_center",
                created_at=now,
            ),
            revision=revision,
        )
    )

    assert payload["revision"]["version"] == 2
    assert len(payload["revision"]["content_hash"]) == 64
    assert payload["revision"]["source_evidence"][0]["observed_at"].startswith("2020-03-01")
