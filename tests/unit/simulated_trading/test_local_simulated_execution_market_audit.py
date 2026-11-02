"""Pure contracts for the optional local simulated-execution market audit."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest

from apps.simulated_trading.domain.execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
)
from tests.unit.risk_center.test_execution_submission_v2 import _market_v2 as _risk_market_v2
from tests.unit.simulated_trading.test_execution_current_reference import (
    AS_OF,
    _canonical_sha256,
    _plan_v3,
)

_TARGET_MODULE = "apps.simulated_trading.domain.execution_current_reference"
_EXECUTED_AT = AS_OF + timedelta(minutes=1)


@pytest.fixture
def subject() -> ModuleType:
    """Load the V3 domain codec and require the optional audit feature."""

    module = importlib.import_module(_TARGET_MODULE)
    required = (
        "LocalSimulatedExecutionMarketAuditV1",
        "SimulatedSettlementPlanBindingV3",
        "bind_settlement_execution_plan_v3",
    )
    missing = tuple(name for name in required if not hasattr(module, name))
    if missing:
        pytest.fail(f"missing local market audit symbols: {missing!r}", pytrace=False)
    return module


def _base_binding(subject: ModuleType) -> tuple[Any, Any]:
    """Build an unchanged synthetic V3 plan and its legacy no-audit binding."""

    plan = _plan_v3(subject)
    binding = subject.bind_settlement_execution_plan_v3(plan, executed_at=_EXECUTED_AT)
    return plan, binding


def _market_audit_for_binding(
    subject: ModuleType,
    binding: Any,
    **scope_changes: object,
) -> Any:
    """Create internally consistent synthetic evidence bound to a V3 receipt."""

    common = binding.common_binding
    identity = binding.identity_evidence
    scope: dict[str, object] = {
        "account_id": common.account_id,
        "user_id": common.user_id,
        "idempotency_key": common.idempotency_key,
        "request_payload_hash": common.request_payload_hash,
        "security_id": identity.security_id,
        "asset_code": identity.asset_code,
        "execution_price": Decimal("10.00"),
        "risk_evaluated_at": common.executed_at,
    }
    scope.update(scope_changes)

    source_hash = "a" * 64
    policy_hash = "b" * 64
    market_bundle_hash = "d" * 64
    rule_hash = "e" * 64
    calendar_hash = "f" * 64
    market_payload = _risk_market_v2().to_payload()
    market_hash = market_payload["content_hash"]
    assert type(market_hash) is str
    policy_id = "fixture-sim-market-policy"
    policy_version = "policy-v1"
    risk_decision = {
        "status": "ALLOWED",
        "order_id": scope["idempotency_key"],
        "market_evidence_content_hash": market_hash,
    }
    risk_decision_hash = _canonical_sha256(risk_decision)
    evaluated_at = scope["risk_evaluated_at"]
    assert hasattr(evaluated_at, "isoformat")
    risk_evaluated_at = evaluated_at.isoformat().replace("+00:00", "Z")
    evidence = {
        "schema": "local-simulated-stop-loss-market-audit.v1",
        "purpose": "local_simulation_only",
        "retained_source": {
            "security_id": scope["security_id"],
            "policy_hash": policy_hash,
            "capture": {"body_sha256": source_hash},
        },
        "market_bundle": {
            "purpose": "local_simulation_only",
            "content_hash": market_bundle_hash,
            "execution_rule_content_hash": rule_hash,
            "policy": {
                "policy_id": policy_id,
                "policy_version": policy_version,
                "content_hash": policy_hash,
            },
            "calendar": {"content_hash": calendar_hash},
            "market": market_payload,
        },
        "risk_decision": risk_decision,
        "risk_evaluated_at": risk_evaluated_at,
        "locked_position": {
            "security_id": scope["security_id"],
            "quantity": "100",
            "available_quantity": "100",
        },
        "qualification": {
            "purpose": "local_simulation_only",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "execution_authority": False,
        },
    }
    evidence_json = json.dumps(
        evidence,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    audit_type = subject.LocalSimulatedExecutionMarketAuditV1
    return audit_type(
        **scope,
        source_id="fixture-retained-local-source",
        source_version="capture-v1",
        source_hash=source_hash,
        source_observed_at=AS_OF - timedelta(minutes=3),
        source_available_at=AS_OF,
        source_valid_until=AS_OF + timedelta(hours=2),
        policy_id=policy_id,
        policy_version=policy_version,
        policy_hash=policy_hash,
        market_hash=market_hash,
        market_bundle_hash=market_bundle_hash,
        rule_hash=rule_hash,
        calendar_hash=calendar_hash,
        risk_decision_hash=risk_decision_hash,
        evidence_json=evidence_json,
    )


def _reseal_audit_payload(payload: dict[str, Any]) -> None:
    """Recompute both canonical seals after a deliberate nested test mutation."""

    payload["evidence_hash"] = _canonical_sha256(payload["evidence"])
    unsigned = {key: value for key, value in payload.items() if key != "content_hash"}
    payload["content_hash"] = _canonical_sha256(unsigned)


def test_v3_without_audit_keeps_exact_legacy_payload_and_canonical_hash(
    subject: ModuleType,
) -> None:
    _, binding = _base_binding(subject)

    expected_legacy_payload = {
        "schema": "simulated-settlement-plan-binding.v3",
        "common_binding": binding.common_binding.to_payload(),
        "identity_evidence": binding.identity_evidence.to_payload(),
    }
    payload = binding.to_payload()
    assert payload == expected_legacy_payload
    assert "local_market_audit" not in payload
    assert binding.content_hash == _canonical_sha256(expected_legacy_payload)
    restored = type(binding).from_payload(payload)
    assert restored.to_payload() == expected_legacy_payload
    assert restored.content_hash == binding.content_hash


def test_valid_audit_round_trips_through_v3_binding(subject: ModuleType) -> None:
    plan, legacy_binding = _base_binding(subject)
    audit = _market_audit_for_binding(subject, legacy_binding)
    evidence = json.loads(audit.evidence_json)
    v2_market = evidence["market_bundle"]["market"]
    v1_evidence_hash = v2_market["market_evidence_v1"]["content_hash"]
    assert evidence["risk_decision"]["market_evidence_content_hash"] == v2_market["content_hash"]
    assert evidence["risk_decision"]["market_evidence_content_hash"] != v1_evidence_hash
    audit_type = subject.LocalSimulatedExecutionMarketAuditV1
    assert audit_type.from_payload(audit.to_payload()) == audit

    binding = subject.bind_settlement_execution_plan_v3(
        plan,
        executed_at=_EXECUTED_AT,
        local_market_audit=audit,
    )
    payload = binding.to_payload()
    assert set(payload) == {
        "schema",
        "common_binding",
        "identity_evidence",
        "local_market_audit",
    }
    assert payload["local_market_audit"] == audit.to_payload()
    assert binding.content_hash == _canonical_sha256(payload)
    restored = type(binding).from_payload(payload)
    assert restored == binding
    assert restored.to_payload() == payload


def test_audit_rejects_v1_market_hash_masquerading_as_the_v2_decision_hash(
    subject: ModuleType,
) -> None:
    """Resealing cannot turn the nested V1 market hash into Risk V2's outer hash."""

    _, binding = _base_binding(subject)
    audit_type = subject.LocalSimulatedExecutionMarketAuditV1
    payload = _market_audit_for_binding(subject, binding).to_payload()
    evidence = payload["evidence"]
    market = evidence["market_bundle"]["market"]
    v1_hash = market["market_evidence_v1"]["content_hash"]
    v2_hash = market["content_hash"]
    assert v1_hash != v2_hash

    evidence["risk_decision"]["market_evidence_content_hash"] = v1_hash
    payload["risk_decision_hash"] = _canonical_sha256(evidence["risk_decision"])
    _reseal_audit_payload(payload)

    with pytest.raises(SettlementPlanBindingValidationError):
        audit_type.from_payload(payload)


