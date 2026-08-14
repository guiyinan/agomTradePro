"""Component coverage for benchmark methodology bundle activation persistence."""

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

from apps.portfolio.application.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationConflict,
    PolicyBenchmarkMethodologyActivationCorruption,
    PolicyBenchmarkMethodologyActivationUnavailable,
)
from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)
from apps.portfolio.domain.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationActor,
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundleActivation,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_codec import (
    PolicyBenchmarkMethodologyActivationCodecError,
    decode_policy_benchmark_methodology_activation,
    decode_policy_benchmark_methodology_activation_subject,
    encode_policy_benchmark_methodology_activation,
    encode_policy_benchmark_methodology_activation_subject,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_models import (
    _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW,
    PortfolioPolicyBenchmarkMethodologyActivationModel,
    PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
    _claim_benchmark_methodology_activation_insert,
)
from apps.portfolio.infrastructure.policy_benchmark_methodology_activation_repository import (
    DjangoPolicyBenchmarkMethodologyActivationRepository,
    _activation_values,
    _subject_values,
)

DEFINITION_AT = datetime(2026, 8, 13, 6, tzinfo=UTC)
REQUESTED_AT = DEFINITION_AT + timedelta(hours=1)
ISSUED_AT = DEFINITION_AT + timedelta(hours=2)
VALID_UNTIL = DEFINITION_AT + timedelta(days=30)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker: object) -> None:
    """Create only this component's two tables, avoiding the full migration graph."""

    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.create_model(PortfolioPolicyBenchmarkMethodologyActivationSubjectModel)
        editor.create_model(PortfolioPolicyBenchmarkMethodologyActivationModel)


def _ref(
    kind: str, marker: str = "a", valid_until: datetime = VALID_UNTIL
) -> PolicyBenchmarkMethodologyRef:
    return PolicyBenchmarkMethodologyRef(
        owner="portfolio",
        artifact_type=kind,
        artifact_id=f"{kind}-cn-v1",
        artifact_version="v1",
        content_hash=marker * 64,
        recorded_at=DEFINITION_AT - timedelta(hours=1),
        valid_until=valid_until,
    )


