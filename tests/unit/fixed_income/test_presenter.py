"""Internal presenter coverage without registering a user-facing route."""

from datetime import UTC, datetime

from apps.fixed_income.domain.entities import (
    FixedIncomeResearchPreview,
    ResearchPreviewStatus,
)
from apps.fixed_income.interface.presenters import present_fixed_income_research_preview


def test_blocked_preview_preserves_non_execution_flags() -> None:
    preview = FixedIncomeResearchPreview(
        status=ResearchPreviewStatus.BLOCKED,
        method_version="fixed-income-research-v1",
        bond_id=None,
        valuation_at=datetime(2024, 1, 1, tzinfo=UTC),
        analytics=None,
        relative_value=None,
        reconciliation=None,
        publication_ids=(),
        blocked_reasons=("bond_master_missing",),
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )

    payload = present_fixed_income_research_preview(preview)

    assert payload["status"] == "blocked"
    assert payload["blocked_reasons"] == ["bond_master_missing"]
    assert payload["must_not_execute"] is True
    assert payload["must_not_use_for_decision"] is True
