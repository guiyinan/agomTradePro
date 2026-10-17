"""Transactional repository for source-available, effective A-share rule versions."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast

from django.db import DEFAULT_DB_ALIAS, DatabaseError, IntegrityError, connections, transaction
from django.db.models import F
from django.utils import timezone

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleConflict,
    ExecutionRuleCorruption,
    ExecutionRuleImportResult,
    ExecutionRuleInputError,
    ExecutionRulePersistenceUnavailable,
    ExecutionRuleUnavailable,
    ExecutionRuleVersionMismatch,
)
from apps.risk_center.application.ashare_execution_rule_lifecycle import (
    ExecutionRuleRetirementConflict,
    ExecutionRuleRetirementCorruption,
    ExecutionRuleRetirementNotFound,
    ExecutionRuleRetirementUnavailable,
)
from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3ReadRecord,
)
from apps.risk_center.domain.ashare_execution_rule_retirement import (
    AShareExecutionRuleRetirementEvidence,
    AShareExecutionRuleRetirementIntent,
    AShareExecutionRuleRetirementTarget,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import AShareExecutionRule
from apps.risk_center.infrastructure.ashare_execution_rule_codec import (
    AShareExecutionRuleCodecError,
    AShareExecutionRuleV2CodecError,
    AShareExecutionRuleV3CodecError,
    decode_a_share_execution_rule,
    decode_a_share_execution_settlement_bundle,
    decode_a_share_execution_submission_rule,
    encode_a_share_execution_rule,
    encode_a_share_execution_settlement_bundle,
    encode_a_share_execution_submission_rule,
)
from apps.risk_center.infrastructure.ashare_execution_rule_models import (
    AShareExecutionRuleModel,
)

_PG_ADVISORY_LOCK_TIMEOUT = timedelta(seconds=2)
_RuleEntry = AShareExecutionRule | ExecutionSubmissionRuleV2 | ExecutionSettlementBundleV3


@dataclass(frozen=True, slots=True)
class _RuleHeader:
    """Unified stored identity, scope, and effective-time projection for all schemas."""

    security_id: str
    rule_id: str
    rule_version: str
    market: str
    board: str
    source_available_at: datetime
    effective_from: datetime
    valid_until: datetime
    content_hash: str


class AShareExecutionRuleClock(Protocol):
    """Clock port for the local database-recorded knowledge timestamp."""

    def now(self) -> datetime:
        """Return the current aware timestamp in the application timezone."""


class DjangoAShareExecutionRuleClock:
    """Read the current aware timestamp through Django's configured timezone."""

    def now(self) -> datetime:
        """Return the current aware timestamp."""

        return timezone.now()


