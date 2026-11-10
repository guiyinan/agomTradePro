"""Pure replay rules for a record-date simulated-account share balance.

Infrastructure must authenticate the zero-origin anchor, complete V4 fill
chains, and immutable company-action rows before constructing these facts.
This module verifies their scope, chronology, revisions, and share arithmetic;
it does not infer an opening position from mutable portfolio snapshots.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
)

_DIGEST_CHARACTERS = frozenset("0123456789abcdef")
_ZERO_SHARES = Decimal("0.000000")
_SHARE_QUANTUM = Decimal("0.000001")
_PROOF_SCHEMA = "simulated-corporate-action-ownership.v1"


class OwnershipAnchorKind(StrEnum):
    """Opening-position evidence supported by this replay contract."""

    ZERO_ORIGIN = "zero_origin"


class OwnershipFillSide(StrEnum):
    """Share direction of one retained simulated fill."""

    BUY = "buy"
    SELL = "sell"


class OwnershipEvidenceError(ValueError):
    """Raised when retained account history cannot prove one exact balance."""

    def __init__(self, message: str, code: str) -> None:
        self.code = code
        super().__init__(message)


def _raise(message: str, code: str) -> NoReturn:
    """Raise one stable domain evidence failure."""

    raise OwnershipEvidenceError(message, code)


def _require_token(value: str, field_name: str, *, max_length: int = 192) -> None:
    """Require a bounded stable locator without whitespace."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(character.isspace() for character in value)
    ):
        _raise(f"{field_name} is not a stable ownership-history locator", _INPUT_INVALID)


def _require_digest(value: str, field_name: str) -> None:
    """Require one lowercase SHA-256 evidence seal."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _DIGEST_CHARACTERS for character in value)
    ):
        _raise(f"{field_name} is not a lowercase SHA-256 digest", _INPUT_INVALID)


def _require_aware(value: datetime, field_name: str) -> None:
    """Reject naive or non-datetime evidence clocks."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _raise(f"{field_name} must be timezone-aware", _INPUT_INVALID)


def _require_share_amount(
    value: Decimal,
    field_name: str,
    *,
    allow_zero: bool,
) -> None:
    """Require an exact, finite share quantity at ledger precision."""

    if type(value) is not Decimal or not value.is_finite():
        _raise(f"{field_name} must be an exact Decimal", _INPUT_INVALID)
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or exponent < -6:
        _raise(f"{field_name} exceeds six decimal places", _INPUT_INVALID)
    if value < _ZERO_SHARES or (not allow_zero and value <= _ZERO_SHARES):
        _raise(
            f"{field_name} must be {'nonnegative' if allow_zero else 'positive'}", _INPUT_INVALID
        )


def _require_share_delta(value: Decimal, field_name: str) -> None:
    """Require an exact signed share delta at ledger precision."""

    if type(value) is not Decimal or not value.is_finite():
        _raise(f"{field_name} must be an exact Decimal", _INPUT_INVALID)
    exponent = value.as_tuple().exponent
    if type(exponent) is not int or exponent < -6:
        _raise(f"{field_name} exceeds six decimal places", _INPUT_INVALID)


def _utc_text(value: datetime) -> str:
    """Return canonical UTC text for proof hashing."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    """Return one non-exponent share quantity representation."""

    return format(value.quantize(_SHARE_QUANTUM), "f")


_INPUT_INVALID = "CORPORATE_ACTION_OWNERSHIP_INPUT_INVALID"
_ANCHOR_UNAVAILABLE = "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE"
_SCOPE_INVALID = "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID"
_RECEIPT_UNSUPPORTED = "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED"
_RECORD_DATE_OPEN = "CORPORATE_ACTION_OWNERSHIP_RECORD_DATE_OPEN"
_SAME_DAY_AMBIGUOUS = "CORPORATE_ACTION_OWNERSHIP_SAME_DAY_AMBIGUOUS"
_EVIDENCE_AFTER_CUTOFF = "CORPORATE_ACTION_OWNERSHIP_EVIDENCE_AFTER_CUTOFF"
_ACTION_REVISION_INVALID = "CORPORATE_ACTION_OWNERSHIP_ACTION_REVISION_INVALID"
_ACTION_REVISION_FORK = "CORPORATE_ACTION_OWNERSHIP_ACTION_REVISION_FORK"
_ACTION_REVERSAL_INVALID = "CORPORATE_ACTION_OWNERSHIP_ACTION_REVERSAL_INVALID"
_ACTION_RECEIVABLE_OPEN = "CORPORATE_ACTION_OWNERSHIP_ACTION_RECEIVABLE_OPEN"
_QUANTITY_INVALID = "CORPORATE_ACTION_OWNERSHIP_QUANTITY_INVALID"


@dataclass(frozen=True, slots=True)
class OwnershipOpeningAnchor:
    """One immutable account-creation fact proving zero initial shares.

    Infrastructure may construct this value only after reading and validating
    the persisted append-only anchor model. A matching ID/hash supplied by an
    untrusted caller is not sufficient evidence by itself.
    """

    account_id: int
    owner_user_id: int
    anchor_id: str
    anchor_kind: OwnershipAnchorKind
    quantity: Decimal
    effective_at: datetime
    observed_at: datetime
    evidence_sha256: str

    def __post_init__(self) -> None:
        """Validate the account-wide zero-origin claim and its retained seal."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
        ):
            _raise("opening-anchor account identity is invalid", _INPUT_INVALID)
        _require_token(self.anchor_id, "anchor_id")
        if type(self.anchor_kind) is not OwnershipAnchorKind:
            _raise("opening-anchor kind is unsupported", _ANCHOR_UNAVAILABLE)
        _require_share_amount(self.quantity, "opening_anchor.quantity", allow_zero=True)
        if self.anchor_kind is OwnershipAnchorKind.ZERO_ORIGIN and self.quantity != _ZERO_SHARES:
            _raise("zero-origin anchor must begin at exactly zero shares", _ANCHOR_UNAVAILABLE)
        _require_aware(self.effective_at, "opening_anchor.effective_at")
        _require_aware(self.observed_at, "opening_anchor.observed_at")
        if self.effective_at > self.observed_at:
            _raise("opening-anchor observation predates its effective time", _ANCHOR_UNAVAILABLE)
        _require_digest(self.evidence_sha256, "opening_anchor.evidence_sha256")