@pytest.mark.parametrize(
    "scope_change",
    (
        {"account_id": 8},
        {"user_id": 12},
        {"idempotency_key": "different-local-order"},
        {"request_payload_hash": "9" * 64},
        {"security_id": "OTHER.SECURITY"},
        {"asset_code": "000001.SZ"},
        {"execution_price": Decimal("10.01")},
        {"risk_evaluated_at": _EXECUTED_AT + timedelta(minutes=1)},
    ),
    ids=[
        "account",
        "user",
        "idempotency-key",
        "request-hash",
        "security",
        "asset-code",
        "execution-price",
        "risk-time",
    ],
)
def test_v3_rejects_a_valid_audit_from_a_different_plan_scope(
    subject: ModuleType,
    scope_change: dict[str, object],
) -> None:
    plan, binding = _base_binding(subject)
    audit = _market_audit_for_binding(subject, binding, **scope_change)
    audit.__post_init__()

    with pytest.raises(SettlementPlanBindingValidationError):
        subject.bind_settlement_execution_plan_v3(
            plan,
            executed_at=_EXECUTED_AT,
            local_market_audit=audit,
        )


@pytest.mark.parametrize(
    "outer_field",
    (
        "source_hash",
        "policy_hash",
        "market_hash",
        "market_bundle_hash",
        "rule_hash",
        "calendar_hash",
        "risk_decision_hash",
    ),
    ids=["source", "policy", "market", "bundle", "rule", "calendar", "risk-decision"],
)
def test_audit_rejects_hashes_that_do_not_match_source_and_decision_evidence(
    subject: ModuleType,
    outer_field: str,
) -> None:
    _, binding = _base_binding(subject)
    payload = _market_audit_for_binding(subject, binding).to_payload()
    payload[outer_field] = "0" * 64

    with pytest.raises(SettlementPlanBindingValidationError):
        subject.LocalSimulatedExecutionMarketAuditV1.from_payload(payload)


