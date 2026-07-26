"""Bridge helpers for recommendation-to-execution links."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from django.db import transaction

from apps.simulated_trading.application.ports import ExecutionLinkRecorderProtocol
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


class ExecutionRecommendationRepositoryProtocol(Protocol):
    """Repository operations required to persist recommendation execution links."""

    def find_execution_match(
        self,
        *,
        account_id: str,
        security_code: str,
        side: str,
        traded_at: datetime,
    ) -> Mapping[str, object] | None: ...

    def update_user_action(
        self,
        *,
        recommendation_id: str,
        user_action: str,
        note: str,
        account_id: str,
    ) -> object | None: ...

    def record_execution_link(
        self,
        *,
        recommendation_id: str,
        transaction_id: int,
        transaction_source: str = "account_transaction",
        account_id: str,
        security_code: str,
        actual_action: str,
        match_method: str,
        match_confidence: float,
        notes: str,
    ) -> Mapping[str, object]: ...


def _require_positive_id(value: object, *, field_name: str) -> int:
    """Return a positive non-boolean identifier."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_nonempty_text(value: object, *, field_name: str) -> str:
    """Return normalized non-empty text used in execution identity fields."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _require_aware_datetime(value: object, *, field_name: str) -> datetime:
    """Return a timezone-aware execution timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value


def _match_identity(match: Mapping[str, object]) -> tuple[str, float]:
    """Validate one repository match without fabricating confidence."""

    recommendation_id = _require_nonempty_text(
        match.get("recommendation_id"),
        field_name="recommendation_id",
    )
    raw_confidence = match.get("match_confidence")
    if raw_confidence is None:
        confidence = 0.85
    elif isinstance(raw_confidence, bool):
        confidence = None
    else:
        confidence = safe_float(raw_confidence)
    if confidence is None or not 0.0 <= confidence <= 1.0:
        raise ValueError("match_confidence must be finite and between 0 and 1")
    return recommendation_id, confidence


def _execution_link_payload(value: object) -> dict[str, object]:
    """Copy one repository result into the public execution-link contract."""

    if not isinstance(value, Mapping):
        raise TypeError("execution link repository returned an invalid payload")
    return {str(key): item for key, item in value.items()}


class DecisionExecutionLinkRecorder(ExecutionLinkRecorderProtocol):
    """Record simulated executions against decision-rhythm recommendations."""

    def __init__(
        self,
        recommendation_repo: ExecutionRecommendationRepositoryProtocol | None = None,
    ) -> None:
        self._recommendation_repo = recommendation_repo

    @property
    def recommendation_repo(self) -> ExecutionRecommendationRepositoryProtocol:
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
        executed_at: datetime,
        match_if_missing: bool = False,
        notes: str = "",
    ) -> dict[str, object] | None:
        normalized_action = str(actual_action or "").strip().lower()
        if normalized_action not in {"buy", "sell"}:
            return None

        try:
            normalized_transaction_id = _require_positive_id(
                transaction_id,
                field_name="transaction_id",
            )
            normalized_account_id = _require_positive_id(account_id, field_name="account_id")
            account_key = str(normalized_account_id)
            normalized_security_code = _require_nonempty_text(
                security_code,
                field_name="security_code",
            ).upper()
            normalized_executed_at = _require_aware_datetime(
                executed_at,
                field_name="executed_at",
            )
        except ValueError:
            return None

        recommendation_key = str(recommendation_id or "").strip()
        match_confidence = 1.0 if recommendation_key else 0.0
        match_method = "auto"

        if not recommendation_key and match_if_missing:
            side = "BUY" if normalized_action == "buy" else "SELL"
            match = self.recommendation_repo.find_execution_match(
                account_id=account_key,
                security_code=normalized_security_code,
                side=side,
                traded_at=normalized_executed_at,
            )
            if match is not None:
                try:
                    recommendation_key, match_confidence = _match_identity(match)
                except (TypeError, ValueError):
                    return None

        if not recommendation_key:
            return None

        try:
            with transaction.atomic():
                updated = self.recommendation_repo.update_user_action(
                    recommendation_id=recommendation_key,
                    user_action="ADOPTED",
                    note=f"Auto simulated execution {normalized_transaction_id}",
                    account_id=account_key,
                )
                if updated is None:
                    raise ValueError("recommendation not found for execution link")
                payload = self.recommendation_repo.record_execution_link(
                    recommendation_id=recommendation_key,
                    transaction_id=normalized_transaction_id,
                    transaction_source="simulated_trade",
                    account_id=account_key,
                    security_code=normalized_security_code,
                    actual_action=normalized_action,
                    match_method=match_method,
                    match_confidence=match_confidence,
                    notes=notes or "Linked by simulated auto trading",
                )
            return _execution_link_payload(payload)
        except Exception as exc:
            logger.warning(
                "Failed to record simulated execution link tx=%s (error_type=%s)",
                normalized_transaction_id,
                type(exc).__name__,
            )
            return None


