"""AgomTradePro SDK - Risk Center module."""

from typing import Any

from .base import BaseModule


class RiskCenterModule(BaseModule):
    """Client wrapper for centralized risk control APIs."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/risk-center")

    def get_floor(self) -> dict[str, Any]:
        response = self._get("floor/")
        return response.get("data", response)

    def update_floor(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._put("floor/", json=payload)
        return response.get("data", response)

    def list_templates(self) -> list[dict[str, Any]]:
        response = self._get("templates/")
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("templates/", json=payload)
        return response.get("data", response)

    def update_template(
        self, template_id: int, payload: dict[str, Any], *, partial: bool = True
    ) -> dict[str, Any]:
        method = self._patch if partial else self._put
        response = method(f"templates/{template_id}/", json=payload)
        return response.get("data", response)

    def list_account_policies(self) -> list[dict[str, Any]]:
        response = self._get("account-policies/")
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def upsert_account_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("account-policies/", json=payload)
        return response.get("data", response)

    def update_account_policy(
        self,
        policy_id: int,
        payload: dict[str, Any],
        *,
        partial: bool = True,
    ) -> dict[str, Any]:
        method = self._patch if partial else self._put
        response = method(f"account-policies/{policy_id}/", json=payload)
        return response.get("data", response)

    def get_account_policy(self, account_id: int) -> dict[str, Any]:
        response = self._get(f"account-policies/by-account/{account_id}/")
        return response.get("data", response)

    def apply_template_to_policy(self, policy_id: int, template_id: int) -> dict[str, Any]:
        response = self._post(
            f"account-policies/{policy_id}/apply-template/",
            json={"template_id": template_id},
        )
        return response.get("data", response)

    def list_exceptions(self, *, account_id: int | None = None) -> list[dict[str, Any]]:
        params = {"account_id": account_id} if account_id is not None else None
        response = self._get("exceptions/", params=params)
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def create_exception(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("exceptions/", json=payload)
        return response.get("data", response)

    def get_effective_policy(self, account_id: int) -> dict[str, Any]:
        response = self._get("effective-policy/", params={"account_id": account_id})
        return response.get("data", response)

    def check_pre_trade(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("pre-trade-check/", json=payload)
        return response.get("data", response)

    def check_post_investment(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("post-investment-check/", json=payload)
        return response.get("data", response)

    def generate_daily_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post("daily-report/", json=payload)
        return response.get("data", response)

    def list_daily_reports(
        self,
        *,
        account_id: int | None = None,
        report_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            key: value
            for key, value in {
                "account_id": account_id,
                "report_date": report_date,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
            }.items()
            if value is not None
        }
        response = self._get("daily-report/", params=params or None)
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def get_daily_report(self, account_id: int, report_date: str) -> dict[str, Any]:
        response = self._get(
            "daily-report/",
            params={"account_id": account_id, "report_date": report_date},
        )
        return response.get("data", response)

    def list_scenarios(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        """List repository-backed stress-scenario definitions."""

        response = self._get(
            "stress-scenarios/",
            params={"include_inactive": str(include_inactive).lower()},
        )
        if isinstance(response, list):
            return response
        return response.get("data", response)

    def get_scenario(self, scenario_key: str) -> dict[str, Any]:
        """Read one scenario and its immutable revision history."""

        response = self._get(f"stress-scenarios/{scenario_key}/")
        return response.get("data", response)

    def get_active_scenario_set(
        self,
        *,
        environment: str = "production",
        purpose: str = "portfolio_stress",
    ) -> dict[str, Any]:
        """Read the active scenario-set revision for one scope."""

        response = self._get(
            "stress-scenario-sets/active/",
            params={"environment": environment, "purpose": purpose},
        )
        return response.get("data", response)

    def validate_scenario_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate a scenario revision without writing it."""

        response = self._post("stress-scenarios/validate-revision/", json=payload)
        return response.get("data", response)

    def preview_scenario_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Preview an immutable replacement revision without activating it."""

        response = self._post("stress-scenarios/preview-revision/", json=payload)
        return response.get("data", response)

    def preview_scenario_action(
        self,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist an exact preview for propose, activate, rollback, or retire."""

        response = self._post(
            "stress-scenarios/preview-revision/",
            json={"operation": operation, **payload},
        )
        return response.get("data", response)

    def propose_scenario_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a draft/proposed revision and persistent human-review proposal."""

        response = self._post("stress-scenarios/propose-revision/", json=payload)
        return response.get("data", response)

    def activate_scenario_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Activate a human-approved scenario-set revision."""

        response = self._post("stress-scenario-sets/activate/", json=payload)
        return response.get("data", response)

    def approve_scenario_proposal(
        self,
        proposal_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Approve a scenario proposal as a human staff principal."""

        response = self._post(
            f"stress-scenario-proposals/{proposal_id}/approve/",
            json=payload,
        )
        return response.get("data", response)

    def reject_scenario_proposal(
        self,
        proposal_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Reject a scenario proposal as a human staff principal."""

        response = self._post(
            f"stress-scenario-proposals/{proposal_id}/reject/",
            json=payload,
        )
        return response.get("data", response)

    def rollback_scenario_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Copy a prior revision into a new revision and activate the copy."""

        response = self._post("stress-scenario-sets/rollback/", json=payload)
        return response.get("data", response)

    def retire_scenario(self, scenario_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Retire a scenario through the governed replacement workflow."""

        response = self._post(f"stress-scenarios/{scenario_key}/retire/", json=payload)
        return response.get("data", response)

    def preview_scenario_matrix(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Preview probability-weighted impacts for an immutable portfolio snapshot."""

        response = self._post("stress-scenario-sets/impact-preview/", json=payload)
        return response.get("data", response)

    def get_market_state_evidence(self) -> dict[str, Any]:
        """Read the five-dimensional market-state evidence card."""

        response = self._get("research/market-state/")
        return response.get("data", response)

    def build_decision_scorecard(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build the governed ex-ante environment/valuation scorecard."""

        response = self._post("research/decision-scorecard/", json=payload)
        return response.get("data", response)

    def generate_strategy_brief(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate an auditable brief from structured, referenced facts."""

        response = self._post("research/strategy-brief/", json=payload)
        return response.get("data", response)
