"""Unit coverage for the neutral Portfolio R4 owner record envelope."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)
from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchDraft,
    R4RollingResearchRecord,
)
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)


def _record() -> R4RollingResearchRecord:
    evaluated_at = datetime(2026, 3, 15, tzinfo=UTC)
    return R4RollingResearchRecord.from_server_clock(
        draft=R4RollingResearchDraft(
            study=build_study(),
            promotion_attestation=promotion_attestation(),
            evaluated_at=evaluated_at,
            producer_code_version="git:r4-code-v1",
            dependency_lock_hash="a" * 64,
            valid_until=datetime(2026, 3, 31, tzinfo=UTC),
        ),
        server_recorded_at=evaluated_at + timedelta(minutes=1),
    )


def test_owner_envelope_keys_are_opaque_stable_and_bound_to_exact_record() -> None:
    record = _record()

    envelope = R4RollingResearchOwnerRecord.create(record)

    assert envelope.owner == "portfolio"
    assert envelope.record == record
    assert envelope.owner_record_key.startswith("por4:")
    assert R4RollingResearchOwnerRecord.create(record) == envelope


def test_owner_envelope_rejects_key_or_owner_substitution() -> None:
    envelope = R4RollingResearchOwnerRecord.create(_record())

    with pytest.raises(ValueError, match="owner record key mismatch"):
        replace(envelope, owner_record_key="por4:" + "0" * 64)
    with pytest.raises(ValueError, match="Portfolio-owned"):
        replace(envelope, owner="research")