@dataclass(frozen=True, slots=True)
class OwnershipFillFact:
    """One V4 fill reconstructed from its immutable receipt and linked Trade."""

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    trade_id: int
    reservation_id: int
    fill_sequence: int
    side: OwnershipFillSide
    quantity: Decimal
    execution_date: date
    occurred_at: datetime
    recorded_at: datetime
    binding_version: int
    receipt_version: int
    receipt_sha256: str

    def __post_init__(self) -> None:
        """Validate fill identity, chronology, and exact receipt locator."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.trade_id) is not int
            or self.trade_id <= 0
            or type(self.reservation_id) is not int
            or self.reservation_id <= 0
            or type(self.fill_sequence) is not int
            or self.fill_sequence <= 0
        ):
            _raise("fill identity is invalid", _INPUT_INVALID)
        for field_name, value in (
            ("security_id", self.security_id),
            ("asset_code", self.asset_code),
        ):
            _require_token(value, field_name)
        if type(self.side) is not OwnershipFillSide:
            _raise("fill side is unsupported", _RECEIPT_UNSUPPORTED)
        _require_share_amount(self.quantity, "fill.quantity", allow_zero=False)
        if type(self.execution_date) is not date:
            _raise("fill execution_date must be an exact date", _INPUT_INVALID)
        _require_aware(self.occurred_at, "fill.occurred_at")
        _require_aware(self.recorded_at, "fill.recorded_at")
        if self.occurred_at > self.recorded_at:
            _raise("fill source event is recorded before it occurred", _RECEIPT_UNSUPPORTED)
        if type(self.binding_version) is not int or self.binding_version <= 0:
            _raise("fill binding version is invalid", _RECEIPT_UNSUPPORTED)
        if type(self.receipt_version) is not int or self.receipt_version <= 0:
            _raise("fill receipt version is invalid", _RECEIPT_UNSUPPORTED)
        _require_digest(self.receipt_sha256, "fill.receipt_sha256")


@dataclass(frozen=True, slots=True)
class CorporateActionOwnershipEvidence:
    """One immutable account-action row with share and receivable effects."""

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    account_revision: int
    entry_id: int
    source_event_id: str
    source_revision_id: str
    action_kind: CorporateActionKind
    stage_key: str
    stage: CorporateActionStage
    entry_kind: CorporateActionEntryKind
    stage_date: date
    posted_at: datetime
    recorded_at: datetime
    share_delta: Decimal
    share_receivable_delta: Decimal
    reversal_of_entry_id: int | None
    supersedes_revision_id: str | None
    evidence_sha256: str

    def __post_init__(self) -> None:
        """Validate immutable stage identity, lineage, and share precision."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.entry_id) is not int
            or self.entry_id <= 0
            or type(self.account_revision) is not int
            or self.account_revision <= 0
        ):
            _raise("company-action entry identity is invalid", _INPUT_INVALID)
        for field_name, value in (
            ("security_id", self.security_id),
            ("asset_code", self.asset_code),
            ("source_event_id", self.source_event_id),
            ("source_revision_id", self.source_revision_id),
            ("stage_key", self.stage_key),
        ):
            _require_token(value, field_name)
        if self.supersedes_revision_id is not None:
            _require_token(self.supersedes_revision_id, "supersedes_revision_id")
            if self.supersedes_revision_id == self.source_revision_id:
                _raise("action revision cannot supersede itself", _ACTION_REVISION_INVALID)
        if (
            type(self.action_kind) is not CorporateActionKind
            or type(self.stage) is not CorporateActionStage
        ):
            _raise("company-action ownership type is unsupported", _ACTION_REVISION_INVALID)
        if type(self.entry_kind) is not CorporateActionEntryKind:
            _raise("company-action entry kind is unsupported", _ACTION_REVISION_INVALID)
        if self.stage_key != f"{self.entry_kind.value}:{self.stage.value}":
            _raise(
                "company-action stage key differs from its immutable identity",
                _ACTION_REVISION_INVALID,
            )
        if type(self.stage_date) is not date:
            _raise("company-action stage date must be an exact date", _INPUT_INVALID)
        _require_aware(self.posted_at, "company_action.posted_at")
        _require_aware(self.recorded_at, "company_action.recorded_at")
        if self.posted_at > self.recorded_at:
            _raise("company-action record time predates its posted time", _ACTION_REVISION_INVALID)
        _require_share_delta(self.share_delta, "company_action.share_delta")
        _require_share_delta(self.share_receivable_delta, "company_action.share_receivable_delta")
        if (
            self.share_delta != _ZERO_SHARES
            and self.stage is not CorporateActionStage.SHARE_DELIVERY
        ):
            _raise("only share delivery may change owned shares", _ACTION_REVISION_INVALID)
        if self.share_receivable_delta != _ZERO_SHARES and self.stage not in {
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
        }:
            _raise(
                "only share entitlement or delivery may change share receivables",
                _ACTION_REVISION_INVALID,
            )
        if (
            self.share_delta != _ZERO_SHARES or self.share_receivable_delta != _ZERO_SHARES
        ) and self.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION:
            _raise("non-share action cannot change share quantities", _ACTION_REVISION_INVALID)
        if self.entry_kind is not CorporateActionEntryKind.REVERSAL:
            if self.share_delta < _ZERO_SHARES:
                _raise("active share delivery cannot reduce owned shares", _ACTION_REVISION_INVALID)
            if (
                self.share_receivable_delta > _ZERO_SHARES
                and self.stage is not CorporateActionStage.SHARE_ENTITLEMENT
            ):
                _raise("only an entitlement may create share receivables", _ACTION_REVISION_INVALID)
            if (
                self.share_receivable_delta < _ZERO_SHARES
                and self.stage is not CorporateActionStage.SHARE_DELIVERY
            ):
                _raise("only delivery may consume share receivables", _ACTION_REVISION_INVALID)
        elif self.share_delta > _ZERO_SHARES:
            _raise("reversal cannot increase owned shares", _ACTION_REVERSAL_INVALID)
        elif (
            self.share_receivable_delta > _ZERO_SHARES
            and self.stage is not CorporateActionStage.SHARE_DELIVERY
        ):
            _raise("reversal receivable increase must negate a delivery", _ACTION_REVERSAL_INVALID)
        elif (
            self.share_receivable_delta < _ZERO_SHARES
            and self.stage is not CorporateActionStage.SHARE_ENTITLEMENT
        ):
            _raise(
                "reversal receivable decrease must negate an entitlement", _ACTION_REVERSAL_INVALID
            )
        if (
            self.stage is CorporateActionStage.SHARE_DELIVERY
            and self.share_delta != -self.share_receivable_delta
        ):
            _raise(
                "share delivery and receivable deltas must offset exactly", _ACTION_REVISION_INVALID
            )
        _require_digest(self.evidence_sha256, "company_action.evidence_sha256")
        if self.entry_kind is CorporateActionEntryKind.REVERSAL:
            if (
                type(self.reversal_of_entry_id) is not int
                or self.reversal_of_entry_id <= 0
                or self.supersedes_revision_id is None
            ):
                _raise("action reversal lacks its exact predecessor", _ACTION_REVERSAL_INVALID)
        elif self.reversal_of_entry_id is not None:
            _raise("non-reversal action cannot name a predecessor row", _ACTION_REVERSAL_INVALID)
        if (
            self.entry_kind is CorporateActionEntryKind.POSTING
            and self.supersedes_revision_id is not None
        ):
            _raise("initial action posting cannot supersede a revision", _ACTION_REVISION_INVALID)
        if (
            self.entry_kind is CorporateActionEntryKind.SUCCESSOR
            and self.supersedes_revision_id is None
        ):
            _raise(
                "action successor requires its exact predecessor revision", _ACTION_REVISION_INVALID
            )
        if self.entry_kind is CorporateActionEntryKind.NO_EFFECT and (
            self.action_kind is not CorporateActionKind.RIGHTS_ISSUE
            or self.stage is not CorporateActionStage.RIGHTS_NOT_EXERCISED
            or self.share_delta != _ZERO_SHARES
            or self.share_receivable_delta != _ZERO_SHARES
        ):
            _raise(
                "no-effect action must be a zero-share rights election", _ACTION_REVISION_INVALID
            )


