"""Typed adapters and readers for legacy opaque account repositories."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol, cast

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerExecutionMatchResult,
    BrokerFactRecord,
    BrokerFactWriteDisposition,
    BrokerTradeReconciliationRepository,
    JsonValue,
    MatchingOutcomeKind,
    NormalizedTradeRow,
)

_logger = logging.getLogger(__name__)
RESOLVED_MATCH_OUTCOMES = frozenset({"matched", "manual_only"})


def _optional_method(target: object, name: str) -> Callable[..., object] | None:
    """Narrow one optional compatibility method at the repository boundary."""
    value = getattr(target, name, None)
    return cast(Callable[..., object], value) if callable(value) else None


class _RepositoryBackedExecutionMatcher:
    """Adapt the historical recommendation repository to the matcher protocol."""

    def __init__(self, recommendation_repo: object) -> None:
        self._recommendation_repo = recommendation_repo

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> Mapping[str, object]:
        """Invoke the old repository methods and narrow mapping results."""
        side = "BUY" if actual_action == "buy" else "SELL"
        find = _optional_method(self._recommendation_repo, "find_execution_match")
        record = _optional_method(self._recommendation_repo, "record_execution_link")
        update = _optional_method(self._recommendation_repo, "update_user_action")
        if find is None or record is None or update is None:
            raise RuntimeError("Recommendation repository does not expose the legacy matcher API")
        match = find(
            account_id=account_id,
            security_code=security_code,
            side=side,
            traded_at=traded_at,
        )
        if not isinstance(match, Mapping):
            match = None
        if match is None:
            response = record(
                recommendation_id="",
                transaction_id=transaction_id,
                account_id=account_id,
                security_code=security_code,
                actual_action=actual_action,
                match_method="manual_only",
                match_confidence=0.0,
                notes="No matching system recommendation",
            )
        else:
            recommendation_id = match.get("recommendation_id")
            confidence = match.get("match_confidence")
            update(
                recommendation_id=recommendation_id,
                user_action="ADOPTED",
                note=f"Matched imported transaction {transaction_id}",
                account_id=account_id,
            )
            response = record(
                recommendation_id=recommendation_id,
                transaction_id=transaction_id,
                account_id=account_id,
                security_code=security_code,
                actual_action=actual_action,
                match_method="auto",
                match_confidence=confidence,
                notes="Matched by account/security/side/time window",
            )
        return response if isinstance(response, Mapping) else {}


def _mapping_integer(mapping: Mapping[str, object], key: str) -> int | None:
    """Return an integer identifier from a matcher result mapping."""
    value = mapping.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _mapping_string(mapping: Mapping[str, object], key: str) -> str | None:
    """Return a string value from a matcher result mapping."""
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


class _BrokerExecutionMatcher(Protocol):
    """Compatibility shape accepted from existing matching integrations."""

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> Mapping[str, object]:
        """Return matcher metadata without swallowing persistence exceptions."""
        ...


def attempt_broker_fact_matching(
    *,
    repo: BrokerTradeReconciliationRepository | None,
    writes: list[tuple[NormalizedTradeRow, BrokerFactRecord, BrokerFactWriteDisposition]],
    row_results: list[dict[str, JsonValue]],
    matcher: _BrokerExecutionMatcher,
) -> int:
    """Match facts inside savepoints and persist retryable failures afterwards."""
    if repo is None or not writes:
        return 0
    account_reader = _optional_method(repo, "get_existing_real_account_id")
    scope_factory = _optional_method(repo, "matching_attempt_scope")
    persist_method = _optional_method(repo, "persist_matching_result")
    if scope_factory is None or persist_method is None:
        failed = BrokerExecutionMatchResult(
            outcome="failed", link_id=None, reason_code="broker_matching_scope_unavailable"
        )
        for _, record, _ in writes:
            if persist_method is not None:
                try:
                    persist_method(transaction_id=record.transaction_id, result=failed)
                except Exception:
                    _logger.exception(
                        "Broker matching failure state could not be saved",
                        extra={"transaction_id": record.transaction_id},
                    )
            _annotate_matching_result(row_results, record.transaction_id, failed)
        return len({record.transaction_id for _, record, _ in writes})

    account_ids: dict[tuple[int, int], int | None] = {}
    failed_ids: set[int] = set()
    for _, initial_record, _ in writes:
        scope = (initial_record.owner_user_id, initial_record.portfolio_id)
        lookup_failed = False
        result: BrokerExecutionMatchResult
        try:
            context = cast(
                AbstractContextManager[BrokerFactRecord],
                scope_factory(
                    owner_user_id=initial_record.owner_user_id,
                    portfolio_id=initial_record.portfolio_id,
                    transaction_id=initial_record.transaction_id,
                ),
            )
            with context as current:
                if current.transaction_id != initial_record.transaction_id:
                    raise ValueError("matching scope returned a different transaction")
                previous = current.matching_attempt
                if previous is not None and previous.outcome in RESOLVED_MATCH_OUTCOMES:
                    result = BrokerExecutionMatchResult(
                        outcome=previous.outcome,
                        link_id=previous.link_id,
                        reason_code=previous.reason_code,
                    )
                else:
                    if scope not in account_ids:
                        resolved_account_id: int | None = None
                        if account_reader is not None:
                            try:
                                value = account_reader(
                                    owner_user_id=scope[0], portfolio_id=scope[1]
                                )
                            except Exception:
                                lookup_failed = True
                                raise
                            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                                resolved_account_id = value
                        account_ids[scope] = resolved_account_id
                    account_id = account_ids[scope]
                    if account_id is None:
                        result = BrokerExecutionMatchResult(
                            outcome="deferred",
                            link_id=None,
                            reason_code=(
                                "real_account_mapping_missing"
                                if account_reader is not None
                                else "real_account_mapping_reader_unavailable"
                            ),
                        )
                    else:
                        result = _match_one(matcher, account_id, current)
                    persist_method(transaction_id=current.transaction_id, result=result)
        except Exception:
            _logger.exception(
                "Broker execution matcher failed inside its savepoint",
                extra={"transaction_id": initial_record.transaction_id},
            )
            result = BrokerExecutionMatchResult(
                outcome="failed",
                link_id=None,
                reason_code=(
                    "real_account_mapping_lookup_failed"
                    if lookup_failed
                    else "broker_matcher_failed"
                ),
            )
            try:
                persist_method(transaction_id=initial_record.transaction_id, result=result)
            except Exception:
                _logger.exception(
                    "Broker execution matching failure state could not be saved",
                    extra={"transaction_id": initial_record.transaction_id},
                )
            failed_ids.add(initial_record.transaction_id)
        if result.outcome == "failed":
            failed_ids.add(initial_record.transaction_id)
        _annotate_matching_result(row_results, initial_record.transaction_id, result)
    return len(failed_ids)


def _match_one(
    matcher: _BrokerExecutionMatcher,
    account_id: int,
    fact: BrokerFactRecord,
) -> BrokerExecutionMatchResult:
    """Invoke the matcher and narrow its legacy response outside any catch."""
    payload = matcher.record_imported_execution(
        account_id=str(account_id),
        transaction_id=fact.transaction_id,
        security_code=fact.asset_code,
        actual_action=fact.action,
        traded_at=fact.traded_at,
    )
    method = payload.get("match_method")
    outcome: MatchingOutcomeKind
    if method == "auto":
        outcome = "matched"
    elif method == "manual_only":
        outcome = "manual_only"
    else:
        outcome = "deferred"
    link_id = _mapping_integer(payload, "id") or _mapping_integer(payload, "execution_link_id")
    return BrokerExecutionMatchResult(
        outcome=outcome,
        link_id=link_id,
        reason_code=_mapping_string(payload, "reason_code"),
    )


def _annotate_matching_result(
    rows: list[dict[str, JsonValue]],
    transaction_id: int,
    result: BrokerExecutionMatchResult,
) -> None:
    """Attach the durable or retryable matcher state to its import row."""
    for row in rows:
        if row.get("transaction_id") == transaction_id:
            row["matching_status"] = result.outcome
            row["matching_reason_code"] = result.reason_code
            break