class DjangoAShareExecutionRuleRepository:
    """Persist and resolve the sole Risk-owned A-share execution-rule table."""

    def __init__(
        self,
        *,
        using: str = DEFAULT_DB_ALIAS,
        clock: AShareExecutionRuleClock | None = None,
    ) -> None:
        """Select the database and local knowledge clock for repository operations."""

        self._using = using
        self._clock = clock or DjangoAShareExecutionRuleClock()

    def import_rules(self, *, rules: tuple[AShareExecutionRule, ...]) -> ExecutionRuleImportResult:
        """Atomically insert a rule batch, preserving identity and window invariants."""

        candidates = self._validate_batch(rules)
        return self._import_candidates(candidates)

    def import_submission_rules(
        self, *, rules: tuple[ExecutionSubmissionRuleV2, ...]
    ) -> ExecutionRuleImportResult:
        """Atomically insert v2 rules through the same identity and window fences."""

        candidates = self._validate_submission_batch(rules)
        return self._import_candidates(candidates)

    def import_settlement_bundles(
        self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
    ) -> ExecutionRuleImportResult:
        """Atomically insert v3 bundles into the existing rule table and fences."""

        candidates = self._validate_settlement_batch(bundles)
        return self._import_candidates(candidates)

    @property
    def database_alias(self) -> str:
        """Return the alias used by rule persistence."""

        return self._using

    @contextmanager
    def retirement_transaction(self, *, security_id: str) -> Iterator[None]:
        """Open the outermost same-security transaction and acquire its write fence."""

        self._validate_security_id(security_id)
        connection = connections[self._using]
        if connection.vendor not in {"sqlite", "postgresql"}:
            raise ExecutionRuleRetirementUnavailable(
                "A-share rule retirement supports only SQLite and PostgreSQL"
            )
        if connection.in_atomic_block:
            raise ExecutionRuleRetirementUnavailable(
                "A-share rule retirement requires ownership of the outer transaction"
            )
        try:
            with transaction.atomic(using=self._using):
                previous_lock_timeout: str | None = None
                if connection.vendor == "postgresql":
                    previous_lock_timeout = self._acquire_postgresql_fences((security_id,))
                else:
                    self._acquire_sqlite_fence((security_id,))
                yield
                if previous_lock_timeout is not None:
                    self._restore_postgresql_lock_timeout(previous_lock_timeout)
        except (
            ExecutionRuleRetirementConflict,
            ExecutionRuleRetirementCorruption,
            ExecutionRuleRetirementNotFound,
            ExecutionRuleRetirementUnavailable,
        ):
            raise
        except IntegrityError as error:
            raise ExecutionRuleRetirementConflict(
                "retirement request identity already has a different winner"
            ) from error
        except DatabaseError as error:
            if self._is_lock_or_storage_unavailable(error):
                raise ExecutionRuleRetirementUnavailable(
                    "retirement transaction could not acquire its storage fence"
                ) from error
            raise ExecutionRuleRetirementUnavailable("retirement transaction failed") from error

    def get_retirement_target(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
    ) -> AShareExecutionRuleRetirementTarget:
        """Lock and decode the exact rule identity and its one-time lifecycle fields."""

        if type(intent) is not AShareExecutionRuleRetirementIntent:
            raise ExecutionRuleRetirementConflict("retirement lookup requires a typed intent")
        if not connections[self._using].in_atomic_block:
            raise ExecutionRuleRetirementUnavailable(
                "retirement target reads require the same-security transaction"
            )
        try:
            request_winners = tuple(
                AShareExecutionRuleModel._default_manager.using(self._using)
                .select_for_update()
                .filter(retirement_request_id=intent.request_id)
                .order_by("id")[:2]
            )
            if len(request_winners) > 1:
                raise ExecutionRuleRetirementCorruption(
                    "retirement request identity has multiple stored winners"
                )
            if request_winners:
                winner = request_winners[0]
                if (
                    winner.security_id != intent.security_id
                    or winner.rule_id != intent.rule_id
                    or winner.rule_version != intent.rule_version
                    or winner.content_hash != intent.expected_content_hash
                ):
                    raise ExecutionRuleRetirementConflict(
                        "request_id is already used by a different retirement"
                    )
            rows = tuple(
                AShareExecutionRuleModel._default_manager.using(self._using)
                .select_for_update()
                .filter(
                    security_id=intent.security_id,
                    rule_id=intent.rule_id,
                    rule_version=intent.rule_version,
                )
                .order_by("id")[:2]
            )
        except DatabaseError as error:
            raise ExecutionRuleRetirementUnavailable(
                "retirement target could not be read"
            ) from error
        if not rows:
            raise ExecutionRuleRetirementNotFound()
        if len(rows) > 1:
            raise ExecutionRuleRetirementCorruption("rule identity has multiple stored rows")
        row = rows[0]
        try:
            stored = self._decode_any_row(row)
        except ExecutionRuleCorruption as error:
            raise ExecutionRuleRetirementCorruption(
                "retirement target has corrupt canonical rule or lifecycle fields"
            ) from error
        header = _rule_header(stored)
        if row.content_hash != intent.expected_content_hash:
            raise ExecutionRuleRetirementConflict(
                "expected content hash differs from the immutable stored rule"
            )
        return AShareExecutionRuleRetirementTarget(
            security_id=header.security_id,
            rule_id=header.rule_id,
            rule_version=header.rule_version,
            content_hash=stored.content_hash,
            rule_recorded_at=row.recorded_at,
            effective_from=header.effective_from,
            valid_until=header.valid_until,
            retirement=_retirement_evidence(row),
        )

    def persist_retirement(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        evidence: AShareExecutionRuleRetirementEvidence,
    ) -> None:
        """Atomically write all retirement columns while preserving canonical rule bytes."""

        if (
            type(intent) is not AShareExecutionRuleRetirementIntent
            or type(evidence) is not AShareExecutionRuleRetirementEvidence
            or evidence.is_empty
        ):
            raise ExecutionRuleRetirementConflict("retirement write requires complete typed values")
        try:
            AShareExecutionRuleRetirementIntent.__post_init__(intent)
            AShareExecutionRuleRetirementEvidence.__post_init__(evidence)
        except (TypeError, ValueError) as error:
            raise ExecutionRuleRetirementConflict("retirement write values are invalid") from error
        if (
            evidence.retirement_request_id != intent.request_id
            or evidence.retirement_effective_at != intent.effective_at
        ):
            raise ExecutionRuleRetirementConflict(
                "retirement evidence differs from the exact request"
            )
        if not connections[self._using].in_atomic_block:
            raise ExecutionRuleRetirementUnavailable(
                "retirement writes require the same-security transaction"
            )
        try:
            updated = (
                AShareExecutionRuleModel._default_manager.using(self._using)
                .filter(
                    security_id=intent.security_id,
                    rule_id=intent.rule_id,
                    rule_version=intent.rule_version,
                    content_hash=intent.expected_content_hash,
                    retirement_request_id__isnull=True,
                )
                .update(
                    retirement_effective_at=evidence.retirement_effective_at,
                    retirement_recorded_at=evidence.retirement_recorded_at,
                    retirement_request_id=evidence.retirement_request_id,
                    retirement_actor_type=evidence.retirement_actor_type,
                    retirement_actor_id=evidence.retirement_actor_id,
                    retirement_request_hash=evidence.retirement_request_hash,
                )
            )
        except IntegrityError as error:
            raise ExecutionRuleRetirementConflict(
                "retirement request identity already has a different winner"
            ) from error
        except DatabaseError as error:
            raise ExecutionRuleRetirementUnavailable(
                "retirement metadata could not be stored"
            ) from error
        if updated != 1:
            raise ExecutionRuleRetirementConflict(
                "rule retirement was concurrently changed or already recorded"
            )

    def _import_candidates(self, candidates: tuple[_RuleEntry, ...]) -> ExecutionRuleImportResult:
        connection = connections[self._using]
        if connection.vendor not in {"sqlite", "postgresql"}:
            raise ExecutionRulePersistenceUnavailable(
                "A-share rule imports support only SQLite and PostgreSQL"
            )
        if connection.vendor == "sqlite" and connection.in_atomic_block:
            raise ExecutionRulePersistenceUnavailable(
                "SQLite rule imports require ownership of the outer transaction"
            )
        security_ids = tuple(sorted({_rule_header(rule).security_id for rule in candidates}))
        try:
            with transaction.atomic(using=self._using):
                previous_lock_timeout: str | None = None
                if connection.vendor == "postgresql":
                    previous_lock_timeout = self._acquire_postgresql_fences(security_ids)
                else:
                    self._acquire_sqlite_fence(security_ids)
                result = self._apply_batch(candidates, security_ids)
                if previous_lock_timeout is not None:
                    self._restore_postgresql_lock_timeout(previous_lock_timeout)
                return result
        except ExecutionRuleUnavailable:
            raise
        except IntegrityError as error:
            raise ExecutionRuleConflict(
                "A-share execution rule identity or content already has a different winner"
            ) from error
        except DatabaseError as error:
            if self._is_lock_or_storage_unavailable(error):
                raise ExecutionRulePersistenceUnavailable(
                    "A-share execution rule transaction could not acquire its storage fence"
                ) from error
            raise ExecutionRulePersistenceUnavailable(
                "A-share execution rule transaction failed"
            ) from error

    def get_effective_rule(self, *, security_id: str, as_of: datetime) -> AShareExecutionRule:
        """Return exactly one rule available and effective at an aware cutoff."""

        self._validate_lookup(security_id=security_id, as_of=as_of)
        try:
            rows = tuple(
                AShareExecutionRuleModel._default_manager.using(self._using)
                .filter(
                    security_id=security_id,
                    recorded_at__lte=as_of,
                    source_available_at__lte=as_of,
                    effective_from__lte=as_of,
                    valid_until__gt=as_of,
                )
                .order_by("effective_from", "id")
            )
        except DatabaseError as error:
            raise ExecutionRulePersistenceUnavailable(
                "A-share execution rule lookup could not read storage"
            ) from error
        visible = tuple(row for row in rows if not _retired_at(row, as_of=as_of))
        if not visible:
            raise ExecutionRuleUnavailable(
                "No source-available effective A-share execution rule is configured"
            )
        if len(visible) != 1:
            raise ExecutionRuleCorruption(
                "More than one A-share execution rule is effective for the security"
            )
        return self._decode_row(visible[0])

    def get_effective_submission_rule(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2:
        """Return exactly one recorded, available, effective v2 rule at a cutoff."""

        self._validate_lookup(security_id=security_id, as_of=as_of)
        try:
            rows = tuple(
                AShareExecutionRuleModel._default_manager.using(self._using)
                .filter(
                    security_id=security_id,
                    recorded_at__lte=as_of,
                    source_available_at__lte=as_of,
                    effective_from__lte=as_of,
                    valid_until__gt=as_of,
                )
                .order_by("effective_from", "id")
            )
        except DatabaseError as error:
            raise ExecutionRulePersistenceUnavailable(
                "A-share execution v2 rule lookup could not read storage"
            ) from error
        visible = tuple(row for row in rows if not _retired_at(row, as_of=as_of))
        if not visible:
            raise ExecutionRuleUnavailable(
                "No source-available effective A-share execution v2 rule is configured"
            )
        if len(visible) != 1:
            raise ExecutionRuleCorruption(
                "More than one A-share execution rule is effective for the security"
            )
        return self._decode_submission_row(visible[0])

    def get_effective_settlement_bundle(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSettlementV3ReadRecord | None:
        """Read an effective v3 bundle with the row's original recorded-at clock."""

        self._validate_lookup(security_id=security_id, as_of=as_of)
        try:
            rows = tuple(
                AShareExecutionRuleModel._default_manager.using(self._using)
                .filter(
                    security_id=security_id,
                    recorded_at__lte=as_of,
                    source_available_at__lte=as_of,
                    effective_from__lte=as_of,
                    valid_until__gt=as_of,
                )
                .order_by("effective_from", "id")
            )
        except DatabaseError as error:
            raise ExecutionRulePersistenceUnavailable(
                "A-share execution v3 rule lookup could not read storage"
            ) from error
        visible = tuple(row for row in rows if not _retired_at(row, as_of=as_of))
        if not visible:
            return None
        if len(visible) != 1:
            raise ExecutionRuleCorruption(
                "More than one A-share execution rule is effective for the security"
            )
        bundle = self._decode_settlement_row(visible[0])
        return ExecutionSettlementV3ReadRecord(bundle=bundle, recorded_at=visible[0].recorded_at)

    @staticmethod
    def _validate_batch(
        rules: tuple[AShareExecutionRule, ...],
    ) -> tuple[AShareExecutionRule, ...]:
        if type(rules) is not tuple or not rules:
            raise ExecutionRuleInputError("rule import requires a nonempty immutable tuple")
        identities: set[tuple[str, str, str]] = set()
        for rule in rules:
            if type(rule) is not AShareExecutionRule:
                raise ExecutionRuleInputError("rule import requires exact typed domain rules")
            try:
                AShareExecutionRule.__post_init__(rule)
            except (TypeError, ValueError) as error:
                raise ExecutionRuleInputError(
                    "rule import contains an invalid domain rule"
                ) from error
            identity = (rule.security_id, rule.rule_id, rule.rule_version)
            if identity in identities:
                raise ExecutionRuleInputError("rule import contains a duplicate rule identity")
            identities.add(identity)
        return rules

    @staticmethod
    def _validate_submission_batch(
        rules: tuple[ExecutionSubmissionRuleV2, ...],
    ) -> tuple[ExecutionSubmissionRuleV2, ...]:
        if type(rules) is not tuple or not rules:
            raise ExecutionRuleInputError("v2 rule import requires a nonempty immutable tuple")
        identities: set[tuple[str, str, str]] = set()
        for rule in rules:
            if type(rule) is not ExecutionSubmissionRuleV2:
                raise ExecutionRuleInputError("v2 rule import requires exact typed domain rules")
            try:
                ExecutionSubmissionRuleV2.__post_init__(rule)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise ExecutionRuleInputError("v2 rule import contains invalid content") from error
            identity = _rule_identity(rule)
            if identity in identities:
                raise ExecutionRuleInputError("v2 rule import contains a duplicate identity")
            identities.add(identity)
        return rules

    @staticmethod
    def _validate_settlement_batch(
        bundles: tuple[ExecutionSettlementBundleV3, ...],
    ) -> tuple[ExecutionSettlementBundleV3, ...]:
        if type(bundles) is not tuple or not bundles:
            raise ExecutionRuleInputError(
                "v3 settlement import requires a nonempty immutable tuple"
            )
        identities: set[tuple[str, str, str]] = set()
        for bundle in bundles:
            if type(bundle) is not ExecutionSettlementBundleV3:
                raise ExecutionRuleInputError(
                    "v3 settlement import requires exact typed domain bundles"
                )
            try:
                ExecutionSettlementBundleV3.__post_init__(bundle)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise ExecutionRuleInputError(
                    "v3 settlement import contains invalid content"
                ) from error
            identity = _rule_identity(bundle)
            if identity in identities:
                raise ExecutionRuleInputError(
                    "v3 settlement import contains a duplicate package identity"
                )
            identities.add(identity)
        return bundles

    @staticmethod
    def _validate_lookup(*, security_id: str, as_of: datetime) -> None:
        DjangoAShareExecutionRuleRepository._validate_security_id(security_id)
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ExecutionRuleInputError("rule lookup requires an aware knowledge cutoff")

    @staticmethod
    def _validate_security_id(security_id: str) -> None:
        if (
            type(security_id) is not str
            or not security_id
            or security_id.strip() != security_id
            or len(security_id) > 192
            or any(character.isspace() for character in security_id)
        ):
            raise ExecutionRuleInputError("security_id must be a bounded canonical token")

    def _apply_batch(
        self,
        candidates: tuple[_RuleEntry, ...],
        security_ids: tuple[str, ...],
    ) -> ExecutionRuleImportResult:
        rows = list(
            AShareExecutionRuleModel._default_manager.using(self._using)
            .filter(security_id__in=security_ids)
            .order_by("security_id", "effective_from", "id")
        )
        stored_by_security: dict[
            str, list[tuple[_RuleEntry, AShareExecutionRuleRetirementEvidence]]
        ] = {security_id: [] for security_id in security_ids}
        identities: dict[tuple[str, str, str], _RuleEntry] = {}
        for row in rows:
            stored = self._decode_any_row(row)
            identity = _rule_identity(stored)
            if identity in identities:
                raise ExecutionRuleCorruption("Stored A-share rule identity is duplicated")
            identities[identity] = stored
            stored_by_security[_rule_header(stored).security_id].append(
                (stored, _retirement_evidence(row))
            )

        inserted: list[_RuleEntry] = []
        unchanged_count = 0
        for candidate in candidates:
            identity = _rule_identity(candidate)
            existing = identities.get(identity)
            if existing is not None:
                if existing != candidate:
                    raise ExecutionRuleConflict(
                        "An existing A-share rule identity has different canonical content"
                    )
                unchanged_count += 1
            else:
                inserted.append(candidate)

        recorded_at = self._recorded_at() if inserted else None

        for candidate in inserted:
            candidate_header = _rule_header(candidate)
            for stored, retirement in stored_by_security[candidate_header.security_id]:
                if self._windows_overlap(
                    candidate,
                    stored,
                    right_retirement=retirement,
                    retirement_as_of=recorded_at,
                ):
                    raise ExecutionRuleConflict(
                        "A-share rule effective windows overlap for the same security"
                    )
        for index, candidate in enumerate(inserted):
            for other in inserted[index + 1 :]:
                if _rule_header(candidate).security_id == _rule_header(
                    other
                ).security_id and self._windows_overlap(candidate, other):
                    raise ExecutionRuleConflict(
                        "A-share rule batch contains overlapping windows for the same security"
                    )

        if inserted:
            assert recorded_at is not None
            for rule in inserted:
                header = _rule_header(rule)
                AShareExecutionRuleModel._default_manager.using(self._using).create(
                    security_id=header.security_id,
                    rule_id=header.rule_id,
                    rule_version=header.rule_version,
                    market=header.market,
                    board=header.board,
                    recorded_at=recorded_at,
                    source_available_at=header.source_available_at,
                    effective_from=header.effective_from,
                    valid_until=header.valid_until,
                    content_hash=rule.content_hash,
                    canonical_payload=_encode_rule_entry(rule),
                )
        return ExecutionRuleImportResult(
            inserted_count=len(inserted), unchanged_count=unchanged_count
        )

    def _recorded_at(self) -> datetime:
        recorded_at = self._clock.now()
        if (
            type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_at.utcoffset() is None
        ):
            raise ExecutionRulePersistenceUnavailable(
                "A-share execution rule clock must return an aware datetime"
            )
        return recorded_at

    @staticmethod
    def _windows_overlap(
        left: _RuleEntry,
        right: _RuleEntry,
        *,
        right_retirement: AShareExecutionRuleRetirementEvidence | None = None,
        retirement_as_of: datetime | None = None,
    ) -> bool:
        left_header = _rule_header(left)
        right_header = _rule_header(right)
        right_end = right_header.valid_until
        if (
            right_retirement is not None
            and not right_retirement.is_empty
            and retirement_as_of is not None
            and right_retirement.retirement_recorded_at is not None
            and right_retirement.retirement_recorded_at <= retirement_as_of
        ):
            assert right_retirement.retirement_effective_at is not None
            right_end = min(right_end, right_retirement.retirement_effective_at)
        return (
            left_header.effective_from < right_end
            and right_header.effective_from < left_header.valid_until
        )

    def _decode_row(self, row: AShareExecutionRuleModel) -> AShareExecutionRule:
        rule = self._decode_any_row(row)
        if type(rule) is not AShareExecutionRule:
            raise ExecutionRuleVersionMismatch(
                "A-share execution v1 reader encountered a different rule schema"
            )
        return rule

    def _decode_submission_row(self, row: AShareExecutionRuleModel) -> ExecutionSubmissionRuleV2:
        rule = self._decode_any_row(row)
        if type(rule) is not ExecutionSubmissionRuleV2:
            raise ExecutionRuleVersionMismatch(
                "A-share execution v2 reader encountered a different rule schema"
            )
        return rule

    def _decode_settlement_row(self, row: AShareExecutionRuleModel) -> ExecutionSettlementBundleV3:
        rule = self._decode_any_row(row)
        if type(rule) is not ExecutionSettlementBundleV3:
            raise ExecutionRuleVersionMismatch(
                "A-share execution v3 reader encountered a different rule schema"
            )
        return rule

    def _decode_any_row(self, row: AShareExecutionRuleModel) -> _RuleEntry:
        if (
            type(row.recorded_at) is not datetime
            or row.recorded_at.tzinfo is None
            or row.recorded_at.utcoffset() is None
        ):
            raise ExecutionRuleCorruption("Stored A-share rule record time is not timezone-aware")
        payload = cast(object, row.canonical_payload)
        try:
            if isinstance(payload, dict) and "settlement_policy_v1" in payload:
                rule: _RuleEntry = decode_a_share_execution_settlement_bundle(payload)
            elif isinstance(payload, dict) and "execution_rule_v1" in payload:
                rule = decode_a_share_execution_submission_rule(payload)
            else:
                rule = decode_a_share_execution_rule(payload)
        except (
            AShareExecutionRuleCodecError,
            AShareExecutionRuleV2CodecError,
            AShareExecutionRuleV3CodecError,
        ) as error:
            raise ExecutionRuleCorruption("Stored A-share rule payload is invalid") from error
        header = _rule_header(rule)
        if (
            row.security_id != header.security_id
            or row.rule_id != header.rule_id
            or row.rule_version != header.rule_version
            or row.market != header.market
            or row.board != header.board
            or row.source_available_at != header.source_available_at
            or row.effective_from != header.effective_from
            or row.valid_until != header.valid_until
            or row.content_hash != header.content_hash
        ):
            raise ExecutionRuleCorruption(
                "Stored A-share rule lookup columns disagree with canonical payload"
            )
        try:
            AShareExecutionRuleRetirementTarget(
                security_id=header.security_id,
                rule_id=header.rule_id,
                rule_version=header.rule_version,
                content_hash=header.content_hash,
                rule_recorded_at=row.recorded_at,
                effective_from=header.effective_from,
                valid_until=header.valid_until,
                retirement=_retirement_evidence(row),
            )
        except (TypeError, ValueError) as error:
            raise ExecutionRuleCorruption(
                "Stored A-share rule retirement metadata is invalid"
            ) from error
        return rule

    def _acquire_sqlite_fence(self, security_ids: tuple[str, ...]) -> None:
        """Reserve SQLite's writer before checking overlap or identity rows."""

        AShareExecutionRuleModel._default_manager.using(self._using).filter(
            security_id__in=security_ids
        ).update(canonical_payload=F("canonical_payload"))

    def _acquire_postgresql_fences(self, security_ids: tuple[str, ...]) -> str:
        connection = connections[self._using]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_isolation'), "
                "current_setting('lock_timeout'), current_setting('lock_timeout')::interval"
            )
            row = cursor.fetchone()
            if (
                not isinstance(row, tuple)
                or len(row) != 3
                or type(row[0]) is not str
                or type(row[1]) is not str
                or not isinstance(row[2], timedelta)
            ):
                raise ExecutionRulePersistenceUnavailable(
                    "PostgreSQL did not return transaction lock settings"
                )
            isolation, previous_timeout, current_timeout = cast(tuple[str, str, timedelta], row)
            if isolation.lower() != "read committed":
                raise ExecutionRulePersistenceUnavailable(
                    "PostgreSQL rule writes require READ COMMITTED isolation"
                )
            bounded_timeout = _PG_ADVISORY_LOCK_TIMEOUT
            if timedelta(0) < current_timeout < bounded_timeout:
                bounded_timeout = current_timeout
            cursor.execute(
                "SELECT set_config('lock_timeout', %s, true)",
                [f"{bounded_timeout.total_seconds():.6f}s"],
            )
            for security_id in security_ids:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    [_postgres_advisory_key(security_id)],
                )
            return previous_timeout

    def _restore_postgresql_lock_timeout(self, previous_timeout: str) -> None:
        connection = connections[self._using]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('lock_timeout', %s, true)",
                [previous_timeout],
            )

    @staticmethod
    def _is_lock_or_storage_unavailable(error: DatabaseError) -> bool:
        current: BaseException | None = error
        while current is not None:
            sqlstate = getattr(current, "sqlstate", None)
            if sqlstate == "55P03":
                return True
            sqlite_code = getattr(current, "sqlite_errorcode", None)
            if type(sqlite_code) is int and (sqlite_code & 0xFF) in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
                sqlite3.SQLITE_READONLY,
            }:
                return True
            message = str(current).lower()
            if any(
                marker in message
                for marker in (
                    "database is locked",
                    "database table is locked",
                    "readonly database",
                    "read-only database",
                    "could not obtain lock",
                    "lock timeout",
                )
            ):
                return True
            current = current.__cause__
        return False


