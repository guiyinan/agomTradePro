"""Component coverage for benchmark cost/tax methodology persistence."""

from __future__ import annotations

import copy
import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.policy_benchmark_cost_tax import (
    PolicyBenchmarkCostTaxRule,
    PolicyBenchmarkCostTaxSourceRef,
    PortfolioPolicyBenchmarkCostTax,
)
from apps.portfolio.infrastructure.policy_benchmark_cost_tax_codec import (
    PolicyBenchmarkCostTaxCodecError,
    decode_policy_benchmark_cost_tax,
    encode_policy_benchmark_cost_tax,
)
from apps.portfolio.infrastructure.policy_benchmark_cost_tax_models import (
    PortfolioPolicyBenchmarkCostTaxModel,
)
from apps.portfolio.infrastructure.policy_benchmark_cost_tax_repository import (
    DjangoPolicyBenchmarkCostTaxRepository,
    PolicyBenchmarkCostTaxConflict,
    PolicyBenchmarkCostTaxCorruption,
    PolicyBenchmarkCostTaxUnavailable,
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


def _source(ordinal: int, kind: str, code: str) -> PolicyBenchmarkCostTaxSourceRef:
    return PolicyBenchmarkCostTaxSourceRef(
        owner="portfolio-cost-authority",
        artifact_type={
            "fee": "benchmark_fee_definition",
            "tax": "benchmark_tax_definition",
        }[kind],
        artifact_id=f"official-{kind}-{ordinal}",
        artifact_version="v1",
        content_hash=f"{ordinal + 1:064x}",
        ordinal=ordinal,
        charge_kind=kind,
        charge_code=code,
        asset_scope_code="CN-EQUITY",
        jurisdiction_code="CN",
        recorded_at=NOW - timedelta(hours=1),
        valid_until=VALID,
    )


def _fee_rule(**changes: object) -> PolicyBenchmarkCostTaxRule:
    values: dict[str, object] = {
        "ordinal": 0,
        "source_ordinal": 0,
        "charge_kind": "fee",
        "charge_code": "broker-commission",
        "asset_scope_code": "CN-EQUITY",
        "jurisdiction_code": "CN",
        "charge_event": "trade",
        "trade_side": "both",
        "calculation_basis": "gross_trade_notional",
        "recognition_timing": "trade_execution",
        "calculation_mode": "rate",
        "rate": Decimal("0.00030000"),
        "fixed_amount": None,
        "minimum_amount": None,
        "maximum_amount": None,
        "charge_currency": "CNY",
        "rate_precision_places": 8,
        "amount_precision_places": 2,
        "rounding_increment": Decimal("0.01"),
        "rounding_mode": "half_up",
    }
    values.update(changes)
    return PolicyBenchmarkCostTaxRule(**values)  # type: ignore[arg-type]


def _tax_rule(**changes: object) -> PolicyBenchmarkCostTaxRule:
    values: dict[str, object] = {
        "ordinal": 1,
        "source_ordinal": 1,
        "charge_kind": "tax",
        "charge_code": "cash-dividend-withholding",
        "asset_scope_code": "CN-EQUITY",
        "jurisdiction_code": "CN",
        "charge_event": "cash_dividend",
        "trade_side": "not_applicable",
        "calculation_basis": "gross_cash_dividend_entitlement",
        "recognition_timing": "entitlement_recognition",
        "calculation_mode": "rate",
        "rate": Decimal("0.1000"),
        "fixed_amount": None,
        "minimum_amount": None,
        "maximum_amount": None,
        "charge_currency": "CNY",
        "rate_precision_places": 4,
        "amount_precision_places": 2,
        "rounding_increment": Decimal("0.0100"),
        "rounding_mode": "half_up",
    }
    values.update(changes)
    return PolicyBenchmarkCostTaxRule(**values)  # type: ignore[arg-type]


def _value(**changes: object) -> PortfolioPolicyBenchmarkCostTax:
    values: dict[str, object] = {
        "methodology_id": "policy-benchmark-cost-tax",
        "methodology_version": "v1",
        "source_priority": (
            _source(0, "fee", "broker-commission"),
            _source(1, "tax", "cash-dividend-withholding"),
        ),
        "charge_rules": (_fee_rule(), _tax_rule()),
        "recorded_at": NOW,
        "valid_until": VALID,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkCostTax(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_roundtrip_idempotency_and_historical_exact_pit_only() -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        assert repo.append(value, recorded_at=NOW) == value
        assert repo.append(value, recorded_at=NOW) == value
    assert PortfolioPolicyBenchmarkCostTaxModel._default_manager.count() == 1
    assert decode_policy_benchmark_cost_tax(encode_policy_benchmark_cost_tax(value)) == value
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
    expired = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(VALID))
    assert (
        expired.get_exact(
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
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    with pytest.raises(PolicyBenchmarkCostTaxConflict, match="private unit"):
        repo.append(value, recorded_at=NOW)
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    changed = _value(charge_rules=(_fee_rule(rate=Decimal("0.0004")), _tax_rule()))
    with repo.atomic(), pytest.raises(PolicyBenchmarkCostTaxConflict, match="first winner"):
        repo.append(changed, recorded_at=NOW)
    with pytest.raises(PolicyBenchmarkCostTaxUnavailable, match="future"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW + timedelta(microseconds=1),
        )


@pytest.mark.django_db(transaction=True)
def test_direct_save_raw_update_delete_and_bulk_paths_are_blocked() -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    values = _model_values(value, NOW)
    with pytest.raises(ValidationError, match="exact insert claim"):
        PortfolioPolicyBenchmarkCostTaxModel(**values).save(force_insert=True)
    with pytest.raises(ValidationError, match="append-only"):
        PortfolioPolicyBenchmarkCostTaxModel(**values).save_base(raw=True)
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCostTaxModel._default_manager.get()
    assert row.persisted_at == row.recorded_at == NOW
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCostTaxModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCostTaxModel._default_manager.bulk_update([row], ["content_hash"])
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCostTaxModel._default_manager.bulk_create(
            [PortfolioPolicyBenchmarkCostTaxModel(**values)]
        )
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkCostTaxModel._default_manager.all().delete()


@pytest.mark.django_db(transaction=True)
def test_closed_world_restore_detects_double_selector_tamper_before_selection() -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCostTaxModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_cost_tax "
            "SET methodology_id=%s, methodology_version=%s, identity_hash=%s, "
            "content_hash=%s WHERE id=%s",
            ["hidden", "hidden", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkCostTaxCorruption, match="headers"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("field_name", ["sources_hash", "charge_rules_hash"])
def test_complete_source_rule_and_kind_header_seals(field_name: str) -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCostTaxModel._default_manager.get()
    replacement = "0" * 64
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE portfolio_policy_benchmark_cost_tax SET {field_name}=%s WHERE id=%s",
            [replacement, row.pk],
        )
    with pytest.raises(PolicyBenchmarkCostTaxCorruption, match="headers"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("field_name", ["fee_source_count", "tax_rule_count"])
def test_source_and_rule_kind_counts_are_database_conserved(field_name: str) -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    with repo.atomic():
        repo.append(_value(), recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCostTaxModel._default_manager.get()

    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE portfolio_policy_benchmark_cost_tax SET {field_name}=%s WHERE id=%s",
                [9, row.pk],
            )


@pytest.mark.django_db(transaction=True)
def test_canonical_decimal_payload_tamper_fails_closed() -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCostTaxModel._default_manager.get()
    payload = copy.deepcopy(row.canonical_payload)
    payload["charge_rules"][0]["rate"] = "3E-4"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_cost_tax SET canonical_payload=%s WHERE id=%s",
            [json.dumps(payload, separators=(",", ":")), row.pk],
        )
    with pytest.raises(PolicyBenchmarkCostTaxCorruption, match="payload"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_ledger_and_persisted_clock_seals_reject_direct_tamper() -> None:
    repo = DjangoPolicyBenchmarkCostTaxRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkCostTaxModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_cost_tax SET ledger_header_hash=%s WHERE id=%s",
            ["0" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkCostTaxCorruption, match="ledger seal"):
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
                    "UPDATE portfolio_policy_benchmark_cost_tax SET persisted_at=%s WHERE id=%s",
                    [NOW + timedelta(microseconds=1), row.pk],
                )


def test_codec_rejects_authority_source_rule_decimal_and_unknown_shape_drift() -> None:
    payload = encode_policy_benchmark_cost_tax(_value())
    variants: list[dict[str, object]] = []
    variants.append({**payload, "owner": "account"})

    source = copy.deepcopy(payload)
    source["source_priority"][0]["jurisdiction_code"] = "US"
    variants.append(source)

    rule = copy.deepcopy(payload)
    rule["charge_rules"][0]["calculation_basis"] = "net_notional"
    variants.append(rule)

    for decimal_value in ("0.000300", "3E-4", "-0", 0.0003):
        decimal_drift = copy.deepcopy(payload)
        decimal_drift["charge_rules"][0]["rate"] = decimal_value
        variants.append(decimal_drift)
    variants.append({**payload, "current": True})

    for variant in variants:
        with pytest.raises(PolicyBenchmarkCostTaxCodecError):
            decode_policy_benchmark_cost_tax(variant)


def test_migration_is_zero_seed_and_matches_runtime_model_state() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0026_policy_benchmark_cost_tax"
    ).Migration
    assert migration.dependencies == [("portfolio", "0025_policy_benchmark_corporate_action")]
    assert len(migration.operations) == 1
    assert not any(isinstance(item, (RunPython, RunSQL)) for item in migration.operations)
    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkCostTaxModel")

    def fields(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        return [
            (field.name, field.deconstruct()[1], field.deconstruct()[2], field.deconstruct()[3])
            for field in model_type._meta.local_fields
        ]

    assert fields(rendered) == fields(PortfolioPolicyBenchmarkCostTaxModel)
    assert [item.deconstruct() for item in rendered._meta.constraints] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkCostTaxModel._meta.constraints
    ]
    assert [item.deconstruct() for item in rendered._meta.indexes] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkCostTaxModel._meta.indexes
    ]
    assert rendered._meta.db_table == PortfolioPolicyBenchmarkCostTaxModel._meta.db_table
    assert rendered._meta.base_manager_name == "objects"
    assert rendered._meta.default_manager_name == "objects"
