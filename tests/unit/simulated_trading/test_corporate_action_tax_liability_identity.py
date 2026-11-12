"""Operation identity is shared by new writes and original journal verification."""

from dataclasses import replace

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityCashAction,
    TaxLiabilityOperationIdentity,
    _scope_for_assessment,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from tests.unit.simulated_trading.test_corporate_action_tax_liability import _taxable_assessment


def _identity():
    assessment = _taxable_assessment()
    return TaxLiabilityOperationIdentity(
        operation_id="synthetic-operation-v1",
        scope=_scope_for_assessment(assessment),
        canonical_account_namespace="account",
        canonical_account_id="canonical-simulated-account-17",
        currency=SimulatedDividendTaxCurrency.CNY,
        assessment_revision_id=assessment.assessment_revision_id,
        supersedes_assessment_revision_id=assessment.supersedes_assessment_revision_id,
        assessment_semantic_sha256=assessment.semantic_sha256,
        stored_assessment_manifest_sha256=assessment.observation_manifest_sha256,
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )


def test_shared_identity_keeps_the_existing_application_wire_digest():
    assert (
        _identity().request_sha256
        == "0d63ab99d2fe79745aea86e2e4cd2f96d3f221f25ecb1cf31eba86014c64d377"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": "different-operation"},
        {"cash_action": None},
        {"canonical_account_id": "different-canonical-account"},
        {"stored_assessment_manifest_sha256": "a" * 64},
    ],
)
def test_identity_binds_original_intent_and_manifest(changes):
    assert replace(_identity(), **changes).request_sha256 != _identity().request_sha256


@pytest.mark.parametrize(
    "changes",
    [
        {"canonical_account_namespace": "simulated"},
        {"currency": "CNY"},
        {"cash_action": "collect_available"},
        {"operation_id": " "},
        {"stored_assessment_manifest_sha256": "not-a-digest"},
    ],
)
def test_identity_rejects_untyped_or_missing_scope(changes):
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_identity(), **changes)


def test_mutating_a_frozen_identity_cannot_reseal_it_as_the_original_operation():
    identity = _identity()
    object.__setattr__(identity, "operation_id", "tampered-operation")
    with pytest.raises(DeferredDividendTaxValidationError):
        identity.verify_integrity()
