"""Current simulation qualifier boundaries and stable entitlement derivation."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from apps.simulated_trading.corporate_action_tax_qualification_composition import (
    DjangoCurrentSimulatedTaxQualificationProvider,
    _record_entitlement,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment
from tests.unit.simulated_trading.test_simulated_dividend_tax_policy_scope import (
    _scope,
    _tax_policy,
)


def _entitlement_inputs():
    """Use explicit synthetic proof/action facts, without claiming source verification."""
    assessment = _assessment()
    scope = replace(
        _scope(policy=_tax_policy(effective_from=date(2024, 1, 1))),
        physical_account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        security_id=assessment.security_id,
        asset_code=assessment.asset_code,
        record_date_from=date(2024, 1, 1),
    )
    return scope, assessment.action, assessment.history.record_date_ownership_proof


def test_entitlement_identity_survives_new_proof_observation():
    scope, action, proof = _entitlement_inputs()
    first = _record_entitlement(scope=scope, action=action, proof=proof)
    refreshed = _record_entitlement(
        scope=scope,
        action=action,
        proof=replace(
            proof,
            ownership_snapshot_id="new-proof-observation",
            ownership_snapshot_sha256="e" * 64,
            ownership_snapshot_observed_at=proof.ownership_snapshot_observed_at
            + timedelta(seconds=1),
        ),
    )
    assert first == refreshed
    assert first.qualified_total_quantity == proof.eligible_quantity
    assert first.kind is scope.record_date_entitlement_rule


def test_new_capture_selection_does_not_change_unchanged_entitlement_semantics():
    scope, action, proof = _entitlement_inputs()
    first = _record_entitlement(scope=scope, action=action, proof=proof)
    refreshed = _record_entitlement(
        scope=replace(
            scope,
            candidate_version="new-current-observation",
            statutory_bundle_version="new-retained-capture-selection",
            known_at=scope.known_at + timedelta(seconds=1),
            valid_until=scope.valid_until + timedelta(minutes=1),
        ),
        action=action,
        proof=proof,
    )
    assert first == refreshed


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", 12345),
        ("owner_user_id", 12345),
        ("security_id", "different-security"),
        ("asset_code", "different-asset"),
        ("record_date", date(2024, 1, 1)),
    ],
)
def test_entitlement_rejects_cross_scope_proof(field, value):
    scope, action, proof = _entitlement_inputs()
    with pytest.raises(BusinessLogicError):
        _record_entitlement(scope=scope, action=action, proof=replace(proof, **{field: value}))


def test_real_qualifier_does_not_accept_nondefault_database_alias(tmp_path):
    with pytest.raises(BusinessLogicError):
        DjangoCurrentSimulatedTaxQualificationProvider(
            runtime_environment="development",
            calendar_dataset_key="explicit-calendar",
            statutory_provider_id=7,
            statutory_body_store_root=Path(tmp_path),
            action_body_store_root=Path(tmp_path),
            deployment_region="explicit-region",
            using="other-database",
        )


@pytest.mark.parametrize("fault", ["sqlite", "alias", "environment"])
def test_write_qualification_requires_exact_pg_uow_before_reading_source(tmp_path, fault):
    provider = DjangoCurrentSimulatedTaxQualificationProvider(
        runtime_environment="development",
        calendar_dataset_key="explicit-calendar",
        statutory_provider_id=7,
        statutory_body_store_root=Path(tmp_path),
        action_body_store_root=Path(tmp_path),
        deployment_region="explicit-region",
    )
    scope, _, _ = _entitlement_inputs()
    with pytest.raises(BusinessLogicError):
        provider.read_current(
            _assessment(),
            canonical_account_id=scope.canonical_account_id,
            environment="other" if fault == "environment" else "development",
            using="other" if fault == "alias" else "default",
            as_of=scope.known_at,
        )
