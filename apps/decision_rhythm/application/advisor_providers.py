"""Default provider adapters used by the auto-advisor application service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from apps.account.application.portfolio_api_services import (
    PortfolioAccessDeniedError,
    PortfolioNotFoundError,
    get_portfolio_positions_read_payload,
)
from apps.decision_rhythm.application.advisor_contracts import (
    ACTIONABLE_SIDES,
    BUY_SIDES,
    AdvisorAccessError,
    AdvisorAccountSnapshot,
    AdvisorHoldingSnapshot,
    AdvisorOrderIntent,
    get_manual_trade_portfolio_id_for_account,
)
from apps.decision_rhythm.application.advisor_execution import (
    _merge_holdings,
    _parse_account_id,
)
from apps.decision_rhythm.application.advisor_intents import (
    _account_type_label,
    _build_signal_invalidation_check,
    _failed_execution_checks,
    _normalize_risk_policy_context,
    _recommendation_source_signal_ids,
    _unique_asset_codes,
)
from apps.decision_rhythm.application.advisor_serialization import (
    _decimal_to_number,
    _optional_decimal,
    _to_decimal,
    _to_decimal_or_none,
)
from apps.simulated_trading.application.interface_services import get_account_access

from .workspace_services import (
    build_recommendation_risk_checks,
    get_signal_payloads,
    get_simulated_position_snapshots,
    list_workspace_recommendations,
)


class WorkspaceRecommendationProvider:
    """Recommendation provider backed by the Decision Workspace list service."""

    def list_recommendations(self, *, account_id: str) -> list[Any]:
        """Return up to 50 non-ignored workspace recommendations."""

        recommendations, _ = list_workspace_recommendations(
            account_id=account_id,
            status=None,
            user_action=None,
            security_code=None,
            include_ignored=False,
            recommendation_id=None,
            page=1,
            page_size=50,
        )
        return recommendations


class RiskCenterAdvisorGateProvider:
    """Advisor risk gate backed by risk_center application use cases."""

    def get_policy_context(self, *, account_id: str) -> dict[str, Any]:
        """Return effective policy plus a stable version fingerprint."""

        from apps.risk_center.application.use_cases import (
            ResolveEffectiveRiskPolicyForAccountUseCase,
        )

        policy = ResolveEffectiveRiskPolicyForAccountUseCase().execute(account_id=int(account_id))
        return _normalize_risk_policy_context(policy, unavailable=False)

    def evaluate_order(
        self,
        *,
        account: dict[str, Any],
        intent: AdvisorOrderIntent,
        holdings: list[AdvisorHoldingSnapshot],
        policy_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate one advisor order against the effective risk policy."""

        version = str(policy_context.get("version") or "risk_policy_unknown")
        if policy_context.get("unavailable"):
            status = "BLOCKED" if intent.side in BUY_SIDES else "REVIEW"
            return {
                "status": status,
                "code": "risk_policy_unavailable",
                "messages": ["个人风险配置不可用，新增买入默认阻断。"],
                "policy_version": version,
                "metrics": {},
            }
        if intent.side not in ACTIONABLE_SIDES or intent.blocking_status != "OK":
            return {
                "status": "SKIPPED",
                "code": "not_actionable",
                "messages": [],
                "policy_version": version,
                "metrics": {},
            }

        from apps.risk_center.application.trade_guard import EvaluatePreTradeRiskUseCase

        total_asset = float(_to_decimal(account.get("total_asset")))
        cash = float(_to_decimal(account.get("available_cash")))
        market_value = float(_to_decimal(account.get("market_value")))
        symbol_position_value = float(
            sum(
                holding.market_value
                for holding in holdings
                if holding.asset_code == intent.asset_code
            )
        )
        normalized_side = "buy" if intent.side in BUY_SIDES else "sell"
        result = EvaluatePreTradeRiskUseCase().execute(
            account_id=int(intent.account_id),
            symbol=intent.asset_code,
            side=normalized_side,
            quantity=float(abs(intent.delta_quantity)),
            price=float(intent.estimated_price or Decimal("0")),
            account_equity=total_asset,
            total_position_value=market_value,
            cash_balance=cash,
            current_symbol_position_value=symbol_position_value,
        )
        messages = [*result.violations, *result.warnings]
        return {
            "status": (
                "OK"
                if result.passed and not result.warnings
                else "REVIEW" if result.passed else "BLOCKED"
            ),
            "code": "risk_gate_passed" if result.passed else "risk_gate_failed",
            "messages": messages,
            "policy_version": version,
            "metrics": result.metrics,
        }


