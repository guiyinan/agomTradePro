"""Append risk execution proofs to the existing account-policy audit table."""

from __future__ import annotations

import json

from django.db import transaction

from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidence,
)
from apps.risk_center.application.portfolio_risk_order_admission import (
    portfolio_risk_order_admission_is_effective,
)
from apps.risk_center.infrastructure.models import RiskPolicyAuditModel


class DjangoPortfolioRiskExecutionEvidenceWriter:
    """Share the simulated ledger transaction; failed executions roll back the proof."""

    def __init__(self, *, using: str) -> None:
        """Bind audit writes to the ledger database without creating a new store."""

        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Identify the exact Django database alias used for atomic evidence writes."""

        return f"django:{self._using}"

    def record_passed_check(self, evidence: PortfolioRiskExecutionEvidence) -> None:
        """Record only allowed simulation results inside the existing transaction."""

        if not transaction.get_connection(self._using).in_atomic_block:
            raise ValueError("portfolio risk execution evidence requires the ledger transaction")
        if not portfolio_risk_order_admission_is_effective(
            evidence.report,
            subject_id=evidence.idempotency_key,
        ):
            raise ValueError("only an actual admitted simulation order can be recorded")
        if evidence.report["account_id"] != evidence.account_id:
            raise ValueError("risk evidence account scope differs from its report")
        input_snapshot: object = json.loads(evidence.input_snapshot_json)
        if not isinstance(input_snapshot, dict):
            raise ValueError("risk execution input snapshot must be an object")
        RiskPolicyAuditModel.objects.using(self._using).create(
            target_type=RiskPolicyAuditModel.TARGET_POLICY,
            target_id=str(evidence.account_policy_id),
            action="portfolio_preexecution",
            actor_id=evidence.owner_user_id,
            before={},
            after={
                "scope": "simulation_only",
                "account_id": evidence.account_id,
                "idempotency_key": evidence.idempotency_key,
                "request_payload_hash": evidence.request_payload_hash,
                "code_version": evidence.code_version,
                "policy_binding_sha256": evidence.policy_binding_sha256,
                "input_snapshot": input_snapshot,
                "risk_result": evidence.report,
            },
            reason="Owner-scoped simulated portfolio risk revalidated before ledger execution.",
        )
