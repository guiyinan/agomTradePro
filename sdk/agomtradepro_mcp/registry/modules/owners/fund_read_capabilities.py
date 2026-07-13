"""fund read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="fund.read.ranking",
        title="Fund Ranking",
        summary="Read the canonical fund ranking for one macro regime.",
        description=(
            "Return ranked fund scores from persisted Fund performance snapshots, "
            "bounded by the requested maximum result count. The canonical endpoint "
            "does not seed, synchronize, calculate missing snapshots, or persist data."
        ),
        owner_app="fund",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="rank_funds",
        tags=("fund", "ranking", "score", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "regime": {
                    "type": "string",
                    "enum": ["Recovery", "Overheat", "Stagflation", "Deflation"],
                    "default": "Recovery",
                },
                "max_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "regime": {"type": "string"},
                "funds": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("rank_funds",),
    ),
    CapabilityManifest(
        capability_key="fund.read.detail",
        title="Fund Detail",
        summary="Read one canonical fund information record.",
        description=(
            "Return canonical fund identity, type, style, setup, manager, custodian, "
            "and scale fields for one fund code."
        ),
        owner_app="fund",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_fund_detail",
        tags=("fund", "detail", "profile", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "minLength": 1},
            },
            "required": ["fund_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string"},
                "fund_name": {"type": "string"},
                "fund_type": {"type": "string"},
                "investment_style": {"type": ["string", "null"]},
                "setup_date": {"type": ["string", "null"], "format": "date"},
                "management_company": {"type": ["string", "null"]},
                "custodian": {"type": ["string", "null"]},
                "fund_scale": {"type": ["string", "number", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("get_fund_detail",),
    ),
    CapabilityManifest(
        capability_key="fund.read.nav_history",
        title="Fund NAV History",
        summary="Read canonical historical NAV observations for one fund.",
        description=(
            "Return fund NAV observations for the optional canonical start and end dates. "
            "The legacy limit argument is intentionally not published because the current "
            "canonical API does not apply it."
        ),
        owner_app="fund",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_fund_nav_history",
        tags=("fund", "nav", "history", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "minLength": 1},
                "start_date": {
                    "type": ["string", "null"],
                    "format": "date",
                },
                "end_date": {
                    "type": ["string", "null"],
                    "format": "date",
                },
            },
            "required": ["fund_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string"},
                "nav_data": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("get_fund_nav_history",),
    ),
    CapabilityManifest(
        capability_key="fund.read.holdings",
        title="Fund Holdings",
        summary="Read canonical holdings for one fund report date.",
        description=(
            "Return canonical fund holdings for the requested report date, or the "
            "latest available report when no date is provided."
        ),
        owner_app="fund",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_fund_holdings",
        tags=("fund", "holdings", "portfolio", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "minLength": 1},
                "report_date": {
                    "type": ["string", "null"],
                    "format": "date",
                },
            },
            "required": ["fund_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string"},
                "report_date": {"type": ["string", "null"]},
                "holdings": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_fund_holdings",),
    ),
]
