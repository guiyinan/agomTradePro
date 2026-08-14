"""Pure contract tests for inactive Portfolio policy benchmark snapshots."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_snapshot import (
    POLICY_BENCHMARK_SNAPSHOT_BLOCKERS,
    PolicyBenchmarkComponent,
    PolicyBenchmarkSourceRef,
    PortfolioPolicyBenchmarkSnapshot,
    validate_policy_benchmark_snapshot_successor,
)

NOW = datetime(2026, 8, 13, 2, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _source(
    owner: str,
    artifact_type: str,
    artifact_id: str,
    *,
    content_hash: str = HASH_A,
    recorded_at: datetime = NOW - timedelta(hours=2),
    valid_until: datetime = NOW + timedelta(days=30),
) -> PolicyBenchmarkSourceRef:
    return PolicyBenchmarkSourceRef(
        owner=owner,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        artifact_version="v1",
        content_hash=content_hash,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _snapshot(**changes: object) -> PortfolioPolicyBenchmarkSnapshot:
    values: dict[str, object] = {
        "snapshot_id": "benchmark-snapshot-1",
        "snapshot_version": "v1",
        "account_namespace": "unified_account",
        "account_id": "42",
        "owner_user_id": 7,
        "base_currency": "CNY",
        "account_identity_ref": _source(
            "account",
            "unified_account_identity_snapshot",
            "account-42",
            content_hash=HASH_A,
            valid_until=NOW + timedelta(days=90),
        ),
        "planning_policy_ref": _source(
            "portfolio",
            "planning_policy_activation",
            "planning-policy-1",
            content_hash=HASH_B,
            valid_until=NOW + timedelta(days=60),
        ),
        "benchmark_definition_ref": _source(
            "portfolio",
            "policy_benchmark_definition",
            "benchmark-definition-1",
            content_hash=HASH_C,
            valid_until=NOW + timedelta(days=30),
        ),
        "components": (
            PolicyBenchmarkComponent(benchmark_code="000300.SH", weight=Decimal("0.6"), ordinal=0),
            PolicyBenchmarkComponent(benchmark_code="000905.SH", weight=Decimal("0.4"), ordinal=1),
        ),
        "cash_weight": Decimal("0"),
        "inception_at": NOW - timedelta(days=1),
        "observed_at": NOW - timedelta(hours=1),
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkSnapshot(**values)  # type: ignore[arg-type]


def test_snapshot_is_content_addressed_but_permanently_inactive() -> None:
    snapshot = _snapshot()

    assert len(snapshot.identity_hash) == 64
    assert len(snapshot.content_hash) == 64
    assert snapshot.permission == "inactive"
    assert snapshot.blocker_codes == POLICY_BENCHMARK_SNAPSHOT_BLOCKERS
    assert snapshot.activation_available is False
    assert snapshot.must_not_execute is True
    assert snapshot.is_knowable_at(NOW) is True

    payload = snapshot.to_payload()
    assert payload["owner"] == "portfolio"
    assert payload["artifact_type"] == "policy_benchmark_snapshot"
    assert payload["schema"] == "portfolio-policy-benchmark-snapshot.v1"
    assert payload["cash_weight"] == "0"
    assert payload["components"] == [
        {"benchmark_code": "000300.SH", "weight": "0.6", "ordinal": 0},
        {"benchmark_code": "000905.SH", "weight": "0.4", "ordinal": 1},
    ]


@pytest.mark.parametrize(
    ("owner", "artifact_type", "field_name"),
    [
        ("portfolio", "unified_account_identity_snapshot", "account_identity_ref"),
        ("account", "planning_policy_activation", "planning_policy_ref"),
        ("simulated_trading", "policy_benchmark_definition", "benchmark_definition_ref"),
    ],
)
def test_snapshot_rejects_wrong_source_owner_or_type(
    owner: str, artifact_type: str, field_name: str
) -> None:
    snapshot = _snapshot()
    bad_ref = _source(owner, artifact_type, "substituted-source")

    with pytest.raises(ValueError, match="owner or artifact type"):
        _snapshot(**{field_name: bad_ref})


def test_source_ref_requires_exact_hash_and_aware_valid_window() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        _source("account", "unified_account_identity_snapshot", "account-42", content_hash="bad")
    with pytest.raises(ValueError, match="timezone-aware"):
        _source(
            "account",
            "unified_account_identity_snapshot",
            "account-42",
            recorded_at=datetime(2026, 8, 13),
        )
    with pytest.raises(ValueError, match="validity window"):
        _source(
            "account",
            "unified_account_identity_snapshot",
            "account-42",
            valid_until=NOW - timedelta(days=3),
        )


@pytest.mark.parametrize("weight", [0.5, 1, True, Decimal("NaN"), Decimal("Infinity")])
def test_component_requires_exact_finite_decimal(weight: object) -> None:
    with pytest.raises((TypeError, ValueError), match="weight"):
        PolicyBenchmarkComponent(
            benchmark_code="000300.SH",
            weight=weight,  # type: ignore[arg-type]
            ordinal=0,
        )


@pytest.mark.parametrize("weight", [Decimal("0"), Decimal("-0"), Decimal("-0.1"), Decimal("1.1")])
def test_component_rejects_out_of_range_or_negative_zero(weight: Decimal) -> None:
    with pytest.raises(ValueError, match="weight"):
        PolicyBenchmarkComponent(benchmark_code="000300.SH", weight=weight, ordinal=0)


def test_snapshot_rejects_duplicate_codes_and_non_contiguous_ordinals() -> None:
    duplicate = (
        PolicyBenchmarkComponent("000300.SH", Decimal("0.5"), 0),
        PolicyBenchmarkComponent("000300.SH", Decimal("0.5"), 1),
    )
    with pytest.raises(ValueError, match="unique"):
        _snapshot(components=duplicate)

    gap = (
        PolicyBenchmarkComponent("000300.SH", Decimal("0.5"), 0),
        PolicyBenchmarkComponent("000905.SH", Decimal("0.5"), 2),
    )
    with pytest.raises(ValueError, match="ordinal"):
        _snapshot(components=gap)


def test_snapshot_does_not_normalize_component_weights() -> None:
    components = (
        PolicyBenchmarkComponent("000300.SH", Decimal("0.6"), 0),
        PolicyBenchmarkComponent("000905.SH", Decimal("0.3"), 1),
    )
    with pytest.raises(ValueError, match="sum exactly to one"):
        _snapshot(components=components)


@pytest.mark.parametrize("cash_weight", [Decimal("0.1"), 0, -0.0])
def test_cash_weight_is_exact_decimal_and_fixed_zero(cash_weight: object) -> None:
    with pytest.raises((TypeError, ValueError), match="cash_weight"):
        _snapshot(cash_weight=cash_weight)


def test_valid_until_must_equal_strict_source_minimum() -> None:
    with pytest.raises(ValueError, match="strict source minimum"):
        _snapshot(valid_until=NOW + timedelta(days=29))


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": NOW - timedelta(days=2)},
        {"recorded_at": NOW - timedelta(hours=2)},
        {"recorded_at": NOW + timedelta(days=30)},
    ],
)
def test_snapshot_rejects_invalid_clock_order(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="clock"):
        _snapshot(**changes)


def test_snapshot_rejects_a_source_not_knowable_at_recording() -> None:
    future_source = _source(
        "portfolio",
        "planning_policy_activation",
        "planning-policy-1",
        content_hash=HASH_B,
        recorded_at=NOW + timedelta(seconds=1),
        valid_until=NOW + timedelta(days=60),
    )
    with pytest.raises(ValueError, match="source is not knowable"):
        _snapshot(planning_policy_ref=future_source)


def test_any_authoritative_change_changes_content_hash() -> None:
    snapshot = _snapshot()
    changed_component = (
        PolicyBenchmarkComponent("000300.SH", Decimal("0.7"), 0),
        PolicyBenchmarkComponent("000905.SH", Decimal("0.3"), 1),
    )
    changed = _snapshot(components=changed_component)

    assert changed.identity_hash == snapshot.identity_hash
    assert changed.content_hash != snapshot.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(snapshot, components=changed_component)


def test_successor_binds_same_account_and_advances_clock() -> None:
    previous = _snapshot()
    successor = _snapshot(
        snapshot_id="benchmark-snapshot-2",
        snapshot_version="v2",
        observed_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=2),
        supersedes_snapshot_hash=previous.content_hash,
    )

    validate_policy_benchmark_snapshot_successor(previous, successor)

    with pytest.raises(ValueError, match="account identity"):
        validate_policy_benchmark_snapshot_successor(
            previous,
            _snapshot(
                snapshot_id="benchmark-snapshot-3",
                snapshot_version="v3",
                account_id="43",
                observed_at=NOW + timedelta(hours=1),
                recorded_at=NOW + timedelta(hours=2),
                supersedes_snapshot_hash=previous.content_hash,
            ),
        )


def test_domain_module_has_no_framework_or_cross_app_imports() -> None:
    source = Path("apps/portfolio/domain/policy_benchmark_snapshot.py").read_text(encoding="utf-8")

    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
