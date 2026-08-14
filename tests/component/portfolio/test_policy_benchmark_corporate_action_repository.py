"""Component coverage for benchmark corporate-action methodology persistence."""

from __future__ import annotations

import copy
import importlib
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.policy_benchmark_corporate_action import (
    PolicyBenchmarkCorporateActionRule,
    PolicyBenchmarkCorporateActionSourceRef,
    PortfolioPolicyBenchmarkCorporateAction,
)
from apps.portfolio.infrastructure.policy_benchmark_corporate_action_codec import (
    PolicyBenchmarkCorporateActionCodecError,
    decode_policy_benchmark_corporate_action,
    encode_policy_benchmark_corporate_action,
)
from apps.portfolio.infrastructure.policy_benchmark_corporate_action_models import (
    PortfolioPolicyBenchmarkCorporateActionModel,
)
from apps.portfolio.infrastructure.policy_benchmark_corporate_action_repository import (
    DjangoPolicyBenchmarkCorporateActionRepository,
    PolicyBenchmarkCorporateActionConflict,
    PolicyBenchmarkCorporateActionCorruption,
    PolicyBenchmarkCorporateActionUnavailable,
    _model_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
VALID = NOW + timedelta(days=30)


@dataclass
class FixedClock:
    """Deterministic aware repository clock."""

    value: datetime

    def now(self) -> datetime:
        return self.value


def _rules() -> tuple[PolicyBenchmarkCorporateActionRule, ...]:
    return (
        PolicyBenchmarkCorporateActionRule(
            0,
            "cash_dividend",
            ("effective_date", "ex_date", "pay_date"),
            "action_terms_effective",
            "recognize_receivable_and_internal_return_once",
            "settle_receivable_without_second_return",
            "cash_receivable_then_cash",
            "internal_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            1,
            "stock_dividend",
            ("effective_date", "ex_date", "pay_date"),
            "action_terms_effective",
            "recognize_share_receivable_and_price_adjustment_once",
            "settle_share_receivable_without_second_adjustment",
            "share_receivable_then_quantity",
            "no_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            2,
            "split",
            ("effective_date",),
            "adjust_quantity_and_reference_price_once",
            "not_applicable",
            "not_applicable",
            "quantity_and_reference_price_adjustment",
            "no_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            3,
            "reverse_split",
            ("effective_date",),
            "adjust_quantity_and_reference_price_once",
            "not_applicable",
            "not_applicable",
            "quantity_and_reference_price_adjustment",
            "no_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            4,
            "rights_issue",
            ("effective_date", "ex_date"),
            "action_terms_effective",
            "establish_entitlement_then_block_without_exact_terms_and_election",
            "not_applicable",
            "block",
            "block",
        ),
    )


def _value(**changes: object) -> PortfolioPolicyBenchmarkCorporateAction:
    source = PolicyBenchmarkCorporateActionSourceRef(
        owner="portfolio",
        artifact_type="benchmark_corporate_action_source_definition",
        artifact_id="official-actions",
        artifact_version="v1",
        content_hash="a" * 64,
        ordinal=0,
        recorded_at=NOW - timedelta(hours=1),
        valid_until=VALID,
    )
    values: dict[str, object] = {
        "methodology_id": "listed-equity-corporate-actions",
        "methodology_version": "v1",
        "security_identifier_namespace": "MIC_TICKER",
        "timezone": "Asia/Shanghai",
        "business_date_cutoff_local": time(18),
        "source_priority": (source,),
        "event_rules": _rules(),
        "missing_action_policy": "fail_closed",
        "unknown_event_type_policy": "fail_closed",
        "recorded_at": NOW,
        "valid_until": VALID,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkCorporateAction(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_roundtrip_idempotency_and_historical_exact_pit_only() -> None:
    repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        assert repo.append(value, recorded_at=NOW) == value
        assert repo.append(value, recorded_at=NOW) == value
    assert (
        decode_policy_benchmark_corporate_action(encode_policy_benchmark_corporate_action(value))
        == value
    )
    assert (
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )
        == value
    )
    assert (
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    expiry_repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(VALID))
    assert (
        expiry_repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=VALID,
        )
        is None
    )
    assert not hasattr(repo, "get_current")
    assert not hasattr(repo, "activate")


@pytest.mark.django_db(transaction=True)
def test_private_uow_first_winner_and_future_cutoff() -> None:
    repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(NOW))
    value = _value()
    with pytest.raises(PolicyBenchmarkCorporateActionConflict, match="private unit"):
        repo.append(value, recorded_at=NOW)
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    with repo.atomic(), pytest.raises(PolicyBenchmarkCorporateActionConflict, match="first winner"):
        repo.append(_value(security_identifier_namespace="ISIN"), recorded_at=NOW)
    with pytest.raises(PolicyBenchmarkCorporateActionUnavailable, match="future"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW + timedelta(microseconds=1),
        )