def _definition(**changes: object) -> PortfolioPolicyBenchmarkDefinition:
    values: dict[str, object] = {
        "definition_id": "balanced-policy-benchmark",
        "definition_version": "v1",
        "base_currency": "CNY",
        "constituents": (
            PolicyBenchmarkConstituentDefinition("CSI300", "000300.SH", "CNY", Decimal("0.6"), 0),
            PolicyBenchmarkConstituentDefinition(
                "CGB_TOTAL_RETURN", "CBA00101.CS", "CNY", Decimal("0.4"), 1
            ),
        ),
        "trading_calendar_ref": _ref("trading_calendar_definition"),
        "price_fixing_ref": _ref("price_fixing_methodology"),
        "fx_fixing_ref": _ref("fx_fixing_methodology"),
        "corporate_action_ref": _ref("corporate_action_methodology"),
        "cost_tax_ref": _ref("cost_tax_methodology"),
        "valuation_timezone": "Asia/Shanghai",
        "valuation_cutoff": "15:00:00",
        "evaluation_window_days": 252,
        "max_price_age_seconds": 86400,
        "max_fx_age_seconds": 86400,
        "missing_price_policy": "fail_closed",
        "missing_fx_policy": "fail_closed",
        "recorded_at": DEFINITION_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkDefinition(**values)  # type: ignore[arg-type]


def _actor(number: int) -> PolicyBenchmarkMethodologyActivationActor:
    return PolicyBenchmarkMethodologyActivationActor(
        actor_id=f"benchmark-staff-{number}",
        user_id=number,
        role="benchmark_configurator",
    )


def _subject(**changes: object) -> PolicyBenchmarkMethodologyActivationSubject:
    values: dict[str, object] = {
        "subject_id": "benchmark-methodology-request-1",
        "subject_version": "v1",
        "definition": _definition(),
        "requested_by": _actor(11),
        "requested_at": REQUESTED_AT,
        "supersedes_activation_hash": None,
    }
    values.update(changes)
    return PolicyBenchmarkMethodologyActivationSubject.create(**values)  # type: ignore[arg-type]


def _activation(**changes: object) -> PolicyBenchmarkMethodologyBundleActivation:
    values: dict[str, object] = {
        "activation_id": "benchmark-methodology-activation-1",
        "activation_version": "v1",
        "subject": _subject(),
        "approved_by": _actor(12),
        "issued_at": ISSUED_AT,
    }
    values.update(changes)
    return PolicyBenchmarkMethodologyBundleActivation.create(**values)  # type: ignore[arg-type]


def _persist_root(
    repository: DjangoPolicyBenchmarkMethodologyActivationRepository,
) -> PolicyBenchmarkMethodologyBundleActivation:
    subject = _subject()
    activation = _activation(subject=subject)
    with repository.atomic():
        assert repository.append_subject(subject, recorded_at=REQUESTED_AT) == subject
        return repository.append(
            activation,
            expected_predecessor_hash=None,
            recorded_at=ISSUED_AT,
        )


def _successor(
    previous: PolicyBenchmarkMethodologyBundleActivation,
    *,
    number: int = 2,
    valid_until: datetime = VALID_UNTIL,
) -> tuple[
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundleActivation,
]:
    definition_at = ISSUED_AT + timedelta(hours=number)
    requested_at = definition_at + timedelta(hours=1)
    issued_at = requested_at + timedelta(hours=1)
    definition = _definition(
        definition_version=f"v{number}",
        trading_calendar_ref=_ref("trading_calendar_definition", valid_until=valid_until),
        price_fixing_ref=_ref("price_fixing_methodology", str(number), valid_until=valid_until),
        fx_fixing_ref=_ref("fx_fixing_methodology", valid_until=valid_until),
        corporate_action_ref=_ref("corporate_action_methodology", valid_until=valid_until),
        cost_tax_ref=_ref("cost_tax_methodology", valid_until=valid_until),
        recorded_at=definition_at,
        valid_until=valid_until,
    )
    subject = _subject(
        subject_id=f"benchmark-methodology-request-{number}",
        subject_version=f"v{number}",
        definition=definition,
        requested_at=requested_at,
        supersedes_activation_hash=previous.content_hash,
    )
    activation = _activation(
        activation_id=f"benchmark-methodology-activation-{number}",
        activation_version=f"v{number}",
        subject=subject,
        issued_at=issued_at,
    )
    return subject, activation


@pytest.mark.django_db(transaction=True)
def test_first_winner_codec_exact_pit_and_authority_roundtrip() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    activation = _persist_root(repository)

    with repository.atomic():
        assert (
            repository.append_subject(activation.subject, recorded_at=REQUESTED_AT)
            == activation.subject
        )
        assert (
            repository.append(activation, expected_predecessor_hash=None, recorded_at=ISSUED_AT)
            == activation
        )
    assert PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.count() == 1
    assert PortfolioPolicyBenchmarkMethodologyActivationModel.objects.count() == 1
    assert (
        decode_policy_benchmark_methodology_activation_subject(
            encode_policy_benchmark_methodology_activation_subject(activation.subject)
        )
        == activation.subject
    )
    assert (
        decode_policy_benchmark_methodology_activation(
            encode_policy_benchmark_methodology_activation(activation)
        )
        == activation
    )
    assert (
        repository.get_subject_winner(
            subject_id=activation.subject.subject_id,
            subject_version=activation.subject.subject_version,
            as_of=ISSUED_AT,
        )
        == activation.subject
    )
    assert (
        repository.get_activation_winner(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            as_of=ISSUED_AT,
        )
        == activation
    )
    assert (
        repository.get_exact_by_hash(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            expected_content_hash=activation.content_hash,
            as_of=ISSUED_AT,
        )
        == activation
    )
    assert (
        repository.get_current_head(definition_id=activation.subject.definition_id, as_of=ISSUED_AT)
        == activation
    )
    assert activation.must_not_execute is True
    assert activation.daily_valuation_authority is False
    assert activation.broker_execution_authority is False


@pytest.mark.django_db(transaction=True)
def test_pit_boundaries_future_naive_and_expired_head_fail_closed() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(VALID_UNTIL))
    activation = _persist_root(repository)

    assert (
        repository.get_exact_by_hash(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            expected_content_hash=activation.content_hash,
            as_of=ISSUED_AT - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        repository.get_current_head(
            definition_id=activation.subject.definition_id, as_of=VALID_UNTIL
        )
        is None
    )
    with pytest.raises(PolicyBenchmarkMethodologyActivationUnavailable, match="future"):
        repository.get_current_head(
            definition_id=activation.subject.definition_id,
            as_of=VALID_UNTIL + timedelta(microseconds=1),
        )
    with pytest.raises(PolicyBenchmarkMethodologyActivationUnavailable, match="naive"):
        repository.get_current_head(
            definition_id=activation.subject.definition_id,
            as_of=datetime(2026, 8, 13, 8),
        )


@pytest.mark.django_db(transaction=True)
def test_successor_cas_and_expired_successor_never_falls_back() -> None:
    expiry = ISSUED_AT + timedelta(hours=8)
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(expiry))
    root = _persist_root(repository)
    subject, successor = _successor(root, valid_until=expiry)
    with repository.atomic():
        repository.append_subject(subject, recorded_at=subject.requested_at)
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.issued_at,
        )

    assert (
        repository.get_current_head(
            definition_id=root.subject.definition_id,
            as_of=successor.issued_at - timedelta(microseconds=1),
        )
        == root
    )
    assert (
        repository.get_current_head(definition_id=root.subject.definition_id, as_of=expiry) is None
    )


