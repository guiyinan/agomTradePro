"""Application-level query helpers for cross-app fund access."""

from __future__ import annotations

from typing import Any

from apps.fund.application.repository_provider import get_fund_repository


def list_asset_master_fund_candidate_codes() -> list[str]:
    """Return fund-domain codes that can seed data-center asset master rows."""

    return get_fund_repository().list_asset_master_candidate_codes()


def list_asset_master_fund_rows(base_codes: list[str]) -> list[dict[str, Any]]:
    """Return local fund rows for data-center asset master backfill."""

    return get_fund_repository().list_asset_master_fund_rows(base_codes)


def list_asset_master_holding_rows(lookup_codes: list[str]) -> list[dict[str, Any]]:
    """Return local holding rows for data-center asset master backfill."""

    return get_fund_repository().list_asset_master_holding_rows(lookup_codes)
