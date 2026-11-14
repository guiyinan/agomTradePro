"""Lossless signed server intents preserve facts while granting no write permission."""

import base64
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionPreparedIntent,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure import corporate_action_owner_intent_codec as codec
from apps.simulated_trading.infrastructure.corporate_action_constructor_codec import (
    encode_corporate_action_constructor,
    restore_corporate_action_constructor,
)
from core.exceptions import BusinessLogicError
from tests.unit.account.test_simulated_corporate_action_write_grant import _binding, _grant
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _NOW,
    _request,
)
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import (
    _assessment,
    _simulated_tax_date_observation,
)


@pytest.mark.parametrize("version", (1, 2))
def test_assessment_constructor_preserves_historical_shape_and_explicit_v2(version):
    assessment = replace(_assessment(), semantic_schema_version=version)
    payload = encode_corporate_action_constructor(assessment)
    assert isinstance(payload, dict)
    assert ("semantic_schema_version" in payload) is (version == 2)
    restored = restore_corporate_action_constructor(payload, CorporateActionTaxAssessment)
    assert restored == assessment
    assert encode_corporate_action_constructor(restored) == payload
    for invalid in (0, 3, True, None, "2"):
        with pytest.raises((ValueError, TypeError)):
            restore_corporate_action_constructor(
                {**payload, "semantic_schema_version": invalid}, CorporateActionTaxAssessment
            )


def _intent(*, tax: bool = False, simulated: bool = False) -> OwnerCorporateActionPreparedIntent:
    """Build synthetic facts only; neither source nor permission is being qualified."""
    assessment = _assessment() if tax else None
    if assessment:
        assessment = replace(
            assessment,
            action=replace(assessment.action, source_namespace="exchange_official_disclosure"),
        )
        if simulated:
            assessment = replace(
                assessment,
                simulated_tax_date_observation=_simulated_tax_date_observation(
                    history=assessment.history
                ),
            )
    request = _request()
    if assessment:
        action = assessment.action
        request = _request(
            account_id=action.account_id,
            owner_user_id=action.owner_user_id,
            security_id=action.security_id,
            asset_code=action.asset_code,
            source_namespace=action.source_namespace,
            source_record_id=action.source_record_id,
            source_event_id=action.source_event_id,
            source_revision_id=action.source_revision_id,
            source_payload_sha256=action.source_payload_sha256,
            record_date=action.record_date,
            effective_date=action.effective_date,
            stage_date=action.effective_date,
            ownership_snapshot_as_of_date=action.record_date,
            cash_amount=Decimal("500"),
        )
    grant = _grant(binding=_binding(owner_user_id=request.owner_user_id))
    return OwnerCorporateActionPreparedIntent(
        action="tax_assess" if tax else "cash_entitlement",
        account_id=request.account_id,
        owner_user_id=request.owner_user_id,
        selector=grant.selector,
        source_reference=request,
        requests=() if tax else (request,),
        assessment=assessment,
        operation_id="synthetic-operation-1",
        prepared_at=_NOW,
        valid_until=_NOW + timedelta(minutes=5),
    )


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setattr(
        codec,
        "get_secrets",
        lambda **kwargs: SimpleNamespace(
            field_encryption_key=base64.urlsafe_b64encode(bytes(range(32))).decode()
        ),
    )


@pytest.mark.parametrize("tax,simulated", [(False, False), (True, False), (True, True)])
def test_signed_intent_roundtrip_keeps_full_original_assessment_and_stage_bytes(
    tax: bool, simulated: bool
) -> None:
    intent = _intent(tax=tax, simulated=simulated)
    token = codec.seal_owner_corporate_action_intent(intent, session_binding="session-1")
    restored = codec.restore_owner_corporate_action_intent(
        token,
        owner_user_id=intent.owner_user_id,
        account_id=intent.account_id,
        session_binding="session-1",
        as_of=_NOW + timedelta(seconds=1),
    )
    assert restored == intent
    assert restored.source_reference.payload_sha256 == intent.source_reference.payload_sha256
    if intent.assessment:
        assert restored.assessment is not None
        assert restored.assessment.semantic_payload_json == intent.assessment.semantic_payload_json
        assert (
            restored.assessment.observation_manifest_json
            == intent.assessment.observation_manifest_json
        )


@pytest.mark.parametrize(
    "failure", ["mac", "owner", "account", "session", "expired", "future", "oversized"]
)
def test_signed_intent_rejects_cross_scope_expired_or_modified_material(failure: str) -> None:
    intent = _intent()
    token = codec.seal_owner_corporate_action_intent(intent, session_binding="session-1")
    if failure == "mac":
        token = token[:-1] + ("1" if token[-1] != "1" else "2")
    elif failure == "oversized":
        token = "x" * 65537
    with pytest.raises(BusinessLogicError):
        codec.restore_owner_corporate_action_intent(
            token,
            owner_user_id=intent.owner_user_id + (failure == "owner"),
            account_id=intent.account_id + (failure == "account"),
            session_binding="another" if failure == "session" else "session-1",
            as_of=(
                intent.valid_until
                if failure == "expired"
                else (_NOW - timedelta(seconds=1) if failure == "future" else _NOW)
            ),
        )


def test_intent_requires_literal_owner_identity_and_exact_tax_source() -> None:
    with pytest.raises(ValueError):
        replace(_intent(), owner_user_id=True)
    with pytest.raises(ValueError):
        replace(_intent(tax=True), source_reference=_request())
