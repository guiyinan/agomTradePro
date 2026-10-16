"""Transactional component tests for early retirement and forward-version import."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import NoReturn
from uuid import UUID

import pytest
from django.db import connections

from apps.audit.application.execution_rule_retirement_audit import (
    AppendExecutionRuleRetirementAuditUseCase,
)
from apps.audit.domain.system_audit_event import (
    AuditCategory,
    AuditOutcome,
    AuditSeverity,
    AuditWritePolicy,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleUnavailable,
)
from apps.risk_center.application.ashare_execution_rule_lifecycle import (
    ExecutionRuleRetirementConflict,
    ExecutionRuleRetirementCorruption,
    ExecutionRuleRetirementDenied,
    ExecutionRuleRetirementInputError,
    ExecutionRuleRetirementUnavailable,
    RetireAShareExecutionRuleUseCase,
    RuleLifecycleAuthorizationDenied,
)
from apps.risk_center.domain.ashare_execution_rule_retirement import (
    AShareExecutionRuleRetirementAuthorization,
    AShareExecutionRuleRetirementEvidence,
    AShareExecutionRuleRetirementIntent,
)
from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import AShareExecutionRule
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.risk_center.infrastructure.ashare_execution_rule_models import (
    AShareExecutionRuleModel,
)
from apps.risk_center.infrastructure.ashare_execution_rule_repository import (
    DjangoAShareExecutionRuleRepository,
)
from core.integration.risk_execution_rule_retirement_audit import (
    CoreRiskExecutionRuleRetirementAuditBridge,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.risk_center.execution_constraints_factories import AS_OF, execution_rule

IMPORT_RECORDED_AT = AS_OF - timedelta(hours=1)
RETIREMENT_RECORDED_AT = AS_OF
RETIREMENT_EFFECTIVE_AT = AS_OF + timedelta(hours=1)
REQUEST_ID = UUID("570b1e2d-286a-4a83-8c4d-bbcb5dd88890")


@pytest.fixture(autouse=True)
def _lifecycle_schema() -> Iterator[None]:
    """Isolate the real Risk and Audit tables without flushing account governance."""
    with isolated_schema((AShareExecutionRuleModel, SystemAuditEventModel, SystemAuditOutboxModel)):
        yield


class _Clock:
    """A mutable deterministic application clock for transactional components."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _SequenceClock(_Clock):
    """Return successive server times to model time passing before the writer fence."""

    def __init__(self, values: tuple[datetime, ...]) -> None:
        super().__init__(values[0])
        self._values = values
        self._last_value = values[-1]
        self._index = 0

    def now(self) -> datetime:
        if self._index < len(self._values):
            value = self._values[self._index]
            self._index += 1
            self._last_value = value
            return value
        return self._last_value


class _Authorizer:
    """Test authority that returns a fixed trusted actor and explicit Audit scope."""

    def __init__(self, result: object = None) -> None:
        self.result = result or AShareExecutionRuleRetirementAuthorization(
            actor_type="staff_user",
            actor_id="operator-17",
            scope_tenant_id="tenant-8",
            scope_owner_id="owner-3",
        )
        self.denied = False

    def authorize(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        as_of: datetime,
    ) -> AShareExecutionRuleRetirementAuthorization:
        assert type(intent) is AShareExecutionRuleRetirementIntent
        assert as_of.tzinfo is not None
        if self.denied:
            raise RuleLifecycleAuthorizationDenied("test denial")
        return self.result  # type: ignore[return-value]


class _RevokedAfterFirstAuthorization(_Authorizer):
    """Allow initial request validation, then revoke before the writer fence."""

    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    def authorize(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        as_of: datetime,
    ) -> AShareExecutionRuleRetirementAuthorization:
        self.call_count += 1
        if self.call_count > 1:
            raise RuleLifecycleAuthorizationDenied("revoked while waiting for writer fence")
        return super().authorize(intent=intent, as_of=as_of)


