"""Tests for the immutable A-share settlement contract and its read boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import cast

import pytest

from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3Corruption,
    ExecutionSettlementV3InputError,
    ExecutionSettlementV3ReadRecord,
    ExecutionSettlementV3Unavailable,
    ReadEffectiveExecutionSettlementV3UseCase,
)
from apps.risk_center.domain.execution_settlement_v3 import (
    MAX_SETTLEMENT_LAG_SESSIONS,
    ExecutionSettlementBundleV3,
    ExecutionSettlementV3ValidationError,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
)
from apps.risk_center.infrastructure.ashare_execution_rule_v3_codec import (
    ASHARE_EXECUTION_RULES_V3_SCHEMA,
    AShareExecutionRuleV3CodecError,
    decode_a_share_execution_settlement_bundle,
    encode_a_share_execution_settlement_bundle,
    parse_a_share_execution_rule_v3_manifest,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _rule_v1() -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id="settlement-v3-rule",
        rule_version="1",
        security_id="SH.SETTLEMENT.SECURITY",
        market="SH",
        board="MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("100000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="exchange-source",
        rule_source_version="2026-10",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=AS_OF - timedelta(minutes=30),
        valid_until=AS_OF + timedelta(days=1),
    )


def _rule_v2(v1: AShareExecutionRule | None = None) -> ExecutionSubmissionRuleV2:
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=v1 if v1 is not None else _rule_v1(),
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board="MAIN",
            price_tick=Decimal("0.01"),
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=10,
            sell_widening_ticks=10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )


def _policy(
    v2: ExecutionSubmissionRuleV2 | None = None,
    *,
    source_observed_at: datetime = AS_OF - timedelta(days=1),
) -> SettlementPolicyV1:
    base_v2 = v2 if v2 is not None else _rule_v2()
    base = base_v2.execution_rule_v1
    return SettlementPolicyV1(
        policy_id="settlement-policy-main",
        policy_version="1",
        security_id=base.security_id,
        market=base.market,
        board=base.board,
        settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
        settlement_lag_sessions=1,
        bound_execution_rule_v2_hash=base_v2.content_hash,
        source_id="settlement-source",
        source_version="2026-10",
        source_hash="b" * 64,
        source_observed_at=source_observed_at,
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=base.effective_from,
        valid_until=base.valid_until,
    )


def _bundle(
    v2: ExecutionSubmissionRuleV2 | None = None,
    policy: SettlementPolicyV1 | None = None,
) -> ExecutionSettlementBundleV3:
    base_v2 = v2 if v2 is not None else _rule_v2()
    settlement_policy = policy if policy is not None else _policy(base_v2)
    return ExecutionSettlementBundleV3(
        bundle_id="settlement-bundle-main",
        bundle_version="1",
        execution_submission_v2=base_v2,
        settlement_policy_v1=settlement_policy,
    )


def _manifest_payload(bundle: ExecutionSettlementBundleV3) -> dict[str, object]:
    return {
        "schema": ASHARE_EXECUTION_RULES_V3_SCHEMA,
        "rules": [bundle.to_payload()],
    }


def _manifest_text(bundle: ExecutionSettlementBundleV3) -> str:
    return json.dumps(_manifest_payload(bundle), ensure_ascii=False, separators=(",", ":"))


def _reseal(payload: dict[str, object]) -> None:
    content = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    payload["content_hash"] = hashlib.sha256(encoded).hexdigest()


def _reseal_manifest_bundle(bundle_payload: dict[str, object]) -> None:
    policy_payload = cast(dict[str, object], bundle_payload["settlement_policy_v1"])
    _reseal(policy_payload)
    _reseal(bundle_payload)


def test_v3_seals_nested_v2_and_an_explicit_settlement_policy() -> None:
    bundle = _bundle()

    payload = bundle.to_payload()

    assert (
        payload["execution_submission_v2"]["content_hash"]
        == bundle.execution_submission_v2.content_hash
    )
    assert bundle.settlement_policy_v1.bound_execution_rule_v2_hash == (
        bundle.execution_submission_v2.content_hash
    )
    assert bundle.settlement_policy_v1.settlement_lag_sessions == 1
    assert len(bundle.content_hash) == 64


@pytest.mark.parametrize("field", ["bundle_id", "bundle_version"])
def test_v3_requires_canonical_outer_bundle_identity(field: str) -> None:
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_bundle(), **{field: " invalid ", "content_hash": ""})


def test_v3_exposes_intersected_window_and_maximum_source_availability() -> None:
    base = _rule_v2().execution_rule_v1
    policy = replace(
        _policy(),
        source_available_at=AS_OF + timedelta(hours=1),
        effective_from=base.effective_from + timedelta(hours=1),
        valid_until=base.valid_until - timedelta(hours=1),
        content_hash="",
    )

    bundle = _bundle(policy=policy)

    assert bundle.effective_from == policy.effective_from
    assert bundle.valid_until == policy.valid_until
    assert bundle.source_available_at == policy.source_available_at
    assert bundle.latest_source_observed_at == policy.source_observed_at
    assert bundle.oldest_source_observed_at == policy.source_observed_at


def test_v3_keeps_distinct_oldest_and_latest_source_observation_clocks() -> None:
    nested_v1 = replace(_rule_v1(), source_observed_at=AS_OF - timedelta(days=3), content_hash="")
    nested_v2 = _rule_v2(nested_v1)
    policy = _policy(nested_v2, source_observed_at=AS_OF - timedelta(days=2))

    bundle = _bundle(nested_v2, policy)

    assert nested_v2.execution_rule_v1.source_observed_at == AS_OF - timedelta(days=3)
    assert bundle.settlement_policy_v1.source_observed_at == AS_OF - timedelta(days=2)
    assert bundle.latest_source_observed_at == AS_OF - timedelta(days=2)
    assert bundle.oldest_source_observed_at == AS_OF - timedelta(days=3)


@pytest.mark.parametrize(
    "base_available_at",
    [AS_OF + timedelta(minutes=30), AS_OF + timedelta(hours=1)],
)
def test_v3_rejects_source_availability_at_or_after_intersected_bundle_expiry(
    base_available_at: datetime,
) -> None:
    nested_v1 = replace(_rule_v1(), source_available_at=base_available_at, content_hash="")
    nested_v2 = _rule_v2(nested_v1)
    policy = replace(
        _policy(nested_v2),
        valid_until=AS_OF + timedelta(minutes=30),
        content_hash="",
    )

    with pytest.raises(ExecutionSettlementV3ValidationError):
        _bundle(nested_v2, policy)


def test_v3_versions_settlement_bundle_without_changing_nested_v2() -> None:
    original = _bundle()
    original_payload = original.to_payload()
    base = original.execution_submission_v2.execution_rule_v1
    next_policy = replace(
        _policy(original.execution_submission_v2),
        policy_version="2",
        source_available_at=AS_OF,
        effective_from=AS_OF,
        valid_until=base.valid_until,
        content_hash="",
    )
    replacement = ExecutionSettlementBundleV3(
        bundle_id=original.bundle_id,
        bundle_version="2",
        execution_submission_v2=original.execution_submission_v2,
        settlement_policy_v1=next_policy,
    )

    assert replacement.execution_submission_v2 is original.execution_submission_v2
    assert (
        replacement.execution_submission_v2.content_hash
        == original.execution_submission_v2.content_hash
    )
    assert replacement.settlement_policy_v1.policy_version == "2"
    assert replacement.effective_from == AS_OF
    assert replacement.valid_until == base.valid_until
    assert replacement.content_hash != original.content_hash
    assert original.to_payload() == original_payload
    assert original.bundle_version == "1"


@pytest.mark.parametrize("lag", [-1, True, MAX_SETTLEMENT_LAG_SESSIONS + 1])
def test_v3_rejects_invalid_or_resource_unbounded_settlement_lag(lag: object) -> None:
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_policy(), settlement_lag_sessions=cast(int, lag))


@pytest.mark.parametrize(
    "field,value",
    [
        ("security_id", "SZ.SETTLEMENT.SECURITY"),
        ("market", "SZ"),
        ("board", "STAR"),
        ("bound_execution_rule_v2_hash", "c" * 64),
    ],
)
def test_v3_requires_policy_scope_to_match_exact_v2_rule(field: str, value: str) -> None:
    policy = replace(_policy(), **{field: value, "content_hash": ""})

    with pytest.raises(ExecutionSettlementV3ValidationError):
        _bundle(policy=policy)


def test_v3_requires_settlement_window_inside_nested_rule_window() -> None:
    base = _rule_v2().execution_rule_v1
    policy = replace(
        _policy(),
        effective_from=base.effective_from - timedelta(seconds=1),
        content_hash="",
    )

    with pytest.raises(ExecutionSettlementV3ValidationError):
        _bundle(policy=policy)


def test_v3_rejects_bad_source_hash_and_inconsistent_source_window() -> None:
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_policy(), source_hash="not-a-sha256")
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(
            _policy(),
            source_observed_at=AS_OF,
            source_available_at=AS_OF - timedelta(seconds=1),
            content_hash="",
        )


def test_v3_rejects_noncanonical_tokens_digest_characters_and_hash_type() -> None:
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_policy(), policy_id=" bad ", content_hash="")
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_policy(), source_hash="g" * 64, content_hash="")
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_policy(), content_hash=cast(str, 17))
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(_policy(), settlement_basis=cast(SettlementBasis, "UNKNOWN"), content_hash="")


def test_v3_requires_an_explicit_lag_without_inventing_a_default() -> None:
    with pytest.raises(TypeError):
        SettlementPolicyV1(
            policy_id="settlement-policy-main",
            policy_version="1",
            security_id="SH.SETTLEMENT.SECURITY",
            market="SH",
            board="MAIN",
            settlement_basis=SettlementBasis.CN_OPEN_MARKET_SESSIONS,
            bound_execution_rule_v2_hash="c" * 64,
            source_id="settlement-source",
            source_version="2026-10",
            source_hash="b" * 64,
            source_observed_at=AS_OF - timedelta(days=1),
            source_available_at=AS_OF - timedelta(hours=1),
            effective_from=AS_OF - timedelta(minutes=30),
            valid_until=AS_OF + timedelta(days=1),
        )
    assert (
        replace(_policy(), settlement_lag_sessions=0, content_hash="").settlement_lag_sessions == 0
    )
    assert (
        replace(
            _policy(),
            settlement_lag_sessions=MAX_SETTLEMENT_LAG_SESSIONS,
            content_hash="",
        ).settlement_lag_sessions
        == MAX_SETTLEMENT_LAG_SESSIONS
    )


def test_v3_rejects_naive_and_unusable_timezone_values() -> None:
    class NoOffset(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta | None:
            return None

        def dst(self, dt: datetime | None) -> timedelta | None:
            return None

    class BrokenOffset(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta:
            raise ValueError("fixture timezone failure")

        def dst(self, dt: datetime | None) -> timedelta:
            return timedelta(0)

    for invalid in (
        datetime(2026, 10, 16, 2, 0),
        datetime(2026, 10, 16, 2, 0, tzinfo=NoOffset()),
        datetime(2026, 10, 16, 2, 0, tzinfo=BrokenOffset()),
    ):
        with pytest.raises(ExecutionSettlementV3ValidationError):
            replace(_policy(), source_available_at=invalid, content_hash="")


def test_v3_normalizes_non_utc_aware_times_to_canonical_utc_text() -> None:
    east_asia = timezone(timedelta(hours=8))
    policy = replace(
        _policy(),
        source_observed_at=(AS_OF - timedelta(days=1)).astimezone(east_asia),
        source_available_at=(AS_OF - timedelta(hours=1)).astimezone(east_asia),
        effective_from=(AS_OF - timedelta(minutes=30)).astimezone(east_asia),
        valid_until=(AS_OF + timedelta(days=1)).astimezone(east_asia),
        content_hash="",
    )

    assert policy.to_payload()["source_available_at"] == (
        AS_OF - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")


def test_v3_wraps_canonical_json_serialization_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _policy()

    def fail_json(*args: object, **kwargs: object) -> str:
        raise ValueError("fixture serialization failure")

    monkeypatch.setattr("apps.risk_center.domain.execution_settlement_v3.json.dumps", fail_json)
    with pytest.raises(ExecutionSettlementV3ValidationError, match="canonical JSON"):
        replace(policy, content_hash="")


def test_v3_rejects_invalid_source_and_effective_windows() -> None:
    policy = _policy()
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(policy, valid_until=policy.source_available_at, content_hash="")
    with pytest.raises(ExecutionSettlementV3ValidationError):
        replace(policy, effective_from=policy.valid_until, content_hash="")


def test_v3_revalidation_detects_mutated_nested_payload() -> None:
    bundle = _bundle()
    object.__setattr__(bundle.settlement_policy_v1, "settlement_lag_sessions", 2)

    with pytest.raises(ExecutionSettlementV3ValidationError):
        bundle.to_payload()


@pytest.mark.parametrize(
    "execution_submission_v2,settlement_policy_v1",
    [
        (cast(ExecutionSubmissionRuleV2, object()), _policy()),
        (_rule_v2(), cast(SettlementPolicyV1, object())),
    ],
)
def test_v3_rejects_inexact_nested_types(
    execution_submission_v2: ExecutionSubmissionRuleV2,
    settlement_policy_v1: SettlementPolicyV1,
) -> None:
    with pytest.raises(ExecutionSettlementV3ValidationError):
        ExecutionSettlementBundleV3(
            bundle_id="settlement-bundle-main",
            bundle_version="1",
            execution_submission_v2=execution_submission_v2,
            settlement_policy_v1=settlement_policy_v1,
        )


def test_v3_wraps_corrupt_nested_v2_revalidation() -> None:
    nested = _rule_v2()
    object.__setattr__(nested, "content_hash", "invalid")

    with pytest.raises(ExecutionSettlementV3ValidationError):
        ExecutionSettlementBundleV3(
            bundle_id="settlement-bundle-main",
            bundle_version="1",
            execution_submission_v2=nested,
            settlement_policy_v1=_policy(),
        )


def test_v3_codec_round_trip_preserves_v1_v2_and_outer_hashes() -> None:
    bundle = _bundle()
    manifest_text = _manifest_text(bundle)

    decoded_manifest = parse_a_share_execution_rule_v3_manifest(manifest_text)
    decoded_single = decode_a_share_execution_settlement_bundle(bundle.to_payload())

    assert decoded_manifest == (bundle,)
    assert decoded_single == bundle
    assert decoded_manifest[0].content_hash == bundle.content_hash
    assert decoded_manifest[0].execution_submission_v2.content_hash == (
        bundle.execution_submission_v2.content_hash
    )
    assert decoded_manifest[0].execution_submission_v2.execution_rule_v1.content_hash == (
        bundle.execution_submission_v2.execution_rule_v1.content_hash
    )
    assert encode_a_share_execution_settlement_bundle(bundle) == bundle.to_payload()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["rules"][0].update(unexpected="value"),
        lambda payload: payload["rules"][0].pop("bundle_id"),
        lambda payload: payload["rules"][0].pop("bundle_version"),
        lambda payload: payload["rules"][0].pop("settlement_policy_v1"),
        lambda payload: payload["rules"][0]["settlement_policy_v1"].update(unknown="value"),
        lambda payload: payload["rules"][0]["execution_submission_v2"].update(unexpected="value"),
        lambda payload: payload["rules"][0]["settlement_policy_v1"].pop("source_hash"),
    ],
)
def test_v3_codec_rejects_unknown_and_missing_fields(mutate) -> None:
    payload = json.loads(_manifest_text(_bundle()))
    mutate(payload)

    with pytest.raises(AShareExecutionRuleV3CodecError):
        parse_a_share_execution_rule_v3_manifest(json.dumps(payload))


def test_v3_codec_rejects_wrong_schema_and_duplicate_keys() -> None:
    text = _manifest_text(_bundle())
    wrong_schema = text.replace(ASHARE_EXECUTION_RULES_V3_SCHEMA, "a-share-execution-rules.v2")
    duplicate = text.replace(
        '"schema":"a-share-execution-rules.v3"',
        '"schema":"a-share-execution-rules.v3","schema":"a-share-execution-rules.v3"',
    )

    with pytest.raises(AShareExecutionRuleV3CodecError):
        parse_a_share_execution_rule_v3_manifest(wrong_schema)
    with pytest.raises(AShareExecutionRuleV3CodecError, match="duplicate"):
        parse_a_share_execution_rule_v3_manifest(duplicate)


@pytest.mark.parametrize(
    "change",
    [
        lambda policy: policy.update(settlement_lag_sessions=True),
        lambda policy: policy.update(settlement_lag_sessions=1.0),
        lambda policy: policy.update(settlement_lag_sessions=MAX_SETTLEMENT_LAG_SESSIONS + 1),
        lambda policy: policy.update(settlement_lag_sessions=-1),
        lambda policy: policy.update(settlement_basis="FUTURE_BASIS"),
        lambda policy: policy.update(source_hash="f" * 63),
        lambda policy: policy.update(source_hash="g" * 64),
        lambda policy: policy.update(source_available_at="2026-10-16T01:00:00+00:00"),
    ],
)
def test_v3_codec_rejects_noncanonical_policy_values_after_resealing(change) -> None:
    payload = json.loads(_manifest_text(_bundle()))
    bundle_payload = cast(dict[str, object], payload["rules"][0])
    policy_payload = cast(dict[str, object], bundle_payload["settlement_policy_v1"])
    change(policy_payload)
    _reseal_manifest_bundle(bundle_payload)

    with pytest.raises(AShareExecutionRuleV3CodecError):
        parse_a_share_execution_rule_v3_manifest(json.dumps(payload))


def test_v3_codec_rejects_nonfinite_json_and_noncanonical_nested_v2_decimal() -> None:
    text = _manifest_text(_bundle())
    with pytest.raises(AShareExecutionRuleV3CodecError):
        parse_a_share_execution_rule_v3_manifest(
            text.replace('"settlement_lag_sessions":1', '"settlement_lag_sessions":NaN')
        )

    payload = json.loads(text)
    bundle_payload = cast(dict[str, object], payload["rules"][0])
    nested = cast(dict[str, object], bundle_payload["execution_submission_v2"])
    price = cast(dict[str, object], nested["price_submission_range"])
    price["price_tick"] = "0.010"
    _reseal(nested)
    _reseal(bundle_payload)
    with pytest.raises(AShareExecutionRuleV3CodecError):
        parse_a_share_execution_rule_v3_manifest(json.dumps(payload))


def test_v3_codec_rejects_overlong_decimal_and_corrupt_outer_hash() -> None:
    payload = json.loads(_manifest_text(_bundle()))
    bundle_payload = cast(dict[str, object], payload["rules"][0])
    nested = cast(dict[str, object], bundle_payload["execution_submission_v2"])
    price = cast(dict[str, object], nested["price_submission_range"])
    price["price_tick"] = "0." + ("0" * 300) + "1"
    _reseal(nested)
    _reseal(bundle_payload)
    with pytest.raises(AShareExecutionRuleV3CodecError):
        parse_a_share_execution_rule_v3_manifest(json.dumps(payload))

    bad_hash = _bundle().to_payload()
    bad_hash["content_hash"] = "0" * 64
    with pytest.raises(AShareExecutionRuleV3CodecError):
        decode_a_share_execution_settlement_bundle(bad_hash)


class _ReadPort:
    def __init__(self, record: object) -> None:
        self.record = record
        self.request: tuple[str, datetime] | None = None

    def get_effective_settlement_bundle(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord:
        self.request = (security_id, as_of)
        return cast(ExecutionSettlementV3ReadRecord, self.record)


def _record(
    bundle: ExecutionSettlementBundleV3 | None = None,
    *,
    recorded_at: datetime = AS_OF - timedelta(minutes=10),
) -> ExecutionSettlementV3ReadRecord:
    return ExecutionSettlementV3ReadRecord(
        bundle=bundle if bundle is not None else _bundle(),
        recorded_at=recorded_at,
    )


def test_v3_read_use_case_checks_scope_source_effective_and_local_knowledge_windows() -> None:
    bundle = _bundle()
    port = _ReadPort(_record(bundle))

    result = ReadEffectiveExecutionSettlementV3UseCase(port).execute(
        security_id=bundle.settlement_policy_v1.security_id,
        as_of=AS_OF,
    )

    assert result == bundle
    assert port.request == (bundle.settlement_policy_v1.security_id, AS_OF)


def test_v3_read_use_case_respects_narrower_policy_window() -> None:
    base = _rule_v2().execution_rule_v1
    policy = replace(
        _policy(),
        effective_from=base.effective_from + timedelta(hours=1),
        valid_until=base.valid_until - timedelta(hours=1),
        content_hash="",
    )
    bundle = _bundle(policy=policy)

    with pytest.raises(ExecutionSettlementV3Corruption):
        ReadEffectiveExecutionSettlementV3UseCase(_ReadPort(_record(bundle))).execute(
            security_id="SH.SETTLEMENT.SECURITY", as_of=AS_OF
        )


@pytest.mark.parametrize(
    "security_id,as_of",
    [
        ("", AS_OF),
        ("SH.SETTLEMENT.SECURITY ", AS_OF),
        ("SH.SETTLEMENT.SECURITY", datetime(2026, 10, 16, 2, 0)),
    ],
)
def test_v3_read_use_case_rejects_invalid_request(security_id: str, as_of: datetime) -> None:
    with pytest.raises(ExecutionSettlementV3InputError):
        ReadEffectiveExecutionSettlementV3UseCase(_ReadPort(_record())).execute(
            security_id=security_id, as_of=as_of
        )


def test_v3_read_use_case_rejects_missing_or_wrongly_typed_record() -> None:
    with pytest.raises(ExecutionSettlementV3Unavailable):
        ReadEffectiveExecutionSettlementV3UseCase(_ReadPort(None)).execute(
            security_id="SH.SETTLEMENT.SECURITY", as_of=AS_OF
        )
    with pytest.raises(ExecutionSettlementV3Corruption):
        ReadEffectiveExecutionSettlementV3UseCase(_ReadPort(object())).execute(
            security_id="SH.SETTLEMENT.SECURITY", as_of=AS_OF
        )


@pytest.mark.parametrize(
    "record",
    [
        _record(recorded_at=AS_OF + timedelta(seconds=1)),
        _record(
            _bundle(
                policy=replace(
                    _policy(),
                    source_available_at=AS_OF + timedelta(seconds=1),
                    content_hash="",
                )
            )
        ),
        _record(_bundle(policy=replace(_policy(), valid_until=AS_OF, content_hash=""))),
    ],
)
def test_v3_read_use_case_blocks_future_knowledge_source_and_expired_windows(
    record: ExecutionSettlementV3ReadRecord,
) -> None:
    with pytest.raises(ExecutionSettlementV3Corruption):
        ReadEffectiveExecutionSettlementV3UseCase(_ReadPort(record)).execute(
            security_id="SH.SETTLEMENT.SECURITY", as_of=AS_OF
        )


def test_v3_read_use_case_revalidates_hash_after_provider_object_mutation() -> None:
    record = _record()
    object.__setattr__(record.bundle.settlement_policy_v1, "settlement_lag_sessions", 2)

    with pytest.raises(ExecutionSettlementV3Corruption):
        ReadEffectiveExecutionSettlementV3UseCase(_ReadPort(record)).execute(
            security_id="SH.SETTLEMENT.SECURITY", as_of=AS_OF
        )
