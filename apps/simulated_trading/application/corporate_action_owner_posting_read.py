"""Typed read-only contract for a completely verified active posting revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    calculate_corporate_action_delta,
)


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionActivePostingHead:
    """One current event head after complete account Audit/Outbox and Domain replay."""

    account_id: int
    owner_user_id: int
    canonical_account_id: str
    source_namespace: str
    source_event_id: str
    source_record_id: str
    source_revision_id: str
    security_id: str
    asset_code: str
    action_kind: CorporateActionKind
    record_date: date
    effective_date: date
    active_entries: tuple[OwnerCorporateActionRevisionEntry, ...]

    def __post_init__(self) -> None:
        """Require a nonempty active stage set bound to this exact source and owner."""

        strings = (
            self.canonical_account_id,
            self.source_namespace,
            self.source_event_id,
            self.source_record_id,
            self.source_revision_id,
            self.security_id,
            self.asset_code,
        )
        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or any(
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 192
                or any(character.isspace() for character in value)
                for value in strings
            )
            or type(self.action_kind) is not CorporateActionKind
            or self.action_kind
            not in {CorporateActionKind.CASH_DIVIDEND, CorporateActionKind.SHARE_DISTRIBUTION}
            or type(self.record_date) is not date
            or type(self.effective_date) is not date
            or type(self.active_entries) is not tuple
            or not self.active_entries
            or len(self.active_entries) > 3
            or any(
                type(entry) is not OwnerCorporateActionRevisionEntry
                for entry in self.active_entries
            )
        ):
            raise ValueError("active corporate-action posting head is incomplete")

        entry_ids: set[int] = set()
        stages: set[CorporateActionStage] = set()
        for entry in self.active_entries:
            entry.__post_init__()
            request = entry.request
            if (
                entry.entry_id in entry_ids
                or entry.delta != calculate_corporate_action_delta(request)
                or request.account_id != self.account_id
                or request.owner_user_id != self.owner_user_id
                or request.source_namespace != self.source_namespace
                or request.source_event_id != self.source_event_id
                or request.source_record_id != self.source_record_id
                or request.source_revision_id != self.source_revision_id
                or request.security_id != self.security_id
                or request.asset_code != self.asset_code
                or request.action_kind is not self.action_kind
                or request.record_date != self.record_date
                or request.effective_date != self.effective_date
                or request.entry_kind
                not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
                or request.stage in stages
            ):
                raise ValueError("active corporate-action stage crosses the selected head")
            entry_ids.add(entry.entry_id)
            stages.add(request.stage)


class OwnerCorporateActionPostingReadPort(Protocol):
    """Read one fully verified, current-source active stage set without writing."""

    def read_current_active_postings(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        canonical_account_id: str | None,
        source_namespace: str,
        source_event_id: str,
        source_record_id: str,
        source_revision_id: str,
        security_id: str,
        asset_code: str,
        action_kind: CorporateActionKind,
        record_date: date,
        effective_date: date,
        as_of: datetime,
        using: str,
    ) -> OwnerCorporateActionActivePostingHead:
        """Return active entries only after full original ledger and head verification."""


__all__ = (
    "OwnerCorporateActionActivePostingHead",
    "OwnerCorporateActionPostingReadPort",
)
