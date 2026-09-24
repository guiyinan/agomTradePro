"""Dashboard Alpha decision-chain aggregation query."""

from typing import Any

from apps.dashboard.application import queries as dashboard_queries
from apps.dashboard.application.queries import (
    AlphaDecisionChainData,
    AlphaVisualizationData,
    DecisionPlaneData,
)


class AlphaDecisionChainQuery:
    """
    Alpha 决策链查询服务。

    将 Alpha Top N 排名、Workflow 可行动候选、待执行队列收束成统一视图，
    供 Dashboard 页面、API、SDK、MCP 共用。
    """

    def execute(
        self,
        top_n: int = 10,
        ic_days: int = 30,
        max_candidates: int = 5,
        max_pending: int = 10,
        user: Any | None = None,
    ) -> AlphaDecisionChainData:
        """执行 Alpha 决策链聚合查询。"""
        if user is not None:
            homepage_data = dashboard_queries.get_alpha_homepage_query().execute(
                user=user, top_n=top_n
            )
            alpha_visualization_data = AlphaVisualizationData(
                stock_scores=homepage_data.top_candidates,
                stock_scores_meta=dict(homepage_data.meta or {}),
                provider_status={},
                coverage_metrics={},
                ic_trends=[],
                ic_trends_meta={},
            )
        else:
            alpha_visualization_data = dashboard_queries.get_alpha_visualization_query().execute(
                top_n=top_n,
                ic_days=ic_days,
                user=user,
            )
        decision_plane_data = dashboard_queries.get_decision_plane_query().execute(
            max_candidates=max_candidates,
            max_pending=max_pending,
            user_id=int(user.id) if user is not None else None,
        )
        return self.build(
            alpha_visualization_data=alpha_visualization_data,
            decision_plane_data=decision_plane_data,
        )

    def build(
        self,
        *,
        alpha_visualization_data: AlphaVisualizationData,
        decision_plane_data: DecisionPlaneData,
    ) -> AlphaDecisionChainData:
        """用已获取的 Alpha 与 Workflow 数据构造统一决策链。"""
        top_stocks = [dict(item) for item in alpha_visualization_data.stock_scores]
        top_match_index = self._build_top_match_index(top_stocks)

        pending_matches = self._build_pending_matches(
            top_stocks,
            decision_plane_data.pending_requests,
        )
        actionable_matches = self._build_actionable_matches(
            top_stocks,
            decision_plane_data.actionable_candidates,
            pending_matches=pending_matches,
        )

        top_rank_only_count = 0
        top10_actionable_count = 0
        top10_pending_count = 0

        enriched_top_stocks: list[dict[str, Any]] = []
        for stock in top_stocks:
            canonical_code = str(stock.get("code") or "").strip().upper()
            actionable_match = actionable_matches.get(canonical_code)
            pending_match = pending_matches.get(canonical_code)

            if pending_match:
                workflow_stage = "pending"
                workflow_stage_label = "待执行队列"
                top10_pending_count += 1
            elif actionable_match:
                workflow_stage = "actionable"
                workflow_stage_label = "可行动候选"
                top10_actionable_count += 1
            else:
                workflow_stage = "top_ranked"
                workflow_stage_label = "仅在 Alpha Top 排名"
                top_rank_only_count += 1

            enriched_stock = dict(stock)
            enriched_stock.update(
                {
                    "workflow_stage": workflow_stage,
                    "workflow_stage_label": workflow_stage_label,
                    "is_actionable": bool(actionable_match),
                    "is_pending": bool(pending_match),
                    "candidate_id": (
                        actionable_match.get("candidate_id") if actionable_match else None
                    ),
                    "pending_request_id": (
                        pending_match.get("request_id") if pending_match else None
                    ),
                    "pending_execution_status": (
                        pending_match.get("execution_status") if pending_match else None
                    ),
                }
            )
            enriched_top_stocks.append(enriched_stock)

        actionable_candidates = [
            self._serialize_actionable_candidate(item, top_match_index)
            for item in decision_plane_data.actionable_candidates
        ]
        pending_requests = [
            self._serialize_pending_request(item, top_match_index)
            for item in decision_plane_data.pending_requests
        ]

        actionable_outside_top10_count = sum(
            1 for item in actionable_candidates if not item["is_in_top10"]
        )
        pending_outside_top10_count = sum(1 for item in pending_requests if not item["is_in_top10"])

        overview = {
            "top_ranked_count": len(enriched_top_stocks),
            "actionable_count": len(actionable_candidates),
            "actionable_total_count": decision_plane_data.alpha_actionable_count,
            "pending_count": len(pending_requests),
            "top10_actionable_count": top10_actionable_count,
            "top10_pending_count": top10_pending_count,
            "top10_rank_only_count": top_rank_only_count,
            "actionable_outside_top10_count": actionable_outside_top10_count,
            "pending_outside_top10_count": pending_outside_top10_count,
            "actionable_conversion_pct": (
                round((top10_actionable_count / len(enriched_top_stocks) * 100), 1)
                if enriched_top_stocks
                else 0.0
            ),
            "pending_conversion_pct": (
                round((top10_pending_count / len(enriched_top_stocks) * 100), 1)
                if enriched_top_stocks
                else 0.0
            ),
            "requested_trade_date": alpha_visualization_data.stock_scores_meta.get(
                "requested_trade_date"
            ),
            "effective_asof_date": alpha_visualization_data.stock_scores_meta.get(
                "effective_asof_date"
            ),
        }

        return AlphaDecisionChainData(
            overview=overview,
            top_stocks=enriched_top_stocks,
            actionable_candidates=actionable_candidates,
            pending_requests=pending_requests,
        )

    def _build_code_aliases(self, code: str) -> set[str]:
        """为关系匹配构建代码别名。"""
        normalized = str(code or "").strip().upper()
        if not normalized:
            return set()

        aliases = {normalized}
        base_code = normalized.split(".")[0]
        if base_code:
            aliases.add(base_code)
        return aliases

    def _normalize_code(self, code: str) -> str:
        """统一比较时的 canonical code。"""
        normalized = str(code or "").strip().upper()
        return normalized

    def _build_top_match_index(self, top_stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """构建 Top N 股票的代码别名索引。"""
        index: dict[str, dict[str, Any]] = {}
        for stock in top_stocks:
            for alias in self._build_code_aliases(stock.get("code", "")):
                index[alias] = stock
        return index

    def _match_top_stock(
        self,
        top_match_index: dict[str, dict[str, Any]],
        code: str,
    ) -> dict[str, Any] | None:
        """根据候选/请求代码匹配当前 Top N 股票。"""
        for alias in self._build_code_aliases(code):
            matched = top_match_index.get(alias)
            if matched:
                return matched
        return None

    def _build_top_lookup_codes(self, top_stocks: list[dict[str, Any]]) -> list[str]:
        """构建 Top N 对应的数据库查询代码集合。"""
        lookup_codes: set[str] = set()
        for stock in top_stocks:
            lookup_codes.update(self._build_code_aliases(stock.get("code", "")))
        return sorted(lookup_codes)

    def _build_pending_matches(
        self,
        top_stocks: list[dict[str, Any]],
        pending_requests: list[Any],
    ) -> dict[str, dict[str, Any]]:
        """基于已加载的待执行请求构建 Top N 命中关系。"""
        if not top_stocks or not pending_requests:
            return {}

        top_match_index = self._build_top_match_index(top_stocks)
        matched: dict[str, dict[str, Any]] = {}
        for item in pending_requests:
            top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
            if not top_stock:
                continue
            canonical_code = self._normalize_code(top_stock.get("code", ""))
            if canonical_code in matched:
                continue
            matched[canonical_code] = {
                "request_id": getattr(item, "request_id", ""),
                "execution_status": getattr(item, "execution_status", ""),
            }
        return matched

    def _build_actionable_matches(
        self,
        top_stocks: list[dict[str, Any]],
        actionable_candidates: list[Any],
        *,
        pending_matches: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """基于已加载的可行动候选构建 Top N 命中关系。"""
        if not top_stocks or not actionable_candidates:
            return {}

        pending_codes = set(pending_matches.keys())
        top_match_index = self._build_top_match_index(top_stocks)
        matched: dict[str, dict[str, Any]] = {}
        for item in actionable_candidates:
            top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
            if not top_stock:
                continue
            canonical_code = self._normalize_code(top_stock.get("code", ""))
            if canonical_code in matched or canonical_code in pending_codes:
                continue
            matched[canonical_code] = {
                "candidate_id": getattr(item, "candidate_id", ""),
                "direction": getattr(item, "direction", ""),
                "confidence": getattr(item, "confidence", None),
            }
        return matched

    def _serialize_actionable_candidate(
        self,
        item: Any,
        top_match_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """序列化可行动候选并补充当前 Top N 关系。"""
        top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
        return {
            "candidate_id": getattr(item, "candidate_id", ""),
            "asset_code": getattr(item, "asset_code", ""),
            "asset_name": getattr(item, "asset_name", ""),
            "direction": getattr(item, "direction", ""),
            "confidence": getattr(item, "confidence", None),
            "asset_class": getattr(item, "asset_class", ""),
            "valuation_repair": getattr(item, "valuation_repair", None),
            "is_in_top10": bool(top_stock),
            "current_top_rank": top_stock.get("rank") if top_stock else None,
            "current_top_score": top_stock.get("score") if top_stock else None,
            "current_top_source": top_stock.get("source") if top_stock else None,
            "origin_stage_label": (
                f"当前 Top 10 第 #{top_stock.get('rank')}" if top_stock else "当前不在 Top 10"
            ),
            "chain_stage": "actionable",
            "chain_stage_label": "可行动候选",
        }

    def _serialize_pending_request(
        self,
        item: Any,
        top_match_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """序列化待执行请求并补充当前 Top N 关系。"""
        top_stock = self._match_top_stock(top_match_index, getattr(item, "asset_code", ""))
        return {
            "request_id": getattr(item, "request_id", ""),
            "asset_code": getattr(item, "asset_code", ""),
            "asset_name": getattr(item, "asset_name", ""),
            "direction": getattr(item, "direction", ""),
            "execution_status": getattr(item, "execution_status", ""),
            "is_in_top10": bool(top_stock),
            "current_top_rank": top_stock.get("rank") if top_stock else None,
            "current_top_score": top_stock.get("score") if top_stock else None,
            "current_top_source": top_stock.get("source") if top_stock else None,
            "origin_stage_label": (
                f"当前 Top 10 第 #{top_stock.get('rank')}" if top_stock else "当前不在 Top 10"
            ),
            "chain_stage": "pending",
            "chain_stage_label": "待执行队列",
        }
