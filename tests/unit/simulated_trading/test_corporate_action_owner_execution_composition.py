"""Composition-only synthetic commands never stand in for native owner authority."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
)
from apps.simulated_trading import corporate_action_owner_execution_composition as execution
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityCashAction
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_owner_intent_codec import _intent
from tests.unit.simulated_trading.test_corporate_action_posting import _share_delivery_request
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _NOW
from tests.unit.simulated_trading.test_corporate_action_share_tax_proof import _proof, _request


def test_prepared_share_model_accepts_only_the_sealed_request_and_same_current_selection(
    monkeypatch,
):
    proof, request = _proof(), _request()
    monkeypatch.setattr(
        execution,
        "read_owner_corporate_action_workflow_runtime",
        lambda **kwargs: SimpleNamespace(
            statutory_provider_id=1,
            statutory_body_store_root=Path("synthetic"),
            deployment_region="test",
        ),
    )
    monkeypatch.setattr(
        execution, "read_current_owner_action_pdf_root", lambda **kwargs: Path("synthetic")
    )
    current = [proof]
    monkeypatch.setattr(
        execution,
        "DjangoCurrentShareCapitalTaxQualificationReader",
        lambda **kwargs: SimpleNamespace(read_current=lambda *a, **k: current[0]),
    )
    reader = execution.DeferredOwnerShareCapitalTaxQualification(
        environment="test",
        canonical_account_id=proof.query.canonical_account_id,
        prepared=proof,
        prepared_requests=(request,),
    )
    assert reader.read_current(request, as_of=_NOW) == proof
    with pytest.raises(BusinessLogicError):
        reader.read_current(replace(request, asset_name="unsealed change"), as_of=_NOW)
    current[0] = replace(proof, configuration_identity_sha256="e" * 64)
    with pytest.raises(BusinessLogicError):
        reader.read_current(request, as_of=_NOW)


def test_public_share_write_requires_independent_full_model_before_any_financial_factory(
    monkeypatch,
):
    base = _intent()
    request = replace(
        _share_delivery_request(),
        account_id=base.account_id,
        owner_user_id=base.owner_user_id,
        source_observed_at=base.source_reference.source_observed_at,
        qualified_at=base.source_reference.qualified_at,
        posted_at=base.source_reference.posted_at,
    )
    intent = replace(base, action="share_delivery", source_reference=request, requests=(request,))
    monkeypatch.setattr(
        execution,
        "DjangoSimulatedCorporateActionWriteScopeLocker",
        lambda **kwargs: pytest.fail("missing model proof reached financial composition"),
    )
    with pytest.raises(BusinessLogicError) as error:
        execution.execute_owner_corporate_action_intent(intent, environment="test")
    assert error.value.code == "SHARE_CAPITAL_TAX_PREVIEW_REQUIRED"


def test_public_posting_composition_always_supplies_actual_original_body_and_window_gate(
    monkeypatch,
):
    captured = {}
    gate = object()
    monkeypatch.setattr(
        execution, "DjangoSimulatedCorporateActionWriteScopeLocker", lambda **kwargs: object()
    )

    def owner_gate(**kwargs):
        captured["owner"] = kwargs
        return gate

    monkeypatch.setattr(execution, "DjangoCorporateActionOwnerGrantGate", owner_gate)

    def window_reader(**kwargs):
        captured["window"] = kwargs
        return object()

    monkeypatch.setattr(
        execution, "build_corporate_action_current_official_window_reader", window_reader
    )
    monkeypatch.setattr(
        execution, "build_corporate_action_ownership_history_repository", lambda **kwargs: object()
    )

    class Factory:
        def __init__(self, **kwargs):
            captured["factory"] = kwargs

        def build_posting_repository(self, **kwargs):
            captured["repository"] = kwargs
            return SimpleNamespace(post_revision_with_audit=lambda requests: ("audited-receipt",))

    monkeypatch.setattr(execution, "DjangoAuditedCorporateActionPostingRepositoryFactory", Factory)
    assert execution.execute_owner_corporate_action_intent(_intent(), environment="test") == (
        "audited-receipt",
    )
    assert (
        captured["owner"]["expected_grant_schema"]
        == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    )
    assert captured["factory"]["owner_grant_gate"] is gate
    assert isinstance(captured["factory"]["window_gate"], execution.CorporateActionWindowAuditGate)
    assert (
        type(captured["window"]["original_body_verifier"])
        is execution.DataCenterCorporateActionOriginalBodyVerifier
    )
    assert captured["repository"]["tax_basis_verifier"] is None


@pytest.mark.parametrize("operation", ("tax_assess", "tax_recognize", "tax_collect"))
def test_tax_dispatch_preserves_separate_assessment_and_withholding_operations(
    monkeypatch, operation
):
    captured = {}
    monkeypatch.setattr(
        execution, "DjangoSimulatedCorporateActionWriteScopeLocker", lambda **kwargs: object()
    )

    def verifier(**kwargs):
        captured["verifier"] = kwargs
        return object()

    monkeypatch.setattr(execution, "DjangoTaxAssessmentOwnerScopeVerifier", verifier)
    monkeypatch.setattr(execution, "DjangoTaxLiabilityOwnerScopeVerifier", verifier)
    monkeypatch.setattr(
        execution, "build_tax_assessment_audit_coordinator", lambda **kwargs: object()
    )

    def run(assessment, **kwargs):
        captured["run"] = kwargs
        return "tax-receipt"

    def build(**kwargs):
        captured["use_case"] = kwargs
        return SimpleNamespace(execute=run)

    monkeypatch.setattr(execution, "build_audited_tax_assessment_use_case", build)
    monkeypatch.setattr(execution, "build_audited_tax_liability_use_case", build)
    monkeypatch.setattr(
        execution,
        "read_owner_corporate_action_workflow_runtime",
        lambda **kwargs: pytest.fail(
            "exact replay must not eagerly resolve optional current routing"
        ),
    )
    intent = replace(_intent(tax=True), action=operation)
    assert (
        execution.execute_owner_corporate_action_intent(intent, environment="test") == "tax-receipt"
    )
    assert (
        captured["verifier"]["expected_grant_schema"]
        == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    )
    assert isinstance(
        captured["verifier"]["qualification_provider"], execution.DeferredOwnerTaxQualification
    )
    if operation == "tax_assess":
        assert "cash_action" not in captured["run"]
    else:
        assert captured["run"]["operation_id"] == intent.operation_id
        assert captured["run"]["cash_action"] == (
            TaxLiabilityCashAction.COLLECT_AVAILABLE if operation == "tax_collect" else None
        )
