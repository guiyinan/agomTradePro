"""Component coverage for the append-only Portfolio R4 rolling ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.portfolio.application.r4_rolling_research_record import R4RollingResearchDraft
from apps.portfolio.domain.macro_risk_rolling_contracts import R4RollingStudyInput
from apps.portfolio.infrastructure.r4_rolling_research_models import (
    R4RollingResearchReceiptModel,
    R4RollingResearchResultModel,
    _r4_repository_append_unit,
)
from apps.portfolio.infrastructure.r4_rolling_research_query import (
    DjangoR4RollingResearchExactQuery,
)
from apps.portfolio.infrastructure.r4_rolling_research_repository import (
    DjangoR4RollingResearchRepository,
)
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)

EVALUATED_AT = datetime(2026, 3, 15, tzinfo=UTC)
RECORDED_AT = EVALUATED_AT + timedelta(minutes=1)
VALID_UNTIL = datetime(2026, 3, 31, tzinfo=UTC)
DEPENDENCY_LOCK_HASH = "a" * 64


class FixedClock:
    """Deterministic repository-owned clock with an observable call count."""

    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        """Return the configured server time."""

        self.calls += 1
        return self.value


def _draft(
    *,
    study: R4RollingStudyInput | None = None,
    valid_until: datetime = VALID_UNTIL,
    producer_code_version: str = "git:r4-code-v1",
    dependency_lock_hash: str = DEPENDENCY_LOCK_HASH,
) -> R4RollingResearchDraft:
    return R4RollingResearchDraft(
        study=study or build_study(),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
        producer_code_version=producer_code_version,
        dependency_lock_hash=dependency_lock_hash,
        valid_until=valid_until,
    )


@pytest.mark.django_db
def test_record_round_trip_is_exact_and_retry_returns_server_clock_winner() -> None:
    clock = FixedClock(RECORDED_AT)
    repository = DjangoR4RollingResearchRepository(clock)
    draft = _draft()

    first = repository.append(draft)
    replay = repository.append(draft)

    assert replay == first
    assert repository.get(first.record_id) == first
    assert first.recorded_at == RECORDED_AT
    assert first.owner == "portfolio"
    assert first.study_id == draft.study.study_id
    assert first.study_version == draft.study.study_version
    assert first.study_content_hash == draft.study.content_hash
    assert first.artifact_hash == first.artifact.content_hash
    assert first.r3_promotion_attestation_hash == draft.promotion_attestation.content_hash
    assert first.split_contract_hash == draft.study.split_contract_hash
    assert first.producer_code_version == draft.producer_code_version
    assert first.dependency_lock_hash == draft.dependency_lock_hash
    assert first.valid_until == VALID_UNTIL
    assert clock.calls == 1
    assert R4RollingResearchReceiptModel._default_manager.count() == 1
    assert R4RollingResearchResultModel._default_manager.count() == 1


@pytest.mark.django_db
def test_same_logical_identity_with_different_study_content_is_rejected() -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))
    repository.append(_draft())
    changed = build_study(minimum_regime_windows=3)

    with pytest.raises(ValueError, match="conflicts with different evidence"):
        repository.append(_draft(study=changed))


@pytest.mark.django_db
def test_same_artifact_with_distinct_reproducibility_environments_can_coexist() -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))

    first = repository.append(_draft())
    second = repository.append(
        _draft(
            producer_code_version="git:r4-code-v2",
            dependency_lock_hash="b" * 64,
        )
    )

    assert first.artifact_hash == second.artifact_hash
    assert first.record_id != second.record_id
    assert first.record_hash != second.record_hash
    assert R4RollingResearchReceiptModel._default_manager.count() == 2
    assert R4RollingResearchResultModel._default_manager.count() == 2


@pytest.mark.django_db
def test_default_base_related_and_bulk_conflict_paths_are_append_only() -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))
    record = repository.append(_draft())
    receipt = R4RollingResearchReceiptModel._default_manager.get(pk=record.record_id)
    result = R4RollingResearchResultModel._default_manager.get(pk=record.record_id)

    for manager, row in (
        (R4RollingResearchReceiptModel._default_manager, receipt),
        (R4RollingResearchReceiptModel._base_manager, receipt),
        (R4RollingResearchResultModel._default_manager, result),
        (R4RollingResearchResultModel._base_manager, result),
    ):
        with pytest.raises(ValidationError, match="cannot be updated"):
            manager.filter(pk=row.pk).update(record_hash="0" * 64)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError, match="bulk updated"):
            manager.bulk_update([row], [row._meta.pk.name])
        with pytest.raises(ValidationError, match="cannot be bulk created"):
            manager.all().bulk_create([type(row)()])
        with pytest.raises(ValidationError, match="cannot be bulk created"):
            manager.all().bulk_create([type(row)()], ignore_conflicts=True)
        with pytest.raises(ValidationError, match="cannot be bulk created"):
            manager.all().bulk_create(
                [type(row)()],
                update_conflicts=True,
                update_fields=[row._meta.pk.name],
                unique_fields=[row._meta.pk.name],
            )

    related = receipt.results
    with pytest.raises(ValidationError, match="cannot be updated"):
        related.all().update(record_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        related.all().delete()
    with pytest.raises(ValidationError, match="bulk updated"):
        related.bulk_update([result], ["artifact_hash"])
    with pytest.raises(ValidationError, match="cannot be bulk created"):
        related.bulk_create([R4RollingResearchResultModel()])
    with pytest.raises(ValidationError, match="cannot be bulk created"):
        related.bulk_create([R4RollingResearchResultModel()], ignore_conflicts=True)
    with pytest.raises(ValidationError, match="repository unit of work"):
        receipt.save()
    with pytest.raises(ValidationError, match="repository unit of work"):
        result.save()
    with pytest.raises(ValidationError, match="append-only"):
        result.delete()


@pytest.mark.django_db
def test_direct_save_rejects_owner_clock_bounds_server_clock_and_missing_uow() -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))
    record = repository.append(_draft())
    source = R4RollingResearchReceiptModel._default_manager.get(pk=record.record_id)

    def receipt(**changes: object) -> R4RollingResearchReceiptModel:
        values: dict[str, object] = {
            "receipt_id": f"direct:{changes.get('suffix', 'test')}",
            "record_version": source.record_version,
            "study_id": source.study_id,
            "study_version": source.study_version,
            "study_content_hash": source.study_content_hash,
            "r3_promotion_attestation_hash": source.r3_promotion_attestation_hash,
            "split_contract_hash": source.split_contract_hash,
            "evaluated_at": source.evaluated_at,
            "owner": source.owner,
            "recorded_at": source.recorded_at,
            "producer_code_version": source.producer_code_version,
            "dependency_lock_hash": source.dependency_lock_hash,
            "valid_until": source.valid_until,
            "study_payload": source.study_payload,
            "promotion_attestation_payload": source.promotion_attestation_payload,
        }
        values.update({key: value for key, value in changes.items() if key != "suffix"})
        return R4RollingResearchReceiptModel(**values)

    with pytest.raises(ValidationError, match="owner must be portfolio"):
        receipt(suffix="owner", owner="research").save(force_insert=True)
    with pytest.raises(ValidationError, match="clock bounds are invalid"):
        receipt(
            suffix="stale",
            recorded_at=EVALUATED_AT - timedelta(microseconds=1),
        ).save(force_insert=True)
    with pytest.raises(ValidationError, match="clock bounds are invalid"):
        receipt(suffix="expired", recorded_at=VALID_UNTIL).save(force_insert=True)
    with pytest.raises(ValidationError, match="repository unit of work"):
        receipt(suffix="uow").save(force_insert=True)
    with _r4_repository_append_unit(RECORDED_AT + timedelta(seconds=1)):
        with pytest.raises(ValidationError, match="repository server clock"):
            receipt(suffix="clock").save(force_insert=True)


@pytest.mark.django_db
def test_concurrent_lookup_miss_returns_first_persisted_clock_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))
    draft = _draft()
    winner = first_repository.append(draft)
    manager = R4RollingResearchResultModel._default_manager
    original_filter = manager.filter
    first_call = True

    def first_lookup_misses(*args: object, **kwargs: object):
        nonlocal first_call
        queryset = original_filter(*args, **kwargs)
        if first_call:
            first_call = False
            return queryset.none()
        return queryset

    monkeypatch.setattr(manager, "filter", first_lookup_misses)
    losing_clock = FixedClock(RECORDED_AT + timedelta(minutes=5))
    replay = DjangoR4RollingResearchRepository(losing_clock).append(draft)

    assert replay == winner
    assert replay.recorded_at == RECORDED_AT
    assert losing_clock.calls == 1
    assert R4RollingResearchResultModel._default_manager.count() == 1


@pytest.mark.django_db
def test_result_failure_rolls_back_receipt_and_expired_server_clock_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))

    def fail_save(self, *args: object, **kwargs: object) -> None:
        raise ValidationError("fault injection")

    monkeypatch.setattr(R4RollingResearchResultModel, "save", fail_save)
    with pytest.raises(ValueError, match="invalid R4 rolling research record"):
        repository.append(_draft())
    assert R4RollingResearchReceiptModel._default_manager.count() == 0
    assert R4RollingResearchResultModel._default_manager.count() == 0

    expired = DjangoR4RollingResearchRepository(FixedClock(VALID_UNTIL))
    with pytest.raises(ValueError, match="invalid R4 rolling research record"):
        expired.append(_draft())
    assert R4RollingResearchReceiptModel._default_manager.count() == 0


@pytest.mark.django_db
def test_raw_header_tamper_is_detected_on_restore() -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))
    record = repository.append(_draft())
    query = DjangoR4RollingResearchExactQuery(repository)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_r4_rolling_research_receipt "
            "SET study_content_hash = %s WHERE receipt_id = %s",
            ["9" * 64, record.record_id],
        )
    with pytest.raises(ValueError, match="receipt metadata or payload mismatch"):
        query.get_exact(
            record_id=record.record_id,
            expected_record_hash=record.record_hash,
            as_of=RECORDED_AT,
        )


@pytest.mark.django_db
def test_exact_query_enforces_hash_knowledge_time_and_strict_expiry() -> None:
    repository = DjangoR4RollingResearchRepository(FixedClock(RECORDED_AT))
    record = repository.append(_draft())
    query = DjangoR4RollingResearchExactQuery(repository)

    envelope = query.get_exact(
        record_id=record.record_id,
        expected_record_hash=record.record_hash,
        as_of=RECORDED_AT,
    )

    assert envelope is not None
    assert envelope.record == record
    assert query.unit_of_work_key == "django:default"
    assert (
        query.get_exact(
            record_id=record.record_id,
            expected_record_hash="0" * 64,
            as_of=RECORDED_AT,
        )
        is None
    )
    assert (
        query.get_exact(
            record_id=record.record_id,
            expected_record_hash=record.record_hash,
            as_of=RECORDED_AT - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        query.get_exact(
            record_id=record.record_id,
            expected_record_hash=record.record_hash,
            as_of=record.valid_until,
        )
        is None
    )
