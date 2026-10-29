"""Exact local daily simulation policy and runtime-binding contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
    LocalDailySimulationPolicyBinding,
    LocalDailySimulationPolicyError,
    LocalDailySimulationPolicyRuntimeProvenance,
)

_POLICY_SCHEMA = "local-daily-simulation-policy.v1"
_BINDING_SCHEMA = "local-daily-simulation-policy-binding.v1"
_READ_AT = datetime(2026, 10, 29, 7, tzinfo=UTC)
_UUID = "2c5e5a47-ef3a-4d03-8d13-a2e1054927b4"


def _policy_payload() -> dict[str, object]:
    """Return one complete explicitly approved daily-simulation policy payload."""

    return {
        "schema_version": _POLICY_SCHEMA,
        "purpose": "historical_daily_simulation",
        "policy_id": "local-daily-a-share",
        "version": "approved-1",
        "price_publication_key": "equity.price.bar.daily",
        "provider_configuration_id": 17,
        "provider_name": "tushare",
        "instrument_snapshot_id": _UUID,
        "currency": "CNY",
        "frequency": "1d",
        "adjustment": "none",
        "volume_unit": "shares",
        "participation_rate": "0.1250",
        "share_step": "100",
        "allowed_qmt_suspend_flags": [-1, 0],
        "currency_basis": "same_session_stock_basic_capture",
        "qmt_status_basis": "owner_authenticated_normalized_daily_status",
        "limit_price_basis": "same_provider_cny_listing_native",
    }


def _provenance_payload() -> dict[str, object]:
    """Return one complete active-profile and snapshot provenance payload."""

    return {
        "runtime_environment": "development",
        "profile_id": "daily-simulation-profile",
        "profile_key": "development-profile",
        "profile_version": 4,
        "profile_content_hash": "a" * 64,
        "profile_activated_at": "2026-10-29T04:00:00Z",
        "snapshot_id": "daily-simulation-snapshot",
        "snapshot_content_hash": "b" * 64,
        "snapshot_generated_at": "2026-10-29T04:00:00Z",
        "snapshot_effective_from": "2026-10-29T04:00:00Z",
        "read_at": "2026-10-29T07:00:00Z",
    }


def _binding_payload() -> dict[str, object]:
    """Return a complete policy binding without any caller-supplied digest."""

    return {
        "schema_version": _BINDING_SCHEMA,
        "policy": _policy_payload(),
        "runtime_provenance": _provenance_payload(),
    }


def test_policy_round_trip_hash_and_explicit_simulation_scope() -> None:
    payload = _policy_payload()

    policy = LocalDailySimulationPolicy.from_payload(payload)

    assert policy.to_payload() == payload
    assert policy.purpose == "historical_daily_simulation"
    assert policy.provider_configuration_id == 17
    assert policy.instrument_snapshot_id == _UUID
    assert policy.currency == "CNY"
    assert policy.participation_rate == Decimal("0.1250")
    assert policy.share_step == Decimal("100")
    assert policy.allowed_qmt_suspend_flags == (-1, 0)
    assert policy.content_hash == LocalDailySimulationPolicy.from_payload(payload).content_hash
    with pytest.raises(FrozenInstanceError):
        policy.provider_name = "other"  # type: ignore[misc]


def test_policy_accepts_provider_configuration_display_name_with_internal_space() -> None:
    payload = {**_policy_payload(), "provider_name": "Tushare Pro"}

    policy = LocalDailySimulationPolicy.from_payload(payload)

    assert policy.provider_name == "Tushare Pro"
    assert policy.to_payload() == payload


@pytest.mark.parametrize(
    "provider_name",
    [" Tushare Pro", "Tushare Pro ", "Tushare\x00Pro", "T" * 101],
)
def test_policy_rejects_provider_configuration_name_with_outer_space_or_control(
    provider_name: str,
) -> None:
    payload = {**_policy_payload(), "provider_name": provider_name}

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


@pytest.mark.parametrize("payload", [None, [], "policy", {1: "bad"}])
def test_policy_decoder_requires_an_exact_json_object(payload: object) -> None:
    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


@pytest.mark.parametrize("change", ["missing", "extra", "schema"])
def test_policy_decoder_rejects_missing_unknown_or_other_schema(change: str) -> None:
    payload = _policy_payload()
    if change == "missing":
        payload.pop("share_step")
    elif change == "extra":
        payload["caller_hash"] = "a" * 64
    else:
        payload["schema_version"] = "local-daily-simulation-policy.v2"

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "apply_time_initial_position_mark"),
        ("policy_id", ""),
        ("version", "with space"),
        ("price_publication_key", ""),
        ("provider_configuration_id", True),
        ("provider_configuration_id", 0),
        ("provider_configuration_id", "17"),
        ("provider_name", ""),
        ("instrument_snapshot_id", None),
        ("instrument_snapshot_id", "2C5E5A47-EF3A-4D03-8D13-A2E1054927B4"),
        ("instrument_snapshot_id", "not-a-uuid"),
        ("currency", "USD"),
        ("frequency", "5m"),
        ("adjustment", "qfq"),
        ("volume_unit", "lots"),
        ("currency_basis", "today_only"),
        ("qmt_status_basis", "provider_label"),
        ("limit_price_basis", "static_ratio"),
    ],
)
def test_policy_decoder_rejects_wrong_identity_types_and_unsupported_semantics(
    field: str,
    value: object,
) -> None:
    payload = _policy_payload()
    payload[field] = value

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("participation_rate", 0.1),
        ("participation_rate", "not-a-decimal"),
        ("participation_rate", "NaN"),
        ("participation_rate", "Infinity"),
        ("participation_rate", "0"),
        ("participation_rate", "1.0001"),
        ("participation_rate", "1e-1"),
        ("share_step", False),
        ("share_step", "0"),
        ("share_step", "-1"),
        ("share_step", "1e2"),
    ],
)
def test_policy_rejects_inexact_nonfinite_noncanonical_or_out_of_range_decimals(
    field: str,
    value: object,
) -> None:
    payload = _policy_payload()
    payload[field] = value

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


@pytest.mark.parametrize(
    "flags",
    [[], [1], [0, 1], [False], [0, 0], "0", None],
)
def test_policy_rejects_missing_unknown_or_malformed_suspend_flags(flags: object) -> None:
    payload = _policy_payload()
    payload["allowed_qmt_suspend_flags"] = flags

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


def test_policy_payload_and_canonical_hash_bind_decimal_scale_and_every_field() -> None:
    original_payload = _policy_payload()
    changed_payload = {**original_payload, "participation_rate": "0.125"}
    original = LocalDailySimulationPolicy.from_payload(original_payload)
    changed = LocalDailySimulationPolicy.from_payload(changed_payload)

    assert original.content_hash != changed.content_hash
    assert original.to_payload()["participation_rate"] == "0.1250"
    assert (
        LocalDailySimulationPolicy.from_payload(
            {**original_payload, "provider_name": "vendor-two"}
        ).content_hash
        != original.content_hash
    )
    assert original.identity == "historical_daily_simulation:local-daily-a-share:approved-1"


@pytest.mark.parametrize(
    "field_values",
    [
        {"participation_rate": 0.125},
        {"participation_rate": Decimal("1.1")},
        {"share_step": Decimal("1e-65")},
        {"share_step": Decimal("0")},
    ],
)
def test_policy_direct_constructor_rejects_wrong_decimal_type_or_exact_bounds(
    field_values: dict[str, object],
) -> None:
    policy = LocalDailySimulationPolicy.from_payload(_policy_payload())

    with pytest.raises(LocalDailySimulationPolicyError):
        replace(policy, **field_values)


def test_runtime_provenance_round_trip_and_chronology() -> None:
    provenance = LocalDailySimulationPolicyRuntimeProvenance.from_payload(_provenance_payload())

    assert provenance.to_payload() == _provenance_payload()
    assert provenance.read_at == _READ_AT
    assert provenance.profile_version == 4


def test_runtime_provenance_rejects_naive_direct_clock() -> None:
    provenance = LocalDailySimulationPolicyRuntimeProvenance.from_payload(_provenance_payload())

    with pytest.raises(LocalDailySimulationPolicyError):
        replace(provenance, read_at=datetime(2026, 10, 29, 7))


def test_runtime_provenance_rejects_clock_that_overflows_utc_serialization() -> None:
    last_representable_local = datetime(9999, 12, 31, 23, 59, tzinfo=timezone(-timedelta(hours=14)))
    provenance = LocalDailySimulationPolicyRuntimeProvenance(
        runtime_environment="development",
        profile_id="daily-simulation-profile",
        profile_key="development-profile",
        profile_version=4,
        profile_content_hash="a" * 64,
        profile_activated_at=last_representable_local,
        snapshot_id="daily-simulation-snapshot",
        snapshot_content_hash="b" * 64,
        snapshot_generated_at=last_representable_local,
        snapshot_effective_from=last_representable_local,
        read_at=last_representable_local,
    )

    with pytest.raises(LocalDailySimulationPolicyError):
        provenance.to_payload()


@pytest.mark.parametrize(
    "change",
    ["missing", "extra", "bad_hash", "bad_version", "naive", "future", "bad_text"],
)
def test_runtime_provenance_decoder_rejects_malformed_identity_hash_and_clocks(
    change: str,
) -> None:
    payload = _provenance_payload()
    if change == "missing":
        payload.pop("snapshot_id")
    elif change == "extra":
        payload["runtime_profile_status"] = "active"
    elif change == "bad_hash":
        payload["snapshot_content_hash"] = "sha256:" + "b" * 64
    elif change == "bad_version":
        payload["profile_version"] = True
    elif change == "naive":
        payload["read_at"] = "2026-10-29T07:00:00"
    elif change == "future":
        payload["snapshot_generated_at"] = "2026-10-29T07:00:01Z"
    else:
        payload["read_at"] = "not-a-clock"

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicyRuntimeProvenance.from_payload(payload)


def test_binding_round_trip_recomputes_digest_and_rejects_supplied_hash() -> None:
    payload = _binding_payload()

    binding = LocalDailySimulationPolicyBinding.from_payload(payload)

    assert binding.to_payload() == payload
    assert (
        binding.proof_content_hash
        == LocalDailySimulationPolicyBinding.from_payload(payload).proof_content_hash
    )
    assert "proof_content_hash" not in binding.to_payload()
    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicyBinding.from_payload(
            {**payload, "proof_content_hash": binding.proof_content_hash}
        )
    binding.validate_at(as_of=_READ_AT)
    with pytest.raises(LocalDailySimulationPolicyError):
        binding.validate_at(as_of=_READ_AT - timedelta(seconds=1))


@pytest.mark.parametrize("change", ["schema", "policy", "provenance", "extra"])
def test_binding_decoder_rejects_mixed_or_unknown_nested_payloads(change: str) -> None:
    payload = _binding_payload()
    if change == "schema":
        payload["schema_version"] = "local-daily-simulation-policy-binding.v2"
    elif change == "policy":
        payload["policy"] = {**_policy_payload(), "purpose": "other"}
    elif change == "provenance":
        payload["runtime_provenance"] = {**_provenance_payload(), "unknown": True}
    else:
        payload["extra"] = "not-accepted"

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicyBinding.from_payload(payload)


def test_policy_and_binding_require_exact_nested_types() -> None:
    policy = LocalDailySimulationPolicy.from_payload(_policy_payload())
    provenance = LocalDailySimulationPolicyRuntimeProvenance.from_payload(_provenance_payload())
    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicyBinding(policy=object(), provenance=provenance)  # type: ignore[arg-type]
    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicyBinding(policy=policy, provenance=object())  # type: ignore[arg-type]
    with pytest.raises(LocalDailySimulationPolicyError):
        replace(policy, allowed_qmt_suspend_flags=(1,))


def test_policy_decoder_rejects_non_string_identity_field() -> None:
    payload = _policy_payload()
    payload["provider_name"] = 17

    with pytest.raises(LocalDailySimulationPolicyError):
        LocalDailySimulationPolicy.from_payload(payload)


def test_runtime_provenance_rejects_nonpositive_direct_profile_version() -> None:
    provenance = LocalDailySimulationPolicyRuntimeProvenance.from_payload(_provenance_payload())

    with pytest.raises(LocalDailySimulationPolicyError):
        replace(provenance, profile_version=0)
