"""Actual current Config Center policy provenance; synthetic model, no tax authority."""

from datetime import date, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.application.runtime_value_evidence import read_active_runtime_value_evidence
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    SIMULATED_DIVIDEND_TAX_POLICY_KEY,
    SimulatedDividendTaxPolicyUnavailable,
    read_current_simulated_dividend_tax_policy,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.unit.simulated_trading.test_corporate_action_tax_policy_composition import _policy_row

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Actual migrated current policy contract; required PostgreSQL workflow.",
    ),
]


def test_native_tax_policy_exact_current_profile_scope_and_disable(owner_world, settings):
    settings.ROOT_URLCONF = "tests.support.ash07_owner_source_test_urls"
    world = owner_world
    before = CorporateActionTaxAssessmentHeaderModel.objects.count()
    query = {
        "environment": "development",
        "account_kind": "simulated",
        "physical_account_id": world.row.pk,
        "canonical_account_id": world.source.account_id,
        "owner_user_id": world.user.pk,
        "security_id": "SH.SYNTHETIC",
        "asset_code": "equity-cn",
        "exchange": SimulatedDividendTaxExchange.SH,
        "persona": SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
        "instrument_kind": SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
        "record_date": date(2025, 6, 1),
    }
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        read_current_simulated_dividend_tax_policy(as_of=timezone.now(), **query)
    now = timezone.now()
    row = _policy_row(
        physical_account_id=world.row.pk,
        canonical_account_id=world.source.account_id,
        owner_user_id=world.user.pk,
        valid_from=(now - timedelta(minutes=1)).isoformat(),
        valid_until=(now + timedelta(hours=1)).isoformat(),
    )
    value = {
        "schema_version": "simulated-dividend-tax-policies.v1",
        "enabled": True,
        "policies": [row],
    }
    activate_runtime_profile_patch(
        environment="development",
        patch={SIMULATED_DIVIDEND_TAX_POLICY_KEY: value},
        actor="native-synthetic-tax-policy",
        reason="explicit model read test, no legal or financial activation",
    )
    read_at = timezone.now()
    selected = read_current_simulated_dividend_tax_policy(as_of=read_at, **query)
    evidence = read_active_runtime_value_evidence(
        environment="development",
        definition_key=SIMULATED_DIVIDEND_TAX_POLICY_KEY,
        as_of=read_at,
    )
    assert evidence is not None
    assert selected.known_at == selected.candidate.known_at == evidence.created_at
    assert selected.effective_at == selected.activated_at == evidence.activated_at
    assert selected.profile_content_hash == evidence.profile_content_hash
    assert selected.snapshot_hash == evidence.snapshot_hash
    reread = read_current_simulated_dividend_tax_policy(as_of=timezone.now(), **query)
    assert reread.candidate.semantic_sha256 == selected.candidate.semantic_sha256
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        read_current_simulated_dividend_tax_policy(
            as_of=timezone.now(), **{**query, "account_kind": "real"}
        )
    activate_runtime_profile_patch(
        environment="development",
        patch={SIMULATED_DIVIDEND_TAX_POLICY_KEY: {**value, "enabled": False}},
        actor="native-synthetic-tax-policy",
        reason="disabled current policy must not reuse an old profile",
    )
    with pytest.raises(SimulatedDividendTaxPolicyUnavailable):
        read_current_simulated_dividend_tax_policy(as_of=timezone.now(), **query)
    assert CorporateActionTaxAssessmentHeaderModel.objects.count() == before
    world.row.refresh_from_db()
    assert world.row.current_cash == world.row.total_value == 10000
