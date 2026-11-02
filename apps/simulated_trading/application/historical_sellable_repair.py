"""Application entry for an explicitly selected native simulated-share repair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from core.exceptions import InvalidInputError


@dataclass(frozen=True)
class HistoricalSellableRepairCommand:
    """Bind one repair action to an owner row and, for apply, its exact preview."""

    action: Literal["apply", "rollback"]
    user_id: int
    account_id: int
    target_position_id: int
    actor_user_id: int
    idempotency_key: str
    apply_event_id: int | None = None
    preview_evidence_cutoff_at: datetime | None = None
    preview_evidence_proof_hash: str | None = None
    preview_available_quantity: Decimal | None = None
    preview_available_quantity_known: bool | None = None


@dataclass(frozen=True)
class HistoricalSellableRepairResult:
    """Stable values returned from an apply/rollback journal append."""

    journal_event_id: int
    apply_event_id: int | None
    action: Literal["apply", "rollback"]
    outcome: Literal["applied", "rolled_back", "replayed"]
    user_id: int
    account_id: int
    target_position_id: int
    before_available_quantity: Decimal
    before_available_quantity_known: bool
    after_available_quantity: Decimal
    after_available_quantity_known: bool
    evidence_cutoff_at: datetime
    evidence_proof_hash: str


class HistoricalSellableRepairRepository(Protocol):
    """Persistence boundary for the one-row G5 apply and rollback transaction."""

    def apply_sellable_repair(
        self,
        *,
        command: HistoricalSellableRepairCommand,
        database_alias: str,
    ) -> HistoricalSellableRepairResult:
        """Atomically update settled available shares and append the apply event."""

    def rollback_sellable_repair(
        self,
        *,
        command: HistoricalSellableRepairCommand,
        database_alias: str,
    ) -> HistoricalSellableRepairResult:
        """Restore one prior value only while its original proof and CAS still hold."""


class HistoricalSellableRepairService:
    """Route explicit repair requests to the locked proof-and-journal repository."""

    def __init__(
        self,
        *,
        repository: HistoricalSellableRepairRepository,
    ) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        command: HistoricalSellableRepairCommand,
        database_alias: str,
    ) -> HistoricalSellableRepairResult:
        """Apply or roll back one owner-selected simulated Position repair."""

        self._validate_command(command, database_alias)
        if command.action == "apply":
            if command.apply_event_id is not None:
                raise InvalidInputError("apply action cannot name an existing apply event")
            return self._repository.apply_sellable_repair(
                command=command,
                database_alias=database_alias,
            )
        if type(command.apply_event_id) is not int or command.apply_event_id <= 0:
            raise InvalidInputError("rollback requires the original apply event id")
        return self._repository.rollback_sellable_repair(
            command=command,
            database_alias=database_alias,
        )

    @staticmethod
    def _validate_command(
        command: HistoricalSellableRepairCommand,
        database_alias: str,
    ) -> None:
        """Reject ambiguous identifiers and non-owner actors before the repository call."""

        if type(command) is not HistoricalSellableRepairCommand:
            raise InvalidInputError("repair command type is invalid")
        if command.action not in ("apply", "rollback"):
            raise InvalidInputError("repair action is unsupported")
        preview_values = (
            command.preview_evidence_cutoff_at,
            command.preview_evidence_proof_hash,
            command.preview_available_quantity,
            command.preview_available_quantity_known,
        )
        if command.action == "apply":
            preview_cutoff = command.preview_evidence_cutoff_at
            preview_hash = command.preview_evidence_proof_hash
            preview_quantity = command.preview_available_quantity
            preview_known = command.preview_available_quantity_known
            if (
                type(preview_cutoff) is not datetime
                or preview_cutoff.tzinfo is None
                or preview_cutoff.utcoffset() is None
                or type(preview_hash) is not str
                or len(preview_hash) != 64
                or any(character not in "0123456789abcdef" for character in preview_hash)
                or type(preview_quantity) is not Decimal
                or not preview_quantity.is_finite()
                or preview_quantity < 0
                or type(preview_known) is not bool
            ):
                raise InvalidInputError(
                    "apply requires the exact cutoff, proof hash, available quantity, and known flag from preview"
                )
        elif any(value is not None for value in preview_values):
            raise InvalidInputError("rollback cannot include a new apply preview")
        for field_name, value in (
            ("user_id", command.user_id),
            ("account_id", command.account_id),
            ("target_position_id", command.target_position_id),
            ("actor_user_id", command.actor_user_id),
        ):
            if type(value) is not int or value <= 0:
                raise InvalidInputError(f"{field_name} must be an exact positive integer")
        if command.actor_user_id != command.user_id:
            raise InvalidInputError("only the selected account owner can repair this row")
        if (
            type(command.idempotency_key) is not str
            or not command.idempotency_key.strip()
            or len(command.idempotency_key) > 128
        ):
            raise InvalidInputError("idempotency key must be nonempty and bounded")
        if not isinstance(database_alias, str) or not database_alias.strip():
            raise InvalidInputError("database alias must be explicit")
        if database_alias != database_alias.strip():
            raise InvalidInputError("database alias cannot contain surrounding whitespace")
