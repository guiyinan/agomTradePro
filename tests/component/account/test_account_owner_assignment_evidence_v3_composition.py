"""Component proof for the Account-only Evidence-v3 read composition."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.account.account_owner_assignment_evidence_v3_composition import (
    build_current_authoritative_account_mapping_v3,
)
from apps.account.application.account_owner_assignment_mapping_v3 import (
    GetCurrentAuthoritativeAccountMappingV3Command,
)


@pytest.mark.django_db(transaction=True)
def test_account_only_mapping_graph_returns_none_for_zero_seed_ledger() -> None:
    """A real empty 0046/0047/0049/0050 graph remains safely unavailable."""

    reader = build_current_authoritative_account_mapping_v3(using="default")

    assert (
        reader.execute(
            GetCurrentAuthoritativeAccountMappingV3Command(
                underlying_unified_account_namespace="simulated-account-row",
                underlying_unified_account_id=1,
                as_of=datetime.now(UTC),
            )
        )
        is None
    )
