"""Test-only exact Tushare batch publication for the ASH07 Owner journey."""

from __future__ import annotations

from datetime import UTC, date

from django.utils import timezone

from apps.config_center.application.runtime_public import get_active_runtime_profile
from apps.data_center.application.m1_reference_price_batch_publication import (
    M1ReferencePriceBatchPublicationCommand,
    M1ReferencePriceBatchPublicationResult,
)
from apps.data_center.application.market_calendar import latest_completed_cn_market_session
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.m1_reference_price_publication_composition import (
    build_m1_reference_price_batch_publication_use_case,
)
from apps.simulated_trading.infrastructure.published_close_price_reader import (
    PublishedClosePriceReader,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database


def publish_and_verify_tushare_close_batch(
    *,
    asset_codes: tuple[str, ...],
    target_trade_date: date,
) -> M1ReferencePriceBatchPublicationResult:
    """Publish exact same-session Tushare bars and verify both through the close reader.

    The caller must finish every ConfigCenter profile change and establish the real,
    current Account/SystemAudit authorities before calling this helper. The M1
    composition performs its own required audit preflight and authority capture.
    This helper never substitutes an authority, provider, clock, or price value.
    """

    assert_native_postgres_test_database()
    if type(target_trade_date) is not date:
        raise TypeError("target_trade_date must be an exact date")
    if type(asset_codes) is not tuple or len(asset_codes) < 2:
        raise ValueError("asset_codes must be an explicit tuple of at least two securities")

    profile_before = get_active_runtime_profile("development")
    if profile_before is None:
        raise AssertionError("the final development ConfigCenter profile is not active")

    cutoff = timezone.now().astimezone(UTC)
    completed_session = latest_completed_cn_market_session(cutoff)
    if completed_session != target_trade_date:
        raise AssertionError(
            "M1 batch date must be the exact latest completed published market session"
        )

    providers = ProviderConfigRepository()
    active_tushare = providers.get_active_by_type("tushare")
    if len(active_tushare) != 1:
        raise AssertionError("exactly one active Tushare provider must be selected")
    provider = active_tushare[0]
    if provider.id is None or provider.id < 1:
        raise AssertionError("the active Tushare provider identity is incomplete")

    use_case = build_m1_reference_price_batch_publication_use_case(
        provider_repository=providers,
        environment="development",
    )
    result = use_case.execute(
        M1ReferencePriceBatchPublicationCommand(
            provider_id=provider.id,
            asset_codes=asset_codes,
            target_trade_date=target_trade_date,
        )
    )
    if (
        result.publication.selected_source != "tushare"
        or result.publication.member_count != len(asset_codes)
        or result.publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    ):
        raise AssertionError("the exact Tushare batch did not produce one qualified M1 group")
    stored_asset_codes = {
        asset_code
        for sync_result in result.sync_results
        for asset_code in sync_result.stored_asset_codes
    }
    if stored_asset_codes != set(asset_codes):
        raise AssertionError("the M1 batch did not store exactly the requested securities")

    profile_after = get_active_runtime_profile("development")
    if (
        profile_after is None
        or profile_after.profile_id != profile_before.profile_id
        or profile_after.version != profile_before.version
    ):
        raise AssertionError("ConfigCenter changed during M1 publication")

    read_at = timezone.now().astimezone(UTC)
    if latest_completed_cn_market_session(read_at) != target_trade_date:
        raise AssertionError("the latest completed market session changed during publication")
    reader = PublishedClosePriceReader()
    for asset_code in asset_codes:
        read = reader.read(asset_code=asset_code, cutoff=read_at)
        publication = read.publication
        if (
            read.blocked_reason is not None
            or read.price_result is None
            or publication is None
            or publication.bar_date != target_trade_date
            or publication.publication_id != result.publication.publication_id
            or publication.publication_hash != result.publication.publication_hash
            or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        ):
            raise AssertionError(
                "published_close did not read the same qualified batch for every security"
            )
    return result


__all__ = ("publish_and_verify_tushare_close_batch",)
