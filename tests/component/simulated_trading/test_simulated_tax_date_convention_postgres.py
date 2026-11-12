"""Actual optional Config Center activation/read/disable; never financial authority."""

from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.application.runtime_value_evidence import read_active_runtime_value_evidence
from apps.simulated_trading.corporate_action_tax_date_convention_composition import (
    SIMULATED_TAX_DATE_CONVENTION_KEY,
    SimulatedDividendTaxDateConventionUnavailable,
    read_current_simulated_dividend_tax_date_convention,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native Config Center and owner-source contract; required PostgreSQL workflow.",
    ),
]


def test_native_date_rule_uses_actual_profile_clocks_and_never_falls_back(owner_world, settings):
    """Explicit configuration supplies a hypothesis; disabling it never reuses the old profile."""
    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    before = CorporateActionPostingModel.objects.count()
    scope = {
        "environment": "development",
        "account_kind": "simulated",
        "physical_account_id": world.row.pk,
        "canonical_account_id": world.source.account_id,
        "owner_user_id": world.user.pk,
    }
    with pytest.raises(SimulatedDividendTaxDateConventionUnavailable):
        read_current_simulated_dividend_tax_date_convention(as_of=timezone.now(), **scope)
    now = timezone.now()
    item = {
        "convention_id": "native-simulation-date-hypothesis",
        "version": "1",
        "physical_account_id": world.row.pk,
        "canonical_account_id": world.source.account_id,
        "owner_user_id": world.user.pk,
        "exchange": "SZ",
        "purchase_open_session_offset": 1,
        "sale_open_session_offset": 1,
        "trade_window_start": "2026-01-01",
        "trade_window_end": "2026-12-31",
        "valid_from": (now - timedelta(minutes=1)).isoformat(),
        "valid_until": (now + timedelta(hours=1)).isoformat(),
        "approval_ref": "isolated-owner-approved-simulation-date-test",
    }
    value = {
        "schema_version": "simulated-dividend-tax-date-conventions.v1",
        "enabled": True,
        "policies": [item],
    }
    activate_runtime_profile_patch(
        environment="development",
        patch={SIMULATED_TAX_DATE_CONVENTION_KEY: value},
        actor="isolated-date-convention-test",
        reason="explicit hypothesis in a migrated test database; no custody or posting authority",
    )
    read_at = timezone.now()
    original = read_current_simulated_dividend_tax_date_convention(as_of=read_at, **scope)
    evidence = read_active_runtime_value_evidence(
        environment="development", definition_key=SIMULATED_TAX_DATE_CONVENTION_KEY, as_of=read_at
    )
    assert evidence is not None
    assert original.known_at == original.convention.known_at == evidence.created_at
    assert original.activated_at == original.effective_at == evidence.activated_at
    assert original.snapshot_generated_at == evidence.snapshot_generated_at
    assert original.snapshot_hash == evidence.snapshot_hash
    assert original.profile_content_hash == evidence.profile_content_hash
    assert original.as_of == read_at and original.account_kind == "simulated"
    assert original.convention.purchase_open_session_offset == 1
    assert original.convention.sale_open_session_offset == 1
    with pytest.raises(SimulatedDividendTaxDateConventionUnavailable):
        read_current_simulated_dividend_tax_date_convention(
            as_of=timezone.now(), **{**scope, "account_kind": "real"}
        )
    activate_runtime_profile_patch(
        environment="development",
        patch={SIMULATED_TAX_DATE_CONVENTION_KEY: {**value, "enabled": False}},
        actor="isolated-date-convention-test",
        reason="disabled current hypothesis must not fall back to the preceding active profile",
    )
    with pytest.raises(SimulatedDividendTaxDateConventionUnavailable):
        read_current_simulated_dividend_tax_date_convention(as_of=timezone.now(), **scope)
    assert CorporateActionPostingModel.objects.count() == before
    world.row.refresh_from_db()
    assert world.row.current_cash == world.row.total_value == 10000