class DecisionDataHealthProvider:
    """Advisor data-health provider backed by data_center readiness payload."""

    def get_health(self, *, asset_codes: list[str]) -> dict[str, Any]:
        """Return decision-grade data readiness for the requested assets."""

        from apps.data_center.application.public import (
            get_decision_data_readiness_payload,
        )

        return get_decision_data_readiness_payload(asset_codes=asset_codes)


class DecisionRhythmExecutionGuardProvider:
    """Execution guard backed by decision-rhythm and signal application services."""

    def evaluate(
        self,
        *,
        recommendation: Any | None,
        intent: AdvisorOrderIntent,
        resolution: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return execution checks that must pass before an order is actionable."""

        if recommendation is None or intent.side not in ACTIONABLE_SIDES:
            return {
                "status": "SKIPPED",
                "code": "no_actionable_recommendation",
                "checks": {},
                "messages": [],
            }

        checks = build_recommendation_risk_checks(
            recommendation,
            _to_decimal_or_none(intent.estimated_price),
        )
        signal_ids = list((resolution or {}).get("source_signal_ids") or [])
        if not signal_ids:
            signal_ids = _recommendation_source_signal_ids(recommendation)
        signal_payloads = get_signal_payloads(signal_ids)
        if signal_payloads:
            checks["signal_invalidation"] = _build_signal_invalidation_check(signal_payloads)

        failed = _failed_execution_checks(checks)
        return {
            "status": "BLOCKED" if failed else "OK",
            "code": "execution_guard_failed" if failed else "execution_guard_passed",
            "checks": checks,
            "messages": [item["reason"] for item in failed if item.get("reason")],
        }


class DataCenterAssetExposureProvider:
    """Asset exposure provider backed by data_center application services."""

    def get_asset_exposures(self, *, asset_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Resolve sector and industry without importing data_center infrastructure."""

        from apps.data_center.application.dtos import ResolveAssetRequest
        from apps.data_center.application.interface_services import (
            make_resolve_asset_use_case,
        )

        use_case = make_resolve_asset_use_case()
        exposures: dict[str, dict[str, Any]] = {}
        for asset_code in _unique_asset_codes(asset_codes):
            response = use_case.execute(ResolveAssetRequest(code=asset_code))
            if response is None:
                exposures[asset_code] = {}
                continue
            exposures[asset_code] = {
                "sector": response.sector,
                "industry": response.industry,
                "asset_type": response.asset_type,
            }
        return exposures


class DecisionExecutionTrackingProvider:
    """Recommendation tracking provider backed by existing execution links."""

    def get_execution_links(
        self,
        *,
        account_id: str,
        recommendation_ids: list[str],
        user: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return recommendation-to-execution links for the current account."""

        if not recommendation_ids:
            return {}

        from core.integration.decision_execution_links import list_decision_execution_links

        links = list_decision_execution_links(
            current_user_id=getattr(user, "id", None),
            is_admin=bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)),
            account_id=account_id,
            recommendation_id=None,
            transaction_source=None,
            limit=200,
        )
        wanted = set(recommendation_ids)
        grouped: dict[str, list[dict[str, Any]]] = {item: [] for item in recommendation_ids}
        for link in links:
            recommendation_id = str(link.get("recommendation_id") or "")
            if recommendation_id in wanted:
                grouped.setdefault(recommendation_id, []).append(dict(link))
        return grouped


class DataCenterRecommendationPerformanceProvider:
    """Recommendation performance provider backed by data_center price facts."""

    def get_close_price_series(
        self,
        *,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        """Return historical close prices for one asset."""

        from core.integration.price_history import (
            fetch_close_price_series_from_data_center,
        )

        return fetch_close_price_series_from_data_center(
            asset_code=asset_code,
            start_date=start_date,
            end_date=end_date,
        )


class RegimePolicyAttributionContextProvider:
    """Attribution context provider backed by Regime/Policy application services."""

    def __init__(self) -> None:
        self._cache: dict[date, dict[str, Any]] = {}

    def get_context(
        self,
        *,
        recommendation_date: date | None,
        outcome_date: date | None,
    ) -> dict[str, Any]:
        """Return Regime and Policy context for recommendation and outcome dates."""

        return {
            "recommendation": self._context_for_date(recommendation_date),
            "outcome": self._context_for_date(outcome_date),
        }

    def _context_for_date(self, target_date: date | None) -> dict[str, Any]:
        if target_date is None:
            return {
                "status": "DATE_UNAVAILABLE",
                "date": None,
                "regime": None,
                "regime_confidence": None,
                "policy_level": None,
                "errors": [],
            }
        if target_date in self._cache:
            return dict(self._cache[target_date])

        errors: list[str] = []
        regime: str | None = None
        regime_confidence: float | None = None
        policy_level: str | None = None
        try:
            from apps.regime.application.interface_services import get_regime_current_payload

            regime_payload = get_regime_current_payload(as_of_date=target_date)
            regime_data = dict(regime_payload.get("data") or {})
            regime = str(regime_data.get("dominant_regime") or "") or None
            regime_confidence = _decimal_to_number(_optional_decimal(regime_data.get("confidence")))
        except Exception as exc:
            errors.append(f"regime:{exc}")

        try:
            from apps.policy.application.query_services import get_policy_status_payload

            policy_payload = get_policy_status_payload(as_of_date=target_date)
            policy_level = str(policy_payload.get("current_level") or "") or None
        except Exception as exc:
            errors.append(f"policy:{exc}")

        payload = {
            "status": "OK" if not errors else "PARTIAL",
            "date": target_date.isoformat(),
            "regime": regime,
            "regime_confidence": regime_confidence,
            "policy_level": policy_level,
            "errors": errors,
        }
        self._cache[target_date] = payload
        return dict(payload)


class AccountHoldingSnapshotProvider:
    """Build a unified holding snapshot for one user-facing account id."""

    def get_snapshot(self, *, account_id: str, user: Any) -> AdvisorAccountSnapshot:
        """Validate account access and return normalized simulated/manual holdings."""

        normalized_account_id = _parse_account_id(account_id)
        access = get_account_access(user, normalized_account_id, action="查看自动投顾建议")
        if not access.allowed:
            raise AdvisorAccessError(access.error or "无权查看该账户", access.status_code or 403)

        account = access.account
        warnings: list[str] = []
        raw_holdings: list[dict[str, Any]] = []

        try:
            raw_holdings.extend(
                {
                    **item,
                    "data_source": "simulated",
                }
                for item in get_simulated_position_snapshots(account_id=normalized_account_id)
            )
        except Exception as exc:
            warnings.append(f"simulated_positions_unavailable:{exc}")

        portfolio_id = get_manual_trade_portfolio_id_for_account(normalized_account_id)
        if portfolio_id is not None:
            try:
                _, payload = get_portfolio_positions_read_payload(
                    user_id=int(user.id),
                    portfolio_id=portfolio_id,
                )
                raw_holdings.extend(
                    {
                        **item,
                        "data_source": "manual_portfolio",
                    }
                    for item in payload
                )
            except (PortfolioAccessDeniedError, PortfolioNotFoundError) as exc:
                warnings.append(f"manual_portfolio_unavailable:{exc}")

        cash = _to_decimal(getattr(account, "current_cash", 0))
        total_asset = _to_decimal(getattr(account, "total_value", 0))
        market_value = _to_decimal(getattr(account, "current_market_value", 0))
        if total_asset <= 0:
            total_asset = cash + market_value
        if total_asset <= 0:
            total_asset = sum(_to_decimal(item.get("market_value")) for item in raw_holdings) + cash

        holdings = _merge_holdings(raw_holdings, total_asset=total_asset)
        baseline = "empty_positions" if not holdings else "existing_positions"
        account_type = str(getattr(account, "account_type", "") or "unknown")

        return AdvisorAccountSnapshot(
            account_summary={
                "account_id": str(normalized_account_id),
                "account_name": getattr(account, "account_name", "")
                or f"账户 {normalized_account_id}",
                "account_type": account_type,
                "account_type_label": _account_type_label(account_type),
                "account_status": "active" if getattr(account, "is_active", False) else "inactive",
                "total_asset": _decimal_to_number(total_asset),
                "cash": _decimal_to_number(cash),
                "available_cash": _decimal_to_number(cash),
                "market_value": _decimal_to_number(market_value),
                "holding_count": len(holdings),
                "baseline": baseline,
            },
            holdings=holdings,
            baseline=baseline,
            warnings=warnings,
        )


__all__ = [
    "WorkspaceRecommendationProvider",
    "RiskCenterAdvisorGateProvider",
    "DecisionDataHealthProvider",
    "DecisionRhythmExecutionGuardProvider",
    "DataCenterAssetExposureProvider",
    "DecisionExecutionTrackingProvider",
    "DataCenterRecommendationPerformanceProvider",
    "RegimePolicyAttributionContextProvider",
    "AccountHoldingSnapshotProvider",
]
