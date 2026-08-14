"""Component coverage for planning-policy activation persistence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.application.planning_policy_activation import (
    PlanningPolicyActivationConflict,
    PlanningPolicyActivationCorruption,
    PlanningPolicyActivationUnavailable,
)
from apps.portfolio.domain.planning_policy_activation import (
    PlanningPolicyActivation,
    PlanningPolicyActivationActor,
    PlanningPolicyActivationSubject,
)
from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition
from apps.portfolio.infrastructure.planning_policy_activation_codec import (
    PlanningPolicyActivationCodecError,
    decode_planning_policy_activation,
    decode_planning_policy_activation_subject,
    encode_planning_policy_activation,
    encode_planning_policy_activation_subject,
)
from apps.portfolio.infrastructure.planning_policy_activation_models import (
    _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW,
    PortfolioPlanningPolicyActivationModel,
    PortfolioPlanningPolicyActivationSubjectModel,
    _claim_planning_policy_activation_insert,
)
from apps.portfolio.infrastructure.planning_policy_activation_repository import (
    DjangoPlanningPolicyActivationRepository,
    _activation_values,
    _subject_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
DEFINITION_AT = NOW - timedelta(hours=1)
VALID_UNTIL = NOW + timedelta(days=30)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _definition(**changes: object) -> PlanningPolicyDefinition:
    values: dict[str, object] = {
        "policy_id": "portfolio-policy-standard",
        "policy_version": "v1",
        "buy_lot_size": 100,
        "fee_rate": Decimal("0.0003"),
        "slippage_rate": Decimal("0.001"),
        "min_rebalance_value": Decimal("1000"),
        "max_asset_weight": Decimal("0.2"),
        "max_volume_participation": Decimal("0.1"),
        "recorded_at": DEFINITION_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PlanningPolicyDefinition(**values)  # type: ignore[arg-type]


def _actor(number: int) -> PlanningPolicyActivationActor:
    return PlanningPolicyActivationActor(
        actor_id=f"portfolio-staff-{number}",
        user_id=number,
        role="portfolio_policy_approver",
    )


def _subject(**changes: object) -> PlanningPolicyActivationSubject:
    values: dict[str, object] = {
        "subject_id": "activation-request-1",
        "subject_version": "v1",
        "definition": _definition(),
        "requested_by": _actor(11),
        "requested_at": NOW,
        "supersedes_activation_hash": None,
    }
    values.update(changes)
    return PlanningPolicyActivationSubject.create(**values)  # type: ignore[arg-type]


def _activation(**changes: object) -> PlanningPolicyActivation:
    values: dict[str, object] = {
        "activation_id": "activation-1",
        "activation_version": "v1",
        "subject": _subject(),
        "approved_by": _actor(12),
        "issued_at": NOW,
    }
    values.update(changes)
    return PlanningPolicyActivation.create(**values)  # type: ignore[arg-type]


def _persist_root(
    repository: DjangoPlanningPolicyActivationRepository,
) -> PlanningPolicyActivation:
    subject = _subject()
    activation = _activation(subject=subject)
    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=NOW) == subject
        return repository.append(
            activation,
            expected_predecessor_hash=None,
            recorded_at=NOW,
        )


def _successor(
    previous: PlanningPolicyActivation,
    *,
    number: int = 2,
    requested_at: datetime | None = None,
    valid_until: datetime = VALID_UNTIL,
) -> tuple[PlanningPolicyActivationSubject, PlanningPolicyActivation]:
    request_time = requested_at or NOW + timedelta(hours=1)
    definition = _definition(
        policy_version=f"v{number}",
        fee_rate=Decimal("0.0004"),
        valid_until=valid_until,
    )
    subject = _subject(
        subject_id=f"activation-request-{number}",
        subject_version=f"v{number}",
        definition=definition,
        requested_at=request_time,
        supersedes_activation_hash=previous.content_hash,
    )
    activation = _activation(
        activation_id=f"activation-{number}",
        activation_version=f"v{number}",
        subject=subject,
        issued_at=request_time,
    )
    return subject, activation


@pytest.mark.django_db(transaction=True)
def test_subject_and_activation_first_winner_codec_and_pit_roundtrip() -> None:
    clock = FixedClock(NOW)
    repository = DjangoPlanningPolicyActivationRepository(clock=clock)
    activation = _persist_root(repository)

    with repository.atomic():
        assert repository.append_subject(activation.subject, recorded_at=NOW) == activation.subject
        assert (
            repository.append(
                activation,
                expected_predecessor_hash=None,
                recorded_at=NOW,
            )
            == activation
        )
    assert PortfolioPlanningPolicyActivationSubjectModel._default_manager.count() == 1
    assert PortfolioPlanningPolicyActivationModel._default_manager.count() == 1
    assert (
        decode_planning_policy_activation_subject(
            encode_planning_policy_activation_subject(activation.subject)
        )
        == activation.subject
    )
    assert (
        decode_planning_policy_activation(encode_planning_policy_activation(activation))
        == activation
    )
    assert (
        repository.get_subject_winner(
            subject_id=activation.subject.subject_id,
            subject_version=activation.subject.subject_version,
            as_of=NOW,
        )
        == activation.subject
    )
    assert (
        repository.get_activation_winner(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            as_of=NOW,
        )
        == activation
    )
    assert (
        repository.get_current_head(policy_id=activation.subject.policy_id, as_of=NOW) == activation
    )


@pytest.mark.django_db(transaction=True)
def test_pit_boundaries_future_and_naive_cutoffs_fail_closed() -> None:
    clock = FixedClock(VALID_UNTIL)
    repository = DjangoPlanningPolicyActivationRepository(clock=clock)
    activation = _persist_root(repository)

    assert (
        repository.get_activation_winner(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        repository.get_current_head(policy_id=activation.subject.policy_id, as_of=VALID_UNTIL)
        is None
    )
    with pytest.raises(PlanningPolicyActivationUnavailable, match="future"):
        repository.get_current_head(
            policy_id=activation.subject.policy_id,
            as_of=VALID_UNTIL + timedelta(microseconds=1),
        )
    with pytest.raises(PlanningPolicyActivationUnavailable, match="naive"):
        repository.get_current_head(
            policy_id=activation.subject.policy_id,
            as_of=datetime(2026, 8, 13, 10),
        )


@pytest.mark.django_db(transaction=True)
def test_successor_cas_and_expired_head_never_falls_back() -> None:
    successor_expiry = NOW + timedelta(hours=2)
    clock = FixedClock(successor_expiry)
    repository = DjangoPlanningPolicyActivationRepository(clock=clock)
    root = _persist_root(repository)
    subject, successor = _successor(root, valid_until=successor_expiry)
    with repository.atomic():
        repository.append_subject(subject, recorded_at=subject.requested_at)
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.issued_at,
        )

    assert (
        repository.get_current_head(
            policy_id=root.subject.policy_id,
            as_of=successor.issued_at - timedelta(microseconds=1),
        )
        == root
    )
    assert (
        repository.get_current_head(
            policy_id=root.subject.policy_id,
            as_of=successor_expiry,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_fork_cross_policy_orphan_and_clock_are_rejected() -> None:
    repository = DjangoPlanningPolicyActivationRepository(
        clock=FixedClock(NOW + timedelta(hours=3))
    )
    root = _persist_root(repository)
    first_subject, first_child = _successor(root, number=2)
    second_subject, second_child = _successor(root, number=3)
    with repository.atomic():
        repository.append_subject(first_subject, recorded_at=first_subject.requested_at)
        repository.append_subject(second_subject, recorded_at=second_subject.requested_at)
        repository.append(
            first_child,
            expected_predecessor_hash=root.content_hash,
            recorded_at=first_child.issued_at,
        )
        with pytest.raises(PlanningPolicyActivationConflict, match="stale"):
            repository.append(
                second_child,
                expected_predecessor_hash=root.content_hash,
                recorded_at=second_child.issued_at,
            )

    cross_policy = _subject(
        subject_id="cross-policy-request",
        subject_version="v1",
        definition=_definition(policy_id="another-policy"),
        requested_at=NOW + timedelta(hours=2),
        supersedes_activation_hash=first_child.content_hash,
    )
    with (
        repository.atomic(),
        pytest.raises(PlanningPolicyActivationConflict, match="logical policy head"),
    ):
        repository.append_subject(cross_policy, recorded_at=cross_policy.requested_at)
    with (
        repository.atomic(),
        pytest.raises(PlanningPolicyActivationConflict, match="authoritative"),
    ):
        repository.append_subject(
            _subject(subject_id="bad-clock"),
            recorded_at=NOW + timedelta(microseconds=1),
        )


@pytest.mark.django_db(transaction=True)
def test_self_approval_is_rejected_by_domain_before_persistence() -> None:
    subject = _subject()
    with pytest.raises(ValueError, match="self approval"):
        PlanningPolicyActivation.create(
            activation_id="self-approved",
            activation_version="v1",
            subject=subject,
            approved_by=subject.requested_by,
            issued_at=NOW,
        )
    assert PortfolioPlanningPolicyActivationModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_direct_save_update_delete_bulk_and_raw_paths_are_blocked() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    activation = _persist_root(repository)
    subject_row = PortfolioPlanningPolicyActivationSubjectModel._default_manager.get()
    activation_row = PortfolioPlanningPolicyActivationModel._default_manager.get()

    for row in (subject_row, activation_row):
        with pytest.raises(ValidationError, match="append-only"):
            row.save()
        with pytest.raises(ValidationError, match="append-only"):
            row.save_base(raw=True)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        PortfolioPlanningPolicyActivationModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be bulk updated"):
        PortfolioPlanningPolicyActivationModel._default_manager.bulk_update(
            [activation_row], ["content_hash"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PortfolioPlanningPolicyActivationSubjectModel._default_manager.all().delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PortfolioPlanningPolicyActivationModel._default_manager.all()._raw_delete("default")
    with pytest.raises(ValidationError, match="exact insert claim"):
        PortfolioPlanningPolicyActivationSubjectModel._default_manager.create(
            **_subject_values(activation.subject, NOW)
        )
    with pytest.raises(ValidationError, match="exact repository appends"):
        PortfolioPlanningPolicyActivationSubjectModel._default_manager.bulk_create(
            [
                PortfolioPlanningPolicyActivationSubjectModel(
                    **_subject_values(activation.subject, NOW)
                )
            ]
        )


@pytest.mark.django_db(transaction=True)
def test_subject_and_activation_identity_first_winners_reject_other_content() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    root = _persist_root(repository)
    conflicting_subject = _subject(definition=_definition(fee_rate=Decimal("0.0009")))
    with (
        repository.atomic(),
        pytest.raises(PlanningPolicyActivationConflict, match="another first winner"),
    ):
        repository.append_subject(conflicting_subject, recorded_at=NOW)

    conflicting_activation = PlanningPolicyActivation.create(
        activation_id=root.activation_id,
        activation_version=root.activation_version,
        subject=root.subject,
        approved_by=_actor(13),
        issued_at=NOW,
    )
    with (
        repository.atomic(),
        pytest.raises(PlanningPolicyActivationConflict, match="another first winner"),
    ):
        repository.append(
            conflicting_activation,
            expected_predecessor_hash=None,
            recorded_at=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_double_selector_tamper_is_detected_by_closed_world_restore() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    activation = _persist_root(repository)
    row = PortfolioPlanningPolicyActivationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_planning_policy_activation SET "
            "activation_id = %s, activation_version = %s, "
            "activation_identity_hash = %s, content_hash = %s WHERE id = %s",
            ["hidden", "hidden-v", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PlanningPolicyActivationCorruption):
        repository.get_activation_winner(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            as_of=NOW,
        )
    with repository.atomic(), pytest.raises(PlanningPolicyActivationCorruption):
        repository.append(activation, expected_predecessor_hash=None, recorded_at=NOW)


@pytest.mark.django_db(transaction=True)
def test_subject_double_selector_and_activation_fk_tamper_are_detected() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    activation = _persist_root(repository)
    subject_row = PortfolioPlanningPolicyActivationSubjectModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_planning_policy_activation_subject SET "
            "subject_id = %s, subject_version = %s, subject_identity_hash = %s, "
            "content_hash = %s WHERE id = %s",
            ["hidden", "hidden-v", "0" * 64, "1" * 64, subject_row.pk],
        )
    with pytest.raises(PlanningPolicyActivationCorruption):
        repository.get_subject_winner(
            subject_id=activation.subject.subject_id,
            subject_version=activation.subject.subject_version,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_foreign_key_and_ledger_header_seals_are_verified() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    activation = _persist_root(repository)
    other_subject = _subject(
        subject_id="other-subject",
        definition=_definition(policy_id="other-policy"),
    )
    with repository.atomic():
        repository.append_subject(other_subject, recorded_at=NOW)
    other_row = PortfolioPlanningPolicyActivationSubjectModel._default_manager.get(
        subject_id=other_subject.subject_id
    )
    activation_row = PortfolioPlanningPolicyActivationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_planning_policy_activation "
            "SET subject_record_id = %s WHERE id = %s",
            [other_row.pk, activation_row.pk],
        )
    with pytest.raises(PlanningPolicyActivationCorruption, match="FK"):
        repository.get_activation_winner(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_subject_ledger_header_seal_tamper_is_detected() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    activation = _persist_root(repository)
    subject_row = PortfolioPlanningPolicyActivationSubjectModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_planning_policy_activation_subject "
            "SET ledger_header_hash = %s WHERE id = %s",
            ["0" * 64, subject_row.pk],
        )
    with pytest.raises(PlanningPolicyActivationCorruption, match="seal"):
        repository.get_subject_winner(
            subject_id=activation.subject.subject_id,
            subject_version=activation.subject.subject_version,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_database_constraints_protect_authority_clock_and_two_person_seal() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    _persist_root(repository)
    row = PortfolioPlanningPolicyActivationModel._default_manager.get()
    for column, value in (
        ("permission", "execution"),
        ("persisted_at", NOW - timedelta(microseconds=1)),
        ("approved_actor_user_id", row.requested_actor_user_id),
    ):
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                f"UPDATE portfolio_planning_policy_activation SET {column} = %s WHERE id = %s",
                [value, row.pk],
            )


@pytest.mark.django_db(transaction=True)
def test_orphan_chain_is_detected_after_exact_claimed_corruption_fixture() -> None:
    repository = DjangoPlanningPolicyActivationRepository(clock=FixedClock(NOW))
    orphan_subject = _subject(supersedes_activation_hash="a" * 64)
    orphan_activation = _activation(subject=orphan_subject)
    with repository.atomic():
        token = _ACTIVE_PLANNING_POLICY_ACTIVATION_UOW.get()
        assert token is not None
        subject_values = _subject_values(orphan_subject, NOW)
        subject_row = PortfolioPlanningPolicyActivationSubjectModel(**subject_values)
        with _claim_planning_policy_activation_insert(
            token=token,
            model_type=PortfolioPlanningPolicyActivationSubjectModel,
            expected_values=subject_values,
        ):
            subject_row.save(force_insert=True)
        activation_values = _activation_values(orphan_activation, NOW)
        claimed = {**activation_values, "subject_record_id": subject_row.pk}
        activation_row = PortfolioPlanningPolicyActivationModel(**claimed)
        with _claim_planning_policy_activation_insert(
            token=token,
            model_type=PortfolioPlanningPolicyActivationModel,
            expected_values=claimed,
        ):
            activation_row.save(force_insert=True)

    with pytest.raises(PlanningPolicyActivationCorruption, match="orphaned"):
        repository.get_current_head(policy_id=orphan_subject.policy_id, as_of=NOW)


def test_codecs_are_strict_and_migration_is_schema_only_zero_seed() -> None:
    subject_payload = encode_planning_policy_activation_subject(_subject())
    with pytest.raises(PlanningPolicyActivationCodecError, match="shape"):
        decode_planning_policy_activation_subject({**subject_payload, "status": "active"})
    activation_payload = encode_planning_policy_activation(_activation())
    with pytest.raises(PlanningPolicyActivationCodecError, match="shape"):
        decode_planning_policy_activation({**activation_payload, "execute": True})

    migration = importlib.import_module(
        "apps.portfolio.migrations.0019_planning_policy_activation"
    ).Migration
    assert migration.dependencies == [("portfolio", "0018_planning_policy_definition")]
    assert len(migration.operations) == 2
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)


def test_migration_model_state_matches_both_runtime_models() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0019_planning_policy_activation"
    ).Migration
    state = ProjectState()
    for operation in migration.operations:
        operation.state_forwards("portfolio", state)

    pairs = (
        (
            state.apps.get_model("portfolio", "PortfolioPlanningPolicyActivationSubjectModel"),
            PortfolioPlanningPolicyActivationSubjectModel,
        ),
        (
            state.apps.get_model("portfolio", "PortfolioPlanningPolicyActivationModel"),
            PortfolioPlanningPolicyActivationModel,
        ),
    )

    def field_state(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        result: list[tuple[str, str, tuple[object, ...], dict[str, object]]] = []
        for field in model_type._meta.local_fields:
            _, path, args, kwargs = field.deconstruct()
            result.append((field.name, path, args, kwargs))
        return result

    for rendered, runtime in pairs:
        assert field_state(rendered) == field_state(runtime)
        assert rendered._meta.db_table == runtime._meta.db_table
        assert [item.deconstruct() for item in rendered._meta.indexes] == [
            item.deconstruct() for item in runtime._meta.indexes
        ]
        assert [item.deconstruct() for item in rendered._meta.constraints] == [
            item.deconstruct() for item in runtime._meta.constraints
        ]
