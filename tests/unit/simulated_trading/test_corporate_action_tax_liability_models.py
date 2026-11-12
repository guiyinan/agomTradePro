"""Private immutable insert claims and lossless financial operation payloads."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.simulated_trading.domain.corporate_action_tax_liability import (
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.infrastructure import corporate_action_tax_liability_models as models
from tests.unit.simulated_trading.test_corporate_action_tax_liability import _taxable_assessment


def _encoded(value):
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return payload, hashlib.sha256(payload.encode()).hexdigest()


def _row():
    assessment = _taxable_assessment()
    transition = plan_corporate_action_tax_liability(
        assessment, prior_state=None, cash_request=None
    )
    state_json, state_sha = _encoded(transition.state_after._payload())
    transition_json, transition_sha = _encoded(transition._payload())
    operation_json, operation_sha = _encoded(
        {"schema": "synthetic-operation", "operation_id": "测试-operation"}
    )
    return models.CorporateActionTaxLiabilityOperationModel(
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        assessment_id=1,
        operation_id="测试-operation",
        operation_request_sha256="a" * 64,
        scope_sha256="b" * 64,
        sequence=1,
        predecessor_id=None,
        canonical_account_namespace="account",
        canonical_account_id="synthetic-canonical-account",
        currency="CNY",
        state_payload_json=state_json,
        state_sha256=state_sha,
        transition_payload_json=transition_json,
        transition_sha256=transition_sha,
        operation_payload_json=operation_json,
        operation_sha256=operation_sha,
        assessed_amount_text="0",
        net_collected_amount_text="0",
        outstanding_amount_text="0",
        tax_due_delta_text="0",
        collected_delta_text="0",
        outstanding_delta_text="0",
        cash_delta_text="0",
        audit_event_id="synthetic-audit",
        audit_event_version="1",
        audit_event_sha256="c" * 64,
        outbox_record_id="synthetic-outbox",
        outbox_payload_sha256="c" * 64,
    )


def test_lossless_payloads_use_the_exact_domain_unicode_codec():
    row = _row()
    models._verify_canonical_payload(row.state_payload_json, row.state_sha256, field_name="state")
    models._verify_canonical_payload(
        row.operation_payload_json, row.operation_sha256, field_name="operation"
    )
    assert "\\u6d4b" in row.operation_payload_json
    assert row._meta.get_field("cash_delta_text").get_internal_type() == "CharField"


@pytest.mark.parametrize("method", ["save", "save_base", "delete"])
def test_direct_financial_row_mutation_has_no_append_capability(method):
    with pytest.raises(ValidationError):
        getattr(_row(), method)()


def test_claim_is_exact_alias_model_values_and_private_uow(monkeypatch):
    monkeypatch.setattr(models, "connections", {"default": SimpleNamespace(in_atomic_block=True)})
    row = _row()
    expected = {
        field.attname: getattr(row, field.attname)
        for field in row._meta.concrete_fields
        if field is not row._meta.auto_field
    }
    with models._activate_tax_liability_uow() as token:
        with models._claim_tax_liability_insert(
            token=token, using="default", model_type=type(row), expected_values=expected
        ):
            models._require_insert_claim(row, using="default")
            row.operation_id = "changed-after-claim"
            with pytest.raises(ValidationError):
                models._require_insert_claim(row, using="default")
    with pytest.raises(ValidationError):
        models._require_insert_claim(_row(), using="default")


@pytest.mark.parametrize("manager", ["objects", "_base_manager", "_default_manager"])
def test_manager_bulk_paths_cannot_create_financial_evidence(manager):
    with pytest.raises(ValidationError):
        getattr(models.CorporateActionTaxLiabilityOperationModel, manager).bulk_create([_row()])


def test_corrupt_payload_is_rejected_before_any_financial_insert():
    row = _row()
    row.state_sha256 = "0" * 64
    with pytest.raises(ValidationError):
        row.save()