@pytest.mark.django_db(transaction=True)
def test_fork_cross_definition_expired_head_and_clock_are_rejected() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(VALID_UNTIL))
    root = _persist_root(repository)
    first_subject, first = _successor(root, number=2)
    second_subject, second = _successor(root, number=3)
    with repository.atomic():
        repository.append_subject(first_subject, recorded_at=first_subject.requested_at)
        repository.append_subject(second_subject, recorded_at=second_subject.requested_at)
        repository.append(
            first,
            expected_predecessor_hash=root.content_hash,
            recorded_at=first.issued_at,
        )
        with pytest.raises(PolicyBenchmarkMethodologyActivationConflict, match="stale"):
            repository.append(
                second,
                expected_predecessor_hash=root.content_hash,
                recorded_at=second.issued_at,
            )

    cross = _subject(
        subject_id="cross-definition-request",
        definition=_definition(definition_id="other-benchmark"),
        requested_at=first.issued_at + timedelta(hours=1),
        supersedes_activation_hash=first.content_hash,
    )
    with (
        repository.atomic(),
        pytest.raises(
            PolicyBenchmarkMethodologyActivationConflict, match="logical definition head"
        ),
    ):
        repository.append_subject(cross, recorded_at=cross.requested_at)
    with (
        repository.atomic(),
        pytest.raises(PolicyBenchmarkMethodologyActivationConflict, match="authoritative"),
    ):
        repository.append_subject(_subject(), recorded_at=REQUESTED_AT + timedelta(seconds=1))


