"""Bridge helpers for recommendation-to-execution links."""

from __future__ import annotations

import logging
from typing import Any

from apps.simulated_trading.application.ports import ExecutionLinkRecorderProtocol

logger = logging.getLogger(__name__)


class DecisionExecutionLinkRecorder(ExecutionLinkRecorderProtocol):
    """Record simulated executions against decision-rhythm recommendations."""

    def __init__(self, recommendation_repo: Any | None = None) -> None:
        self._recommendation_repo = recommendation_repo

    @property
    def recommendation_repo(self) -> Any:
        if self._recommendation_repo is None:
            from apps.decision_rhythm.application.repository_provider import (
                get_unified_recommendation_repository,
            )

            self._recommendation_repo = get_unified_recommendation_repository()
        return self._recommendation_repo

    def record_execution(
        self,
        *,
        recommendation_id: str | None,
        transaction_id: int,
        account_id: int,
        security_code: str,
        actual_action: str,
        executed_at,
        match_if_missing: bool = False,
        notes: str = "",
    ) -> dict | None:
        normalized_action = str(actual_action or "").strip().lower()
        if normalized_action not in {"buy", "sell"}:
            return None

        account_key = str(account_id)
        recommendation_key = str(recommendation_id or "").strip()
        match_confidence = 1.0 if recommendation_key else 0.0
        match_method = "auto"

        if not recommendation_key and match_if_missing:
            side = "BUY" if normalized_action == "buy" else "SELL"
            match = self.recommendation_repo.find_execution_match(
                account_id=account_key,
                security_code=security_code,
                side=side,
                traded_at=executed_at,
            )
            if match:
                recommendation_key = str(match["recommendation_id"])
                match_confidence = float(match.get("match_confidence", 0.85) or 0.85)

        if not recommendation_key:
            return None

        try:
            self.recommendation_repo.update_user_action(
                recommendation_id=recommendation_key,
                user_action="ADOPTED",
                note=f"Auto simulated execution {transaction_id}",
                account_id=account_key,
            )
            return self.recommendation_repo.record_execution_link(
                recommendation_id=recommendation_key,
                transaction_id=transaction_id,
                transaction_source="simulated_trade",
                account_id=account_key,
                security_code=security_code,
                actual_action=normalized_action,
                match_method=match_method,
                match_confidence=match_confidence,
                notes=notes or "Linked by simulated auto trading",
            )
        except Exception as exc:
            logger.warning(
                "Failed to record simulated execution link tx=%s rec=%s: %s",
                transaction_id,
                recommendation_key,
                exc,
            )
            return None


def build_decision_execution_link_recorder() -> ExecutionLinkRecorderProtocol:
    """Build the default decision execution link recorder."""

    return DecisionExecutionLinkRecorder()


def list_decision_execution_links(
    *,
    current_user_id: int | None,
    is_admin: bool,
    account_id: str | None = None,
    recommendation_id: str | None = None,
    transaction_source: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent execution links with user account scoping."""

    from apps.decision_rhythm.application.repository_provider import (
        get_unified_recommendation_repository,
    )

    account_ids: list[str] | None = None
    if not is_admin:
        if current_user_id is None:
            return []
        from apps.simulated_trading.application.repository_provider import (
            get_simulated_account_repository,
        )

        accounts = get_simulated_account_repository().get_by_user(current_user_id)
        account_ids = [str(account.account_id) for account in accounts]
        if account_id and str(account_id) not in account_ids:
            return []

    return get_unified_recommendation_repository().list_execution_links(
        account_ids=account_ids,
        account_id=account_id,
        recommendation_id=recommendation_id,
        transaction_source=transaction_source,
        limit=limit,
    )
