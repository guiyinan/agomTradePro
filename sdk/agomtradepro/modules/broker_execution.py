"""AgomTradePro SDK - governed QMT live execution module."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from .base import BaseModule


class BrokerOrderActionFlags(TypedDict):
    """Stable lifecycle or actor-authorization flags for one order."""

    approve: bool
    reject: bool
    cancel: bool


class BrokerOrderEvidenceSummary(TypedDict):
    """Typed display-only Evidence summary published by Broker core."""

    output_owner: str
    output_artifact_type: str
    output_artifact_id: str
    output_artifact_version: str
    output_content_hash: str
    envelope_content_hash: str
    operator_spec_content_hash: str
    claim_kind: str
    method_kind: str
    research_family: str
    governance_state: str
    permission: str
    blocker_codes: list[str]
    dependency_flags: list[str]
    track_record_availability: str
    track_record_content_hash: str | None
    n_eff: str | None
    coverage: str | None
    evaluated_at: str
    valid_until: str
    must_not_use_for_decision: bool
    must_not_execute: bool


class BrokerOrderEventMetadata(TypedDict):
    """Bounded broker event metadata; untyped event payloads are omitted."""

    event_id: str
    event_type: str
    status: str
    occurred_at: str
    received_at: str


class BrokerOrderFill(TypedDict):
    """Bounded persisted fill projection."""

    broker_trade_id: str
    quantity: str
    price: str
    amount: str
    occurred_at: str


class BrokerOrderDetail(TypedDict):
    """Governed order-detail markers preserved by the SDK boundary."""

    evaluated_at: str
    lifecycle_transitions: BrokerOrderActionFlags
    actor_authorization: BrokerOrderActionFlags
    transport_blocker_codes: list[str]
    event_payload_policy: str
    risk_snapshot_policy: str
    risk_snapshot_content_hash: str | None
    approval_evidence_status: str
    approval_evidence_blocker_codes: list[str]
    approval_evidence: BrokerOrderEvidenceSummary | None
    permission: str
    must_not_use_for_decision: bool
    must_not_execute: bool
    events: list[BrokerOrderEventMetadata]
    fills: list[BrokerOrderFill]


class BrokerExecutionModule(BaseModule):
    """Formal client for strict reads and preview/commit live execution workflows."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/broker-execution")

    @staticmethod
    def _data(response: dict[str, Any]) -> Any:
        return response.get("data", response)

    def overview(self) -> dict[str, Any]:
        return self._data(self._get("/"))

    def list_orders(
        self,
        *,
        account_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params = {
            key: value
            for key, value in {"account_id": account_id, "status": status, "limit": limit}.items()
            if value is not None
        }
        return self._data(self._get("orders/", params=params))

    def get_order(self, client_order_id: str) -> BrokerOrderDetail:
        """Preserve the core Evidence, blocker, and actor-authorization markers."""

        return cast(
            BrokerOrderDetail,
            self._data(self._get(f"orders/{client_order_id}/")),
        )

    def order_action(
        self,
        client_order_id: str,
        action: str,
        *,
        reason: str,
        preview_only: bool = True,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {"reason": reason, "preview_only": preview_only}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if expected_version is not None:
            payload["expected_version"] = expected_version
        return self._data(self._post(f"orders/{client_order_id}/{action}/", json=payload))

    def approve_order(self, client_order_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.order_action(client_order_id, "approve", **kwargs)

    def reject_order(self, client_order_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.order_action(client_order_id, "reject", **kwargs)

    def request_cancel(self, client_order_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.order_action(client_order_id, "cancel", **kwargs)

    def set_kill_switch(
        self,
        *,
        account_id: int,
        active: bool,
        reason: str,
        preview_only: bool = True,
        idempotency_key: str | None = None,
        reauth_password: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "account_id": account_id,
            "active": active,
            "reason": reason,
            "preview_only": preview_only,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if reauth_password is not None:
            payload["reauth"] = {
                "method": "password",
                "credential": reauth_password,
            }
        return self._data(self._post("kill-switch/", json=payload))

    def connections(self) -> dict[str, Any]:
        return self._data(self._get("connections/"))

    def reconciliations(self, *, limit: int = 100) -> dict[str, Any]:
        return self._data(self._get("reconciliations/", params={"limit": limit}))

    def resolve_reconciliation(
        self,
        run_id: int,
        *,
        resolution: str,
        reason: str,
        preview_only: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "resolution": resolution,
            "reason": reason,
            "preview_only": preview_only,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return self._data(self._post(f"reconciliations/{run_id}/resolve/", json=payload))

    def audit(self, *, limit: int = 100) -> dict[str, Any]:
        return self._data(self._get("audit/", params={"limit": limit}))
