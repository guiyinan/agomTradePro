"""Current simulated tax qualification and full synthetic paid-cash journey tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.db import connection

from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_context import (
    _build_current_tax_qualification_context,
    run_blocked_payment_tax_collection_journey,
    run_paid_cash_tax_collection_journey,
)
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Current tax qualification requires migrated PostgreSQL state.",
    ),
]


def test_current_tax_qualification_rebuilds_real_persisted_owner_facts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    preserve_account_authority_generation: None,
) -> None:
    """Keep the original assessment-only default grant and future synthetic payout."""
    _build_current_tax_qualification_context(
        monkeypatch,
        tmp_path,
        preserve_account_authority_generation,
    )


def test_real_paid_cash_stage_keeps_exact_current_audit_and_withholding_grants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    preserve_account_authority_generation: None,
) -> None:
    """Prove audited synthetic cash payment precedes current tax collection."""
    with isolated_task_channels():
        run_paid_cash_tax_collection_journey(
            monkeypatch,
            tmp_path,
            preserve_account_tax_authority_generation=preserve_account_authority_generation,
        )


@pytest.mark.parametrize("payment_state", ("missing", "unreached"))
def test_tax_collection_requires_reached_audited_cash_payment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    preserve_account_authority_generation: None,
    payment_state: str,
) -> None:
    """Missing and future payment records cannot create a tax debit or journal."""
    with isolated_task_channels():
        run_blocked_payment_tax_collection_journey(
            monkeypatch,
            tmp_path,
            preserve_account_tax_authority_generation=preserve_account_authority_generation,
            payment_state=payment_state,
        )
