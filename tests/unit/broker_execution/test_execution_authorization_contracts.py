from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from apps.broker_execution.application.evidence_gate import (
    blocked_lease_result,
    broker_order_evidence_integrated,
)
from apps.broker_execution.domain.execution_authorization_contracts import (
    BrokerExecutionAuthorizationReceiptContract,
    BrokerExecutionAuthorizationScope,
    BrokerExecutionPermission,
    ExactAuthorizationArtifactRef,
    validate_receipt_successor,
)

BASE_TIME = datetime(2026, 8, 13, 2, tzinfo=timezone.utc)


def _ref(owner: str, artifact_type: str, artifact_id: str) -> ExactAuthorizationArtifactRef:
    return ExactAuthorizationArtifactRef(
        owner=owner,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _scope(**changes: object) -> BrokerExecutionAuthorizationScope:
    values: dict[str, object] = {
        "account_id": 7,
        "plan_ref": _ref("portfolio", "transition_plan", "plan-1"),
        "plan_approval_ref": _ref("portfolio", "transition_plan_approval_receipt", "approval-1"),
        "order_ref": _ref(
            "broker_execution",
            "live_order_approval_snapshot",
            "56f9ae53-7606-46de-bf88-a6543f822d4a",
        ),
        "evidence_output_ref": _ref("equity", "recommendation", "output-1"),
        "evidence_envelope_ref": _ref("research", "evidence_envelope", "envelope-1"),
        "operator_spec_ref": _ref("research", "evidence_operator_spec", "operator-1"),
        "track_record_ref": _ref("research", "track_record_snapshot", "track-1"),
        "risk_authorization_ref": _ref("risk_center", "broker_order_risk_authorization", "risk-1"),
        "benchmark_snapshot_ref": _ref("portfolio", "policy_benchmark_snapshot", "benchmark-1"),
        "plan_valid_until": BASE_TIME + timedelta(hours=5),
        "order_valid_until": BASE_TIME + timedelta(hours=4),
        "evidence_valid_until": BASE_TIME + timedelta(hours=3),
        "risk_valid_until": BASE_TIME + timedelta(hours=2),
        "benchmark_valid_until": BASE_TIME + timedelta(hours=6),
    }
    values.update(changes)
    return BrokerExecutionAuthorizationScope(**values)  # type: ignore[arg-type]


def _receipt(**changes: object) -> BrokerExecutionAuthorizationReceiptContract:
    scope = changes.pop("scope", _scope())
    assert isinstance(scope, BrokerExecutionAuthorizationScope)
    values: dict[str, object] = {
        "receipt_id": "broker-live-order-authorization:order-1:v1",
        "scope": scope,
        "evidence_permission": BrokerExecutionPermission.EXECUTION_ELIGIBLE,
        "risk_permission": BrokerExecutionPermission.EXECUTION_ELIGIBLE,
        "approved_by_user_id": 19,
        "approved_by_role": "owner",
        "issued_at": BASE_TIME + timedelta(minutes=1),
        "valid_until": scope.valid_until,
    }
    values.update(changes)
    return BrokerExecutionAuthorizationReceiptContract(**values)  # type: ignore[arg-type]


def test_scope_and_receipt_are_canonical_but_explicitly_inactive() -> None:
    scope = _scope()
    receipt = _receipt(scope=scope)

    assert len(scope.scope_content_hash) == 64
    assert scope.valid_until == BASE_TIME + timedelta(hours=2)
    assert len(receipt.content_hash) == 64
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True
    assert receipt.to_payload()["must_not_execute"] is True
    assert broker_order_evidence_integrated() is False
    assert blocked_lease_result()["orders"] == []


@pytest.mark.parametrize(
    ("field_name", "bad_ref"),
    [
        ("plan_ref", _ref("broker_execution", "transition_plan", "plan-1")),
        (
            "plan_approval_ref",
            _ref("portfolio", "transition_plan", "approval-1"),
        ),
        (
            "order_ref",
            _ref("portfolio", "live_order_approval_snapshot", "order-1"),
        ),
        (
            "evidence_envelope_ref",
            _ref("research", "evidence_summary", "envelope-1"),
        ),
        (
            "risk_authorization_ref",
            _ref("research", "broker_order_risk_authorization", "risk-1"),
        ),
    ],
)
def test_scope_rejects_owner_or_artifact_substitution(
    field_name: str, bad_ref: ExactAuthorizationArtifactRef
) -> None:
    with pytest.raises(ValueError):
        _scope(**{field_name: bad_ref})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda scope: replace(scope, account_id=8, scope_content_hash=""),
        lambda scope: replace(
            scope,
            evidence_output_ref=_ref("equity", "recommendation", "output-2"),
            scope_content_hash="",
        ),
        lambda scope: replace(
            scope,
            risk_valid_until=scope.risk_valid_until + timedelta(seconds=1),
            scope_content_hash="",
        ),
    ],
)
def test_each_scope_identity_change_changes_hash(
    mutation: Callable[[BrokerExecutionAuthorizationScope], BrokerExecutionAuthorizationScope],
) -> None:
    original = _scope()
    changed = mutation(original)
    assert changed.scope_content_hash != original.scope_content_hash


def test_scope_rejects_tampered_hash_and_naive_clock() -> None:
    with pytest.raises(ValueError, match="scope_content_hash"):
        _scope(scope_content_hash="b" * 64)
    with pytest.raises(ValueError, match="timezone-aware"):
        _scope(risk_valid_until=datetime(2026, 8, 13, 4))


@pytest.mark.parametrize(
    "field_name",
    ["evidence_permission", "risk_permission"],
)
def test_contract_rejects_non_execution_upstream_permission(field_name: str) -> None:
    with pytest.raises(ValueError, match="not execution eligible"):
        _receipt(**{field_name: BrokerExecutionPermission.DISPLAY_ONLY})


def test_contract_requires_strict_validity_intersection_and_canonical_hash() -> None:
    scope = _scope()
    with pytest.raises(ValueError, match="strict upstream minimum"):
        _receipt(scope=scope, valid_until=scope.valid_until + timedelta(seconds=1))
    with pytest.raises(ValueError, match="content_hash"):
        _receipt(scope=scope, content_hash="b" * 64)


def test_successor_must_bind_exact_head_subject_and_advance_clock() -> None:
    previous = _receipt()
    successor_scope = replace(
        previous.scope,
        risk_valid_until=previous.scope.risk_valid_until + timedelta(hours=1),
        scope_content_hash="",
    )
    successor = _receipt(
        receipt_id="broker-live-order-authorization:order-1:v2",
        scope=successor_scope,
        issued_at=previous.issued_at + timedelta(minutes=1),
        valid_until=successor_scope.valid_until,
        supersedes_receipt_hash=previous.content_hash,
    )
    validate_receipt_successor(previous, successor)

    with pytest.raises(ValueError, match="exact previous"):
        validate_receipt_successor(
            previous,
            replace(successor, supersedes_receipt_hash="b" * 64, content_hash=""),
        )
    with pytest.raises(ValueError, match="clock must advance"):
        validate_receipt_successor(
            previous,
            replace(successor, issued_at=previous.issued_at, content_hash=""),
        )
