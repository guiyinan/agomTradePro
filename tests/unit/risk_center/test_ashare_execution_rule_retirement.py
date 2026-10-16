"""Pure-domain coverage for immutable early retirement of A-share rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from apps.risk_center.domain.ashare_execution_rule_retirement import (
    AShareExecutionRuleRetirementAuthorization,
    AShareExecutionRuleRetirementConflict,
    AShareExecutionRuleRetirementEvidence,
    AShareExecutionRuleRetirementIntent,
    AShareExecutionRuleRetirementTarget,
    AShareExecutionRuleRetirementValidationError,
    build_retirement_evidence,
    retirement_request_hash,
    verify_retirement_replay,
)

RECORDED_AT = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
EFFECTIVE_FROM = datetime(2026, 10, 1, tzinfo=UTC)
VALID_UNTIL = datetime(2027, 1, 1, tzinfo=UTC)
REQUEST_ID = UUID("570b1e2d-286a-4a83-8c4d-bbcb5dd88890")
CONTENT_HASH = "a" * 64


def _intent(**overrides: object) -> AShareExecutionRuleRetirementIntent:
    values: dict[str, object] = {
        "security_id": "XSHG.600000",
        "rule_id": "sse-mainboard",
        "rule_version": "2026-10-v1",
        "expected_content_hash": CONTENT_HASH,
        "request_id": REQUEST_ID,
        "effective_at": RECORDED_AT + timedelta(days=2),
        "reason_code": "operator-requested",
    }
    values.update(overrides)
    return AShareExecutionRuleRetirementIntent(**values)  # type: ignore[arg-type]


def _authorization(**overrides: str) -> AShareExecutionRuleRetirementAuthorization:
    values = {
        "actor_type": "staff_user",
        "actor_id": "operator-17",
        "scope_tenant_id": "tenant-8",
        "scope_owner_id": "owner-3",
    }
    values.update(overrides)
    return AShareExecutionRuleRetirementAuthorization(**values)


def _target(
    *,
    retirement: AShareExecutionRuleRetirementEvidence | None = None,
    **overrides: object,
) -> AShareExecutionRuleRetirementTarget:
    values: dict[str, object] = {
        "security_id": "XSHG.600000",
        "rule_id": "sse-mainboard",
        "rule_version": "2026-10-v1",
        "content_hash": CONTENT_HASH,
        "rule_recorded_at": EFFECTIVE_FROM,
        "effective_from": EFFECTIVE_FROM,
        "valid_until": VALID_UNTIL,
        "retirement": retirement or AShareExecutionRuleRetirementEvidence(),
    }
    values.update(overrides)
    return AShareExecutionRuleRetirementTarget(**values)  # type: ignore[arg-type]


def test_build_and_replay_bind_exact_rule_request_actor_and_scope() -> None:
    intent = _intent()
    authorization = _authorization()
    target = _target()

    evidence = build_retirement_evidence(
        target=target,
        intent=intent,
        authorization=authorization,
        recorded_at=RECORDED_AT,
    )
    replay_target = replace(target, retirement=evidence)

    assert evidence.retirement_request_id == REQUEST_ID
    assert evidence.retirement_effective_at == intent.effective_at
    assert evidence.retirement_recorded_at == RECORDED_AT
    assert evidence.retirement_actor_id == "operator-17"
    assert len(evidence.retirement_request_hash or "") == 64
    assert (
        verify_retirement_replay(
            target=replay_target,
            intent=intent,
            authorization=authorization,
        )
        == evidence
    )


def test_request_hash_changes_for_actor_scope_and_reason() -> None:
    intent = _intent()
    authorization = _authorization()
    digest = retirement_request_hash(intent=intent, authorization=authorization)

    assert digest != retirement_request_hash(
        intent=intent,
        authorization=_authorization(actor_id="operator-18"),
    )
    assert digest != retirement_request_hash(
        intent=intent,
        authorization=_authorization(scope_owner_id="owner-4"),
    )
    assert digest != retirement_request_hash(
        intent=_intent(reason_code="correction"),
        authorization=authorization,
    )


def test_retirement_keeps_base_rule_unicode_identity_semantics_and_bounds_reason() -> None:
    unicode_rule = _target(
        security_id="测试.证券",
        rule_id="规则-主板",
        rule_version="版本甲",
    )
    unicode_intent = _intent(
        security_id="测试.证券",
        rule_id="规则-主板",
        rule_version="版本甲",
    )
    assert (
        build_retirement_evidence(
            target=unicode_rule,
            intent=unicode_intent,
            authorization=_authorization(),
            recorded_at=RECORDED_AT,
        ).retirement_request_id
        == REQUEST_ID
    )

    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _intent(reason_code="a" * 129)


def test_retirement_recorded_time_cannot_precede_original_rule_record() -> None:
    later_recorded_rule = _target(rule_recorded_at=RECORDED_AT + timedelta(seconds=1))
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        build_retirement_evidence(
            target=later_recorded_rule,
            intent=_intent(),
            authorization=_authorization(),
            recorded_at=RECORDED_AT,
        )


@pytest.mark.parametrize(
    ("effective_at", "recorded_at"),
    [
        (RECORDED_AT - timedelta(microseconds=1), RECORDED_AT),
        (EFFECTIVE_FROM - timedelta(seconds=1), RECORDED_AT - timedelta(days=1)),
        (VALID_UNTIL, RECORDED_AT),
    ],
)
def test_build_rejects_backdated_or_out_of_window_retirement(
    effective_at: datetime, recorded_at: datetime
) -> None:
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        build_retirement_evidence(
            target=_target(),
            intent=_intent(effective_at=effective_at),
            authorization=_authorization(),
            recorded_at=recorded_at,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"security_id": "XSHG.600001"},
        {"rule_id": "another-rule"},
        {"rule_version": "v2"},
        {"expected_content_hash": "b" * 64},
    ],
)
def test_build_rejects_a_different_rule_identity_or_hash(overrides: dict[str, str]) -> None:
    with pytest.raises(AShareExecutionRuleRetirementConflict):
        build_retirement_evidence(
            target=_target(),
            intent=_intent(**overrides),
            authorization=_authorization(),
            recorded_at=RECORDED_AT,
        )


def test_build_rejects_existing_winner_and_replay_rejects_other_request() -> None:
    intent = _intent()
    authorization = _authorization()
    evidence = build_retirement_evidence(
        target=_target(),
        intent=intent,
        authorization=authorization,
        recorded_at=RECORDED_AT,
    )
    retired_target = _target(retirement=evidence)

    with pytest.raises(AShareExecutionRuleRetirementConflict):
        build_retirement_evidence(
            target=retired_target,
            intent=intent,
            authorization=authorization,
            recorded_at=RECORDED_AT,
        )
    with pytest.raises(AShareExecutionRuleRetirementConflict):
        verify_retirement_replay(
            target=retired_target,
            intent=_intent(request_id=UUID("670b1e2d-286a-4a83-8c4d-bbcb5dd88891")),
            authorization=authorization,
        )


def test_replay_rejects_actor_scope_reason_or_recorded_hash_substitution() -> None:
    intent = _intent()
    authorization = _authorization()
    evidence = build_retirement_evidence(
        target=_target(),
        intent=intent,
        authorization=authorization,
        recorded_at=RECORDED_AT,
    )
    target = _target(retirement=evidence)

    for changed_intent, changed_authorization in (
        (_intent(reason_code="data-correction"), authorization),
        (intent, _authorization(actor_id="operator-18")),
        (intent, _authorization(scope_tenant_id="tenant-9")),
    ):
        with pytest.raises(AShareExecutionRuleRetirementConflict):
            verify_retirement_replay(
                target=target,
                intent=changed_intent,
                authorization=changed_authorization,
            )

    corrupt = replace(evidence, retirement_request_hash="b" * 64)
    with pytest.raises(AShareExecutionRuleRetirementConflict):
        verify_retirement_replay(
            target=_target(retirement=corrupt),
            intent=intent,
            authorization=authorization,
        )


def test_evidence_must_be_all_null_or_complete_and_valid() -> None:
    assert AShareExecutionRuleRetirementEvidence().is_empty

    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        AShareExecutionRuleRetirementEvidence(retirement_request_id=REQUEST_ID)
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        AShareExecutionRuleRetirementEvidence(
            retirement_effective_at=RECORDED_AT,
            retirement_recorded_at=RECORDED_AT + timedelta(seconds=1),
            retirement_request_id=REQUEST_ID,
            retirement_actor_type="staff_user",
            retirement_actor_id="operator-17",
            retirement_request_hash="c" * 64,
        )


def test_target_rejects_corrupt_window_and_retirement_outside_original_window() -> None:
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _target(valid_until=EFFECTIVE_FROM)

    evidence = build_retirement_evidence(
        target=_target(),
        intent=_intent(),
        authorization=_authorization(),
        recorded_at=RECORDED_AT,
    )
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _target(retirement=replace(evidence, retirement_effective_at=VALID_UNTIL))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"security_id": "XSHG.600000 "},
        {"rule_id": "rule with spaces"},
        {"rule_version": ""},
        {"expected_content_hash": "A" * 64},
        {"request_id": "570b1e2d-286a-4a83-8c4d-bbcb5dd88890"},
        {"effective_at": datetime(2026, 10, 16, 9, 0)},
        {"reason_code": "Bad Reason"},
    ],
)
def test_intent_rejects_noncanonical_fields(kwargs: dict[str, object]) -> None:
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _intent(**kwargs)


def test_authorization_and_target_reject_bad_typed_or_token_values() -> None:
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _authorization(actor_id="operator 17")
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _target(content_hash="not-a-hash")
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _target(retirement=object())
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        _target(security_id="x" * 193)


def test_public_operations_reject_wrong_outer_types_and_naive_recorded_time() -> None:
    intent = _intent()
    authorization = _authorization()
    target = _target()

    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        retirement_request_hash(intent=object(), authorization=authorization)  # type: ignore[arg-type]
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        retirement_request_hash(intent=intent, authorization=object())  # type: ignore[arg-type]
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        build_retirement_evidence(
            target=object(),  # type: ignore[arg-type]
            intent=intent,
            authorization=authorization,
            recorded_at=RECORDED_AT,
        )
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        build_retirement_evidence(
            target=target,
            intent=object(),  # type: ignore[arg-type]
            authorization=authorization,
            recorded_at=RECORDED_AT,
        )
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        build_retirement_evidence(
            target=target,
            intent=intent,
            authorization=object(),  # type: ignore[arg-type]
            recorded_at=RECORDED_AT,
        )
    with pytest.raises(AShareExecutionRuleRetirementValidationError):
        build_retirement_evidence(
            target=target,
            intent=intent,
            authorization=authorization,
            recorded_at=datetime(2026, 10, 16, 9, 0),
        )
    with pytest.raises(AShareExecutionRuleRetirementConflict):
        verify_retirement_replay(
            target=target,
            intent=intent,
            authorization=authorization,
        )