@pytest.mark.django_db(transaction=True)
def test_direct_save_raw_update_delete_and_bulk_paths_are_blocked() -> None:
    repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(NOW))
    value = _value()
    values = _model_values(value, NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        PortfolioPolicyBenchmarkCorporateActionModel(**values).save(force_insert=True)
    with pytest.raises(ValidationError, match="append-only"):
        PortfolioPolicyBenchmarkCorporateActionModel(**values).save_base(raw=True)
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCorporateActionModel._default_manager.get()
    assert row.persisted_at == row.recorded_at == NOW
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCorporateActionModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCorporateActionModel._default_manager.bulk_update(
            [row], ["content_hash"]
        )
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCorporateActionModel._default_manager.bulk_create(
            [PortfolioPolicyBenchmarkCorporateActionModel(**values)]
        )
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCorporateActionModel._default_manager.all().delete()


@pytest.mark.django_db(transaction=True)
def test_closed_world_restore_detects_a_tampered_hidden_row_before_selection() -> None:
    repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCorporateActionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_corporate_action "
            "SET methodology_id=%s WHERE id=%s",
            ["hidden-methodology", row.pk],
        )
    with pytest.raises(PolicyBenchmarkCorporateActionCorruption, match="headers"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("field_name", ["sources_hash", "event_rules_hash"])
def test_source_and_event_matrix_header_seals(field_name: str) -> None:
    repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCorporateActionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE portfolio_policy_benchmark_corporate_action "
            f"SET {field_name}=%s WHERE id=%s",
            ["0" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkCorporateActionCorruption, match="headers"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_ledger_and_clock_seals_reject_direct_tamper() -> None:
    repo = DjangoPolicyBenchmarkCorporateActionRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCorporateActionModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_corporate_action "
            "SET ledger_header_hash=%s WHERE id=%s",
            ["0" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkCorporateActionCorruption, match="ledger seal"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE portfolio_policy_benchmark_corporate_action "
                    "SET persisted_at=%s WHERE id=%s",
                    [NOW + timedelta(microseconds=1), row.pk],
                )


def test_codec_rejects_authority_event_source_timezone_and_unknown_shape_drift() -> None:
    payload = encode_policy_benchmark_corporate_action(_value())
    variants: list[dict[str, object]] = []

    authority = copy.deepcopy(payload)
    authority["owner"] = "data_center"
    variants.append(authority)

    event = copy.deepcopy(payload)
    event_rules = event["event_rules"]
    assert type(event_rules) is list
    event_rules[0]["event_type"] = "special_dividend"
    variants.append(event)

    source = copy.deepcopy(payload)
    sources = source["source_priority"]
    assert type(sources) is list
    sources[0]["artifact_type"] = "mutable_corporate_action_fact"
    variants.append(source)

    timezone_drift = copy.deepcopy(payload)
    timezone_drift["timezone"] = "Not/AZone"
    variants.append(timezone_drift)
    variants.append({**payload, "current": True})

    for variant in variants:
        with pytest.raises(PolicyBenchmarkCorporateActionCodecError):
            decode_policy_benchmark_corporate_action(variant)


def test_migration_is_zero_seed_and_matches_runtime_model_state() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0025_policy_benchmark_corporate_action"
    ).Migration
    assert migration.dependencies == [
        ("portfolio", "0024_align_transition_approval_persistence_clock")
    ]
    assert len(migration.operations) == 1
    assert not any(isinstance(item, (RunPython, RunSQL)) for item in migration.operations)
    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkCorporateActionModel")

    def fields(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        return [
            (field.name, field.deconstruct()[1], field.deconstruct()[2], field.deconstruct()[3])
            for field in model_type._meta.local_fields
        ]

    assert fields(rendered) == fields(PortfolioPolicyBenchmarkCorporateActionModel)
    assert [item.deconstruct() for item in rendered._meta.constraints] == [
        item.deconstruct()
        for item in PortfolioPolicyBenchmarkCorporateActionModel._meta.constraints
    ]
    assert [item.deconstruct() for item in rendered._meta.indexes] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkCorporateActionModel._meta.indexes
    ]
    assert rendered._meta.db_table == (PortfolioPolicyBenchmarkCorporateActionModel._meta.db_table)
    assert rendered._meta.base_manager_name == "objects"
    assert rendered._meta.default_manager_name == "objects"