class DecisionManualTradeExecutionMatcher:
    """Match imported manual trades to decision-rhythm recommendations."""

    def __init__(
        self,
        recommendation_repo: ExecutionRecommendationRepositoryProtocol | None = None,
    ) -> None:
        self._recommendation_repo = recommendation_repo

    @property
    def recommendation_repo(self) -> ExecutionRecommendationRepositoryProtocol:
        if self._recommendation_repo is None:
            from apps.decision_rhythm.application.repository_provider import (
                get_unified_recommendation_repository,
            )

            self._recommendation_repo = get_unified_recommendation_repository()
        return self._recommendation_repo

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> dict[str, object]:
        normalized_action = str(actual_action or "").strip().lower()
        side = {"buy": "BUY", "sell": "SELL"}.get(normalized_action)
        if side is None:
            raise ValueError("actual_action must be buy or sell")
        normalized_account_id = _require_nonempty_text(account_id, field_name="account_id")
        normalized_transaction_id = _require_positive_id(
            transaction_id,
            field_name="transaction_id",
        )
        normalized_security_code = _require_nonempty_text(
            security_code,
            field_name="security_code",
        ).upper()
        normalized_traded_at = _require_aware_datetime(traded_at, field_name="traded_at")

        match = self.recommendation_repo.find_execution_match(
            account_id=normalized_account_id,
            security_code=normalized_security_code,
            side=side,
            traded_at=normalized_traded_at,
        )
        if match is None:
            return _execution_link_payload(
                self.recommendation_repo.record_execution_link(
                    recommendation_id="",
                    transaction_id=normalized_transaction_id,
                    account_id=normalized_account_id,
                    security_code=normalized_security_code,
                    actual_action=normalized_action,
                    match_method="manual_only",
                    match_confidence=0.0,
                    notes="No matching system recommendation",
                )
            )

        recommendation_id, match_confidence = _match_identity(match)
        with transaction.atomic():
            updated = self.recommendation_repo.update_user_action(
                recommendation_id=recommendation_id,
                user_action="ADOPTED",
                note=f"Matched imported transaction {normalized_transaction_id}",
                account_id=normalized_account_id,
            )
            if updated is None:
                raise ValueError("recommendation not found for execution link")
            payload = self.recommendation_repo.record_execution_link(
                recommendation_id=recommendation_id,
                transaction_id=normalized_transaction_id,
                account_id=normalized_account_id,
                security_code=normalized_security_code,
                actual_action=normalized_action,
                match_method="auto",
                match_confidence=match_confidence,
                notes="Matched by account/security/side/time window",
            )
        return _execution_link_payload(payload)


def build_decision_execution_link_recorder() -> ExecutionLinkRecorderProtocol:
    """Build the default decision execution link recorder."""

    return DecisionExecutionLinkRecorder()


def build_manual_trade_execution_matcher() -> DecisionManualTradeExecutionMatcher:
    """Build the default manual-trade execution matcher."""

    return DecisionManualTradeExecutionMatcher()


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

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer between 1 and 200")
    normalized_account_filter = str(account_id or "").strip() or None
    normalized_recommendation_filter = str(recommendation_id or "").strip() or None
    normalized_source_filter = str(transaction_source or "").strip() or None

    account_ids: list[str] | None = None
    if not is_admin:
        if current_user_id is None or isinstance(current_user_id, bool) or current_user_id <= 0:
            return []
        from apps.simulated_trading.application.repository_provider import (
            get_simulated_account_repository,
        )

        accounts = get_simulated_account_repository().get_by_user(current_user_id)
        account_ids = [str(account.account_id) for account in accounts]
        if normalized_account_filter and normalized_account_filter not in account_ids:
            return []

    raw_links: object = get_unified_recommendation_repository().list_execution_links(
        account_ids=account_ids,
        account_id=normalized_account_filter,
        recommendation_id=normalized_recommendation_filter,
        transaction_source=normalized_source_filter,
        limit=limit,
    )
    if not isinstance(raw_links, list) or not all(isinstance(link, dict) for link in raw_links):
        raise TypeError("execution link repository returned an invalid list payload")
    return [_execution_link_payload(link) for link in raw_links]
