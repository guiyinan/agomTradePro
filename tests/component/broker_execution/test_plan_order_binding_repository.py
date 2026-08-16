"""Component coverage for Broker Plan-to-Order append-only persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.migrations import RunPython, RunSQL

from apps.broker_execution.application.plan_order_binding import (
    BrokerPlanOrderBindingConflict,
    BrokerPlanOrderBindingCorruption,
    BrokerPlanOrderBindingRepository,
    BrokerPlanOrderBindingUnavailable,
)
from apps.broker_execution.domain.plan_order_binding import (
    BROKER_PLAN_ORDER_BINDING_SCHEMA,
    BrokerPlanOrderBinding,
    canonical_plan_order_payload_hash_v1,
)
from apps.broker_execution.infrastructure.plan_order_binding_codec import (
    BrokerPlanOrderBindingCodecError,
    decode_broker_plan_order_binding,
    encode_broker_plan_order_binding,
)
from apps.broker_execution.infrastructure.plan_order_binding_models import (
    BrokerPlanOrderBindingModel,
)
from apps.broker_execution.infrastructure.plan_order_binding_repository import (
    DjangoBrokerPlanOrderBindingRepository,
    _model_values,
    _validate_closed_world,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_models import (
    _activate_portfolio_broker_binding_uow,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _payload(**changes: object) -> str:
    value: dict[str, object] = {
        "asset_code": "600000.SH",
        "side": "buy",
        "quantity": 100,
        "reference_price": "10.2500",
        "estimated_fee": "5.00",
        "status": "draft",
        "remaining_quantity": 100,
        "constraints": [
            {
                "rule_code": "max-position",
                "asset_code": "600000.SH",
                "allowed": True,
                "original_quantity": 100,
                "allowed_quantity": 100,
                "reason": "within limit",
            }
        ],
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _binding(**changes: object) -> BrokerPlanOrderBinding:
    payload = changes.pop("plan_order_payload_json", _payload())
    assert type(payload) is str
    values: dict[str, object] = {
        "binding_id": "plan-order-binding-1",
        "binding_version": BROKER_PLAN_ORDER_BINDING_SCHEMA,
        "portfolio_plan_id": "transition-plan-1",
        "portfolio_plan_version": 2,
        "portfolio_plan_content_hash": "a" * 64,
        "portfolio_account_id": "portfolio-account-7",
        "portfolio_receipt_id": "portfolio-receipt-1",
        "portfolio_receipt_version": "portfolio-receipt.v1",
        "portfolio_receipt_content_hash": "b" * 64,
        "portfolio_subject_id": "portfolio-subject-1",
        "portfolio_subject_version": "portfolio-subject.v1",
        "portfolio_subject_content_hash": "c" * 64,
        "plan_order_ordinal": 0,
        "plan_order_payload_json": payload,
        "plan_order_content_hash": canonical_plan_order_payload_hash_v1(payload),
        "broker_account_id": 7,
        "order_artifact_id": ORDER_ID,
        "order_artifact_version": "broker-live-order-approval-artifact.v1.3",
        "order_artifact_identity_hash": "d" * 64,
        "order_artifact_content_hash": "e" * 64,
        "order_approval_digest": "f" * 64,
        "order_version": 3,
        "portfolio_plan_valid_until": NOW + timedelta(hours=3),
        "portfolio_receipt_valid_until": NOW + timedelta(hours=2),
        "order_artifact_valid_until": NOW + timedelta(hours=1),
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return BrokerPlanOrderBinding(**values)  # type: ignore[arg-type]


def _successor(previous: BrokerPlanOrderBinding, **changes: object) -> BrokerPlanOrderBinding:
    values: dict[str, object] = {
        "binding_id": "plan-order-binding-2",
        "portfolio_receipt_content_hash": "9" * 64,
        "recorded_at": NOW + timedelta(minutes=1),
        "supersedes_binding_hash": previous.content_hash,
    }
    values.update(changes)
    return _binding(**values)


def _repository(
    clock: FixedClock | None = None,
) -> DjangoBrokerPlanOrderBindingRepository:
    return DjangoBrokerPlanOrderBindingRepository(
        clock=clock or FixedClock(NOW + timedelta(minutes=10))
    )


def _accepts_protocol(
    repository: BrokerPlanOrderBindingRepository,
) -> BrokerPlanOrderBindingRepository:
    return repository


@pytest.mark.django_db
def test_append_round_trip_protocol_canonical_bytes_and_exact_pit() -> None:
    repository = _repository()
    assert _accepts_protocol(repository) is repository
    binding = _binding()
    with repository.atomic():
        persisted = repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)

    assert persisted == binding
    row = BrokerPlanOrderBindingModel._default_manager.get()
    assert row.plan_order_payload_json == binding.plan_order_payload_json
    assert row.canonical_row_byte_hash == binding.plan_order_content_hash
    assert decode_broker_plan_order_binding(encode_broker_plan_order_binding(binding)) == binding
    assert (
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=NOW,
        )
        == binding
    )
    assert (
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )


@pytest.mark.django_db
def test_full_subject_chain_and_expired_successor_never_falls_back() -> None:
    repository = _repository()
    root = _binding()
    successor = _successor(
        root,
        portfolio_plan_valid_until=NOW + timedelta(minutes=2),
        portfolio_receipt_valid_until=NOW + timedelta(minutes=2),
        order_artifact_valid_until=NOW + timedelta(minutes=2),
        valid_until=NOW + timedelta(minutes=2),
    )
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )

    selector = {
        "plan_id": root.portfolio_plan_id,
        "plan_version": root.portfolio_plan_version,
        "plan_order_ordinal": root.plan_order_ordinal,
        "order_artifact_id": root.order_artifact_id,
    }
    assert repository.get_current_head(**selector, as_of=NOW) == root
    assert repository.get_current_head(**selector, as_of=successor.valid_until) is None


@pytest.mark.django_db
def test_private_uow_and_foreign_token_are_rejected() -> None:
    repository = _repository()
    binding = _binding()
    with pytest.raises(BrokerPlanOrderBindingConflict, match="private unit"):
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    token = object()
    with (
        _activate_portfolio_broker_binding_uow(token),
        pytest.raises(BrokerPlanOrderBindingConflict, match="private unit"),
    ):
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)


@pytest.mark.django_db
def test_identity_root_and_predecessor_claims_are_first_winner_only() -> None:
    repository = _repository()
    root = _binding()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    identity_conflict = _binding(portfolio_receipt_content_hash="8" * 64)
    with repository.atomic(), pytest.raises(BrokerPlanOrderBindingConflict, match="first winner"):
        repository.append(identity_conflict, expected_predecessor_hash=None, recorded_at=NOW)
    root_conflict = _binding(binding_id="other-root", portfolio_receipt_content_hash="7" * 64)
    with repository.atomic(), pytest.raises(BrokerPlanOrderBindingConflict, match="claim"):
        repository.append(root_conflict, expected_predecessor_hash=None, recorded_at=NOW)

    successor = _successor(root)
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.recorded_at,
        )
    fork = _successor(root, binding_id="fork", portfolio_receipt_content_hash="6" * 64)
    with repository.atomic(), pytest.raises(BrokerPlanOrderBindingConflict, match="claim"):
        repository.append(
            fork,
            expected_predecessor_hash=root.content_hash,
            recorded_at=fork.recorded_at,
        )


@pytest.mark.django_db
def test_direct_mutation_delete_bulk_raw_and_unclaimed_create_are_blocked() -> None:
    repository = _repository()
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPlanOrderBindingModel._default_manager.get()

    row.portfolio_plan_id = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        BrokerPlanOrderBindingModel._default_manager.update(portfolio_plan_id="tampered")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        BrokerPlanOrderBindingModel._default_manager.all().delete()
    values = _model_values(binding, recorded_at=NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerPlanOrderBindingModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerPlanOrderBindingModel._default_manager.bulk_create(
            [BrokerPlanOrderBindingModel(**values)]
        )
    with pytest.raises(ValidationError, match="append-only"):
        BrokerPlanOrderBindingModel(**values).save_base(raw=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("portfolio_plan_content_hash", "9" * 64),
        ("portfolio_receipt_content_hash", "8" * 64),
        ("order_artifact_content_hash", "7" * 64),
        ("canonical_row_byte_hash", "6" * 64),
        ("persisted_at", NOW + timedelta(seconds=1)),
    ],
)
def test_source_row_and_persisted_seal_tamper_fail_closed(column: str, replacement: object) -> None:
    repository = _repository()
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPlanOrderBindingModel._default_manager.get()
    if column == "persisted_at":
        with pytest.raises(IntegrityError):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE broker_execution_plan_order_binding SET {column} = %s WHERE id = %s",
                    [replacement, row.pk],
                )
        return
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE broker_execution_plan_order_binding SET {column} = %s WHERE id = %s",
            [replacement, row.pk],
        )
    with pytest.raises(BrokerPlanOrderBindingCorruption):
        repository.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=NOW,
        )


@pytest.mark.django_db
def test_double_selector_tamper_cannot_hide_binding() -> None:
    repository = _repository()
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPlanOrderBindingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_plan_order_binding SET portfolio_plan_id = %s, "
            "order_artifact_id = %s, binding_id = %s, content_hash = %s WHERE id = %s",
            ["hidden-plan", "75df9306-cb1d-47de-8588-3bfce22a7930", "hidden", "9" * 64, row.pk],
        )
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="headers"):
        repository.get_current_head(
            plan_id=binding.portfolio_plan_id,
            plan_version=binding.portfolio_plan_version,
            plan_order_ordinal=binding.plan_order_ordinal,
            order_artifact_id=binding.order_artifact_id,
            as_of=NOW,
        )
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="headers"):
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=NOW,
        )


def test_closed_world_rejects_orphan_fork_and_cross_subject_link() -> None:
    root = _binding()
    orphan = _successor(root, supersedes_binding_hash="9" * 64)
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="missing"):
        _validate_closed_world((orphan,))
    first = _successor(root)
    second = _successor(root, binding_id="fork", portfolio_receipt_content_hash="8" * 64)
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="multiple"):
        _validate_closed_world((root, first, second))
    cross = _successor(
        root,
        binding_id="cross-subject",
        plan_order_ordinal=1,
        plan_order_payload_json=_payload(asset_code="000001.SZ"),
    )
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="link"):
        _validate_closed_world((root, cross))


@pytest.mark.django_db
def test_noncanonical_payload_and_future_cutoff_fail_closed() -> None:
    repository = _repository(FixedClock(NOW))
    binding = _binding()
    with repository.atomic():
        repository.append(binding, expected_predecessor_hash=None, recorded_at=NOW)
    row = BrokerPlanOrderBindingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_plan_order_binding SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="canonical"):
        repository.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=NOW,
        )
    with pytest.raises(BrokerPlanOrderBindingUnavailable, match="future"):
        repository.get_current_head(
            plan_id=binding.portfolio_plan_id,
            plan_version=binding.portfolio_plan_version,
            plan_order_ordinal=binding.plan_order_ordinal,
            order_artifact_id=binding.order_artifact_id,
            as_of=NOW + timedelta(microseconds=1),
        )


def test_codec_strict_and_0012_is_schema_only_zero_seed() -> None:
    payload = encode_broker_plan_order_binding(_binding())
    with pytest.raises(BrokerPlanOrderBindingCodecError, match="shape"):
        decode_broker_plan_order_binding({**payload, "unknown": True})
    migration = importlib.import_module(
        "apps.broker_execution.migrations.0012_plan_order_binding"
    ).Migration
    assert migration.dependencies == [("broker_execution", "0011_portfolio_broker_account_binding")]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