class _AuditThenFail:
    """Commit through the real Audit writer, then force outer Risk rollback."""

    def __init__(self, bridge: CoreRiskExecutionRuleRetirementAuditBridge) -> None:
        self._bridge = bridge

    @property
    def database_alias(self) -> str:
        return self._bridge.database_alias

    def execute_retirement_in_caller_transaction(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        authorization: AShareExecutionRuleRetirementAuthorization,
        evidence: AShareExecutionRuleRetirementEvidence,
        exact_replay: bool,
    ) -> NoReturn:
        self._bridge.execute_retirement_in_caller_transaction(
            intent=intent,
            authorization=authorization,
            evidence=evidence,
            exact_replay=exact_replay,
        )
        raise ExecutionRuleRetirementUnavailable("failure after real event/outbox append")


def _intent(
    rule: AShareExecutionRule,
    *,
    request_id: UUID = REQUEST_ID,
    effective_at: datetime = RETIREMENT_EFFECTIVE_AT,
    reason_code: str = "operator-requested",
) -> AShareExecutionRuleRetirementIntent:
    return AShareExecutionRuleRetirementIntent(
        security_id=rule.security_id,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        expected_content_hash=rule.content_hash,
        request_id=request_id,
        effective_at=effective_at,
        reason_code=reason_code,
    )