@pytest.mark.parametrize("field", ("evidence_hash", "content_hash"))
def test_audit_rejects_tampered_envelope_hashes(
    subject: ModuleType,
    field: str,
) -> None:
    _, binding = _base_binding(subject)
    payload = _market_audit_for_binding(subject, binding).to_payload()
    payload[field] = "0" * 64

    with pytest.raises(SettlementPlanBindingValidationError):
        subject.LocalSimulatedExecutionMarketAuditV1.from_payload(payload)


def test_audit_rejects_unknown_wire_and_nested_evidence_keys(subject: ModuleType) -> None:
    _, binding = _base_binding(subject)
    audit_type = subject.LocalSimulatedExecutionMarketAuditV1

    extra_envelope = _market_audit_for_binding(subject, binding).to_payload()
    extra_envelope["future_field"] = True
    with pytest.raises(SettlementPlanBindingValidationError):
        audit_type.from_payload(extra_envelope)

    extra_evidence = _market_audit_for_binding(subject, binding).to_payload()
    extra_evidence["evidence"]["future_field"] = True
    _reseal_audit_payload(extra_evidence)
    with pytest.raises(SettlementPlanBindingValidationError):
        audit_type.from_payload(extra_evidence)


def test_audit_rejects_false_allowed_decisions_and_removed_scope_restrictions(
    subject: ModuleType,
) -> None:
    _, binding = _base_binding(subject)
    audit_type = subject.LocalSimulatedExecutionMarketAuditV1
    mutations = (
        ("qualification", "must_not_use_for_decision", False),
        ("qualification", "must_not_execute", False),
        ("qualification", "execution_authority", True),
        ("qualification", "purpose", "broker_execution"),
        ("risk_decision", "status", "DENIED"),
    )
    for container_key, field, value in mutations:
        payload = _market_audit_for_binding(subject, binding).to_payload()
        payload["evidence"][container_key][field] = value
        if container_key == "risk_decision":
            payload["risk_decision_hash"] = _canonical_sha256(payload["evidence"]["risk_decision"])
        _reseal_audit_payload(payload)
        with pytest.raises(SettlementPlanBindingValidationError):
            audit_type.from_payload(payload)


def test_audit_rejects_reversed_source_clock_order(subject: ModuleType) -> None:
    _, binding = _base_binding(subject)
    audit = _market_audit_for_binding(subject, binding)

    for changes in (
        {"source_available_at": audit.source_observed_at - timedelta(seconds=1)},
        {"risk_evaluated_at": audit.source_available_at - timedelta(seconds=1)},
        {"source_valid_until": audit.risk_evaluated_at},
    ):
        with pytest.raises(SettlementPlanBindingValidationError):
            replace(audit, **changes)
