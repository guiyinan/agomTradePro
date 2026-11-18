"""Pure TDD contracts for the Owner-only exact-code collection-scope repair."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from apps.data_center.application.asset_active_maintenance import (
    AssetActiveMaintenance,
    AssetActiveMaintenanceError,
)
from apps.data_center.domain.asset_active_maintenance import (
    AssetMaintenanceTarget,
    AssetMasterMaintenancePlan,
    AssetMasterRowSnapshot,
    MaintenanceAuditObservation,
    MaintenanceAuditReceipt,
    MaintenanceAuthorityContext,
    MaintenanceOwner,
    SourceOccurrencePin,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
)

UTC_NOW = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)
FIELDS = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)
CODE_EXCHANGE = (
    ("000016.SZ", "SZSE", "SZ"),
    ("002731.SZ", "SZSE", "SZ"),
    ("301139.SZ", "SZSE", "SZ"),
    ("601059.SH", "SSE", "SH"),
    ("601198.SH", "SSE", "SH"),
)


def _source() -> InstrumentReferenceCandidate:
    contract = InstrumentReferenceProviderContract(
        contract_id="tushare.stock_basic",
        contract_version="v1",
        provider_name="tushare",
        dataset_key="tushare.stock_basic.reference",
        api_name="stock_basic",
        fields=FIELDS,
        exchange_scope=("SSE", "SZSE"),
        list_status_scope=("D",),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="test.crosswalk",
        crosswalk_version="v1",
        exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
    )
    audit_refs = (
        RawAuditReference(
            "101",
            "1",
            "a" * 64,
            "0f84554d-6341-43f9-b4dd-1eaed9d39d00",
            "205ab56d-9f75-487b-996e-7e7b1c86d2e1",
        ),
        RawAuditReference(
            "102",
            "1",
            "b" * 64,
            "0f84554d-6341-43f9-b4dd-1eaed9d39d00",
            "205ab56d-9f75-487b-996e-7e7b1c86d2e1",
        ),
    )
    occurrence_ids = (
        UUID("d805500e-c59c-4b89-b07b-fb605c54ffb1"),
        UUID("fa3f7e75-87b2-4e43-8744-93179fa94870"),
    )
    exchanges = ("SSE", "SZSE")
    occurrences: list[InstrumentReferenceOccurrence] = []
    records: list[InstrumentReferenceRecord] = []
    for index, exchange in enumerate(exchanges):
        selected = tuple(item for item in CODE_EXCHANGE if item[1] == exchange)
        occurrences.append(
            InstrumentReferenceOccurrence(
                occurrence_id=occurrence_ids[index],
                exchange=exchange,
                list_status="D",
                raw_audit_reference=audit_refs[index],
                raw_payload_id=f"payload-{index + 1}",
                raw_payload_hash=f"sha256:{(str(index + 1) * 64)}",
                response_body_sha256=("c" if index == 0 else "d") * 64,
                response_completed_at=UTC_NOW - timedelta(minutes=index + 1),
                row_count=len(selected),
            )
        )
        occurrence = occurrences[-1]
        for code, row_exchange, suffix in selected:
            records.append(
                InstrumentReferenceRecord(
                    ts_code=code,
                    name=f"Source name {code}",
                    source_exchange=row_exchange,
                    source_market="",
                    source_list_status="D",
                    list_date_raw=None,
                    list_date=None,
                    delist_date_raw="20261019",
                    delist_date=date(2026, 10, 19),
                    exchange_suffix=suffix,
                    occurrence_id=occurrence.occurrence_id,
                    raw_audit_reference=occurrence.raw_audit_reference,
                    raw_payload_id=occurrence.raw_payload_id,
                    raw_payload_hash=occurrence.raw_payload_hash,
                )
            )
    return InstrumentReferenceCandidate(
        provider_contract=contract,
        crosswalk=crosswalk,
        occurrences=tuple(occurrences),
        records=tuple(records),
    )


def _plan(source: InstrumentReferenceCandidate | None = None) -> AssetMasterMaintenancePlan:
    candidate = source or _source()
    pins = tuple(
        SourceOccurrencePin(
            exchange=item.exchange,
            raw_audit_reference=item.raw_audit_reference,
            raw_payload_id=item.raw_payload_id,
            raw_payload_hash=item.raw_payload_hash,
            response_body_sha256=item.response_body_sha256,
            response_completed_at=item.response_completed_at,
            row_count=item.row_count,
        )
        for item in candidate.occurrences
    )
    return AssetMasterMaintenancePlan(
        plan_file_sha256="e" * 64,
        target_date=date(2026, 11, 17),
        targets=tuple(
            AssetMaintenanceTarget(
                code=code,
                asset_pk=index,
                exchange=exchange,
                expected_delist_date=None,
                expected_updated_at=UTC_NOW - timedelta(days=4),
                expected_preserved_state_sha256=f"{index:064x}",
            )
            for index, (code, exchange, _suffix) in enumerate(CODE_EXCHANGE, start=1)
        ),
        provider_contract=candidate.provider_contract,
        crosswalk=candidate.crosswalk,
        source_occurrences=pins,
    )


def _states(plan: AssetMasterMaintenancePlan) -> tuple[AssetMasterRowSnapshot, ...]:
    return tuple(
        AssetMasterRowSnapshot(
            asset_pk=target.asset_pk,
            code=target.code,
            asset_type="stock",
            exchange=target.exchange,
            is_active=True,
            delist_date=None,
            updated_at=target.expected_updated_at,
            preserved_state_sha256=target.expected_preserved_state_sha256,
        )
        for target in sorted(plan.targets, key=lambda item: item.asset_pk)
    )


class FakeSourceReader:
    unit_of_work_key = "django:default"

    def __init__(self, candidate: InstrumentReferenceCandidate) -> None:
        self.candidate = candidate
        self.reads = 0

    def read_verified(self, plan: AssetMasterMaintenancePlan) -> InstrumentReferenceCandidate:
        self.reads += 1
        return self.candidate


class FakeRepository:
    unit_of_work_key = "django:default"

    def __init__(self, states: tuple[AssetMasterRowSnapshot, ...]) -> None:
        self.states = list(states)
        self.updated: list[tuple[int, str, date, datetime]] = []

    def lock_exact_targets(
        self, targets: tuple[AssetMaintenanceTarget, ...]
    ) -> tuple[AssetMasterRowSnapshot, ...]:
        return tuple(sorted(self.states, key=lambda item: item.asset_pk))

    def deactivate_exact_targets(
        self,
        transitions: tuple[object, ...],
    ) -> int:
        changed = 0
        for transition in transitions:
            for index, state in enumerate(self.states):
                if (
                    state.asset_pk == transition.asset_pk
                    and state.code == transition.code
                    and state.is_active
                ):
                    self.states[index] = replace(
                        state,
                        is_active=False,
                        delist_date=transition.source_delist_date,
                        updated_at=transition.updated_at,
                    )
                    self.updated.append(
                        (
                            transition.asset_pk,
                            transition.code,
                            transition.source_delist_date,
                            transition.updated_at,
                        )
                    )
                    changed += 1
        return changed

    def read_exact_targets(
        self, targets: tuple[AssetMaintenanceTarget, ...]
    ) -> tuple[AssetMasterRowSnapshot, ...]:
        return tuple(sorted(self.states, key=lambda item: item.asset_pk))


class FakeUnitOfWork:
    unit_of_work_key = "django:default"

    def __init__(self, repository: FakeRepository, audit: FakeAuditPort) -> None:
        self.repository = repository
        self.audit = audit

    @contextmanager
    def atomic(self) -> Iterator[None]:
        original = list(self.repository.states)
        original_updates = list(self.repository.updated)
        original_receipt = self.audit.receipt
        original_observations = list(self.audit.observations)
        try:
            yield
        except BaseException:
            self.repository.states = original
            self.repository.updated = original_updates
            self.audit.receipt = original_receipt
            self.audit.observations = original_observations
            raise


class FakeOwnerPort:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.owner = MaintenanceOwner(
            user_id=7,
            username="real-owner",
            actor_id="django-user:7",
            is_authenticated=True,
            is_active=True,
            can_change_assetmaster=True,
        )

    def current_owner(self) -> MaintenanceOwner:
        return self.owner

    def is_current(self, expected: MaintenanceOwner) -> bool:
        return self.allowed and expected == self.owner


class FakeAuthorityPort:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed

    def current_context(
        self, owner: MaintenanceOwner, *, as_of: datetime
    ) -> MaintenanceAuthorityContext:
        return MaintenanceAuthorityContext(
            actor_id=owner.actor_id,
            user_id=owner.user_id,
            tenant_id="tenant-1",
            owner_id="owner-1",
            authority_content_hash="b" * 64,
            valid_until=as_of + timedelta(hours=1),
        )

    def is_current(self, context: MaintenanceAuthorityContext, *, as_of: datetime) -> bool:
        return self.allowed and as_of.tzinfo is not None


class FakeAuditPort:
    unit_of_work_key = "django:default"

    def __init__(self, owner_port: FakeOwnerPort, authority_port: FakeAuthorityPort) -> None:
        self.receipt: MaintenanceAuditReceipt | None = None
        self.observations: list[MaintenanceAuditObservation] = []
        self.fail_record = False
        self.revoke_owner_after_record = False
        self.revoke_authority_after_record = False
        self.owner_port = owner_port
        self.authority_port = authority_port

    def find_exact(self, plan_digest: str) -> MaintenanceAuditReceipt | None:
        if self.receipt is not None and self.receipt.plan_digest != plan_digest:
            raise AssetActiveMaintenanceError("audit_idempotency_conflict")
        return self.receipt

    def record_once(self, observation: MaintenanceAuditObservation) -> MaintenanceAuditReceipt:
        if self.fail_record:
            raise RuntimeError("audit unavailable")
        self.observations.append(observation)
        self.receipt = MaintenanceAuditReceipt(
            plan_digest=observation.plan_digest,
            plan_file_sha256=observation.plan_file_sha256,
            actor_id=observation.actor.actor_id,
            tenant_id=observation.authority.tenant_id,
            owner_id=observation.authority.owner_id,
            authority_content_hash=observation.authority.authority_content_hash,
            provider_contract_hash=observation.provider_contract.content_hash,
            crosswalk_hash=observation.crosswalk.content_hash,
            plan_metadata=observation.plan_metadata,
            source_occurrences=observation.source_occurrences,
            transitions=observation.transitions,
            event_id=f"asset-scope-maintenance:{observation.plan_digest}",
            event_content_sha256="a" * 64,
            outbox_id=UUID("6fbf5e95-6a23-47eb-9d1f-3418e58273ed"),
            recorded_at=observation.occurred_at,
        )
        if self.revoke_owner_after_record:
            self.owner_port.allowed = False
        if self.revoke_authority_after_record:
            self.authority_port.allowed = False
        return self.receipt


class FixedClock:
    def now(self) -> datetime:
        return UTC_NOW


def _use_case(
    *,
    candidate: InstrumentReferenceCandidate | None = None,
    states: tuple[AssetMasterRowSnapshot, ...] | None = None,
    owner_allowed: bool = True,
    authority_allowed: bool = True,
) -> tuple[AssetActiveMaintenance, FakeRepository, FakeSourceReader, FakeAuditPort]:
    source_candidate = candidate or _source()
    plan = _plan(source_candidate)
    repository = FakeRepository(states or _states(plan))
    source_reader = FakeSourceReader(source_candidate)
    owner_port = FakeOwnerPort(allowed=owner_allowed)
    authority_port = FakeAuthorityPort(allowed=authority_allowed)
    audit = FakeAuditPort(owner_port, authority_port)
    return (
        AssetActiveMaintenance(
            source_reader=source_reader,
            owner_port=owner_port,
            authority_port=authority_port,
            repository=repository,
            unit_of_work=FakeUnitOfWork(repository, audit),
            audit=audit,
            clock=FixedClock(),
        ),
        repository,
        source_reader,
        audit,
    )


def test_valid_source_stops_only_plan_targets_and_records_one_user_audit() -> None:
    source = _source()
    plan = _plan(source)
    use_case, repository, reader, audit = _use_case(candidate=source)

    result = use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert result.outcome == "success"
    assert result.requested == result.succeeded == result.stored == 5
    assert len(repository.updated) == 5
    assert len(audit.observations) == 1
    assert audit.observations[0].actor.actor_id == "django-user:7"
    assert len(audit.observations[0].source_occurrences) == 2
    assert all(not state.is_active for state in repository.states)
    assert reader.reads == 2
    assert source.must_not_use_for_decision is True
    assert source.must_not_execute is True


def test_source_missing_exact_plan_record_blocks_without_deactivating() -> None:
    candidate = _source()
    with pytest.raises(ValueError):
        replace(candidate, records=candidate.records[:-1])


def test_source_date_after_target_or_non_d_status_blocks() -> None:
    source = _source()
    records = tuple(
        replace(record, delist_date=date(2026, 11, 18), delist_date_raw="20261118")
        for record in source.records
    )
    candidate = replace(source, records=records)
    plan = _plan(candidate)
    use_case, repository, _reader, _audit = _use_case(candidate=candidate)

    with pytest.raises(AssetActiveMaintenanceError):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)
    assert repository.updated == []


def test_owner_permission_and_data02_authority_are_rechecked_before_any_write() -> None:
    plan = _plan()
    for owner_allowed, authority_allowed in ((False, True), (True, False)):
        use_case, repository, _reader, _audit = _use_case(
            owner_allowed=owner_allowed, authority_allowed=authority_allowed
        )
        with pytest.raises(AssetActiveMaintenanceError):
            use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)
        assert repository.updated == []


def test_wrong_asset_pk_or_exchange_blocks_before_dml() -> None:
    plan = _plan()
    states = list(_states(plan))
    states[0] = replace(states[0], asset_pk=99)
    use_case, repository, _reader, _audit = _use_case(states=tuple(states))

    with pytest.raises(AssetActiveMaintenanceError):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert repository.updated == []


def test_audit_failure_rolls_back_all_five_master_updates() -> None:
    plan = _plan()
    use_case, repository, _reader, audit = _use_case()
    audit.fail_record = True

    with pytest.raises(RuntimeError, match="audit unavailable"):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert repository.updated == []
    assert all(state.is_active for state in repository.states)


def test_exact_replay_is_noop_but_unrecorded_inactive_state_blocks() -> None:
    plan = _plan()
    use_case, repository, _reader, audit = _use_case()
    use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)
    first_updates = list(repository.updated)

    replay = use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert replay.outcome == "noop"
    assert repository.updated == first_updates
    assert len(audit.observations) == 1

    unrecorded, inactive_repo, _reader2, _audit2 = _use_case()
    inactive_repo.states = [
        replace(state, is_active=False, delist_date=date(2026, 10, 19))
        for state in inactive_repo.states
    ]
    with pytest.raises(AssetActiveMaintenanceError, match="asset_target_preimage_changed"):
        unrecorded.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)


def test_plan_hash_mismatch_blocks_before_source_or_repository_access() -> None:
    plan = _plan()
    use_case, repository, reader, _audit = _use_case()

    with pytest.raises(AssetActiveMaintenanceError, match="plan_hash_mismatch"):
        use_case.execute(plan, expected_plan_file_sha256="f" * 64)

    assert reader.reads == 0
    assert repository.updated == []


@pytest.mark.parametrize("field", ("updated_at", "preserved_state_sha256"))
def test_reviewed_preimage_drift_blocks_before_any_mutation(field: str) -> None:
    plan = _plan()
    states = list(_states(plan))
    states[0] = replace(states[0], **{field: (UTC_NOW if field == "updated_at" else "f" * 64)})
    use_case, repository, _reader, _audit = _use_case(states=tuple(states))

    with pytest.raises(AssetActiveMaintenanceError, match="asset_target_preimage_changed"):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert repository.updated == []


def test_future_target_date_is_rejected_before_owner_or_source_access() -> None:
    plan = replace(_plan(), target_date=date(2026, 11, 19))
    use_case, repository, reader, _audit = _use_case()

    with pytest.raises(AssetActiveMaintenanceError, match="target_date_in_future"):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert reader.reads == 0
    assert repository.updated == []


def test_future_owner_reviewed_preimage_clock_is_rejected_before_source_access() -> None:
    plan = _plan()
    future_target = replace(plan.targets[0], expected_updated_at=UTC_NOW + timedelta(minutes=1))
    future_plan = replace(plan, targets=(future_target, *plan.targets[1:]))
    use_case, repository, reader, _audit = _use_case()

    with pytest.raises(AssetActiveMaintenanceError, match="asset_preimage_clock_from_future"):
        use_case.execute(future_plan, expected_plan_file_sha256=future_plan.plan_file_sha256)

    assert reader.reads == 0
    assert repository.updated == []


def test_future_response_clock_is_rejected_before_source_replay() -> None:
    source = _source()
    future_occurrences = tuple(
        replace(item, response_completed_at=UTC_NOW + timedelta(minutes=1))
        for item in source.occurrences
    )
    future_source = replace(source, occurrences=future_occurrences)
    plan = _plan(future_source)
    use_case, repository, reader, _audit = _use_case(candidate=future_source)

    with pytest.raises(AssetActiveMaintenanceError, match="source_response_from_future"):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert reader.reads == 0
    assert repository.updated == []


@pytest.mark.parametrize("revoked", ("owner", "authority"))
def test_authority_and_owner_are_rechecked_after_audit_before_commit(revoked: str) -> None:
    plan = _plan()
    use_case, repository, _reader, audit = _use_case()
    if revoked == "owner":
        audit.revoke_owner_after_record = True
        expected_code = "owner_authentication_or_permission_changed"
    else:
        audit.revoke_authority_after_record = True
        expected_code = "data02_authority_changed_or_expired"

    with pytest.raises(AssetActiveMaintenanceError, match=expected_code):
        use_case.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)

    assert repository.updated == []
    assert all(state.is_active for state in repository.states)
    assert audit.receipt is None
    assert audit.observations == []