@pytest.mark.django_db(transaction=True)
def test_private_uow_direct_save_update_delete_bulk_and_raw_are_blocked() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    activation = _persist_root(repository)
    subject_row = PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.get()
    activation_row = PortfolioPolicyBenchmarkMethodologyActivationModel.objects.get()

    for row in (subject_row, activation_row):
        with pytest.raises(ValidationError, match="append-only"):
            row.save()
        with pytest.raises(ValidationError, match="append-only"):
            row.save_base(raw=True)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        PortfolioPolicyBenchmarkMethodologyActivationModel.objects.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be bulk updated"):
        PortfolioPolicyBenchmarkMethodologyActivationModel.objects.bulk_update(
            [activation_row], ["content_hash"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.all().delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PortfolioPolicyBenchmarkMethodologyActivationModel.objects.all()._raw_delete("default")
    with pytest.raises(ValidationError, match="exact insert claim"):
        PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.create(
            **_subject_values(activation.subject, REQUESTED_AT)
        )
    with pytest.raises(ValidationError, match="exact repository appends"):
        PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.bulk_create(
            [
                PortfolioPolicyBenchmarkMethodologyActivationSubjectModel(
                    **_subject_values(activation.subject, REQUESTED_AT)
                )
            ]
        )
    with pytest.raises(PolicyBenchmarkMethodologyActivationConflict, match="private unit"):
        repository.append_subject(activation.subject, recorded_at=REQUESTED_AT)


@pytest.mark.django_db(transaction=True)
def test_subject_and_activation_first_winner_reject_other_content() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    root = _persist_root(repository)
    conflicting_subject = _subject(
        definition=_definition(price_fixing_ref=_ref("price_fixing_methodology", "b"))
    )
    with (
        repository.atomic(),
        pytest.raises(PolicyBenchmarkMethodologyActivationConflict, match="another first winner"),
    ):
        repository.append_subject(conflicting_subject, recorded_at=REQUESTED_AT)

    conflicting_activation = PolicyBenchmarkMethodologyBundleActivation.create(
        activation_id=root.activation_id,
        activation_version=root.activation_version,
        subject=root.subject,
        approved_by=_actor(13),
        issued_at=ISSUED_AT,
    )
    with (
        repository.atomic(),
        pytest.raises(PolicyBenchmarkMethodologyActivationConflict, match="another first winner"),
    ):
        repository.append(
            conflicting_activation,
            expected_predecessor_hash=None,
            recorded_at=ISSUED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_detects_five_source_header_payload_and_fk_tamper() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    activation = _persist_root(repository)
    subject_row = PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_method_activation_subject "
            "SET price_fixing_ref_hash = %s WHERE id = %s",
            ["0" * 64, subject_row.pk],
        )
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption, match="headers"):
        repository.get_subject_winner(
            subject_id=activation.subject.subject_id,
            subject_version=activation.subject.subject_version,
            as_of=ISSUED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_detects_double_selector_and_ledger_tamper() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    activation = _persist_root(repository)
    row = PortfolioPolicyBenchmarkMethodologyActivationModel.objects.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_method_activation SET "
            "activation_id = %s, activation_version = %s, "
            "activation_identity_hash = %s, content_hash = %s WHERE id = %s",
            ["hidden", "hidden-v", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption):
        repository.get_exact_by_hash(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            expected_content_hash=activation.content_hash,
            as_of=ISSUED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_foreign_key_binding_is_verified() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    activation = _persist_root(repository)
    other = _subject(
        subject_id="other-subject",
        definition=_definition(definition_id="other-benchmark"),
    )
    with repository.atomic():
        repository.append_subject(other, recorded_at=REQUESTED_AT)
    other_row = PortfolioPolicyBenchmarkMethodologyActivationSubjectModel.objects.get(
        subject_id=other.subject_id
    )
    activation_row = PortfolioPolicyBenchmarkMethodologyActivationModel.objects.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_method_activation "
            "SET subject_record_id = %s WHERE id = %s",
            [other_row.pk, activation_row.pk],
        )
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption, match="FK"):
        repository.get_activation_winner(
            activation_id=activation.activation_id,
            activation_version=activation.activation_version,
            as_of=ISSUED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_database_constraints_protect_authority_clock_actor_and_root_cas() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    root = _persist_root(repository)
    row = PortfolioPolicyBenchmarkMethodologyActivationModel.objects.get()
    for column, value in (
        ("permission", "broker_execution"),
        ("persisted_at", ISSUED_AT - timedelta(microseconds=1)),
        ("approved_actor_user_id", row.requested_actor_user_id),
    ):
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                f"UPDATE portfolio_policy_benchmark_method_activation "
                f"SET {column} = %s WHERE id = %s",
                [value, row.pk],
            )
    duplicate = _activation(
        activation_id="another-root",
        activation_version="v2",
        subject=_subject(subject_id="another-root-request", subject_version="v2"),
    )
    with repository.atomic():
        token = _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.get()
        assert token is not None
        subject_values = _subject_values(duplicate.subject, REQUESTED_AT)
        subject_model = PortfolioPolicyBenchmarkMethodologyActivationSubjectModel(**subject_values)
        with _claim_benchmark_methodology_activation_insert(
            token=token,
            model_type=PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
            expected_values=subject_values,
        ):
            subject_model.save(force_insert=True)
        values = _activation_values(duplicate, ISSUED_AT)
        claimed = {**values, "subject_record_id": subject_model.pk}
        model = PortfolioPolicyBenchmarkMethodologyActivationModel(**claimed)
        with (
            _claim_benchmark_methodology_activation_insert(
                token=token,
                model_type=PortfolioPolicyBenchmarkMethodologyActivationModel,
                expected_values=claimed,
            ),
            pytest.raises(IntegrityError),
        ):
            model.save(force_insert=True)
    assert (
        repository.get_current_head(definition_id=root.subject.definition_id, as_of=ISSUED_AT)
        == root
    )


@pytest.mark.django_db(transaction=True)
def test_orphan_chain_is_detected_after_exact_claimed_corruption_fixture() -> None:
    repository = DjangoPolicyBenchmarkMethodologyActivationRepository(clock=FixedClock(ISSUED_AT))
    orphan_subject = _subject(supersedes_activation_hash="a" * 64)
    orphan_activation = _activation(subject=orphan_subject)
    with repository.atomic():
        token = _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.get()
        assert token is not None
        subject_values = _subject_values(orphan_subject, REQUESTED_AT)
        subject_row = PortfolioPolicyBenchmarkMethodologyActivationSubjectModel(**subject_values)
        with _claim_benchmark_methodology_activation_insert(
            token=token,
            model_type=PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
            expected_values=subject_values,
        ):
            subject_row.save(force_insert=True)
        activation_values = _activation_values(orphan_activation, ISSUED_AT)
        claimed = {**activation_values, "subject_record_id": subject_row.pk}
        activation_row = PortfolioPolicyBenchmarkMethodologyActivationModel(**claimed)
        with _claim_benchmark_methodology_activation_insert(
            token=token,
            model_type=PortfolioPolicyBenchmarkMethodologyActivationModel,
            expected_values=claimed,
        ):
            activation_row.save(force_insert=True)
    with pytest.raises(PolicyBenchmarkMethodologyActivationCorruption, match="root"):
        repository.get_current_head(definition_id=orphan_subject.definition_id, as_of=ISSUED_AT)


def test_codecs_are_strict_and_migration_is_schema_only_zero_seed() -> None:
    subject_payload = encode_policy_benchmark_methodology_activation_subject(_subject())
    with pytest.raises(PolicyBenchmarkMethodologyActivationCodecError, match="shape"):
        decode_policy_benchmark_methodology_activation_subject(
            {**subject_payload, "status": "active"}
        )
    activation_payload = encode_policy_benchmark_methodology_activation(_activation())
    with pytest.raises(PolicyBenchmarkMethodologyActivationCodecError, match="shape"):
        decode_policy_benchmark_methodology_activation(
            {**activation_payload, "must_not_execute": False}
        )
    bad_bundle = dict(subject_payload)
    bundle = dict(bad_bundle["bundle"])  # type: ignore[arg-type]
    bundle["methodology_refs"] = list(reversed(bundle["methodology_refs"]))  # type: ignore[arg-type]
    bad_bundle["bundle"] = bundle
    with pytest.raises(PolicyBenchmarkMethodologyActivationCodecError):
        decode_policy_benchmark_methodology_activation_subject(bad_bundle)

    migration = importlib.import_module(
        "apps.portfolio.migrations.0027_policy_benchmark_methodology_activation"
    ).Migration
    assert migration.dependencies == [("portfolio", "0026_policy_benchmark_cost_tax")]
    assert len(migration.operations) == 2
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)


def test_migration_state_matches_both_runtime_models() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0027_policy_benchmark_methodology_activation"
    ).Migration
    state = ProjectState()
    for operation in migration.operations:
        operation.state_forwards("portfolio", state)

    pairs = (
        (
            state.apps.get_model(
                "portfolio", "PortfolioPolicyBenchmarkMethodologyActivationSubjectModel"
            ),
            PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
        ),
        (
            state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkMethodologyActivationModel"),
            PortfolioPolicyBenchmarkMethodologyActivationModel,
        ),
    )

    def field_state(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        result: list[tuple[str, str, tuple[object, ...], dict[str, object]]] = []
        for field in model_type._meta.local_fields:
            _, path, args, kwargs = field.deconstruct()
            result.append((field.name, path, args, kwargs))
            return sorted(result)

    for rendered, runtime in pairs:
        assert field_state(rendered) == field_state(runtime)
        assert rendered._meta.db_table == runtime._meta.db_table
        assert [item.deconstruct() for item in rendered._meta.indexes] == [
            item.deconstruct() for item in runtime._meta.indexes
        ]
        assert [item.deconstruct() for item in rendered._meta.constraints] == [
            item.deconstruct() for item in runtime._meta.constraints
        ]
