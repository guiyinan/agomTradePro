"""Build immutable display facts for one fully verified owner correction batch."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import NoReturn

from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
    PreparedOwnerCorporateActionRevision,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)


def _invalid(message: str) -> NoReturn:
    """Raise one typed preview-input failure without substituting economics."""

    raise CorporateActionInputValidationError(
        message,
        code="CORPORATE_ACTION_REVISION_PREVIEW_INVALID",
    )


def _source_scope(request: CorporateActionStageRequest) -> tuple[object, ...]:
    """Return stable logical owner/event identity shared across source revisions."""

    return (
        request.account_id,
        request.owner_user_id,
        request.security_id,
        request.asset_code,
        request.source_namespace,
        request.source_event_id,
        request.action_kind,
    )


def _inverse(delta: CorporateActionLedgerDelta) -> CorporateActionLedgerDelta:
    """Return the exact signed inverse of an immutable retained ledger delta."""

    return CorporateActionLedgerDelta(
        cash=-delta.cash,
        cash_receivable=-delta.cash_receivable,
        shares=-delta.shares,
        share_receivable=-delta.share_receivable,
        available_shares=-delta.available_shares,
    )


def _valid_delta(delta: object) -> bool:
    """Require all five preview effects to remain exact finite Decimals."""

    return type(delta) is CorporateActionLedgerDelta and all(
        type(value) is Decimal and value.is_finite()
        for value in (
            delta.cash,
            delta.cash_receivable,
            delta.shares,
            delta.share_receivable,
            delta.available_shares,
        )
    )


def _valid_digest(value: object) -> bool:
    """Accept one lowercase SHA-256 request identity."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validated_active_entries(
    *,
    prepared_batch: PreparedOwnerCorporateActionRevision,
    active_entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> dict[int, OwnerCorporateActionRevisionEntry]:
    """Validate and index the exact active entries replaced by a full batch."""

    if (
        type(prepared_batch) is not PreparedOwnerCorporateActionRevision
        or type(active_entries) is not tuple
        or not active_entries
        or len(active_entries) > 3
        or any(type(entry) is not OwnerCorporateActionRevisionEntry for entry in active_entries)
    ):
        _invalid("complete typed active history and prepared batch are required")
    prepared_batch.__post_init__()
    for entry in active_entries:
        entry.__post_init__()
    first_active = active_entries[0].request
    if first_active.action_kind not in {
        CorporateActionKind.CASH_DIVIDEND,
        CorporateActionKind.SHARE_DISTRIBUTION,
    }:
        _invalid("unsupported correction preview action family")

    active_by_id: dict[int, OwnerCorporateActionRevisionEntry] = {}
    active_by_stage: dict[CorporateActionStage, OwnerCorporateActionRevisionEntry] = {}
    for entry in active_entries:
        request = entry.request
        if (
            request.entry_kind
            not in {
                CorporateActionEntryKind.POSTING,
                CorporateActionEntryKind.SUCCESSOR,
            }
            or request.source_revision_id != prepared_batch.previous_revision_id
            or request.action_kind is not first_active.action_kind
            or _source_scope(request) != _source_scope(first_active)
            or entry.entry_id in active_by_id
            or request.stage in active_by_stage
            or entry.delta != calculate_corporate_action_delta(request)
        ):
            _invalid("active owner entry is not one exact current stage")
        active_by_id[entry.entry_id] = entry
        active_by_stage[request.stage] = entry

    requests = prepared_batch.requests
    batch_size = len(requests) // 2
    reversals = requests[:batch_size]
    successors = requests[batch_size:]
    if len(active_by_id) != batch_size or set(active_by_stage) != {
        request.stage for request in successors
    }:
        _invalid("correction batch does not reverse and replace the complete active stage set")
    first_request = requests[0]
    if any(
        request.action_kind is not first_request.action_kind
        or _source_scope(request) != _source_scope(first_request)
        or request.supersedes_revision_id != prepared_batch.previous_revision_id
        or request.source_revision_id != prepared_batch.current_revision_id
        for request in requests
    ) or _source_scope(first_request) != _source_scope(first_active):
        _invalid("correction batch and verified active entries cross source or owner scope")

    reversal_target_ids: set[int] = set()
    for request in reversals:
        target_id = request.reversal_of_entry_id
        if type(target_id) is not int or target_id <= 0:
            _invalid("reversal does not identify one exact active predecessor stage")
        target = active_by_id.get(target_id)
        if (
            request.entry_kind is not CorporateActionEntryKind.REVERSAL
            or target is None
            or target_id in reversal_target_ids
            or target.request.stage is not request.stage
            or target.request.action_kind is not request.action_kind
            or target.request.source_revision_id != prepared_batch.previous_revision_id
        ):
            _invalid("reversal does not identify one exact active predecessor stage")
        reversal_target_ids.add(target_id)
    if reversal_target_ids != set(active_by_id):
        _invalid("correction batch omits or duplicates an active reversal target")
    if any(request.entry_kind is not CorporateActionEntryKind.SUCCESSOR for request in successors):
        _invalid("correction batch successor section contains another entry kind")
    return active_by_id


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionRevisionPreviewRow:
    """One canonical correction request paired with its exact signed ledger effect."""

    entry_kind: CorporateActionEntryKind
    action_kind: CorporateActionKind
    stage: CorporateActionStage
    reverses_entry_id: int | None
    previous_source_revision_id: str
    source_revision_id: str
    request_payload_sha256: str
    signed_delta: CorporateActionLedgerDelta

    def __post_init__(self) -> None:
        """Reject partial row identity or non-finite financial presentation values."""

        if (
            type(self.entry_kind) is not CorporateActionEntryKind
            or self.entry_kind
            not in {CorporateActionEntryKind.REVERSAL, CorporateActionEntryKind.SUCCESSOR}
            or type(self.action_kind) is not CorporateActionKind
            or self.action_kind
            not in {CorporateActionKind.CASH_DIVIDEND, CorporateActionKind.SHARE_DISTRIBUTION}
            or type(self.stage) is not CorporateActionStage
            or (
                self.entry_kind is CorporateActionEntryKind.REVERSAL
                and (type(self.reverses_entry_id) is not int or self.reverses_entry_id <= 0)
            )
            or (
                self.entry_kind is CorporateActionEntryKind.SUCCESSOR
                and self.reverses_entry_id is not None
            )
            or type(self.previous_source_revision_id) is not str
            or not self.previous_source_revision_id.strip()
            or len(self.previous_source_revision_id) > 192
            or any(character.isspace() for character in self.previous_source_revision_id)
            or type(self.source_revision_id) is not str
            or not self.source_revision_id.strip()
            or len(self.source_revision_id) > 192
            or any(character.isspace() for character in self.source_revision_id)
            or self.previous_source_revision_id == self.source_revision_id
            or not _valid_digest(self.request_payload_sha256)
            or not _valid_delta(self.signed_delta)
        ):
            _invalid("correction preview row is incomplete or invalid")


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionRevisionPreview:
    """Full immutable correction request batch with paired reversal and successor deltas."""

    prepared_batch: PreparedOwnerCorporateActionRevision
    rows: tuple[OwnerCorporateActionRevisionPreviewRow, ...]
    _active_entries: tuple[OwnerCorporateActionRevisionEntry, ...] = field(repr=False)

    def __post_init__(self) -> None:
        """Bind every displayed row to its exact canonical Domain request."""

        if (
            type(self.prepared_batch) is not PreparedOwnerCorporateActionRevision
            or type(self.rows) is not tuple
            or len(self.rows) != len(self.prepared_batch.requests)
            or any(type(row) is not OwnerCorporateActionRevisionPreviewRow for row in self.rows)
        ):
            _invalid("correction preview rows do not match their prepared batch")
        active_by_id = _validated_active_entries(
            prepared_batch=self.prepared_batch,
            active_entries=self._active_entries,
        )
        reversal_target_ids: set[int] = set()
        for row, request in zip(self.rows, self.prepared_batch.requests, strict=True):
            row.__post_init__()
            if (
                row.entry_kind is not request.entry_kind
                or row.action_kind is not request.action_kind
                or row.stage is not request.stage
                or row.reverses_entry_id != request.reversal_of_entry_id
                or row.previous_source_revision_id != request.supersedes_revision_id
                or row.source_revision_id != request.source_revision_id
                or row.request_payload_sha256 != request.payload_sha256
            ):
                _invalid("preview row differs from its canonical correction request")
            if request.entry_kind is CorporateActionEntryKind.REVERSAL:
                target_id = row.reverses_entry_id
                if type(target_id) is not int or target_id <= 0:
                    _invalid("preview reversal has no exact active-entry target")
                target = active_by_id.get(target_id)
                if (
                    target is None
                    or target_id in reversal_target_ids
                    or row.signed_delta != _inverse(target.delta)
                ):
                    _invalid("preview reversal delta differs from the retained active entry")
                reversal_target_ids.add(target_id)
            elif row.signed_delta != calculate_corporate_action_delta(request):
                _invalid("successor preview delta differs from its canonical request")
        if reversal_target_ids != set(active_by_id):
            _invalid("preview does not include every active reversal exactly once")

    @property
    def previous_source_revision_id(self) -> str:
        """Return the exact active source revision the complete batch replaces."""

        return self.prepared_batch.previous_revision_id

    @property
    def current_source_revision_id(self) -> str:
        """Return the exact new source revision represented by the batch."""

        return self.prepared_batch.current_revision_id


