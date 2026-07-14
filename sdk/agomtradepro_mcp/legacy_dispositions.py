"""Machine-readable disposition registry for unreplaced legacy MCP tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

LEGACY_DISPOSITIONS = frozenset(
    {"keep_task", "aggregate", "internal_only", "legacy_compat", "remove", "unsupported"}
)


@dataclass(frozen=True)
class LegacyToolDisposition:
    """Governance decision for one raw MCP tool without a formal replacement."""

    tool_name: str
    owner_app: str
    disposition: str
    rationale: str
    recommended_capability_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable governance record."""

        return asdict(self)


def _group(
    owner_app: str,
    disposition: str,
    tool_names: tuple[str, ...],
    rationale: str,
    recommended_capability_keys: tuple[str, ...] = (),
) -> tuple[LegacyToolDisposition, ...]:
    """Build records that share one owner and governance decision."""

    return tuple(
        LegacyToolDisposition(
            tool_name=tool_name,
            owner_app=owner_app,
            disposition=disposition,
            rationale=rationale,
            recommended_capability_keys=recommended_capability_keys,
        )
        for tool_name in tool_names
    )


LEGACY_TOOL_DISPOSITIONS: tuple[LegacyToolDisposition, ...] = (
    *_group(
        "account",
        "legacy_compat",
        ("export_positions_csv",),
        "CSV rendering is a client-local compatibility concern, not an MCP capability.",
        ("account.read.position_records",),
    ),
    *_group(
        "account",
        "legacy_compat",
        ("export_transactions_csv",),
        "CSV rendering is a client-local compatibility concern, not an MCP capability.",
        ("account.read.transaction_records",),
    ),
    *_group(
        "account",
        "legacy_compat",
        ("export_capital_flows_csv",),
        "CSV rendering is a client-local compatibility concern, not an MCP capability.",
        ("account.read.capital_flow_records",),
    ),
    *_group(
        "account",
        "aggregate",
        ("export_account_bundle_json",),
        "The bundle combines independently governed account resources and must be composed by the caller.",
        (
            "account.read.portfolio_detail",
            "account.read.position_records",
            "account.read.transaction_records",
            "account.read.capital_flow_records",
        ),
    ),
    *_group(
        "agent_runtime",
        "internal_only",
        ("agent_chat", "agent_generate_report", "agent_generate_signal"),
        "Recursive AI generation belongs to the internal agent runtime and must not be exposed as an MCP operation.",
    ),
    *_group(
        "dashboard",
        "aggregate",
        ("get_dashboard_summary_v1",),
        "The legacy dashboard summary is a side-effectful composite; callers must compose strict governed reads.",
        (
            "system.read.regime.current",
            "system.read.policy.status",
            "dashboard.read.asset_allocation",
            "dashboard.read.position_catalog",
        ),
    ),
    *_group(
        "dashboard",
        "aggregate",
        ("get_dashboard_regime_quadrant_v1",),
        "Regime quadrant data already has a strict canonical owner.",
        ("system.read.regime.current", "regime.read.distribution"),
    ),
    *_group(
        "dashboard",
        "aggregate",
        ("get_dashboard_signal_status_v1",),
        "Signal status must be read from the governed signal catalog rather than the dashboard composite.",
        ("signal.read.list",),
    ),
    *_group(
        "dashboard",
        "aggregate",
        ("get_dashboard_alpha_decision_chain_v1", "get_dashboard_alpha_candidates"),
        "Dashboard Alpha projections must be composed from persisted Alpha history and candidate reads.",
        ("dashboard.read.alpha_history", "alpha_trigger.read.candidate_list"),
    ),
    *_group(
        "equity",
        "aggregate",
        ("get_stock_detail",),
        "The legacy detail method scans a broad pool; callers must compose canonical stock facts instead.",
        (
            "equity.read.pool_catalog",
            "equity.read.valuation_analysis",
            "equity.read.financial_history",
        ),
    ),
    *_group(
        "events",
        "unsupported",
        ("replay_events",),
        "The canonical replay route has no real target subscriber and can report success after no-op failures.",
    ),
    *_group(
        "factor",
        "aggregate",
        ("what_are_the_best_value_stocks", "what_are_the_best_growth_stocks"),
        "Named factor presets are parameterizations of the governed top-stocks calculation.",
        ("factor.compute.top_stocks",),
    ),
    *_group(
        "factor",
        "aggregate",
        ("explain_factor_type",),
        "Factor education belongs to catalog metadata rather than a separate operation.",
        ("factor.read.definition_catalog",),
    ),
    *_group(
        "factor",
        "aggregate",
        ("recommend_portfolio_for_regime",),
        "Portfolio guidance must combine governed Regime advice with persisted Factor configurations.",
        ("regime.read.action_recommendation", "factor.read.config_catalog"),
    ),
    *_group(
        "fund",
        "aggregate",
        ("get_fund_recommendations",),
        "Recommendations are a view over the governed persisted ranking.",
        ("fund.read.ranking",),
    ),
    *_group(
        "fund",
        "aggregate",
        ("analyze_fund",),
        "Fund analysis is a caller composition of independently governed persisted reads.",
        ("fund.read.detail", "fund.read.score", "fund.read.nav_history", "fund.read.holdings"),
    ),
    *_group(
        "hedge",
        "aggregate",
        ("explain_hedge_method",),
        "Hedge method descriptions belong to persisted pair metadata and capability schemas.",
        ("hedge.read.pair_catalog",),
    ),
    *_group(
        "hedge",
        "aggregate",
        ("recommend_hedge_for_asset",),
        "Hedge recommendations must be derived from governed pair and effectiveness evidence.",
        ("hedge.read.pair_catalog", "hedge.compute.effectiveness"),
    ),
    *_group(
        "prompt",
        "internal_only",
        ("prompt_chat", "generate_prompt_report", "generate_prompt_signal"),
        "Prompt execution recursively invokes AI providers and remains an internal application concern.",
    ),
    *_group(
        "pulse",
        "aggregate",
        ("explain_pulse_dimensions",),
        "Pulse explanations belong to snapshot schemas and documentation, not a standalone operation.",
        ("pulse.read.current", "pulse.read.history"),
    ),
    *_group(
        "realtime",
        "legacy_compat",
        ("list_price_alerts",),
        "The governed owner-scoped alert list is the canonical replacement.",
        ("realtime.read.alerts",),
    ),
    *_group(
        "realtime",
        "legacy_compat",
        ("create_price_alert",),
        "The governed confirmed alert creation workflow is the canonical replacement.",
        ("realtime.create.price_alert",),
    ),
    *_group(
        "realtime",
        "legacy_compat",
        ("delete_price_alert",),
        "The governed confirmed alert deletion workflow is the canonical replacement.",
        ("realtime.delete.price_alert",),
    ),
    *_group(
        "regime",
        "aggregate",
        ("explain_regime",),
        "Regime explanation is already represented by the governed navigator contract.",
        ("regime.read.navigator",),
    ),
    *_group(
        "regime",
        "aggregate",
        ("get_recommended_assets",),
        "Asset guidance must use the evidence-bearing governed action recommendation.",
        ("regime.read.action_recommendation",),
    ),
    *_group(
        "rotation",
        "aggregate",
        ("get_rotation_recommendation", "what_to_buy_now"),
        "Actionable rotation output must come from persisted governed signals.",
        ("rotation.read.latest_signal_list",),
    ),
    *_group(
        "rotation",
        "aggregate",
        ("list_rotation_assets", "export_rotation_assets"),
        "Dynamic-price and export wrappers are replaced by the persisted asset catalog.",
        ("rotation.read.asset_catalog",),
    ),
    *_group(
        "rotation",
        "aggregate",
        ("explain_rotation_strategy",),
        "Strategy explanation is metadata from governed configuration and template reads.",
        ("rotation.read.config_detail", "rotation.read.template_catalog"),
    ),
    *_group(
        "rotation",
        "aggregate",
        ("get_asset_info",),
        "Asset information must use the persisted asset-detail owner without dynamic price hydration.",
        ("rotation.read.asset_detail",),
    ),
)

