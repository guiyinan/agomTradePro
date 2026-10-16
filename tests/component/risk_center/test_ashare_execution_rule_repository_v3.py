"""Single-table repository behavior for v3 settlement bundles."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleConflict,
    ExecutionRuleCorruption,
    ExecutionRuleInputError,
    ExecutionRuleVersionMismatch,
)
from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3ReadRecord,
    ExecutionSettlementV3Unavailable,
    ReadEffectiveExecutionSettlementV3UseCase,
)
from apps.risk_center.domain.ashare_execution_rule_retirement import (
    AShareExecutionRuleRetirementAuthorization,
    AShareExecutionRuleRetirementIntent,
    build_retirement_evidence,
)
from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
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
from tests.support.isolated_schema import isolated_schema

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _rule_schema() -> Iterator[None]:
    """Isolate only the immutable rule table used by this component module."""

    with isolated_schema((AShareExecutionRuleModel,)):
        yield


class _FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _v1(
    *,
    security_id: str = "V3.REPOSITORY.SECURITY",
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
    source_available_at: datetime | None = None,
) -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id="nested-v1-rule",
        rule_version="1",
        security_id=security_id,
        market="SH",
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="nested-source",
        rule_source_version="2026-10",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=source_available_at or AS_OF - timedelta(hours=3),
        effective_from=effective_from or AS_OF - timedelta(hours=2),
        valid_until=valid_until or AS_OF + timedelta(hours=4),
    )


def _v2(
    *,
    security_id: str = "V3.REPOSITORY.SECURITY",
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
    source_available_at: datetime | None = None,
) -> ExecutionSubmissionRuleV2:
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=_v1(
            security_id=security_id,
            effective_from=effective_from,
            valid_until=valid_until,
            source_available_at=source_available_at,
        ),
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board="MAIN",
            price_tick=Decimal("0.01"),
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


def _bundle(
    *,
    v2: ExecutionSubmissionRuleV2 | None = None,
    bundle_version: str = "1",
    policy_version: str = "1",
    lag: int = 1,
    effective_from: datetime | None = None,
    valid_until: datetime | None = None,
    source_available_at: datetime | None = None,
) -> ExecutionSettlementBundleV3:
    nested = v2 or _v2()
    base = nested.execution_rule_v1
    available = source_available_at or AS_OF - timedelta(hours=1)
    policy = SettlementPolicyV1(
        policy_id="settlement-policy",
        policy_version=policy_version,
        security_id=base.security_id,
        market=base.market,
        board=base.board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=lag,
        bound_execution_rule_v2_hash=nested.content_hash,
        source_id="settlement-source",
        source_version="2026-10",
        source_hash="b" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=available,
        effective_from=effective_from or base.effective_from,
        valid_until=valid_until or base.valid_until,
    )
    return ExecutionSettlementBundleV3(
        bundle_id="settlement-package",
        bundle_version=bundle_version,
        execution_submission_v2=nested,
        settlement_policy_v1=policy,
    )


def _repository(*, recorded_at: datetime | None = None) -> DjangoAShareExecutionRuleRepository:
    return DjangoAShareExecutionRuleRepository(
        clock=_FixedClock(recorded_at or AS_OF - timedelta(minutes=1))
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v3_repository_stores_outer_identity_intersection_and_recorded_at() -> None:
    repository = _repository()
    base = _v2()
    bundle = _bundle(
        v2=base,
        effective_from=AS_OF - timedelta(hours=1),
        valid_until=AS_OF + timedelta(hours=1),
        source_available_at=AS_OF - timedelta(minutes=30),
    )

    imported = repository.import_settlement_bundles(bundles=(bundle,))
    repeated = repository.import_settlement_bundles(bundles=(bundle,))
    row = AShareExecutionRuleModel.objects.get(security_id=base.execution_rule_v1.security_id)
    result = ReadEffectiveExecutionSettlementV3UseCase(repository).execute(
        security_id=base.execution_rule_v1.security_id,
        as_of=AS_OF,
    )

    assert (imported.inserted_count, imported.unchanged_count) == (1, 0)
    assert (repeated.inserted_count, repeated.unchanged_count) == (0, 1)
    assert row.rule_id == bundle.bundle_id
    assert row.rule_version == bundle.bundle_version
    assert row.effective_from == bundle.effective_from
    assert row.valid_until == bundle.valid_until
    assert row.source_available_at == bundle.source_available_at
    assert row.canonical_payload == bundle.to_payload()
    assert result == bundle
    record = repository.get_effective_settlement_bundle(
        security_id=base.execution_rule_v1.security_id,
        as_of=AS_OF,
    )
    assert type(record) is ExecutionSettlementV3ReadRecord
    assert record.recorded_at == row.recorded_at


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v3_same_nested_v2_hash_versions_adjacent_policies_independently() -> None:
    repository = _repository()
    nested = _v2()
    base = nested.execution_rule_v1
    first = _bundle(
        v2=nested,
        bundle_version="1",
        policy_version="2",
        lag=2,
        effective_from=base.effective_from,
        valid_until=AS_OF,
    )
    second = _bundle(
        v2=nested,
        bundle_version="2",
        policy_version="1",
        lag=1,
        effective_from=AS_OF,
        valid_until=base.valid_until,
    )

    result = repository.import_settlement_bundles(bundles=(first, second))
    rows = tuple(AShareExecutionRuleModel.objects.order_by("effective_from"))
    active = ReadEffectiveExecutionSettlementV3UseCase(repository).execute(
        security_id=base.security_id,
        as_of=AS_OF,
    )

    assert result.inserted_count == 2
    assert first.execution_submission_v2.content_hash == second.execution_submission_v2.content_hash
    assert first.content_hash != second.content_hash
    assert [(row.rule_id, row.rule_version) for row in rows] == [
        (first.bundle_id, "1"),
        (second.bundle_id, "2"),
    ]
    assert rows[0].valid_until == rows[1].effective_from == AS_OF
    assert active == second


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v3_same_package_identity_rejects_changed_policy_content() -> None:
    repository = _repository()
    original = _bundle()
    changed = _bundle(lag=2)
    repository.import_settlement_bundles(bundles=(original,))

    with pytest.raises(ExecutionRuleConflict):
        repository.import_settlement_bundles(bundles=(changed,))

    assert AShareExecutionRuleModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v3_import_rejects_repeated_identity_inside_one_batch() -> None:
    repository = _repository()
    bundle = _bundle()

    with pytest.raises(ExecutionRuleInputError):
        repository.import_settlement_bundles(bundles=(bundle, bundle))

    assert AShareExecutionRuleModel.objects.count() == 0


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
@pytest.mark.parametrize(
    ("existing_schema", "v3_first"),
    [("v1", False), ("v1", True), ("v2", False), ("v2", True)],
)
def test_v3_overlapping_windows_conflict_across_schema_versions(
    existing_schema: str, v3_first: bool
) -> None:
    repository = _repository()
    nested = _v2()
    bundle = _bundle(v2=nested)
    if existing_schema == "v1":
        existing = _v1(security_id=nested.execution_rule_v1.security_id)
    else:
        existing = _v2(
            security_id=nested.execution_rule_v1.security_id,
            effective_from=AS_OF - timedelta(hours=1),
            valid_until=AS_OF + timedelta(hours=1),
        )

    if v3_first:
        repository.import_settlement_bundles(bundles=(bundle,))
        with pytest.raises(ExecutionRuleConflict):
            if existing_schema == "v1":
                repository.import_rules(rules=(existing,))
            else:
                repository.import_submission_rules(rules=(existing,))
    else:
        if existing_schema == "v1":
            repository.import_rules(rules=(existing,))
        else:
            repository.import_submission_rules(rules=(existing,))
        with pytest.raises(ExecutionRuleConflict):
            repository.import_settlement_bundles(bundles=(bundle,))

    assert AShareExecutionRuleModel.objects.count() == 1


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
@pytest.mark.parametrize("future_source", [False, True])
def test_v3_reader_hides_future_source_or_future_local_recording(future_source: bool) -> None:
    as_of = AS_OF
    if future_source:
        bundle = _bundle(source_available_at=AS_OF + timedelta(minutes=1))
        repository = _repository()
    else:
        bundle = _bundle()
        repository = _repository(recorded_at=AS_OF + timedelta(minutes=1))
    repository.import_settlement_bundles(bundles=(bundle,))

    with pytest.raises(ExecutionSettlementV3Unavailable):
        ReadEffectiveExecutionSettlementV3UseCase(repository).execute(
            security_id=bundle.settlement_policy_v1.security_id,
            as_of=as_of,
        )

    assert (
        ReadEffectiveExecutionSettlementV3UseCase(repository).execute(
            security_id=bundle.settlement_policy_v1.security_id,
            as_of=AS_OF + timedelta(minutes=2),
        )
        == bundle
    )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
@pytest.mark.parametrize("corrupt_column", [False, True])
def test_v3_reader_rejects_payload_or_lookup_column_tampering(corrupt_column: bool) -> None:
    repository = _repository()
    bundle = _bundle()
    repository.import_settlement_bundles(bundles=(bundle,))
    row = AShareExecutionRuleModel.objects.get(content_hash=bundle.content_hash)
    if corrupt_column:
        AShareExecutionRuleModel.objects.filter(pk=row.pk).update(
            effective_from=row.effective_from - timedelta(seconds=1)
        )
    else:
        payload = dict(row.canonical_payload)
        payload["bundle_version"] = "tampered"
        AShareExecutionRuleModel.objects.filter(pk=row.pk).update(canonical_payload=payload)

    with pytest.raises(ExecutionRuleCorruption):
        repository.get_effective_settlement_bundle(
            security_id=bundle.settlement_policy_v1.security_id,
            as_of=AS_OF,
        )


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_v1_and_v2_readers_reject_v3_rows_without_unwrapping() -> None:
    repository = _repository()
    bundle = _bundle()
    repository.import_settlement_bundles(bundles=(bundle,))
    security_id = bundle.settlement_policy_v1.security_id

    with pytest.raises(ExecutionRuleVersionMismatch):
        repository.get_effective_rule(security_id=security_id, as_of=AS_OF)
    with pytest.raises(ExecutionRuleVersionMismatch):
        repository.get_effective_submission_rule(security_id=security_id, as_of=AS_OF)


@pytest.mark.django_db(transaction=True, available_apps=["apps.risk_center"])
def test_retirement_header_targets_v3_package_then_allows_new_rollback_version() -> None:
    repository = _repository()
    nested = _v2()
    base = nested.execution_rule_v1
    retired_bundle = _bundle(
        v2=nested,
        bundle_version="2",
        policy_version="2",
        lag=2,
        effective_from=base.effective_from,
        valid_until=base.valid_until,
    )
    repository.import_settlement_bundles(bundles=(retired_bundle,))
    intent = AShareExecutionRuleRetirementIntent(
        security_id=base.security_id,
        rule_id=retired_bundle.bundle_id,
        rule_version=retired_bundle.bundle_version,
        expected_content_hash=retired_bundle.content_hash,
        request_id=UUID("43339eb8-a6df-4a96-91ef-174c562f119b"),
        effective_at=AS_OF,
        reason_code="policy-rollback",
    )
    authorization = AShareExecutionRuleRetirementAuthorization(
        actor_type="test_operator",
        actor_id="rule-admin",
        scope_tenant_id="test-tenant",
        scope_owner_id="test-owner",
    )

    with repository.retirement_transaction(security_id=base.security_id):
        target = repository.get_retirement_target(intent=intent)
        assert target.rule_id == retired_bundle.bundle_id
        assert target.rule_version == retired_bundle.bundle_version
        assert target.effective_from == retired_bundle.effective_from
        assert target.valid_until == retired_bundle.valid_until
        evidence = build_retirement_evidence(
            target=target,
            intent=intent,
            authorization=authorization,
            recorded_at=AS_OF - timedelta(minutes=1),
        )
        repository.persist_retirement(intent=intent, evidence=evidence)

    rollback_bundle = _bundle(
        v2=nested,
        bundle_version="3",
        policy_version="1",
        lag=1,
        effective_from=AS_OF,
        valid_until=base.valid_until,
    )
    imported = repository.import_settlement_bundles(bundles=(rollback_bundle,))

    assert imported.inserted_count == 1
    assert (
        ReadEffectiveExecutionSettlementV3UseCase(repository).execute(
            security_id=base.security_id,
            as_of=AS_OF,
        )
        == rollback_bundle
    )
