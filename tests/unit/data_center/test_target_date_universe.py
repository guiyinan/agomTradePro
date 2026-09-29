"""Point-in-time A-share scope requires explicit listing-date provenance."""

from datetime import date

from apps.data_center.domain.entities import AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.domain.target_date_universe import build_target_date_a_share_scope


def _asset(
    code: str,
    *,
    list_date: date | None,
    evidence_status: str | None = None,
    source: str | None = None,
    is_active: bool = True,
) -> AssetMaster:
    extra: dict[str, object] = {}
    if evidence_status is not None:
        extra["list_date_evidence_status"] = evidence_status
    if source is not None:
        extra["list_date_source"] = source
    return AssetMaster(
        code=code,
        name=code,
        short_name=code,
        asset_type=AssetType.STOCK,
        exchange=(
            MarketExchange.BSE
            if code.endswith(".BJ")
            else MarketExchange.SSE if code.endswith(".SH") else MarketExchange.SZSE
        ),
        is_active=is_active,
        list_date=list_date,
        extra=extra,
    )


def test_target_scope_excludes_only_verified_later_dates_and_keeps_unknowns() -> None:
    target = date(2026, 9, 28)
    active_assets = (
        _asset(
            "301716.SZ",
            list_date=date(2026, 9, 29),
            evidence_status="verified",
            source="tushare.new_share[provider_id=7].issue_date",
        ),
        _asset(
            "920202.BJ",
            list_date=date(2026, 9, 29),
            evidence_status="verified",
            source="tushare.stock_basic[provider_id=7].list_date",
        ),
        _asset(
            "000001.SZ",
            list_date=target,
            evidence_status="verified",
            source="tushare.stock_basic[provider_id=7].list_date",
        ),
        _asset(
            "600000.SH",
            list_date=date(1999, 11, 10),
            evidence_status="verified",
            source="tushare.stock_basic[provider_id=7].list_date",
        ),
        # Legacy dates without provenance are not proof that the asset was unlisted.
        _asset("000002.SZ", list_date=date(2026, 9, 30)),
        _asset(
            "600001.SH",
            list_date=date(2026, 9, 30),
            evidence_status="conflict",
            source="provider-conflict",
        ),
        _asset("000003.SZ", list_date=None),
        _asset("000004.SZ", list_date=date(2026, 9, 30), is_active=False),
    )

    scope = build_target_date_a_share_scope(target, active_assets)

    assert scope.candidate_codes == (
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
        "301716.SZ",
        "600000.SH",
        "600001.SH",
        "920202.BJ",
    )
    assert scope.requested_codes == (
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
        "600000.SH",
        "600001.SH",
    )
    assert tuple(item.asset_code for item in scope.excluded_not_yet_listed) == (
        "301716.SZ",
        "920202.BJ",
    )
    assert tuple(item.list_date for item in scope.excluded_not_yet_listed) == (
        date(2026, 9, 29),
        date(2026, 9, 29),
    )
    assert scope.unknown_listing_date_codes == ("000002.SZ", "000003.SZ", "600001.SH")
