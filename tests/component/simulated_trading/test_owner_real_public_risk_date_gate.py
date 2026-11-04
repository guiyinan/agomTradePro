"""Unmarked retained-candidate date gate, separate from Native DB E2E fixtures."""

from __future__ import annotations

import json
from datetime import date

import pytest
from django.utils import timezone

from tests.component.simulated_trading import test_owner_real_public_risk_sources as owner_case


def test_retained_november_03_candidate_hits_harness_date_gate_only() -> None:
    """Check only that historical retained facts cannot pass the current-date harness."""

    candidate_path = owner_case._RETAINED_2026_11_03_CANDIDATE
    if not candidate_path.is_file():
        pytest.skip(
            "the November 03 raw source facts are ignored external evidence and are absent in CI"
        )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8-sig"))
    source_date = date.fromisoformat(candidate["business_date"])
    current_date = timezone.now().astimezone(owner_case._SHANGHAI).date()
    if source_date >= current_date:
        pytest.skip("the retained source date has not yet become historical")
    with pytest.raises(AssertionError, match="historical evidence must remain expired/unknown"):
        owner_case._load_candidate(candidate_path)