def _postgres_advisory_key(security_id: str) -> int:
    digest = hashlib.sha256(
        b"risk-center-ashare-execution-rule:" + security_id.encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _retirement_evidence(
    row: AShareExecutionRuleModel,
) -> AShareExecutionRuleRetirementEvidence:
    """Restore the all-null or complete typed retirement metadata from one row."""

    try:
        evidence = AShareExecutionRuleRetirementEvidence(
            retirement_effective_at=row.retirement_effective_at,
            retirement_recorded_at=row.retirement_recorded_at,
            retirement_request_id=row.retirement_request_id,
            retirement_actor_type=row.retirement_actor_type,
            retirement_actor_id=row.retirement_actor_id,
            retirement_request_hash=row.retirement_request_hash,
        )
        AShareExecutionRuleRetirementTarget(
            security_id=row.security_id,
            rule_id=row.rule_id,
            rule_version=row.rule_version,
            content_hash=row.content_hash,
            rule_recorded_at=row.recorded_at,
            effective_from=row.effective_from,
            valid_until=row.valid_until,
            retirement=evidence,
        )
        return evidence
    except (TypeError, ValueError) as error:
        raise ExecutionRuleCorruption(
            "Stored A-share rule retirement metadata is incomplete or invalid"
        ) from error


def _retired_at(row: AShareExecutionRuleModel, *, as_of: datetime) -> bool:
    """Apply a retirement only after it was recorded and became effective."""

    evidence = _retirement_evidence(row)
    if evidence.is_empty:
        return False
    assert evidence.retirement_effective_at is not None
    assert evidence.retirement_recorded_at is not None
    return evidence.retirement_recorded_at <= as_of and evidence.retirement_effective_at <= as_of


def _rule_header(rule: _RuleEntry) -> _RuleHeader:
    """Map each public schema to its one immutable stored/lifecycle identity."""

    if type(rule) is AShareExecutionRule:
        AShareExecutionRule.__post_init__(rule)
        base = rule
        rule_id = rule.rule_id
        rule_version = rule.rule_version
        source_available_at = rule.source_available_at
        effective_from = rule.effective_from
        valid_until = rule.valid_until
    elif type(rule) is ExecutionSubmissionRuleV2:
        ExecutionSubmissionRuleV2.__post_init__(rule)
        base = rule.execution_rule_v1
        rule_id = base.rule_id
        rule_version = base.rule_version
        source_available_at = base.source_available_at
        effective_from = base.effective_from
        valid_until = base.valid_until
    elif type(rule) is ExecutionSettlementBundleV3:
        ExecutionSettlementBundleV3.__post_init__(rule)
        base = rule.execution_submission_v2.execution_rule_v1
        rule_id = rule.bundle_id
        rule_version = rule.bundle_version
        source_available_at = rule.source_available_at
        effective_from = rule.effective_from
        valid_until = rule.valid_until
    else:
        raise TypeError("rule must use an exact supported domain type")
    return _RuleHeader(
        security_id=base.security_id,
        rule_id=rule_id,
        rule_version=rule_version,
        market=base.market,
        board=base.board,
        source_available_at=source_available_at,
        effective_from=effective_from,
        valid_until=valid_until,
        content_hash=rule.content_hash,
    )


def _rule_identity(rule: _RuleEntry) -> tuple[str, str, str]:
    header = _rule_header(rule)
    return (header.security_id, header.rule_id, header.rule_version)


def _encode_rule_entry(rule: _RuleEntry) -> dict[str, object]:
    if isinstance(rule, AShareExecutionRule):
        if type(rule) is not AShareExecutionRule:
            raise TypeError("rule must use an exact supported domain type")
        return encode_a_share_execution_rule(rule)
    if isinstance(rule, ExecutionSubmissionRuleV2):
        if type(rule) is not ExecutionSubmissionRuleV2:
            raise TypeError("rule must use an exact supported domain type")
        return encode_a_share_execution_submission_rule(rule)
    if isinstance(rule, ExecutionSettlementBundleV3):
        if type(rule) is not ExecutionSettlementBundleV3:
            raise TypeError("rule must use an exact supported domain type")
        return encode_a_share_execution_settlement_bundle(rule)
    raise TypeError("rule must use an exact supported domain type")
