"""Reference publication never acquires ordinary decision eligibility."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationState,
)

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def _reference() -> CanonicalPublication:
    return CanonicalPublication(
        publication_id="one",
        dataset_key="equity.price.limit",
        publication_key="price-limit:scope",
        policy_version="v1",
        state=PublicationState.REFERENCE_PUBLISHED,
        selected_source="provider",
        publication_hash="a" * 64,
        coverage=CoverageSnapshot(
            coverage_id="coverage",
            publication_id="one",
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=NOW,
        ),
        member_count=1,
        published_at=NOW,
        must_not_use_for_decision=True,
        blocked_reason="PRICE_LIMIT_REFERENCE_ONLY",
    )


def test_reference_publication_retains_decision_block() -> None:
    publication = _reference()
    assert publication.must_not_use_for_decision is True
    assert publication.state.value == "reference_published"


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_key": "equity.price.bar"},
        {"must_not_use_for_decision": False},
        {"selected_source": ""},
        {"published_at": None},
        {"member_count": 0},
        {"blocked_reason": ""},
    ],
)
def test_reference_publication_rejects_eligibility_or_missing_evidence(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_reference(), **changes)


def test_ordinary_published_invariant_is_unchanged() -> None:
    with pytest.raises(ValueError, match="cannot be blocked"):
        replace(_reference(), state=PublicationState.PUBLISHED)


def test_replaced_reference_keeps_a_separate_restricted_state() -> None:
    publication = replace(_reference(), state=PublicationState.REFERENCE_SUPERSEDED)
    assert publication.state.value == "reference_superseded"
    assert publication.state is not PublicationState.SUPERSEDED
    with pytest.raises(ValueError):
        replace(publication, must_not_use_for_decision=False)