def build_owner_corporate_action_revision_preview(
    *,
    prepared_batch: PreparedOwnerCorporateActionRevision,
    active_entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> OwnerCorporateActionRevisionPreview:
    """Pair a canonical batch with exact inverse and successor ledger deltas.

    ``active_entries`` must come from the caller's complete, Audit/Outbox-verified
    locked owner-history read and the Domain active-head replay. This pure pairing
    revalidates stage membership, scope, request deltas, and reversal targets; it
    does not query the ledger or establish posting authority itself.
    """

    active_by_id = _validated_active_entries(
        prepared_batch=prepared_batch,
        active_entries=active_entries,
    )
    requests = prepared_batch.requests
    batch_size = len(requests) // 2
    reversals = requests[:batch_size]
    successors = requests[batch_size:]
    rows: list[OwnerCorporateActionRevisionPreviewRow] = []
    for request in reversals:
        target_id = request.reversal_of_entry_id
        if type(target_id) is not int:
            _invalid("reversal does not identify one exact active predecessor stage")
        target = active_by_id[target_id]
        rows.append(
            OwnerCorporateActionRevisionPreviewRow(
                entry_kind=request.entry_kind,
                action_kind=request.action_kind,
                stage=request.stage,
                reverses_entry_id=target_id,
                previous_source_revision_id=prepared_batch.previous_revision_id,
                source_revision_id=prepared_batch.current_revision_id,
                request_payload_sha256=request.payload_sha256,
                signed_delta=_inverse(target.delta),
            )
        )
    for request in successors:
        if request.entry_kind is not CorporateActionEntryKind.SUCCESSOR:
            _invalid("correction batch successor section contains another entry kind")
        rows.append(
            OwnerCorporateActionRevisionPreviewRow(
                entry_kind=request.entry_kind,
                action_kind=request.action_kind,
                stage=request.stage,
                reverses_entry_id=None,
                previous_source_revision_id=prepared_batch.previous_revision_id,
                source_revision_id=prepared_batch.current_revision_id,
                request_payload_sha256=request.payload_sha256,
                signed_delta=calculate_corporate_action_delta(request),
            )
        )
    return OwnerCorporateActionRevisionPreview(
        prepared_batch=prepared_batch,
        rows=tuple(rows),
        _active_entries=active_entries,
    )


__all__ = (
    "OwnerCorporateActionRevisionPreview",
    "OwnerCorporateActionRevisionPreviewRow",
    "build_owner_corporate_action_revision_preview",
)
