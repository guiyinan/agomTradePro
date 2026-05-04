#!/usr/bin/env python
"""Run a focused local smoke test for the fund research API, SDK, and MCP layers."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_SETTINGS_MODULE = "core.settings.development"


@dataclass(frozen=True)
class HoldingSample:
    fund_code: str
    report_date: date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local fund research smoke for API, SDK, and MCP.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGOMTRADEPRO_BASE_URL", DEFAULT_BASE_URL),
        help="Backend base URL. Defaults to AGOMTRADEPRO_BASE_URL or %(default)s.",
    )
    parser.add_argument(
        "--api-token",
        default=os.getenv("AGOMTRADEPRO_API_TOKEN"),
        help="DRF token. Defaults to AGOMTRADEPRO_API_TOKEN.",
    )
    parser.add_argument(
        "--auto-token-user",
        default=None,
        help="Generate a fresh local token for this Django username if --api-token is omitted.",
    )
    parser.add_argument(
        "--settings-module",
        default=os.getenv("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE),
        help="Django settings module used for local token/data discovery.",
    )
    parser.add_argument(
        "--regime",
        default="auto",
        help="Regime used for ranking/screening. Use 'auto' to resolve current regime from SDK.",
    )
    parser.add_argument(
        "--max-count",
        type=int,
        default=5,
        help="Requested candidate count for rank/screen checks.",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Optional path to write the smoke summary JSON.",
    )
    return parser.parse_args()


def _ensure_no_proxy() -> None:
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
    os.environ.setdefault("no_proxy", "127.0.0.1,localhost")


def _setup_django(settings_module: str) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    import django

    django.setup()


def _generate_local_token(settings_module: str, username: str) -> str:
    _setup_django(settings_module)

    from django.contrib.auth.models import User

    from apps.account.infrastructure.models import UserAccessTokenModel

    user = User.objects.get(username=username)
    _, key = UserAccessTokenModel.create_token(
        user=user,
        name=f"fund-research-smoke-{uuid4().hex[:8]}",
    )
    return key


def _discover_holding_sample(settings_module: str) -> HoldingSample:
    _setup_django(settings_module)

    from apps.fund.infrastructure.models import FundHoldingModel

    row = (
        FundHoldingModel.objects.order_by("-report_date").values("fund_code", "report_date").first()
    )
    if not row:
        raise RuntimeError("No fund holding sample found in local database.")
    return HoldingSample(
        fund_code=str(row["fund_code"]),
        report_date=row["report_date"],
    )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _build_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Token {api_token}"}


def _choose_screen_payload(regime: str, max_count: int) -> dict[str, Any]:
    return {
        "regime": regime,
        "custom_styles": ["成长"],
        "max_count": max_count,
    }


def _coerce_score_date(raw_value: str) -> date:
    return date.fromisoformat(raw_value)


def run_api_smoke(
    *,
    base_url: str,
    api_token: str,
    regime: str,
    max_count: int,
    holding_sample: HoldingSample,
) -> dict[str, Any]:
    headers = _build_headers(api_token)
    screen_payload = _choose_screen_payload(regime, max_count)

    rank_response = requests.get(
        f"{base_url}/api/fund/rank/",
        params={"regime": regime, "max_count": max_count},
        headers=headers,
        timeout=20,
    )
    rank_response.raise_for_status()
    rank_payload = rank_response.json()
    _assert(rank_payload.get("count", 0) > 0, "Fund API rank returned no candidates.")

    first_fund = rank_payload["funds"][0]
    first_code = first_fund["fund_code"]
    score_date = _coerce_score_date(first_fund["score_date"])
    year_start = score_date.replace(month=1, day=1)

    screen_response = requests.post(
        f"{base_url}/api/fund/screen/",
        json=screen_payload,
        headers=headers,
        timeout=20,
    )
    screen_response.raise_for_status()
    screen_result = screen_response.json()
    _assert(
        screen_result.get("success") is True,
        "Fund API screen did not return success=true.",
    )

    info_response = requests.get(
        f"{base_url}/api/fund/info/{first_code}/",
        headers=headers,
        timeout=20,
    )
    info_response.raise_for_status()
    info_payload = info_response.json()

    nav_response = requests.get(
        f"{base_url}/api/fund/nav/{first_code}/",
        params={
            "start_date": year_start.isoformat(),
            "end_date": score_date.isoformat(),
        },
        headers=headers,
        timeout=20,
    )
    nav_response.raise_for_status()
    nav_payload = nav_response.json()
    _assert(nav_payload.get("count", 0) > 0, "Fund API nav returned no rows.")

    holding_response = requests.get(
        f"{base_url}/api/fund/holding/{holding_sample.fund_code}/",
        params={"report_date": holding_sample.report_date.isoformat()},
        headers=headers,
        timeout=20,
    )
    holding_response.raise_for_status()
    holding_payload = holding_response.json()
    _assert(
        holding_payload.get("count", 0) > 0,
        "Fund API holding returned no rows for discovered holding sample.",
    )

    performance_response = requests.post(
        f"{base_url}/api/fund/performance/calculate/",
        json={
            "fund_code": first_code,
            "start_date": year_start.isoformat(),
            "end_date": score_date.isoformat(),
        },
        headers=headers,
        timeout=20,
    )
    performance_response.raise_for_status()
    performance_payload = performance_response.json()
    _assert(
        performance_payload.get("success") is True,
        "Fund API performance calculate returned success=false.",
    )

    return {
        "screen_payload": screen_payload,
        "rank_top_codes": [item["fund_code"] for item in rank_payload["funds"]],
        "screen_codes": screen_result.get("fund_codes", []),
        "info_name": info_payload["fund"]["fund_name"],
        "nav_count": nav_payload["count"],
        "holding_sample": {
            "fund_code": holding_sample.fund_code,
            "report_date": holding_sample.report_date.isoformat(),
            "count": holding_payload["count"],
        },
        "performance_fund_code": performance_payload["fund_code"],
        "performance_total_return": performance_payload["performance"]["total_return"],
        "first_code": first_code,
        "score_date": score_date.isoformat(),
    }


def run_sdk_smoke(
    *,
    regime: str,
    max_count: int,
    holding_sample: HoldingSample,
    first_code: str,
    score_date: date,
    screen_payload: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    try:
        ranked = client.fund.rank_funds(regime=regime, max_count=max_count)
        _assert(len(ranked) > 0, "Fund SDK rank returned no candidates.")

        screened = client.fund.screen_funds(
            regime=screen_payload["regime"],
            custom_styles=screen_payload.get("custom_styles"),
            custom_types=screen_payload.get("custom_types"),
            min_scale=screen_payload.get("min_scale"),
            limit=max_count,
        )
        _assert(
            screened.get("success") is True,
            "Fund SDK screen did not return success=true.",
        )

        detail = client.fund.get_fund_detail(first_code)
        nav_history = client.fund.get_nav_history(
            first_code,
            start_date=score_date.replace(month=1, day=1),
            end_date=score_date,
            limit=max_count,
        )
        holdings = client.fund.get_holdings(
            holding_sample.fund_code,
            report_date=holding_sample.report_date,
        )
        performance = client.fund.get_performance(first_code, period="1y")
    finally:
        client.close()

    _assert(len(nav_history) > 0, "Fund SDK nav returned no rows.")
    _assert(len(holdings) > 0, "Fund SDK holdings returned no rows.")
    _assert(
        performance.get("success", True) is True,
        f"Fund SDK performance failed: {performance}",
    )

    return {
        "rank_top_codes": [item["fund_code"] for item in ranked],
        "screen_codes": screened.get("fund_codes", []),
        "detail_name": detail["fund_name"],
        "nav_count": len(nav_history),
        "holding_count": len(holdings),
        "performance_total_return": performance["total_return"],
    }


async def run_mcp_smoke(
    *,
    regime: str,
    max_count: int,
    holding_sample: HoldingSample,
    first_code: str,
    score_date: date,
    screen_payload: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro_mcp.server import server

    rank = await server.call_tool(
        "rank_funds",
        {"regime": regime, "max_count": max_count},
    )
    screen = await server.call_tool(
        "screen_funds",
        {
            "regime": screen_payload["regime"],
            "custom_styles": screen_payload.get("custom_styles"),
            "custom_types": screen_payload.get("custom_types"),
            "min_scale": screen_payload.get("min_scale"),
            "limit": max_count,
        },
    )
    detail = await server.call_tool("get_fund_detail", {"fund_code": first_code})
    nav = await server.call_tool(
        "get_fund_nav_history",
        {
            "fund_code": first_code,
            "start_date": score_date.replace(month=1, day=1).isoformat(),
            "end_date": score_date.isoformat(),
            "limit": max_count,
        },
    )
    holdings = await server.call_tool(
        "get_fund_holdings",
        {
            "fund_code": holding_sample.fund_code,
            "report_date": holding_sample.report_date.isoformat(),
        },
    )
    performance = await server.call_tool(
        "get_fund_performance",
        {"fund_code": first_code, "period": "1y"},
    )

    rank_text = str(rank)
    screen_text = str(screen)
    detail_text = str(detail)
    nav_text = str(nav)
    holdings_text = str(holdings)
    performance_text = str(performance)

    _assert(first_code in rank_text, "Fund MCP rank output does not contain the top code.")
    _assert(first_code in detail_text, "Fund MCP detail output does not contain the target code.")
    _assert(
        first_code in nav_text and "nav_date" in nav_text,
        "Fund MCP nav output does not contain the expected fund code/nav fields.",
    )
    _assert(
        holding_sample.fund_code in holdings_text,
        "Fund MCP holdings output does not contain the holding sample code.",
    )
    _assert(
        "success" in performance_text or "total_return" in performance_text,
        "Fund MCP performance output looks invalid.",
    )

    return {
        "tool_count": len(await server.list_tools()),
        "rank_preview": rank_text[:160],
        "screen_preview": screen_text[:160],
        "detail_preview": detail_text[:160],
        "nav_preview": nav_text[:160],
        "holdings_preview": holdings_text[:160],
        "performance_preview": performance_text[:160],
    }


def main() -> int:
    args = parse_args()
    _ensure_no_proxy()

    api_token = args.api_token
    if not api_token and args.auto_token_user:
        api_token = _generate_local_token(args.settings_module, args.auto_token_user)
    if not api_token:
        print(
            "Missing API token. Pass --api-token or use --auto-token-user for local smoke.",
            file=sys.stderr,
        )
        return 2

    os.environ["AGOMTRADEPRO_BASE_URL"] = args.base_url
    os.environ["AGOMTRADEPRO_API_TOKEN"] = api_token

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient(base_url=args.base_url, api_token=api_token)
    try:
        regime = args.regime
        if regime == "auto":
            regime = client.regime.get_current().dominant_regime
    finally:
        client.close()

    holding_sample = _discover_holding_sample(args.settings_module)

    try:
        api_summary = run_api_smoke(
            base_url=args.base_url,
            api_token=api_token,
            regime=regime,
            max_count=args.max_count,
            holding_sample=holding_sample,
        )
        sdk_summary = run_sdk_smoke(
            regime=regime,
            max_count=args.max_count,
            holding_sample=holding_sample,
            first_code=api_summary["first_code"],
            score_date=date.fromisoformat(api_summary["score_date"]),
            screen_payload=api_summary["screen_payload"],
        )
        mcp_summary = asyncio.run(
            run_mcp_smoke(
                regime=regime,
                max_count=args.max_count,
                holding_sample=holding_sample,
                first_code=api_summary["first_code"],
                score_date=date.fromisoformat(api_summary["score_date"]),
                screen_payload=api_summary["screen_payload"],
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[fund-smoke] FAILED: {exc}", file=sys.stderr)
        return 1

    summary = {
        "base_url": args.base_url,
        "regime": regime,
        "api": api_summary,
        "sdk": sdk_summary,
        "mcp": mcp_summary,
    }

    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
