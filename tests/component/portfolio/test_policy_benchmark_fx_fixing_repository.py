"""Component coverage for benchmark FX-fixing persistence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.db.migrations import RunPython, RunSQL
from django.db.migrations.state import ProjectState

from apps.portfolio.domain.policy_benchmark_fx_fixing import (
    PolicyBenchmarkFxSourceRef,
    PortfolioPolicyBenchmarkFxFixing,
)
from apps.portfolio.infrastructure.policy_benchmark_fx_fixing_codec import (
    PolicyBenchmarkFxFixingCodecError,
    decode_policy_benchmark_fx_fixing,
    encode_policy_benchmark_fx_fixing,
)
from apps.portfolio.infrastructure.policy_benchmark_fx_fixing_models import (
    PortfolioPolicyBenchmarkFxFixingModel,
)
from apps.portfolio.infrastructure.policy_benchmark_fx_fixing_repository import (
    DjangoPolicyBenchmarkFxFixingRepository,
    PolicyBenchmarkFxFixingConflict,
    PolicyBenchmarkFxFixingCorruption,
    _model_values,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)
VALID = NOW + timedelta(days=30)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _value(**changes: object) -> PortfolioPolicyBenchmarkFxFixing:
    source = PolicyBenchmarkFxSourceRef(
        "portfolio",
        "benchmark_fx_source_definition",
        "official",
        "v1",
        "a" * 64,
        0,
        NOW - timedelta(hours=1),
        VALID,
    )
    values: dict[str, object] = {
        "methodology_id": "usdcny-fixing",
        "methodology_version": "v1",
        "base_currency": "USD",
        "quote_currency": "CNY",
        "fixing_convention": "quote_per_base",
        "inverse_rate_allowed": False,
        "timezone": "Asia/Shanghai",
        "valuation_cutoff_local": time(16, 30),
        "source_priority": (source,),
        "stale_after_seconds": 86400,
        "triangulation_policy": "prohibited",
        "source_failure_policy": "block",
        "missing_fx_policy": "fail_closed",
        "recorded_at": NOW,
        "valid_until": VALID,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkFxFixing(**values)  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
def test_roundtrip_idempotency_and_exact_pit() -> None:
    repo = DjangoPolicyBenchmarkFxFixingRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        assert repo.append(value, recorded_at=NOW) == value
        assert repo.append(value, recorded_at=NOW) == value
    assert decode_policy_benchmark_fx_fixing(encode_policy_benchmark_fx_fixing(value)) == value
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
def test_private_uow_and_first_winner() -> None:
    repo = DjangoPolicyBenchmarkFxFixingRepository(clock=FixedClock(NOW))
    value = _value()
    with pytest.raises(PolicyBenchmarkFxFixingConflict, match="private unit"):
        repo.append(value, recorded_at=NOW)
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    with repo.atomic(), pytest.raises(PolicyBenchmarkFxFixingConflict, match="first winner"):
        repo.append(_value(stale_after_seconds=1), recorded_at=NOW)


@pytest.mark.django_db(transaction=True)
def test_mutation_paths_blocked() -> None:
    repo = DjangoPolicyBenchmarkFxFixingRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkFxFixingModel._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkFxFixingModel._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        PortfolioPolicyBenchmarkFxFixingModel._default_manager.bulk_create(
            [PortfolioPolicyBenchmarkFxFixingModel(**_model_values(value, NOW))]
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_and_source_header_tamper() -> None:
    repo = DjangoPolicyBenchmarkFxFixingRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkFxFixingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_fx_fixing SET methodology_id=%s, identity_hash=%s, content_hash=%s WHERE id=%s",
            ["hidden", "0" * 64, "1" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkFxFixingCorruption):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


@pytest.mark.django_db(transaction=True)
def test_header_seals() -> None:
    repo = DjangoPolicyBenchmarkFxFixingRepository(clock=FixedClock(NOW))
    value = _value()
    with repo.atomic():
        repo.append(value, recorded_at=NOW)
    row = PortfolioPolicyBenchmarkFxFixingModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_policy_benchmark_fx_fixing SET sources_hash=%s WHERE id=%s",
            ["0" * 64, row.pk],
        )
    with pytest.raises(PolicyBenchmarkFxFixingCorruption, match="headers"):
        repo.get_exact(
            methodology_id=value.methodology_id,
            methodology_version="v1",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )


def test_codec_rejects_noncanonical_and_unknown() -> None:
    payload = encode_policy_benchmark_fx_fixing(_value())
    with pytest.raises(PolicyBenchmarkFxFixingCodecError):
        decode_policy_benchmark_fx_fixing({**payload, "currency_pair": "CNY/USD"})
    with pytest.raises(PolicyBenchmarkFxFixingCodecError):
        decode_policy_benchmark_fx_fixing({**payload, "current": True})


def test_migration_zero_seed_and_state_drift() -> None:
    migration = importlib.import_module(
        "apps.portfolio.migrations.0023_policy_benchmark_fx_fixing"
    ).Migration
    assert migration.dependencies == [("portfolio", "0022_policy_benchmark_price_fixing")]
    assert len(migration.operations) == 1
    assert not any(isinstance(item, (RunPython, RunSQL)) for item in migration.operations)
    state = ProjectState()
    migration.operations[0].state_forwards("portfolio", state)
    rendered = state.apps.get_model("portfolio", "PortfolioPolicyBenchmarkFxFixingModel")

    def fields(
        model_type: type[models.Model],
    ) -> list[tuple[str, str, tuple[object, ...], dict[str, object]]]:
        return [
            (field.name, field.deconstruct()[1], field.deconstruct()[2], field.deconstruct()[3])
            for field in model_type._meta.local_fields
        ]

    assert fields(rendered) == fields(PortfolioPolicyBenchmarkFxFixingModel)
    assert [x.deconstruct() for x in rendered._meta.constraints] == [
        x.deconstruct() for x in PortfolioPolicyBenchmarkFxFixingModel._meta.constraints
    ]