@dataclass(frozen=True, slots=True)
class OwnershipReplayRequest:
    """Exact scope and as-known cutoff for one record-date replay."""

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    record_date: date
    record_date_end_exclusive: datetime
    exchange: str
    exchange_timezone_name: str
    cutoff_policy_id: str
    cutoff_policy_sha256: str
    evidence_cutoff_at: datetime
    opening_anchor: OwnershipOpeningAnchor | None
    fills: tuple[OwnershipFillFact, ...]
    corporate_actions: tuple[CorporateActionOwnershipEvidence, ...]

    def __post_init__(self) -> None:
        """Reject mixed-scope, incomplete-container, or malformed replay requests."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
        ):
            _raise("ownership replay account identity is invalid", _INPUT_INVALID)
        for field_name, value in (
            ("security_id", self.security_id),
            ("asset_code", self.asset_code),
        ):
            _require_token(value, field_name)
        if type(self.record_date) is not date:
            _raise("ownership replay record_date must be an exact date", _INPUT_INVALID)
        _require_aware(self.record_date_end_exclusive, "record_date_end_exclusive")
        _require_token(self.exchange, "exchange")
        _require_token(self.exchange_timezone_name, "exchange_timezone_name")
        _require_token(self.cutoff_policy_id, "cutoff_policy_id")
        _require_digest(self.cutoff_policy_sha256, "cutoff_policy_sha256")
        try:
            exchange_timezone = ZoneInfo(self.exchange_timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise OwnershipEvidenceError(
                "exchange timezone is not qualified", _INPUT_INVALID
            ) from error
        expected_record_date_end = datetime.combine(
            self.record_date + timedelta(days=1),
            time.min,
            tzinfo=exchange_timezone,
        )
        if self.record_date_end_exclusive.astimezone(UTC) != expected_record_date_end.astimezone(
            UTC
        ):
            _raise(
                "record-date cutoff does not match the qualified exchange-local boundary",
                _INPUT_INVALID,
            )
        _require_aware(self.evidence_cutoff_at, "evidence_cutoff_at")
        if (
            self.opening_anchor is not None
            and type(self.opening_anchor) is not OwnershipOpeningAnchor
        ):
            _raise("ownership replay anchor has an unsupported type", _ANCHOR_UNAVAILABLE)
        if type(self.fills) is not tuple or any(
            type(item) is not OwnershipFillFact for item in self.fills
        ):
            _raise("ownership fill evidence must be an exact tuple", _INPUT_INVALID)
        if type(self.corporate_actions) is not tuple or any(
            type(item) is not CorporateActionOwnershipEvidence for item in self.corporate_actions
        ):
            _raise("company-action evidence must be an exact tuple", _INPUT_INVALID)


@dataclass(frozen=True, slots=True)
class RecordDateOwnershipProof:
    """Replay result sealed to one account, asset, record date, and source set."""

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    record_date: date
    ownership_snapshot_as_of_date: date
    record_date_end_exclusive: datetime
    exchange: str
    exchange_timezone_name: str
    cutoff_policy_id: str
    cutoff_policy_sha256: str
    eligible_quantity: Decimal
    ownership_snapshot_id: str
    ownership_snapshot_sha256: str
    ownership_snapshot_observed_at: datetime


def _validate_scope(
    *,
    request: OwnershipReplayRequest,
    account_id: int,
    owner_user_id: int,
    security_id: str,
    asset_code: str,
    label: str,
) -> None:
    """Require one evidence row to match the exact account and instrument."""

    if (
        account_id != request.account_id
        or owner_user_id != request.owner_user_id
        or security_id != request.security_id
        or asset_code != request.asset_code
    ):
        _raise(f"{label} belongs to another owner, account, or instrument", _SCOPE_INVALID)


def _reversal_index(
    rows: tuple[CorporateActionOwnershipEvidence, ...],
) -> dict[int, CorporateActionOwnershipEvidence]:
    """Validate correction links and return the unique reversal for each target."""

    by_id = {row.entry_id: row for row in rows}
    if len(by_id) != len(rows):
        _raise("company-action entry IDs are duplicated", _ACTION_REVISION_INVALID)
    reversed_by: dict[int, CorporateActionOwnershipEvidence] = {}
    for row in rows:
        if row.entry_kind is not CorporateActionEntryKind.REVERSAL:
            continue
        target = by_id.get(row.reversal_of_entry_id or 0)
        if (
            target is None
            or target.entry_kind
            not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
            or target.account_id != row.account_id
            or target.owner_user_id != row.owner_user_id
            or target.security_id != row.security_id
            or target.asset_code != row.asset_code
            or target.source_event_id != row.source_event_id
            or target.source_revision_id != row.supersedes_revision_id
            or target.action_kind is not row.action_kind
            or target.stage is not row.stage
            or row.account_revision <= target.account_revision
            or row.share_delta != -target.share_delta
            or row.share_receivable_delta != -target.share_receivable_delta
            or row.entry_id == target.entry_id
        ):
            _raise(
                "company-action reversal does not exactly negate its predecessor",
                _ACTION_REVERSAL_INVALID,
            )
        if target.entry_id in reversed_by:
            _raise("company-action stage has multiple reversals", _ACTION_REVERSAL_INVALID)
        reversed_by[target.entry_id] = row
    return reversed_by


def _active_action_rows(
    rows: tuple[CorporateActionOwnershipEvidence, ...],
    reversed_by: dict[int, CorporateActionOwnershipEvidence],
) -> tuple[CorporateActionOwnershipEvidence, ...]:
    """Select one source-revision head per event after validating its lineage."""

    by_event: dict[str, list[CorporateActionOwnershipEvidence]] = {}
    for row in rows:
        by_event.setdefault(row.source_event_id, []).append(row)
    active_rows: list[CorporateActionOwnershipEvidence] = []
    for event_id, event_rows in by_event.items():
        revisions: set[str] = set()
        superseded: set[str] = set()
        supersedes_by_revision: dict[str, str | None] = {}
        stage_keys: set[tuple[str, str]] = set()
        for row in event_rows:
            revisions.add(row.source_revision_id)
            prior = supersedes_by_revision.get(row.source_revision_id)
            if (
                row.source_revision_id in supersedes_by_revision
                and prior != row.supersedes_revision_id
            ):
                _raise(
                    "one action revision has conflicting predecessor bindings",
                    _ACTION_REVISION_INVALID,
                )
            supersedes_by_revision[row.source_revision_id] = row.supersedes_revision_id
            if row.supersedes_revision_id is not None:
                superseded.add(row.supersedes_revision_id)
            stage_identity = (row.source_revision_id, row.stage_key)
            if stage_identity in stage_keys:
                _raise("company-action revision duplicates one stage key", _ACTION_REVISION_INVALID)
            stage_keys.add(stage_identity)
        if event_id == "" or not revisions:
            _raise("company-action event identity is empty", _ACTION_REVISION_INVALID)
        for revision in superseded:
            if revision not in revisions:
                _raise(
                    "company-action successor has no retained predecessor", _ACTION_REVISION_INVALID
                )
            successor_revisions = tuple(
                candidate
                for candidate, predecessor in supersedes_by_revision.items()
                if predecessor == revision
            )
            if len(successor_revisions) != 1:
                _raise("company-action predecessor has multiple successors", _ACTION_REVISION_FORK)
            successor_revision = successor_revisions[0]
            for prior_row in event_rows:
                if prior_row.source_revision_id == revision and prior_row.entry_kind in {
                    CorporateActionEntryKind.POSTING,
                    CorporateActionEntryKind.SUCCESSOR,
                }:
                    reversal = reversed_by.get(prior_row.entry_id)
                    if reversal is None or reversal.source_revision_id != successor_revision:
                        _raise(
                            "company-action successor does not reverse every predecessor stage",
                            _ACTION_REVERSAL_INVALID,
                        )
        heads = revisions - superseded
        if len(heads) != 1:
            _raise(
                "company-action revision lineage has multiple or no heads", _ACTION_REVISION_FORK
            )
        head = next(iter(heads))
        head_rows = tuple(row for row in event_rows if row.source_revision_id == head)
        if any(
            row.entry_kind is CorporateActionEntryKind.REVERSAL for row in head_rows
        ) and not any(
            row.entry_kind
            in {
                CorporateActionEntryKind.SUCCESSOR,
                CorporateActionEntryKind.NO_EFFECT,
            }
            for row in head_rows
        ):
            _raise(
                "active action revision contains reversals without a successor",
                _ACTION_REVISION_INVALID,
            )
        active_rows.extend(
            row for row in head_rows if row.entry_kind is not CorporateActionEntryKind.REVERSAL
        )
    return tuple(active_rows)


def _fill_payload(fill: OwnershipFillFact) -> dict[str, object]:
    """Build the exact canonical hash payload for one receipt-backed fill."""

    return {
        "account_id": fill.account_id,
        "asset_code": fill.asset_code,
        "binding_version": fill.binding_version,
        "execution_date": fill.execution_date.isoformat(),
        "occurred_at": _utc_text(fill.occurred_at),
        "owner_user_id": fill.owner_user_id,
        "quantity": _decimal_text(fill.quantity),
        "receipt_sha256": fill.receipt_sha256,
        "receipt_version": fill.receipt_version,
        "recorded_at": _utc_text(fill.recorded_at),
        "reservation_id": fill.reservation_id,
        "security_id": fill.security_id,
        "side": fill.side.value,
        "trade_id": fill.trade_id,
        "fill_sequence": fill.fill_sequence,
    }


def _action_payload(row: CorporateActionOwnershipEvidence) -> dict[str, object]:
    """Build the exact canonical hash payload for one immutable action stage."""

    return {
        "account_id": row.account_id,
        "account_revision": row.account_revision,
        "action_kind": row.action_kind.value,
        "asset_code": row.asset_code,
        "entry_id": row.entry_id,
        "entry_kind": row.entry_kind.value,
        "evidence_sha256": row.evidence_sha256,
        "owner_user_id": row.owner_user_id,
        "posted_at": _utc_text(row.posted_at),
        "recorded_at": _utc_text(row.recorded_at),
        "reversal_of_entry_id": row.reversal_of_entry_id,
        "security_id": row.security_id,
        "share_delta": _decimal_text(row.share_delta),
        "share_receivable_delta": _decimal_text(row.share_receivable_delta),
        "source_event_id": row.source_event_id,
        "source_revision_id": row.source_revision_id,
        "stage": row.stage.value,
        "stage_date": row.stage_date.isoformat(),
        "stage_key": row.stage_key,
        "supersedes_revision_id": row.supersedes_revision_id,
    }


def replay_record_date_ownership(request: OwnershipReplayRequest) -> RecordDateOwnershipProof:
    """Replay a complete zero-origin account/security history through record-date close.

    The record-date cutoff is the qualified exclusive start of the following
    exchange-local calendar day. Infrastructure must supply the timezone and
    matching versioned policy provenance. Evidence must have been observed by
    that boundary. Because the current source contract cannot prove the legal
    intraday ordering of record-date fills or share-action stages, any such
    same-day activity blocks the proof. Only fills and delivered share deltas
    strictly before the record date are replayed.
    """

    if type(request) is not OwnershipReplayRequest:
        _raise("ownership replay requires the exact typed request", _INPUT_INVALID)
    request.__post_init__()
    anchor = request.opening_anchor
    if anchor is None:
        _raise("account has no immutable zero-origin anchor", _ANCHOR_UNAVAILABLE)
    if anchor.account_id != request.account_id or anchor.owner_user_id != request.owner_user_id:
        _raise("opening anchor belongs to another owner or account", _SCOPE_INVALID)
    if anchor.anchor_kind is not OwnershipAnchorKind.ZERO_ORIGIN or anchor.quantity != _ZERO_SHARES:
        _raise(
            "record-date replay requires an exact zero-origin account anchor", _ANCHOR_UNAVAILABLE
        )
    if anchor.observed_at > request.evidence_cutoff_at:
        _raise("opening anchor was observed after the replay cutoff", _EVIDENCE_AFTER_CUTOFF)
    record_date_end = request.record_date_end_exclusive
    if request.evidence_cutoff_at.astimezone(UTC) < record_date_end.astimezone(UTC):
        _raise("record-date evidence does not cover the complete local date", _RECORD_DATE_OPEN)
    exchange_timezone = ZoneInfo(request.exchange_timezone_name)
    anchor_local_date = anchor.effective_at.astimezone(exchange_timezone).date()
    if anchor_local_date >= request.record_date:
        _raise("zero-origin anchor is not earlier than the record date", _ANCHOR_UNAVAILABLE)

    fill_keys: set[tuple[int, int, int]] = set()
    receipt_hashes: set[str] = set()
    relevant_fills: list[OwnershipFillFact] = []
    for fill in request.fills:
        _validate_scope(
            request=request,
            account_id=fill.account_id,
            owner_user_id=fill.owner_user_id,
            security_id=fill.security_id,
            asset_code=fill.asset_code,
            label="fill receipt",
        )
        if fill.binding_version != 4 or fill.receipt_version not in (1, 2):
            _raise(
                "record-date replay only accepts complete V4 fill receipts", _RECEIPT_UNSUPPORTED
            )
        if fill.occurred_at.astimezone(exchange_timezone).date() != fill.execution_date:
            _raise("fill source clock differs from its sealed market session", _RECEIPT_UNSUPPORTED)
        fill_key = (fill.reservation_id, fill.fill_sequence, fill.trade_id)
        if fill_key in fill_keys or fill.receipt_sha256 in receipt_hashes:
            _raise("fill receipt identity is duplicated", _RECEIPT_UNSUPPORTED)
        fill_keys.add(fill_key)
        receipt_hashes.add(fill.receipt_sha256)
        if fill.execution_date > request.record_date:
            continue
        if fill.execution_date == request.record_date:
            _raise("record-date fill ordering is ambiguous", _SAME_DAY_AMBIGUOUS)
        if (
            fill.recorded_at > request.evidence_cutoff_at
            or fill.occurred_at > request.evidence_cutoff_at
        ):
            _raise(
                "pre-record-date fill was not known by the replay cutoff", _EVIDENCE_AFTER_CUTOFF
            )
        if fill.occurred_at <= anchor.effective_at:
            _raise("fill predates the account zero-origin anchor", _ANCHOR_UNAVAILABLE)
        relevant_fills.append(fill)

    action_rows = request.corporate_actions
    action_keys: set[tuple[str, str, str]] = set()
    account_revisions: set[int] = set()
    for row in action_rows:
        _validate_scope(
            request=request,
            account_id=row.account_id,
            owner_user_id=row.owner_user_id,
            security_id=row.security_id,
            asset_code=row.asset_code,
            label="company-action entry",
        )
        action_key = (row.source_event_id, row.source_revision_id, row.stage_key)
        if action_key in action_keys:
            _raise("company-action stage identity is duplicated", _ACTION_REVISION_INVALID)
        action_keys.add(action_key)
        if row.account_revision in account_revisions:
            _raise("company-action account revision is duplicated", _ACTION_REVISION_INVALID)
        account_revisions.add(row.account_revision)
        if row.stage_date <= request.record_date and row.recorded_at > request.evidence_cutoff_at:
            _raise(
                "record-date company-action history was observed after the replay cutoff",
                _EVIDENCE_AFTER_CUTOFF,
            )

    for event_id in {row.source_event_id for row in action_rows}:
        event_rows = tuple(row for row in action_rows if row.source_event_id == event_id)
        has_pre_record_stage = any(row.stage_date <= request.record_date for row in event_rows)
        if has_pre_record_stage and any(
            row.recorded_at > request.evidence_cutoff_at for row in event_rows
        ):
            _raise(
                "record-date company-action revision was observed after the replay cutoff",
                _EVIDENCE_AFTER_CUTOFF,
            )
    reversed_by = _reversal_index(action_rows)
    active_actions = _active_action_rows(action_rows, reversed_by)
    relevant_actions: list[CorporateActionOwnershipEvidence] = []
    for row in action_rows:
        if row.stage_date <= anchor_local_date and (
            row.share_delta != _ZERO_SHARES or row.share_receivable_delta != _ZERO_SHARES
        ):
            _raise(
                "share-changing company action predates the zero-origin anchor", _ANCHOR_UNAVAILABLE
            )
    for row in active_actions:
        if row.stage_date > request.record_date:
            continue
        if row.stage_date == request.record_date and (
            row.share_delta != _ZERO_SHARES or row.share_receivable_delta != _ZERO_SHARES
        ):
            _raise("record-date share-action ordering is ambiguous", _SAME_DAY_AMBIGUOUS)
        if row.stage_date == anchor_local_date and (
            row.share_delta != _ZERO_SHARES or row.share_receivable_delta != _ZERO_SHARES
        ):
            _raise("anchor-date share-action ordering is ambiguous", _ANCHOR_UNAVAILABLE)
        if row.stage_date < request.record_date:
            relevant_actions.append(row)

    relevant_action_events = {row.source_event_id for row in relevant_actions}
    for row in action_rows:
        if (
            row.source_event_id in relevant_action_events
            and row.recorded_at > request.evidence_cutoff_at
        ):
            _raise(
                "active company-action revision was not known by the replay cutoff",
                _EVIDENCE_AFTER_CUTOFF,
            )

    change_dates = {fill.execution_date for fill in relevant_fills}
    action_dates = {
        row.stage_date
        for row in relevant_actions
        if row.share_delta != _ZERO_SHARES or row.share_receivable_delta != _ZERO_SHARES
    }
    if change_dates & action_dates:
        _raise("same-day fill and corporate-action ordering is ambiguous", _SAME_DAY_AMBIGUOUS)

    pending_receivables: dict[tuple[str, str], Decimal] = {}
    receivable_rows = sorted(
        relevant_actions,
        key=lambda item: (
            item.source_event_id,
            item.source_revision_id,
            item.stage_date,
            item.account_revision,
        ),
    )
    for row in receivable_rows:
        receivable_key = (row.source_event_id, row.source_revision_id)
        balance = pending_receivables.get(receivable_key, _ZERO_SHARES) + row.share_receivable_delta
        if balance < _ZERO_SHARES:
            _raise("share delivery precedes its retained entitlement", _ACTION_RECEIVABLE_OPEN)
        pending_receivables[receivable_key] = balance
    if any(value != _ZERO_SHARES for value in pending_receivables.values()):
        _raise(
            "share entitlement remains undelivered at the record-date cutoff",
            _ACTION_RECEIVABLE_OPEN,
        )

    fills_by_date: dict[date, list[OwnershipFillFact]] = {}
    for fill in relevant_fills:
        fills_by_date.setdefault(fill.execution_date, []).append(fill)
    for execution_date, day_fills in fills_by_date.items():
        ordered_fills = sorted(day_fills, key=lambda item: item.occurred_at.astimezone(UTC))
        instants = [item.occurred_at.astimezone(UTC) for item in ordered_fills]
        if len(instants) != len(set(instants)):
            _raise("fill sequence has an ambiguous shared source timestamp", _SAME_DAY_AMBIGUOUS)
        fills_by_date[execution_date] = ordered_fills

    quantity = anchor.quantity
    for change_date in sorted(change_dates | action_dates):
        day_fills = fills_by_date.get(change_date, [])
        for fill in day_fills:
            quantity += fill.quantity if fill.side is OwnershipFillSide.BUY else -fill.quantity
            if quantity < _ZERO_SHARES:
                _raise("retained fill chronology produces negative owned shares", _QUANTITY_INVALID)
            _require_share_amount(quantity, "replayed_quantity", allow_zero=True)
        quantity += sum(
            (row.share_delta for row in relevant_actions if row.stage_date == change_date),
            _ZERO_SHARES,
        )
        if quantity < _ZERO_SHARES:
            _raise("company-action history produces negative owned shares", _QUANTITY_INVALID)
        _require_share_amount(quantity, "replayed_quantity", allow_zero=True)

    fills_for_hash = sorted(
        relevant_fills,
        key=lambda item: (
            item.execution_date,
            item.occurred_at.astimezone(UTC),
            item.reservation_id,
            item.fill_sequence,
            item.trade_id,
        ),
    )
    actions_for_hash = sorted(
        action_rows,
        key=lambda item: (item.source_event_id, item.source_revision_id, item.entry_id),
    )
    proof_payload: dict[str, object] = {
        "schema": _PROOF_SCHEMA,
        "scope": {
            "account_id": request.account_id,
            "owner_user_id": request.owner_user_id,
            "security_id": request.security_id,
            "asset_code": request.asset_code,
            "record_date": request.record_date.isoformat(),
            "record_date_end_exclusive": _utc_text(record_date_end),
            "exchange": request.exchange,
            "exchange_timezone_name": request.exchange_timezone_name,
            "cutoff_policy_id": request.cutoff_policy_id,
            "cutoff_policy_sha256": request.cutoff_policy_sha256,
            "evidence_cutoff_at": _utc_text(request.evidence_cutoff_at),
        },
        "opening_anchor": {
            "anchor_id": anchor.anchor_id,
            "anchor_kind": anchor.anchor_kind.value,
            "effective_at": _utc_text(anchor.effective_at),
            "observed_at": _utc_text(anchor.observed_at),
            "evidence_sha256": anchor.evidence_sha256,
            "quantity": _decimal_text(anchor.quantity),
        },
        "fills": [_fill_payload(item) for item in fills_for_hash],
        "corporate_actions": [_action_payload(item) for item in actions_for_hash],
        "eligible_quantity": _decimal_text(quantity),
    }
    canonical_payload = json.dumps(
        proof_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    proof_sha256 = hashlib.sha256(canonical_payload).hexdigest()
    proof_id = (
        f"simulated-account-ownership.v1:{request.account_id}:"
        f"{request.asset_code}:{request.record_date.isoformat()}:{proof_sha256}"
    )
    return RecordDateOwnershipProof(
        account_id=request.account_id,
        owner_user_id=request.owner_user_id,
        security_id=request.security_id,
        asset_code=request.asset_code,
        record_date=request.record_date,
        ownership_snapshot_as_of_date=request.record_date,
        record_date_end_exclusive=record_date_end,
        exchange=request.exchange,
        exchange_timezone_name=request.exchange_timezone_name,
        cutoff_policy_id=request.cutoff_policy_id,
        cutoff_policy_sha256=request.cutoff_policy_sha256,
        eligible_quantity=quantity,
        ownership_snapshot_id=proof_id,
        ownership_snapshot_sha256=proof_sha256,
        ownership_snapshot_observed_at=request.evidence_cutoff_at,
    )


__all__ = [
    "CorporateActionOwnershipEvidence",
    "OwnershipAnchorKind",
    "OwnershipEvidenceError",
    "OwnershipFillFact",
    "OwnershipFillSide",
    "OwnershipOpeningAnchor",
    "OwnershipReplayRequest",
    "RecordDateOwnershipProof",
    "replay_record_date_ownership",
]
