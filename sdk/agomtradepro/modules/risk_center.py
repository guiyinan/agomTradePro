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

    def update_template(self, template_id: int, payload: dict[str, Any], *, partial: bool = True) -> dict[str, Any]:
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