_BY_TOOL_NAME = {record.tool_name: record for record in LEGACY_TOOL_DISPOSITIONS}


def list_legacy_tool_dispositions() -> tuple[LegacyToolDisposition, ...]:
    """Return all curated legacy tool governance decisions."""

    return LEGACY_TOOL_DISPOSITIONS


def get_legacy_tool_disposition(tool_name: str) -> LegacyToolDisposition | None:
    """Return the disposition for one raw tool, if classified."""

    return _BY_TOOL_NAME.get(tool_name)


def validate_legacy_tool_dispositions() -> None:
    """Reject duplicate, malformed, or semantically incomplete records."""

    if len(_BY_TOOL_NAME) != len(LEGACY_TOOL_DISPOSITIONS):
        raise ValueError("Duplicate legacy MCP disposition tool_name detected")
    for record in LEGACY_TOOL_DISPOSITIONS:
        if record.disposition not in LEGACY_DISPOSITIONS:
            raise ValueError(
                f"Unsupported legacy MCP disposition for {record.tool_name}: "
                f"{record.disposition}"
            )
        if not record.tool_name or not record.owner_app or not record.rationale:
            raise ValueError(f"Incomplete legacy MCP disposition: {record!r}")
        if record.disposition in {"aggregate", "legacy_compat"}:
            if not record.recommended_capability_keys:
                raise ValueError(
                    f"{record.tool_name} must declare recommended governed capabilities"
                )


validate_legacy_tool_dispositions()
