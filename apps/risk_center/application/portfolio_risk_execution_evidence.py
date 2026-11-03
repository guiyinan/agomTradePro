"""Existing risk-policy audit storage for a committed simulation risk check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload


@dataclass(frozen=True, slots=True)
class PortfolioRiskExecutionEvidence:
    """Complete risk inputs/results bound to the exact existing order request."""

    account_id: int
    owner_user_id: int
    account_policy_id: int
    idempotency_key: str
    request_payload_hash: str
    code_version: str
    policy_binding_sha256: str
    report: PortfolioRiskReportPayload
    input_snapshot_json: str


class PortfolioRiskExecutionEvidenceWriter(Protocol):
    """Append to the existing risk-policy audit in the ledger transaction."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction scope used by this writer."""
        ...

    def record_passed_check(self, evidence: PortfolioRiskExecutionEvidence) -> None:
        """Retain one actual passed check; no side effects are permitted on GET."""
        ...
