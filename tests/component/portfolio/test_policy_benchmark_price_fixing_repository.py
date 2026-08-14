"""Component coverage for benchmark price-fixing persistence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.policy_benchmark_price_fixing import (
    PolicyBenchmarkPriceSourceRef,
    PortfolioPolicyBenchmarkPriceFixing,
)
from apps.portfolio.infrastructure.policy_benchmark_price_fixing_codec import (
    PolicyBenchmarkPriceFixingCodecError,
    decode_policy_benchmark_price_fixing,
    encode_policy_benchmark_price_fixing,
)
from apps.portfolio.infrastructure.policy_benchmark_price_fixing_models import (
    PortfolioPolicyBenchmarkPriceFixingModel,
)
from apps.portfolio.infrastructure.policy_benchmark_price_fixing_repository import (
    DjangoPolicyBenchmarkPriceFixingRepository,
    PolicyBenchmarkPriceFixingConflict,
    PolicyBenchmarkPriceFixingCorruption,
    _model_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
VALID_UNTIL = NOW + timedelta(days=30)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _source() -> PolicyBenchmarkPriceSourceRef:
    return PolicyBenchmarkPriceSourceRef(
        "portfolio",
        "benchmark_price_source_definition",
        "official-cn-eod",
        "v1",
        "a" * 64,
        0,
        NOW - timedelta(hours=1),
        VALID_UNTIL,
    )


def _definition(**changes: object) -> PortfolioPolicyBenchmarkPriceFixing:
    values: dict[str, object] = {
        "methodology_id": "cn-price-fixing",
        "methodology_version": "v1",
        "price_identifier_namespace": "MIC_TICKER",
        "price_field": "close",
        "adjustment_basis": "unadjusted",
        "venue": "XSHG",
        "timezone": "Asia/Shanghai",
        "valuation_cutoff_local": time(15, 30),
        "source_priority": (_source(),),
        "stale_after_seconds": 86400,
        "missing_price_policy": "fail_closed",
        "recorded_at": NOW,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkPriceFixing(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_append_codec_idempotency_and_exact_pit_roundtrip() -> None:
    repo = DjangoPolicyBenchmarkPriceFixingRepository(clock=FixedClock(NOW))
    value = _definition()
    with repo.atomic():
        assert repo.append(value, recorded_at=NOW) == value
        assert repo.append(value, recorded_at=NOW) == value
    assert PortfolioPolicyBenchmarkPriceFixingModel._default_manager.count() == 1
    assert (
        decode_policy_benchmark_price_fixing(encode_policy_benchmark_price_fixing(value)) == value
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


@pytest.mark.django_db(transaction=True)
def test_private_uow_and_first_winner_fail_closed() -> None:
    repo = DjangoPolicyBenchmarkPriceFixingRepository(clock=FixedClock(NOW))
    value = _definition()
    with pytest.raises(PolicyBenchmarkPriceFixingConflict, match="private unit"):
        repo.append(value, recorded_at=NOW)
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    with repo.atomic(), pytest.raises(PolicyBenchmarkPriceFixingConflict, match="first winner"):
        repo.append(_definition(stale_after_seconds=1), recorded_at=NOW)


@pytest.mark.django_db(transaction=True)
def test_direct_save_update_delete_bulk_and_raw_paths_are_blocked() -> None:
    repo = DjangoPolicyBenchmarkPriceFixingRepository(clock=FixedClock(NOW))
    value = _definition()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkPriceFixingModel._default_manager.get()
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(raw=True)
    with pytest.raises(ValidationError, match="updated"):
        PortfolioPolicyBenchmarkPriceFixingModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="exact repository"):
        PortfolioPolicyBenchmarkPriceFixingModel._default_manager.bulk_create(
            [PortfolioPolicyBenchmarkPriceFixingModel(**_model_values(value, NOW))]
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_restore_detects_hidden_double_selector_tamper() -> None:
    repo = DjangoPolicyBenchmarkPriceFixingRepository(clock=FixedClock(NOW))
    value = _definition()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkPriceFixingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_price_fixing SET methodology_id=%s, methodology_version=%s, identity_hash=%s, content_hash=%s WHERE id=%s",
            ["hidden", "hidden", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkPriceFixingCorruption):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_sources_cutoff_and_ledger_headers_are_sealed() -> None:
    repo = DjangoPolicyBenchmarkPriceFixingRepository(clock=FixedClock(NOW))
    value = _definition()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkPriceFixingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_price_fixing SET sources_hash=%s WHERE id=%s",
            ["0" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkPriceFixingCorruption, match="headers"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_ledger_and_persisted_clock_seals_fail_closed() -> None:
    repo = DjangoPolicyBenchmarkPriceFixingRepository(clock=FixedClock(NOW))
    value = _definition()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkPriceFixingModel._default_manager.get()
    with connection.cursor() as cursor, pytest.raises(IntegrityError):
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_price_fixing SET persisted_at=%s WHERE id=%s",
            [NOW - timedelta(microseconds=1), row.pk],
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_price_fixing SET ledger_header_hash=%s WHERE id=%s",
            ["1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkPriceFixingCorruption, match="ledger seal"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


def test_codec_rejects_noncanonical_cutoff_source_and_unknown_fields() -> None:
    payload = encode_policy_benchmark_price_fixing(_definition())
    with pytest.raises(PolicyBenchmarkPriceFixingCodecError, match="non-canonical"):
        decode_policy_benchmark_price_fixing({**payload, "valuation_cutoff_local": "15:30"})
    sources = list(payload["source_priority"])  # type: ignore[arg-type]
    sources[0] = {**sources[0], "ordinal": True}  # type: ignore[arg-type]
    with pytest.raises(PolicyBenchmarkPriceFixingCodecError):
        decode_policy_benchmark_price_fixing({**payload, "source_priority": sources})
    with pytest.raises(PolicyBenchmarkPriceFixingCodecError, match="shape"):
        decode_policy_benchmark_price_fixing({**payload, "current": True})


def test_migration_is_schema_only_zero_seed_and_matches_runtime_model() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0022_policy_benchmark_price_fixing"
    ).Migration
    assert migration.dependencies == [("portfolio", "0021_policy_benchmark_trading_calendar")]
    assert len(migration.operations) == 1
    assert not any(isinstance(item, (RunPython, RunSQL)) for item in migration.operations)
    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkPriceFixingModel")

    def fields(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        result = []
        for field in model_type._meta.local_fields:
            _, path, args, kwargs = field.deconstruct()
            result.append((field.name, path, args, kwargs))
        return result

    assert fields(rendered) == fields(PortfolioPolicyBenchmarkPriceFixingModel)
    assert [item.deconstruct() for item in rendered._meta.indexes] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkPriceFixingModel._meta.indexes
    ]
    assert [item.deconstruct() for item in rendered._meta.constraints] == [
        item.deconstruct() for item in PortfolioPolicyBenchmarkPriceFixingModel._meta.constraints
    ]
