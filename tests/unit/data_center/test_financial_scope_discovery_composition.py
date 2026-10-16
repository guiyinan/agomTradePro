"""Target-date composition contracts for financial scope discovery."""

from datetime import UTC, date, datetime

import pytest

from apps.data_center import financial_scope_discovery_composition as composition
from apps.data_center.domain.financial_scope_discovery import FinancialScopeDiscoveryError
from apps.data_center.domain.target_date_universe import (
    NotYetListedAsset,
    TargetDateAssetUniverseScope,
)


def _scope(*, requested_codes: tuple[str, ...]) -> TargetDateAssetUniverseScope:
    """Build one scope that excludes a stock listed after the frozen date."""

    excluded_code = "301569.SZ"
    return TargetDateAssetUniverseScope(
        target_date=date(2026, 10, 14),
        candidate_codes=tuple(sorted((*requested_codes, excluded_code))),
        requested_codes=tuple(sorted(requested_codes)),
        excluded_not_yet_listed=(
            NotYetListedAsset(
                asset_code=excluded_code,
                list_date=date(2026, 10, 15),
                evidence_source="tushare.stock_basic",
            ),
        ),
        unknown_listing_date_codes=(),
    )


def test_target_date_universe_source_excludes_later_listings_and_rechecks_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the frozen date's requested denominator on every authority revalidation."""

    scopes = iter(
        (
            _scope(requested_codes=("000001.SZ",)),
            _scope(requested_codes=("000001.SZ", "000002.SZ")),
        )
    )
    observed_dates: list[date] = []

    def resolve(target_trade_date: date) -> TargetDateAssetUniverseScope:
        observed_dates.append(target_trade_date)
        return next(scopes)

    monkeypatch.setattr(
        composition,
        "build_target_date_a_share_universe_scope",
        resolve,
    )
    source = composition.TargetDateFinancialScopeDiscoveryUniverseSource(date(2026, 10, 14))

    assert source.get_active_asset_codes() == ("000001.SZ",)
    assert source.get_active_asset_codes() == ("000001.SZ", "000002.SZ")
    assert observed_dates == [date(2026, 10, 14), date(2026, 10, 14)]


def test_target_date_universe_source_rejects_datetime() -> None:
    """Keep date and datetime identities distinct at the composition boundary."""

    with pytest.raises(
        FinancialScopeDiscoveryError,
        match="FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID",
    ):
        composition.TargetDateFinancialScopeDiscoveryUniverseSource(
            datetime(2026, 10, 14, tzinfo=UTC)
        )


def test_binding_uses_checked_in_v2_contract_parser_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exporter must not bind a v2 contract to the obsolete hardcoded v1 parser."""
    from types import SimpleNamespace

    from apps.data_center.infrastructure.financial_scope_discovery_reader import (
        load_financial_scope_discovery_contract,
    )
    from apps.data_center.infrastructure.rehearsal_identity import RehearsalProviderIdentity

    identity = RehearsalProviderIdentity(
        role="akshare_financial_route:19",
        provider_id=19,
        source="akshare_financial",
        version="fixture",
        endpoint_id="fixture-endpoint",
        deployment_region="isolated-test",
    )
    monkeypatch.setattr(
        composition, "configured_akshare_financial_identity", lambda **kwargs: identity
    )
    monkeypatch.setattr(composition, "akshare_financial_deployment_region", lambda: "isolated-test")
    contract = load_financial_scope_discovery_contract()
    binding = composition.build_financial_scope_discovery_binding(
        provider=SimpleNamespace(id=19, source_type="akshare", is_active=True),
        candidate_sha="a" * 40,
    )
    assert binding.contract_version == "2026-10-16.v2"
    assert (
        binding.parser_id == contract["parser"]["parser_id"] == "akshare-financial-scope-parser.v2"
    )
