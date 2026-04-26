"""Market-source bridges used by asset analysis."""

from __future__ import annotations

from typing import Any


def screen_equity_assets_for_pool(context, filters: dict[str, Any]) -> list[Any]:
    """Screen and score equity assets through the owning equity module."""
    from apps.equity.application.services import EquityMultiDimScorer
    from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository

    repo = DjangoEquityAssetRepository()
    scorer = EquityMultiDimScorer(repo)

    filter_dict: dict[str, Any] = {}
    if filters.get("sector"):
        filter_dict["sector"] = filters["sector"]
    if filters.get("market"):
        filter_dict["market"] = filters["market"]
    if filters.get("min_market_cap") is not None:
        filter_dict["min_market_cap"] = filters["min_market_cap"]
    if filters.get("max_pe") is not None:
        filter_dict["max_pe"] = filters["max_pe"]

    assets = repo.get_assets_by_filter(asset_type="equity", filters=filter_dict)
    return scorer.score_batch(assets, context)


def screen_fund_assets_for_pool(context, filters: dict[str, Any]) -> list[Any]:
    """Screen and score fund assets through the owning fund module."""
    from apps.fund.application.services import FundMultiDimScorer
    from apps.fund.infrastructure.repositories import DjangoFundAssetRepository

    repo = DjangoFundAssetRepository()
    scorer = FundMultiDimScorer(repo)

    filter_dict: dict[str, Any] = {}
    if filters.get("fund_type"):
        filter_dict["fund_type"] = filters["fund_type"]
    if filters.get("investment_style"):
        filter_dict["investment_style"] = filters["investment_style"]
    if filters.get("min_scale") is not None:
        filter_dict["min_scale"] = filters["min_scale"]

    assets = repo.get_assets_by_filter(asset_type="fund", filters=filter_dict)
    return scorer.score_batch(assets, context)


def get_market_asset_repository(asset_type: str):
    """Return an owning-module asset repository for supported market asset types."""
    if asset_type == "fund":
        from apps.fund.infrastructure.repositories import DjangoFundAssetRepository

        return DjangoFundAssetRepository()
    if asset_type == "equity":
        from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository

        return DjangoEquityAssetRepository()
    raise ValueError(f"Unsupported market asset type: {asset_type}")


def resolve_equity_names(codes: set[str]) -> dict[str, str]:
    """Resolve stock names through the owning equity module."""
    if not codes:
        return {}

    from apps.equity.infrastructure.models import StockInfoModel

    resolved: dict[str, str] = {}
    rows = StockInfoModel._default_manager.filter(stock_code__in=list(codes)).values(
        "stock_code",
        "name",
    )
    for row in rows:
        if row["name"]:
            resolved[row["stock_code"]] = row["name"]
    return resolved


def resolve_fund_names(codes: set[str]) -> dict[str, str]:
    """Resolve fund names through the owning fund module."""
    if not codes:
        return {}

    from apps.fund.infrastructure.models import FundInfoModel

    resolved: dict[str, str] = {}
    code_to_fund_code = {code: code.split(".")[0] for code in codes}
    rows = FundInfoModel._default_manager.filter(
        fund_code__in=list(set(code_to_fund_code.values()))
    ).values("fund_code", "fund_name")
    fund_name_map = {row["fund_code"]: row["fund_name"] for row in rows}
    for code, fund_code in code_to_fund_code.items():
        if fund_code in fund_name_map and fund_name_map[fund_code]:
            resolved[code] = fund_name_map[fund_code]
    return resolved


def resolve_fund_holding_names(codes: set[str]) -> dict[str, str]:
    """Backfill stock names from fund holdings through the owning fund module."""
    if not codes:
        return {}

    from apps.fund.infrastructure.models import FundHoldingModel

    resolved: dict[str, str] = {}
    code_to_base = {code: code.split(".")[0] for code in codes}
    rows = (
        FundHoldingModel.objects.filter(stock_code__in=list(codes))
        .order_by("stock_code", "-report_date")
        .values("stock_code", "stock_name")
    )
    seen_codes: set[str] = set()
    for row in rows:
        stock_code = row["stock_code"]
        stock_name = row["stock_name"]
        if not stock_code or not stock_name or stock_code in seen_codes:
            continue
        seen_codes.add(stock_code)
        resolved[stock_code] = stock_name

    if len(resolved) < len(codes):
        base_rows = (
            FundHoldingModel.objects.filter(stock_code__in=list(code_to_base.values()))
            .order_by("stock_code", "-report_date")
            .values("stock_code", "stock_name")
        )
        base_name_map: dict[str, str] = {}
        for row in base_rows:
            stock_code = row["stock_code"]
            stock_name = row["stock_name"]
            if stock_code and stock_name and stock_code not in base_name_map:
                base_name_map[stock_code] = stock_name
        for code, base_code in code_to_base.items():
            if code not in resolved and base_code in base_name_map:
                resolved[code] = base_name_map[base_code]

    return resolved
