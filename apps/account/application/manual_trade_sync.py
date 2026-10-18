"""Facts-first orchestration for broker executions and their local reconciliation."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast

from django.utils import timezone

from apps.account.application.broker_trade_reconciliation_contracts import (
    BalanceSnapshot,
    BaselineRequest,
    BrokerBalanceSnapshotSummary,
    BrokerBaselineDecision,
    BrokerFactCandidate,
    BrokerFactPreviewConflictCode,
    BrokerFactProjectionResult,
    BrokerFactRecord,
    BrokerFactSetReconciliationResult,
    BrokerFactWriteDisposition,
    BrokerImportPreviewContext,
    BrokerTradeFactParser,
    BrokerTradeReconciliationRepository,
    JsonValue,
    NormalizedTradeRow,
)
from apps.account.application.manual_trade_compatibility import (
    _optional_method,
    _RepositoryBackedExecutionMatcher,
    attempt_broker_fact_matching,
)
from apps.account.application.manual_trade_fact_identity import (
    _same_execution,
    _same_source_execution,
    _to_fact_identity,
)
from apps.account.application.manual_trade_review_summary import (
    ManualTradeReviewSummaryUseCase as ManualTradeReviewSummaryUseCase,
)
from apps.account.application.repository_provider import (
    build_normalized_broker_trade_file_parser,
    get_broker_trade_reconciliation_repository,
    get_manual_trade_sync_repository,
)
from apps.account.domain.broker_trade_reconciliation import BrokerReconciliationState
from apps.account.domain.broker_trade_reconciliation_fingerprints import (
    broker_fact_set_fingerprint,
)
from core.integration.decision_execution_links import build_manual_trade_execution_matcher

logger = logging.getLogger(__name__)
MAX_BROKER_TRADE_IMPORT_ROWS = 5000
RESOLVED_MATCH_OUTCOMES = frozenset({"matched", "manual_only"})
RETRYABLE_FACT_STATES = frozenset(
    {
        BrokerReconciliationState.LEGACY_UNVERIFIED,
        BrokerReconciliationState.AWAITING_BASELINE,
        BrokerReconciliationState.PROJECTION_PENDING,
        BrokerReconciliationState.PROJECTION_BLOCKED,
    }
)


class ManualTradeSyncReadRepository(Protocol):
    """Legacy read/batch summary surface retained for callers during migration."""

    def get_owned_portfolio(self, *, user_id: int, portfolio_id: int) -> object | None:
        """Return an owner-scoped portfolio object or None."""
        ...

    def broker_trade_key_exists(self, broker_trade_key: str) -> bool:
        """Check the historical stable-key index without changing it."""
        ...


class ManualTradeExecutionMatcher(Protocol):
    """Compatibility interface to the existing recommendation matcher."""

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> Mapping[str, object]:
        """Return an opaque matcher response for Application to narrow."""
        ...


@dataclass(frozen=True)
class BrokerTradeImportResult:
    """Public import summary plus private, preview-bound continuation context."""

    total_rows: int
    valid_rows: int
    duplicate_rows: int
    error_rows: int
    rows: list[dict[str, JsonValue]]
    errors: list[dict[str, JsonValue]]
    imported_rows: int = 0
    skipped_rows: int = 0
    batch_id: int | None = None
    facts_saved_count: int = 0
    duplicate_facts_reused_count: int = 0
    pending_fact_count: int = 0
    projected_fact_count: int = 0
    already_in_baseline_count: int = 0
    projection_blocked_count: int = 0
    matching_failed_count: int = 0
    reconciliation_conflict_code: BrokerFactPreviewConflictCode | None = None
    reconciliation_error_code: str | None = None
    batch_summary_error_code: str | None = None
    balance_unavailable: bool = False
    _preview_context: BrokerImportPreviewContext | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def expected_fact_set_fingerprint(self) -> str | None:
        """Expose the preview digest at the stable public response level."""
        return (
            self._preview_context.expected_fact_set_fingerprint
            if self._preview_context is not None
            else None
        )

    @property
    def expected_balance_fingerprint(self) -> str | None:
        """Expose the local balance CAS digest without returning internal snapshots."""
        return (
            self._preview_context.expected_balance_fingerprint
            if self._preview_context is not None
            else None
        )

    @property
    def balance_snapshots(self) -> tuple[BrokerBalanceSnapshotSummary, ...]:
        """Return display-only balances without internal IDs or CAS hashes."""
        if self._preview_context is None:
            return ()
        return tuple(
            BrokerBalanceSnapshotSummary(
                asset_code=snapshot.asset_code,
                kind=snapshot.kind,
                total_shares=snapshot.total_shares,
                available_quantity=snapshot.available_quantity,
                available_quantity_known=snapshot.available_quantity_known,
                average_cost=snapshot.average_cost,
                reference_mark=snapshot.reference_mark,
                reference_mark_as_of=snapshot.reference_mark_as_of,
                valuation_status=snapshot.valuation_status,
                source_updated_at=snapshot.source_updated_at,
                observed_at=snapshot.observed_at,
                blocked_reason_code=snapshot.blocked_reason_code,
            )
            for snapshot in self._preview_context.snapshots
        )

    @property
    def new_fact_rows(self) -> int:
        """Return how many preview rows have no matching persisted fact."""
        return self._preview_context.new_fact_rows if self._preview_context else 0

    @property
    def retryable_existing_rows(self) -> int:
        """Return how many existing facts can still be reconciled or matched."""
        return self._preview_context.retryable_existing_rows if self._preview_context else 0

    @property
    def terminal_duplicate_rows(self) -> int:
        """Return how many existing facts already have a terminal outcome."""
        return self._preview_context.terminal_duplicate_rows if self._preview_context else 0


@dataclass(frozen=True)
class _PreparedRows:
    """Unique stable-key rows and row issues derived from one parsed file."""

    raw_row_count: int
    rows: tuple[NormalizedTradeRow, ...]
    errors: tuple[dict[str, JsonValue], ...]
    duplicate_source_rows: int
    has_identity_conflict: bool


class ManualTradeImportUseCase:
    """Preview and persist actual broker facts before optional local reconciliation."""

    def __init__(
        self,
        *,
        sync_repo: ManualTradeSyncReadRepository | None = None,
        portfolio_repo: object | None = None,
        recommendation_repo: object | None = None,
        parser: object | None = None,
        position_service: object | None = None,
        execution_matcher: ManualTradeExecutionMatcher | None = None,
        reconciliation_repo: BrokerTradeReconciliationRepository | None = None,
    ) -> None:
        """Build the facts-first use case with legacy injection compatibility.

        ``portfolio_repo`` and ``position_service`` remain accepted for old callers,
        but actual broker executions must never use simulated order/close operations.
        A caller that injects only the old sync repository gets preview-only behavior
        unless it also supplies the complete reconciliation port.
        """
        injected_sync_repo = sync_repo is not None
        self.sync_repo = sync_repo or cast(
            ManualTradeSyncReadRepository,
            get_manual_trade_sync_repository(),
        )
        self.reconciliation_repo = reconciliation_repo
        if self.reconciliation_repo is None and not injected_sync_repo:
            self.reconciliation_repo = get_broker_trade_reconciliation_repository()
        self.parser: BrokerTradeFactParser = build_normalized_broker_trade_file_parser(
            raw_parser=parser
        )
        if execution_matcher is not None:
            self.execution_matcher = execution_matcher
        elif recommendation_repo is not None:
            self.execution_matcher = _RepositoryBackedExecutionMatcher(recommendation_repo)
        else:
            self.execution_matcher = cast(
                ManualTradeExecutionMatcher,
                build_manual_trade_execution_matcher(),
            )
        # Keep these old arguments source-compatible without triggering mutations.
        self._compat_portfolio_repo = portfolio_repo
        self._compat_position_service = position_service

    def preview(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        broker_name: str,
        filename: str,
        content: bytes,
    ) -> BrokerTradeImportResult:
        """Validate a source file and show local balances without writing anything."""
        self._require_owned_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        repo = self.reconciliation_repo
        full_preview = repo is not None and self._has_preview_port(repo)
        prepared = self._parse_file(
            content=content,
            filename=filename,
            broker_name=broker_name,
            portfolio_id=portfolio_id,
            preserve_source_rows=not full_preview,
        )
        file_hash = hashlib.sha256(content).hexdigest()
        fact_fingerprint = (
            self._fact_fingerprint(
                prepared=prepared,
                owner_user_id=user_id,
                portfolio_id=portfolio_id,
                source_file_sha256=file_hash,
            )
            if full_preview
            else None
        )
        preview_rows = [row.to_preview_dict() for row in prepared.rows]
        duplicate_count = prepared.duplicate_source_rows
        new_rows = 0
        retryable_rows = 0
        terminal_rows = 0
        snapshots: tuple[BalanceSnapshot, ...] = ()
        balance_fingerprint: str | None = None
        balance_unavailable = True
        preview_fact_fingerprint = fact_fingerprint
        errors = list(prepared.errors)
        repo = self.reconciliation_repo
        if repo is not None and self._has_preview_port(repo):
            try:
                balance = repo.capture_balance_preview(
                    owner_user_id=user_id,
                    portfolio_id=portfolio_id,
                    asset_codes=tuple(sorted({row.asset_code for row in prepared.rows})),
                )
                snapshots = balance.snapshots
                balance_fingerprint = balance.expected_balance_fingerprint
                balance_unavailable = False
                for index, row in enumerate(prepared.rows):
                    existing = repo.get_fact_by_stable_key(
                        owner_user_id=user_id,
                        portfolio_id=portfolio_id,
                        broker_trade_key=row.broker_trade_key,
                    )
                    if existing is None:
                        new_rows += 1
                        continue
                    duplicate_count += 1
                    if not _same_execution(existing, row, broker_name=broker_name):
                        preview_fact_fingerprint = None
                        terminal_rows += 1
                        errors.append(
                            {
                                "row_number": row.row_number,
                                "error_code": "broker_stable_key_conflict",
                                "message": "同一券商成交编号已对应不同的成交事实",
                            }
                        )
                        preview_rows[index] = row.to_preview_dict(duplicate=True) | {
                            "status": "stable_key_conflict"
                        }
                    elif existing.reconciliation.state in RETRYABLE_FACT_STATES:
                        retryable_rows += 1
                        preview_rows[index] = row.to_preview_dict(duplicate=True) | {
                            "status": "retryable_existing_fact"
                        }
                    else:
                        terminal_rows += 1
                        preview_rows[index] = row.to_preview_dict(duplicate=True) | {
                            "status": "terminal_duplicate"
                        }
            except Exception:
                logger.exception(
                    "Broker balance preview unavailable",
                    extra={"portfolio_id": portfolio_id},
                )
                errors.append(
                    {
                        "error_code": "broker_balance_preview_unavailable",
                        "message": "本地余额快照暂不可用；仍可保存成交事实为待核对状态",
                    }
                )
                snapshots = ()
                balance_fingerprint = None
                preview_fact_fingerprint = None
                balance_unavailable = True
                new_rows = 0
                retryable_rows = 0
                terminal_rows = 0
        else:
            legacy_exists = _optional_method(self.sync_repo, "broker_trade_key_exists")
            if legacy_exists is not None:
                for index, row in enumerate(prepared.rows):
                    try:
                        duplicate = bool(legacy_exists(row.broker_trade_key))
                    except Exception:
                        duplicate = False
                        errors.append(
                            {
                                "row_number": row.row_number,
                                "error_code": "broker_duplicate_lookup_unavailable",
                                "message": "无法读取重复成交索引",
                            }
                        )
                    if duplicate:
                        duplicate_count += 1
                        terminal_rows += 1
                        preview_rows[index] = row.to_preview_dict(duplicate=True)
                    else:
                        new_rows += 1

        context = BrokerImportPreviewContext(
            owner_user_id=user_id,
            portfolio_id=portfolio_id,
            source_file_sha256=file_hash,
            expected_fact_set_fingerprint=(
                preview_fact_fingerprint
                if not prepared.has_identity_conflict and not prepared.errors
                else None
            ),
            expected_balance_fingerprint=balance_fingerprint,
            snapshots=snapshots,
            new_fact_rows=new_rows,
            retryable_existing_rows=retryable_rows,
            terminal_duplicate_rows=terminal_rows,
        )
        return BrokerTradeImportResult(
            total_rows=prepared.raw_row_count,
            valid_rows=len(prepared.rows),
            duplicate_rows=duplicate_count,
            error_rows=len(errors),
            rows=preview_rows,
            errors=errors,
            balance_unavailable=balance_unavailable,
            _preview_context=context,
        )

    def confirm(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        broker_name: str,
        filename: str,
        content: bytes,
        baseline_decision: BrokerBaselineDecision = "pending",
        expected_fact_set_fingerprint: str | None = None,
        expected_balance_fingerprint: str | None = None,
        baseline_as_of: datetime | None = None,
    ) -> BrokerTradeImportResult:
        """Persist actual executions first, then attempt explicit baseline handling.

        Repository operations use their own atomic scopes but intentionally do not
        claim to commit around an outer transaction owned by an HTTP/MCP caller.
        """
        self._require_owned_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        prepared = self._parse_file(
            content=content,
            filename=filename,
            broker_name=broker_name,
            portfolio_id=portfolio_id,
        )
        file_hash = hashlib.sha256(content).hexdigest()
        errors = list(prepared.errors)
        batch, batch_id, batch_error = self._try_create_batch(
            user_id=user_id,
            portfolio_id=portfolio_id,
            broker_name=broker_name,
            filename=filename,
            file_hash=file_hash,
            total_rows=prepared.raw_row_count,
            rows=prepared.rows,
        )
        repo = self.reconciliation_repo
        if repo is None or not self._has_fact_write_port(repo):
            errors.append(
                {
                    "error_code": "broker_fact_repository_unavailable",
                    "message": "成交事实存储暂不可用；未报告任何成交已保存",
                }
            )
            self._try_update_batch(
                batch=batch,
                imported_rows=0,
                skipped_rows=0,
                errors=errors,
            )
            return BrokerTradeImportResult(
                total_rows=prepared.raw_row_count,
                valid_rows=len(prepared.rows),
                duplicate_rows=0,
                error_rows=len(errors),
                rows=[row.to_preview_dict() | {"status": "not_saved"} for row in prepared.rows],
                errors=errors,
                batch_id=batch_id,
                batch_summary_error_code=batch_error,
            )

        writes: list[tuple[NormalizedTradeRow, BrokerFactRecord, BrokerFactWriteDisposition]] = []
        row_results: list[dict[str, JsonValue]] = []
        conflict_keys: set[str] = set()
        facts_saved = 0
        facts_reused = 0
        fact_write_incomplete = False
        for row in prepared.rows:
            candidate = BrokerFactCandidate(
                owner_user_id=user_id,
                portfolio_id=portfolio_id,
                first_import_batch_id=batch_id,
                source_file_sha256=file_hash,
                source_filename=filename,
                broker_name=broker_name,
                source_row=row,
            )
            try:
                write_result = repo.persist_fact_first(candidate)
            except Exception:
                fact_write_incomplete = True
                logger.exception(
                    "Broker execution fact persistence failed",
                    extra={"row_number": row.row_number, "portfolio_id": portfolio_id},
                )
                errors.append(
                    {
                        "row_number": row.row_number,
                        "error_code": "broker_fact_persistence_failed",
                        "message": "成交事实保存失败；本条未计入已保存数量",
                    }
                )
                row_results.append(row.to_preview_dict() | {"status": "fact_persistence_failed"})
                continue
            if write_result.disposition == "stable_key_conflict":
                fact_write_incomplete = True
                conflict_keys.add(row.broker_trade_key)
                errors.append(
                    {
                        "row_number": row.row_number,
                        "error_code": "broker_stable_key_conflict",
                        "message": write_result.conflict_reason_code
                        or "同一券商成交编号已对应不同的成交事实",
                    }
                )
                row_results.append(
                    row.to_preview_dict(duplicate=True) | {"status": "stable_key_conflict"}
                )
                continue
            record = write_result.record
            if record is None:
                fact_write_incomplete = True
                errors.append(
                    {
                        "row_number": row.row_number,
                        "error_code": "broker_fact_write_result_incomplete",
                        "message": "事实存储未返回可核验的成交记录",
                    }
                )
                row_results.append(row.to_preview_dict() | {"status": "fact_write_unverified"})
                continue
            if write_result.disposition == "created":
                facts_saved += 1
                status = "fact_saved"
            else:
                facts_reused += 1
                status = "existing_fact_reused"
            writes.append((row, record, write_result.disposition))
            row_results.append(
                row.to_preview_dict(duplicate=write_result.disposition != "created")
                | {"status": status, "transaction_id": record.transaction_id}
            )

        reconciliation: BrokerFactSetReconciliationResult | None = None
        conflict_code: BrokerFactPreviewConflictCode | None = None
        reconciliation_error_code: str | None = None
        if baseline_as_of is not None and timezone.is_naive(baseline_as_of):
            reconciliation_error_code = "BROKER_BASELINE_AS_OF_MUST_BE_AWARE"
        elif baseline_decision not in {"pending", "included", "excluded"}:
            reconciliation_error_code = "BROKER_BASELINE_DECISION_INVALID"
        elif conflict_keys or prepared.has_identity_conflict:
            reconciliation_error_code = "BROKER_FACT_SET_CONTAINS_KEY_CONFLICT"
        elif not writes:
            reconciliation_error_code = "BROKER_FACT_SET_EMPTY"
        elif baseline_decision in {"included", "excluded"} and prepared.errors:
            reconciliation_error_code = "BROKER_FACT_SET_HAS_INVALID_ROWS"
        elif baseline_decision in {"included", "excluded"} and fact_write_incomplete:
            reconciliation_error_code = "BROKER_FACT_SET_PERSISTENCE_INCOMPLETE"
        elif baseline_decision in {"included", "excluded"} and (
            not expected_fact_set_fingerprint or not expected_balance_fingerprint
        ):
            reconciliation_error_code = "BROKER_BASELINE_PREVIEW_REQUIRED"
        elif repo is None or not self._has_reconcile_port(repo):
            reconciliation_error_code = "BROKER_RECONCILIATION_REPOSITORY_UNAVAILABLE"
        else:
            request = BaselineRequest(
                decision=baseline_decision,
                baseline_as_of=baseline_as_of,
                expected_fact_set_fingerprint=expected_fact_set_fingerprint,
                expected_balance_fingerprint=expected_balance_fingerprint,
            )
            try:
                reconciliation = repo.reconcile_fact_set(
                    owner_user_id=user_id,
                    portfolio_id=portfolio_id,
                    decision_batch_id=batch_id,
                    transaction_ids=tuple(record.transaction_id for _, record, _ in writes),
                    source_file_sha256=file_hash,
                    request=request,
                )
                conflict_code = reconciliation.conflict_code
            except Exception:
                logger.exception(
                    "Broker fact-set reconciliation failed after fact persistence",
                    extra={"portfolio_id": portfolio_id, "decision": baseline_decision},
                )
                reconciliation_error_code = "BROKER_RECONCILIATION_ATTEMPT_FAILED"

        matching_failed = self._attempt_matching(repo, writes, row_results)
        current_fact_states, unavailable_fact_reasons = self._resolve_current_fact_states(
            repo=repo,
            writes=writes,
            reconciliation=reconciliation,
            owner_user_id=user_id,
            portfolio_id=portfolio_id,
        )
        self._annotate_fact_outcomes(
            row_results=row_results,
            current_fact_states=current_fact_states,
            unavailable_fact_reasons=unavailable_fact_reasons,
        )
        row_numbers = {
            transaction_id: row.get("row_number")
            for row in row_results
            if isinstance((transaction_id := row.get("transaction_id")), int)
        }
        for transaction_id, error_code in unavailable_fact_reasons.items():
            error: dict[str, JsonValue] = {
                "error_code": error_code,
                "message": _reconciliation_error_message(error_code),
            }
            row_number = row_numbers.get(transaction_id)
            if isinstance(row_number, str) or (
                isinstance(row_number, int) and not isinstance(row_number, bool)
            ):
                error["row_number"] = row_number
            errors.append(error)
        (
            projected_count,
            already_in_baseline_count,
            blocked_count,
            pending_count,
        ) = self._fact_state_counts(
            writes=writes,
            current_fact_states=current_fact_states,
        )
        if reconciliation_error_code is not None:
            errors.append(
                {
                    "error_code": reconciliation_error_code,
                    "message": _reconciliation_error_message(reconciliation_error_code),
                }
            )
        if conflict_code is not None:
            errors.append(
                {
                    "error_code": conflict_code,
                    "message": "预览后的成交集合或本地余额已变化；成交事实已保存，可重新预览后核对",
                }
            )
        summary_error = self._try_update_batch(
            batch=batch,
            imported_rows=facts_saved,
            skipped_rows=facts_reused,
            errors=errors,
        )
        if summary_error is not None:
            batch_error = summary_error
        return BrokerTradeImportResult(
            total_rows=prepared.raw_row_count,
            valid_rows=len(prepared.rows),
            duplicate_rows=facts_reused,
            error_rows=len(errors),
            rows=row_results,
            errors=errors,
            imported_rows=facts_saved,
            skipped_rows=facts_reused,
            batch_id=batch_id,
            facts_saved_count=facts_saved,
            duplicate_facts_reused_count=facts_reused,
            pending_fact_count=pending_count,
            projected_fact_count=projected_count,
            already_in_baseline_count=already_in_baseline_count,
            projection_blocked_count=blocked_count,
            matching_failed_count=matching_failed,
            reconciliation_conflict_code=conflict_code,
            reconciliation_error_code=reconciliation_error_code,
            batch_summary_error_code=batch_error,
        )

    def _parse_file(
        self,
        *,
        content: bytes,
        filename: str,
        broker_name: str,
        portfolio_id: int,
        preserve_source_rows: bool = False,
    ) -> _PreparedRows:
        """Parse bounded facts, optionally retaining legacy preview-only rows."""
        result = self.parser.parse_normalized_facts(
            content=content,
            filename=filename,
            broker_name=broker_name,
            portfolio_id=portfolio_id,
        )
        raw_count = len(result.rows) + len(result.errors)
        if raw_count > MAX_BROKER_TRADE_IMPORT_ROWS:
            raise ValueError(
                f"Broker trade import cannot exceed {MAX_BROKER_TRADE_IMPORT_ROWS} rows"
            )
        errors: list[dict[str, JsonValue]] = [
            {
                "row_number": issue.row_number,
                "error_code": issue.error_code,
                "error": issue.message,
                "message": issue.message,
            }
            for issue in result.errors
        ]
        if preserve_source_rows:
            # Older injected preview ports have no exact fact-set CAS. Keep all typed
            # rows visible and withhold the fingerprint instead of deduplicating them.
            return _PreparedRows(
                raw_row_count=raw_count,
                rows=result.rows,
                errors=tuple(errors),
                duplicate_source_rows=0,
                has_identity_conflict=False,
            )

        unique_rows: dict[str, NormalizedTradeRow] = {}
        duplicate_source_rows = 0
        identity_conflict = False
        for row in result.rows:
            prior = unique_rows.get(row.broker_trade_key)
            if prior is None:
                unique_rows[row.broker_trade_key] = row
            elif _same_source_execution(prior, row):
                duplicate_source_rows += 1
            else:
                identity_conflict = True
                errors.append(
                    {
                        "row_number": row.row_number,
                        "error_code": "broker_duplicate_key_in_file_conflict",
                        "message": "同一文件中的稳定成交键对应不同的成交事实",
                    }
                )
        return _PreparedRows(
            raw_row_count=raw_count,
            rows=tuple(unique_rows.values()),
            errors=tuple(errors),
            duplicate_source_rows=duplicate_source_rows,
            has_identity_conflict=identity_conflict,
        )

    def _require_owned_portfolio(self, *, user_id: int, portfolio_id: int) -> object:
        """Verify ownership through the established read repository."""
        portfolio = self.sync_repo.get_owned_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        if portfolio is None:
            raise LookupError(f"Portfolio {portfolio_id} does not exist or is not owned by user")
        return portfolio

    @staticmethod
    def _has_preview_port(repo: object) -> bool:
        """Return whether the injected repository supports full preview reads."""
        return all(
            callable(getattr(repo, name, None))
            for name in ("capture_balance_preview", "get_fact_by_stable_key")
        )

    @staticmethod
    def _has_fact_write_port(repo: object) -> bool:
        """Return whether the repository can durably save facts before projection."""
        return all(
            callable(getattr(repo, name, None))
            for name in ("persist_fact_first", "get_fact_by_stable_key")
        )

    @staticmethod
    def _has_reconcile_port(repo: object) -> bool:
        """Return whether a fact repository can persist a baseline decision."""
        return callable(getattr(repo, "reconcile_fact_set", None))

    @staticmethod
    def _fact_fingerprint(
        *,
        prepared: _PreparedRows,
        owner_user_id: int,
        portfolio_id: int,
        source_file_sha256: str,
    ) -> str | None:
        """Fingerprint the exact valid file fact set or withhold it on row errors."""
        if prepared.errors or prepared.has_identity_conflict:
            return None
        identities = tuple(_to_fact_identity(row) for row in prepared.rows)
        return broker_fact_set_fingerprint(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            source_file_sha256=source_file_sha256,
            facts=identities,
        )

    def _try_create_batch(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        broker_name: str,
        filename: str,
        file_hash: str,
        total_rows: int,
        rows: tuple[NormalizedTradeRow, ...],
    ) -> tuple[object | None, int | None, str | None]:
        """Write an optional display summary without making it the fact store."""
        create_method = _optional_method(self.sync_repo, "create_import_batch")
        if create_method is None:
            return None, None, "BROKER_BATCH_SUMMARY_UNAVAILABLE"
        try:
            batch = create_method(
                user_id=user_id,
                portfolio_id=portfolio_id,
                broker_name=broker_name,
                source_filename=filename,
                file_hash=file_hash,
                total_rows=total_rows,
                preview_rows=[row.to_preview_dict() for row in rows[:50]],
            )
        except Exception:
            logger.exception("Broker import batch summary creation failed")
            return None, None, "BROKER_BATCH_SUMMARY_CREATE_FAILED"
        batch_id = getattr(batch, "id", None)
        if isinstance(batch_id, bool) or not isinstance(batch_id, int) or batch_id <= 0:
            return batch, None, "BROKER_BATCH_SUMMARY_ID_UNAVAILABLE"
        return batch, batch_id, None

    def _try_update_batch(
        self,
        *,
        batch: object | None,
        imported_rows: int,
        skipped_rows: int,
        errors: list[dict[str, JsonValue]],
    ) -> str | None:
        """Update optional batch counts after fact operations have finished."""
        if batch is None:
            return None
        update_method = _optional_method(self.sync_repo, "update_import_batch_result")
        if update_method is None:
            return "BROKER_BATCH_SUMMARY_UPDATE_UNAVAILABLE"
        try:
            update_method(
                batch,
                imported_rows=imported_rows,
                skipped_rows=skipped_rows,
                error_rows=len(errors),
                errors=errors,
            )
        except Exception:
            logger.exception("Broker import batch summary update failed")
            return "BROKER_BATCH_SUMMARY_UPDATE_FAILED"
        return None

    def _attempt_matching(
        self,
        repo: BrokerTradeReconciliationRepository | None,
        writes: list[tuple[NormalizedTradeRow, BrokerFactRecord, BrokerFactWriteDisposition]],
        row_results: list[dict[str, JsonValue]],
    ) -> int:
        """Run matching through the repository's owner-locked savepoint scope."""
        return attempt_broker_fact_matching(
            repo=repo,
            writes=writes,
            row_results=row_results,
            matcher=self.execution_matcher,
        )

    @staticmethod
    def _annotate_fact_outcomes(
        *,
        row_results: list[dict[str, JsonValue]],
        current_fact_states: Mapping[int, BrokerFactProjectionResult | BrokerFactRecord],
        unavailable_fact_reasons: Mapping[int, str],
    ) -> None:
        """Expose one current persisted fact state or a stable unavailable receipt."""
        for row in row_results:
            transaction_id = row.get("transaction_id")
            if not isinstance(transaction_id, int):
                continue
            current = current_fact_states.get(transaction_id)
            if isinstance(current, BrokerFactProjectionResult):
                row["reconciliation_state"] = current.state.value
                row["projection_outcome"] = current.outcome
                if current.reason_code is not None:
                    row["reconciliation_reason_code"] = current.reason_code
                else:
                    row.pop("reconciliation_reason_code", None)
            elif isinstance(current, BrokerFactRecord):
                row["reconciliation_state"] = current.reconciliation.state.value
                if current.reconciliation.last_reason_code is not None:
                    row["reconciliation_reason_code"] = current.reconciliation.last_reason_code
                else:
                    row.pop("reconciliation_reason_code", None)
                last_projection = current.reconciliation.last_projection
                if last_projection is not None:
                    row["projection_outcome"] = last_projection.outcome
                else:
                    row.pop("projection_outcome", None)
            else:
                row["status"] = "fact_unavailable"
                row["status_reason"] = unavailable_fact_reasons.get(
                    transaction_id,
                    "BROKER_FACT_CURRENT_STATE_UNAVAILABLE",
                )
                row.pop("reconciliation_state", None)
                row.pop("reconciliation_reason_code", None)
                row.pop("projection_outcome", None)

    @staticmethod
    def _resolve_current_fact_states(
        *,
        repo: BrokerTradeReconciliationRepository | None,
        writes: list[tuple[NormalizedTradeRow, BrokerFactRecord, BrokerFactWriteDisposition]],
        reconciliation: BrokerFactSetReconciliationResult | None,
        owner_user_id: int,
        portfolio_id: int,
    ) -> tuple[
        dict[int, BrokerFactProjectionResult | BrokerFactRecord],
        dict[int, str],
    ]:
        """Resolve current states once for both row receipts and batch counters."""
        records_by_id = {record.transaction_id: record for _, record, _ in writes}
        if reconciliation is None:
            current: dict[int, BrokerFactProjectionResult | BrokerFactRecord] = {}
        else:
            current = {
                fact.transaction_id: fact
                for fact in reconciliation.facts
                if fact.transaction_id in records_by_id
            }
        unavailable: dict[int, str] = {}
        reader = _optional_method(repo, "get_fact_by_stable_key") if repo is not None else None
        for _, initial, _ in writes:
            if initial.transaction_id in current:
                continue
            if (
                reader is None
                or not initial.broker_trade_key
                or initial.owner_user_id != owner_user_id
                or initial.portfolio_id != portfolio_id
            ):
                unavailable[initial.transaction_id] = "BROKER_FACT_CURRENT_STATE_UNAVAILABLE"
                continue
            try:
                value = reader(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio_id,
                    broker_trade_key=initial.broker_trade_key,
                )
            except Exception:
                logger.exception(
                    "Broker fact current-state read failed",
                    extra={"transaction_id": initial.transaction_id},
                )
                unavailable[initial.transaction_id] = "BROKER_FACT_CURRENT_STATE_UNAVAILABLE"
                continue
            if value is None:
                unavailable[initial.transaction_id] = "BROKER_FACT_CURRENT_STATE_UNAVAILABLE"
                continue
            if (
                not isinstance(value, BrokerFactRecord)
                or value.transaction_id != initial.transaction_id
                or value.owner_user_id != owner_user_id
                or value.portfolio_id != portfolio_id
                or value.broker_trade_key != initial.broker_trade_key
            ):
                logger.error(
                    "Broker fact current-state read returned a mismatched record",
                    extra={"transaction_id": initial.transaction_id},
                )
                unavailable[initial.transaction_id] = "BROKER_FACT_CURRENT_STATE_UNAVAILABLE"
                continue
            current[initial.transaction_id] = value
        return current, unavailable

    @staticmethod
    def _fact_state_counts(
        *,
        writes: list[tuple[NormalizedTradeRow, BrokerFactRecord, BrokerFactWriteDisposition]],
        current_fact_states: Mapping[int, BrokerFactProjectionResult | BrokerFactRecord],
    ) -> tuple[int, int, int, int]:
        """Count only states resolved from reconciliation or a fresh scoped read."""
        projected = 0
        already_in_baseline = 0
        blocked = 0
        pending = 0
        for _, initial, _ in writes:
            current = current_fact_states.get(initial.transaction_id)
            if current is None:
                continue
            state = (
                current.state
                if isinstance(current, BrokerFactProjectionResult)
                else current.reconciliation.state
            )
            if state is BrokerReconciliationState.PROJECTED:
                projected += 1
            elif state is BrokerReconciliationState.ALREADY_IN_BASELINE:
                already_in_baseline += 1
            elif state is BrokerReconciliationState.PROJECTION_BLOCKED:
                blocked += 1
            elif state in {
                BrokerReconciliationState.LEGACY_UNVERIFIED,
                BrokerReconciliationState.AWAITING_BASELINE,
                BrokerReconciliationState.PROJECTION_PENDING,
            }:
                pending += 1
        return projected, already_in_baseline, blocked, pending


def _reconciliation_error_message(error_code: str) -> str:
    """Translate stable application errors into recovery-oriented Chinese copy."""
    messages = {
        "BROKER_BASELINE_AS_OF_MUST_BE_AWARE": "基准日期必须包含时区",
        "BROKER_BASELINE_DECISION_INVALID": "基准选择无效；成交事实仍已单独处理",
        "BROKER_FACT_SET_EMPTY": "没有可核对的有效成交事实",
        "BROKER_FACT_SET_CONTAINS_KEY_CONFLICT": "文件含稳定成交键冲突；请先处理冲突行",
        "BROKER_BASELINE_PREVIEW_REQUIRED": "请重新预览本批成交和本地余额后再选择纳入或排除",
        "BROKER_FACT_CURRENT_STATE_UNAVAILABLE": "成交事实当前状态无法确认，未重建；请重新导入并先核对文件和余额",
        "BROKER_RECONCILIATION_REPOSITORY_UNAVAILABLE": "核对服务暂不可用；成交事实已保存并可重试",
        "BROKER_RECONCILIATION_ATTEMPT_FAILED": "核对暂未完成；成交事实已保存并可重试",
    }
    return messages.get(error_code, "成交事实已保存，但核对尚未完成")
