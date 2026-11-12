from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    HoldingPeriodTaxBand,
    TaxRoundingMode,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementRuleKind,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    STATUTORY_REVISION_SET_SCHEMA,
    SimulatedDividendTaxCurrency,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
    SimulatedDividendTaxPolicyScope,
)

_NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
_REVISION_SHA = "a" * 64


def _tax_policy(
    *,
    source_identity: str | None = None,
    source_sha256: str = _REVISION_SHA,
    effective_from: date = date(2025, 1, 1),
    effective_through: date | None = date(2025, 12, 31),
) -> DeferredDividendTaxPolicy:
    """Build explicit synthetic terms; values are test inputs, not legal rates."""

    return DeferredDividendTaxPolicy(
        policy_id="synthetic-policy",
        version="fixture-v1",
        effective_from=effective_from,
        effective_through=effective_through,
        source_identity=(
            f"{STATUTORY_REVISION_SET_SCHEMA}:{_REVISION_SHA}"
            if source_identity is None
            else source_identity
        ),
        source_sha256=source_sha256,
        bands=(
            HoldingPeriodTaxBand(
                band_id="synthetic-short",
                maximum_holding_months=12,
                taxable_dividend_ratio=Decimal("1"),
                withholding_rate=Decimal("0.2"),
            ),
            HoldingPeriodTaxBand(
                band_id="synthetic-long",
                maximum_holding_months=None,
                taxable_dividend_ratio=Decimal("0"),
                withholding_rate=Decimal("0"),
            ),
        ),
        currency_quantum=Decimal("0.01"),
        rounding_mode=TaxRoundingMode.HALF_UP,
    )


def _scope(
    *,
    known_at: datetime = _NOW - timedelta(days=3),
    policy: DeferredDividendTaxPolicy | None = None,
) -> SimulatedDividendTaxPolicyScope:
    """Build one complete synthetic simulation-only policy scope."""

    return SimulatedDividendTaxPolicyScope(
        candidate_id="synthetic-candidate",
        candidate_version="fixture-v1",
        account_kind="simulated",
        physical_account_id=17,
        canonical_account_id="account-v2:fixture-17",
        owner_user_id=29,
        security_id="SH.SYNTHETIC",
        asset_code="equity-cn",
        exchange=SimulatedDividendTaxExchange.SH,
        persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
        instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
        currency=SimulatedDividendTaxCurrency.CNY,
        record_date_entitlement_rule=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
        applicability_ref="synthetic-reviewed-applicability-v1",
        record_date_from=date(2025, 1, 1),
        record_date_through=date(2025, 12, 31),
        valid_from=_NOW - timedelta(days=2),
        valid_until=_NOW + timedelta(days=2),
        known_at=known_at,
        statutory_bundle_id="synthetic-source-bundle",
        statutory_bundle_version="fixture-capture-v1",
        statutory_revision_set_sha256=_REVISION_SHA,
        tax_policy=_tax_policy() if policy is None else policy,
    )


def test_scope_is_explicit_simulation_candidate_with_semantic_digest() -> None:
    scope = _scope()
    same_terms_new_observation = _scope(known_at=_NOW - timedelta(days=1))

    scope.verify_for(
        account_kind="simulated",
        physical_account_id=17,
        canonical_account_id="account-v2:fixture-17",
        owner_user_id=29,
        security_id="SH.SYNTHETIC",
        asset_code="equity-cn",
        exchange=SimulatedDividendTaxExchange.SH,
        persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
        instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
        record_date=date(2025, 6, 1),
        as_of=_NOW,
    )

    assert scope.semantic_sha256 == same_terms_new_observation.semantic_sha256
    assert scope.tax_policy.source_identity == (
        f"{STATUTORY_REVISION_SET_SCHEMA}:{scope.statutory_revision_set_sha256}"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_kind": "real"},
        {"physical_account_id": True},
        {"canonical_account_id": ""},
        {"owner_user_id": 0},
        {"security_id": "bad token"},
        {"asset_code": ""},
        {"exchange": "SH"},
        {"persona": "unlisted_or_unknown"},
        {"instrument_kind": "option"},
        {"applicability_ref": ""},
        {"record_date_from": datetime(2025, 1, 1, tzinfo=UTC)},
        {"record_date_through": date(2024, 12, 31)},
        {"valid_from": datetime(2026, 11, 12)},
        {"valid_until": _NOW - timedelta(days=2)},
        {"known_at": datetime(2026, 11, 12)},
        {"statutory_bundle_id": ""},
        {"statutory_bundle_version": ""},
        {"statutory_revision_set_sha256": "G" * 64},
    ],
)
def test_scope_rejects_untyped_or_missing_candidate_facts(changes: dict[str, object]) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_scope(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"account_kind": "real"},
        {"physical_account_id": 18},
        {"canonical_account_id": "foreign-account"},
        {"owner_user_id": 30},
        {"security_id": "SZ.OTHER"},
        {"asset_code": "other-asset"},
        {"exchange": SimulatedDividendTaxExchange.SZ},
        {"persona": "another-persona"},
        {"instrument_kind": "option"},
        {"record_date": date(2024, 12, 31)},
        {"record_date": date(2026, 1, 1)},
    ],
)
def test_verify_for_rejects_cross_scope_or_date_mismatch(changes: dict[str, object]) -> None:
    requested: dict[str, object] = {
        "account_kind": "simulated",
        "physical_account_id": 17,
        "canonical_account_id": "account-v2:fixture-17",
        "owner_user_id": 29,
        "security_id": "SH.SYNTHETIC",
        "asset_code": "equity-cn",
        "exchange": SimulatedDividendTaxExchange.SH,
        "persona": SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
        "instrument_kind": SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
        "record_date": date(2025, 6, 1),
        "as_of": _NOW,
    }
    requested.update(changes)

    with pytest.raises(DeferredDividendTaxValidationError):
        _scope().verify_for(**requested)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "as_of",
    [
        _NOW - timedelta(days=4),
        _NOW + timedelta(days=2),
    ],
)
def test_verify_for_rejects_unknown_or_expired_scope(as_of: datetime) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        _scope().verify_for(
            account_kind="simulated",
            physical_account_id=17,
            canonical_account_id="account-v2:fixture-17",
            owner_user_id=29,
            security_id="SH.SYNTHETIC",
            asset_code="equity-cn",
            exchange=SimulatedDividendTaxExchange.SH,
            persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
            instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
            record_date=date(2025, 6, 1),
            as_of=as_of,
        )


def test_policy_source_set_and_applicable_record_window_must_match() -> None:
    bad_source = _tax_policy(
        source_identity="some-other-source",
        source_sha256="b" * 64,
    )
    bad_policy_window = _tax_policy(
        effective_from=date(2025, 2, 1),
        effective_through=date(2025, 12, 31),
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        _scope(policy=bad_source)
    with pytest.raises(DeferredDividendTaxValidationError):
        _scope(policy=bad_policy_window)