def _use_case(
    *,
    repository: DjangoAShareExecutionRuleRepository,
    clock: _Clock,
    authorizer: _Authorizer | None = None,
    audit: object | None = None,
) -> RetireAShareExecutionRuleUseCase:
    writer = audit or CoreRiskExecutionRuleRetirementAuditBridge(
        AppendExecutionRuleRetirementAuditUseCase(
            DjangoSystemAuditEventOutboxCoordinator(using="default")
        )
    )
    return RetireAShareExecutionRuleUseCase(
        repository=repository,
        authorizer=authorizer or _Authorizer(),
        audit=writer,  # type: ignore[arg-type]
        clock=clock,
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_retirement_is_same_transaction_pit_visible_and_forward_rollback_is_new_version() -> None:
    clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=clock)
    original = execution_rule()
    repository.import_rules(rules=(original,))
    original_row = AShareExecutionRuleModel.objects.get(content_hash=original.content_hash)
    original_payload = original_row.canonical_payload
    original_hash = original_row.content_hash
    before_retirement = repository.get_effective_rule(
        security_id=original.security_id,
        as_of=IMPORT_RECORDED_AT,
    )
    assert before_retirement.content_hash == original.content_hash

    clock.value = RETIREMENT_RECORDED_AT
    use_case = _use_case(repository=repository, clock=clock)
    intent = _intent(original)
    first = use_case.execute(intent=intent)

    assert first.exact_replay is False
    event_id = f"risk-rule-retirement-{REQUEST_ID}"
    event_row = SystemAuditEventModel.objects.get(event_id=event_id)
    outbox_row = SystemAuditOutboxModel.objects.get(event_id=event_id)
    assert event_row.event_version == "1"
    assert event_row.schema_version == "system-audit-event.v1"
    assert event_row.event_type == "risk.execution_rule.retired"
    assert event_row.category == AuditCategory.SYSTEM_CONFIGURATION.value
    assert event_row.owner == "risk_center"
    assert event_row.write_policy == AuditWritePolicy.TRANSACTIONAL_OUTBOX.value
    assert event_row.outcome == AuditOutcome.SUCCESS.value
    assert event_row.severity == AuditSeverity.WARNING.value
    assert event_row.reason_codes == ["execution_rule_retired"]
    assert event_row.actor_type == "staff_user"
    assert event_row.actor_id == "operator-17"
    assert event_row.scope_tenant_id == "tenant-8"
    assert event_row.scope_owner_id == "owner-3"
    assert event_row.detail_schema == "risk.execution_rule.retired.v1"
    assert event_row.detail == {
        "security_id": original.security_id,
        "rule_id": original.rule_id,
        "rule_version": original.rule_version,
        "content_hash": original.content_hash,
        "request_id": str(REQUEST_ID),
        "request_hash": first.request_hash,
        "reason_code": "operator-requested",
        "effective_at": RETIREMENT_EFFECTIVE_AT.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
    }
    assert event_row.stream_id == f"risk.execution-rule:{original.security_id}"
    assert event_row.sequence_no == 1
    assert event_row.predecessor_hash is None
    assert event_row.content_hash == first.audit_event_hash
    assert outbox_row.outbox_id == first.audit_outbox_id
    assert outbox_row.idempotency_key == event_row.idempotency_key
    assert outbox_row.payload_hash == event_row.content_hash
    assert outbox_row.payload == event_row.canonical_payload

    row = AShareExecutionRuleModel.objects.get(content_hash=original.content_hash)
    assert row.retirement_recorded_at == RETIREMENT_RECORDED_AT
    assert row.retirement_effective_at == RETIREMENT_EFFECTIVE_AT
    assert row.retirement_request_id == REQUEST_ID
    assert row.retirement_actor_id == "operator-17"
    assert row.retirement_request_hash == first.request_hash
    assert row.canonical_payload == original_payload
    assert row.content_hash == original_hash

    assert (
        repository.get_effective_rule(
            security_id=original.security_id,
            as_of=RETIREMENT_RECORDED_AT - timedelta(microseconds=1),
        ).content_hash
        == original.content_hash
    )
    assert (
        repository.get_effective_rule(
            security_id=original.security_id,
            as_of=RETIREMENT_RECORDED_AT,
        ).content_hash
        == original.content_hash
    )
    with pytest.raises(ExecutionRuleUnavailable):
        repository.get_effective_rule(
            security_id=original.security_id,
            as_of=RETIREMENT_EFFECTIVE_AT,
        )

    clock.value = RETIREMENT_RECORDED_AT + timedelta(minutes=10)
    replay = use_case.execute(intent=intent)
    assert replay.exact_replay is True
    assert replay.recorded_at == first.recorded_at
    assert replay.audit_event_hash == first.audit_event_hash
    assert replay.audit_outbox_id == first.audit_outbox_id
    assert SystemAuditEventModel.objects.filter(event_id=event_id).count() == 1
    assert SystemAuditOutboxModel.objects.filter(event_id=event_id).count() == 1

    rollback = replace(
        original,
        rule_version="rollback-v2",
        effective_from=RETIREMENT_EFFECTIVE_AT,
        valid_until=original.valid_until + timedelta(days=1),
        content_hash="",
    )
    assert repository.import_rules(rules=(rollback,)).inserted_count == 1
    assert (
        repository.get_effective_rule(
            security_id=original.security_id,
            as_of=RETIREMENT_EFFECTIVE_AT,
        ).content_hash
        == rollback.content_hash
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_exact_replay_conflict_and_request_id_reuse_across_securities() -> None:
    clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=clock)
    first_rule = execution_rule()
    second_rule = execution_rule(security_id="TEST.SECURITY.2")
    repository.import_rules(rules=(first_rule, second_rule))
    clock.value = RETIREMENT_RECORDED_AT
    use_case = _use_case(repository=repository, clock=clock)
    use_case.execute(intent=_intent(first_rule))

    with pytest.raises(ExecutionRuleRetirementConflict):
        use_case.execute(intent=_intent(first_rule, reason_code="data-correction"))
    with pytest.raises(ExecutionRuleRetirementConflict):
        use_case.execute(intent=_intent(second_rule))
    assert (
        AShareExecutionRuleModel.objects.get(
            content_hash=second_rule.content_hash
        ).retirement_request_id
        is None
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_denial_untrusted_authority_and_audit_failure_leave_no_retirement() -> None:
    clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=clock)
    rule = execution_rule()
    repository.import_rules(rules=(rule,))
    clock.value = RETIREMENT_RECORDED_AT
    denied_authorizer = _Authorizer()
    denied_authorizer.denied = True
    with pytest.raises(ExecutionRuleRetirementDenied):
        _use_case(
            repository=repository,
            clock=clock,
            authorizer=denied_authorizer,
        ).execute(intent=_intent(rule))

    with pytest.raises(ExecutionRuleRetirementDenied):
        _use_case(
            repository=repository,
            clock=clock,
            authorizer=_Authorizer(result={"actor_id": "self-asserted"}),
        ).execute(intent=_intent(rule))

    with pytest.raises(ExecutionRuleRetirementUnavailable):
        _use_case(
            repository=repository,
            clock=clock,
            audit=_AuditThenFail(
                CoreRiskExecutionRuleRetirementAuditBridge(
                    AppendExecutionRuleRetirementAuditUseCase(
                        DjangoSystemAuditEventOutboxCoordinator(using="default")
                    )
                )
            ),
        ).execute(intent=_intent(rule))
    row = AShareExecutionRuleModel.objects.get(content_hash=rule.content_hash)
    assert row.retirement_request_id is None
    assert row.canonical_payload == rule.to_payload()
    event_id = f"risk-rule-retirement-{REQUEST_ID}"
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM audit_system_event WHERE event_id = %s", [event_id])
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT COUNT(*) FROM audit_system_outbox WHERE event_id = %s", [event_id])
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_replay_with_missing_outbox_is_corruption_and_does_not_recreate_it() -> None:
    clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=clock)
    rule = execution_rule()
    repository.import_rules(rules=(rule,))
    clock.value = RETIREMENT_RECORDED_AT
    use_case = _use_case(repository=repository, clock=clock)
    result = use_case.execute(intent=_intent(rule))
    assert result.exact_replay is False

    with connections["default"].cursor() as cursor:
        cursor.execute(
            "DELETE FROM audit_system_outbox WHERE event_id = %s",
            [f"risk-rule-retirement-{REQUEST_ID}"],
        )
    clock.value = RETIREMENT_RECORDED_AT + timedelta(minutes=5)
    with pytest.raises(ExecutionRuleRetirementCorruption):
        use_case.execute(intent=_intent(rule))
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM audit_system_outbox WHERE event_id = %s",
            [f"risk-rule-retirement-{REQUEST_ID}"],
        )
        assert cursor.fetchone() == (0,)
    assert (
        AShareExecutionRuleModel.objects.get(content_hash=rule.content_hash).retirement_request_id
        == REQUEST_ID
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_retirement_rejects_effective_time_before_rule_import_time() -> None:
    clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=clock)
    rule = execution_rule()
    repository.import_rules(rules=(rule,))
    clock.value = IMPORT_RECORDED_AT - timedelta(seconds=1)
    with pytest.raises(ExecutionRuleRetirementInputError):
        _use_case(repository=repository, clock=clock).execute(intent=_intent(rule))


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_retirement_rejects_effective_time_that_passes_before_writer_fence() -> None:
    setup_clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=setup_clock)
    rule = execution_rule()
    repository.import_rules(rules=(rule,))
    final_time = RETIREMENT_EFFECTIVE_AT + timedelta(seconds=1)
    lifecycle_clock = _SequenceClock((RETIREMENT_RECORDED_AT, final_time))

    with pytest.raises(ExecutionRuleRetirementInputError):
        _use_case(repository=repository, clock=lifecycle_clock).execute(intent=_intent(rule))

    row = AShareExecutionRuleModel.objects.get(content_hash=rule.content_hash)
    assert row.retirement_request_id is None
    event_id = f"risk-rule-retirement-{REQUEST_ID}"
    assert not SystemAuditEventModel.objects.filter(event_id=event_id).exists()
    assert not SystemAuditOutboxModel.objects.filter(event_id=event_id).exists()


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_v3_retirement_audits_outer_identity_and_preserves_nested_rule_on_forward_rollback() -> (
    None
):
    """Exercise V3 through the real retirement, Audit, and Outbox transaction."""
    clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=clock)
    base = execution_rule()
    nested = ExecutionSubmissionRuleV2(
        execution_rule_v1=base,
        price_submission_range=PriceSubmissionRangeRule(
            market=base.market,
            board=base.board,
            price_tick=base.price_tick,
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=10,
            sell_widening_ticks=10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )
    policy = SettlementPolicyV1(
        policy_id="fixture-settlement-policy",
        policy_version="fixture-1",
        security_id=base.security_id,
        market=base.market,
        board=base.board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=nested.content_hash,
        source_id="fixture-settlement-source",
        source_version="fixture-only",
        source_hash="c" * 64,
        source_observed_at=base.source_observed_at,
        source_available_at=base.source_available_at,
        effective_from=AS_OF - timedelta(minutes=90),
        valid_until=AS_OF + timedelta(hours=5),
    )
    original = ExecutionSettlementBundleV3(
        bundle_id="fixture-settlement-bundle",
        bundle_version="fixture-package-1",
        execution_submission_v2=nested,
        settlement_policy_v1=policy,
    )
    repository.import_settlement_bundles(bundles=(original,))
    stored = AShareExecutionRuleModel.objects.get(content_hash=original.content_hash)
    original_payload = stored.canonical_payload
    assert stored.effective_from == policy.effective_from
    assert stored.valid_until == policy.valid_until
    intent = AShareExecutionRuleRetirementIntent(
        security_id=base.security_id,
        rule_id=original.bundle_id,
        rule_version=original.bundle_version,
        expected_content_hash=original.content_hash,
        request_id=REQUEST_ID,
        effective_at=RETIREMENT_EFFECTIVE_AT,
        reason_code="operator-requested",
    )
    clock.value = RETIREMENT_RECORDED_AT
    use_case = _use_case(repository=repository, clock=clock)
    first = use_case.execute(intent=intent)
    event_id = f"risk-rule-retirement-{REQUEST_ID}"
    event = SystemAuditEventModel.objects.get(event_id=event_id)
    outbox = SystemAuditOutboxModel.objects.get(event_id=event_id)
    assert event.detail["rule_id"] == original.bundle_id
    assert event.detail["rule_version"] == original.bundle_version
    assert event.detail["content_hash"] == original.content_hash
    assert event.detail["rule_id"] != base.rule_id
    assert event.content_hash == first.audit_event_hash == outbox.payload_hash
    assert outbox.payload == event.canonical_payload
    assert (
        repository.get_effective_settlement_bundle(
            security_id=base.security_id, as_of=RETIREMENT_EFFECTIVE_AT
        )
        is None
    )

    clock.value = AS_OF + timedelta(minutes=10)
    replay = use_case.execute(intent=intent)
    assert replay.exact_replay is True
    assert replay.audit_event_hash == first.audit_event_hash
    assert replay.audit_outbox_id == first.audit_outbox_id
    rollback = replace(
        original,
        bundle_version="fixture-package-rollback-2",
        settlement_policy_v1=replace(
            policy,
            policy_version="fixture-policy-rollback-2",
            effective_from=RETIREMENT_EFFECTIVE_AT,
            content_hash="",
        ),
        content_hash="",
    )
    assert repository.import_settlement_bundles(bundles=(rollback,)).inserted_count == 1
    restored = repository.get_effective_settlement_bundle(
        security_id=base.security_id, as_of=RETIREMENT_EFFECTIVE_AT
    )
    assert restored is not None
    assert restored.bundle == rollback
    assert restored.bundle.execution_submission_v2.content_hash == nested.content_hash
    stored.refresh_from_db()
    assert stored.canonical_payload == original_payload
    assert stored.content_hash == original.content_hash
    assert SystemAuditEventModel.objects.filter(event_id=event_id).count() == 1
    assert SystemAuditOutboxModel.objects.filter(event_id=event_id).count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center", "apps.audit"])
def test_retirement_reauthorizes_after_writer_fence_and_rejects_revocation() -> None:
    setup_clock = _Clock(IMPORT_RECORDED_AT)
    repository = DjangoAShareExecutionRuleRepository(clock=setup_clock)
    rule = execution_rule()
    repository.import_rules(rules=(rule,))
    authorizer = _RevokedAfterFirstAuthorization()
    lifecycle_clock = _SequenceClock((RETIREMENT_RECORDED_AT, RETIREMENT_RECORDED_AT))

    with pytest.raises(ExecutionRuleRetirementDenied):
        _use_case(
            repository=repository,
            clock=lifecycle_clock,
            authorizer=authorizer,
        ).execute(intent=_intent(rule))

    assert authorizer.call_count == 2
    row = AShareExecutionRuleModel.objects.get(content_hash=rule.content_hash)
    assert row.retirement_request_id is None
    event_id = f"risk-rule-retirement-{REQUEST_ID}"
    assert not SystemAuditEventModel.objects.filter(event_id=event_id).exists()
    assert not SystemAuditOutboxModel.objects.filter(event_id=event_id).exists()
