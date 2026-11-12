"""Persist prospective zero-origin anchors for newly created simulated accounts."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Q
from django.utils import timezone

from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    OwnershipHistoryFillSource,
    RecordDateOwnershipSourceRead,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    CorporateActionOwnershipEvidence,
    OwnershipAnchorKind,
    OwnershipFillFact,
    OwnershipFillSide,
    OwnershipOpeningAnchor,
    OwnershipReplayRequest,
    RecordDateOwnershipProof,
    replay_record_date_ownership,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_account_history import (
    validate_account_v4_fill_history,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_ownership_anchor_models import (
    SimulatedAccountOwnershipAnchorModel,
    _activate_ownership_anchor_uow,
    _claim_ownership_anchor_insert,
    simulated_account_ownership_anchor_sha256,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError

_ZERO_SHARES = Decimal("0.000000")
_ZERO_ORIGIN_ANCHOR_ID_PREFIX = "simulated-account-zero-origin.v1:"
_ACTIVE_ACCOUNT_CREATION_UOW: ContextVar[object | None] = ContextVar(
    "simulated_account_ownership_anchor_account_creation_uow",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _NewAccountClaim:
    """Private one-use proof that this service inserted the exact account row."""

    token: object
    account_id: int
    owner_user_id: int
    created_at: datetime
    using: str


_ACTIVE_NEW_ACCOUNT: ContextVar[_NewAccountClaim | None] = ContextVar(
    "simulated_account_ownership_anchor_new_account_claim",
    default=None,
)


@dataclass(frozen=True, slots=True)
class QualifiedExchangeTimezone:
    """Carry one exchange timezone bound to immutable Config Center evidence."""

    exchange: str
    timezone_name: str
    policy_id: str
    policy_sha256: str

    def __post_init__(self) -> None:
        """Reject an unqualified exchange, timezone, or policy digest."""

        if (
            type(self.exchange) is not str
            or not self.exchange
            or type(self.timezone_name) is not str
            or not self.timezone_name
            or type(self.policy_id) is not str
            or not self.policy_id
            or type(self.policy_sha256) is not str
            or len(self.policy_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.policy_sha256)
        ):
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE",
                "exchange timezone policy evidence is malformed",
            )
        try:
            ZoneInfo(self.timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE",
                "exchange timezone policy names an unknown timezone",
            ) from error


class ExchangeTimezonePolicyReader(Protocol):
    """Read the versioned exchange-local clock policy at one explicit cutoff."""

    def read_exchange_timezone_policy(
        self,
        *,
        exchange: str,
        as_of: datetime,
    ) -> QualifiedExchangeTimezone:
        """Return qualified timezone provenance or raise a typed block."""


@dataclass(frozen=True, slots=True)
class VerifiedSimulatedAccountOriginCalendar:
    """Bind the account origin and decision date to one exchange timezone policy."""

    origin_on: date
    decision_on: date
    timezone_policy: QualifiedExchangeTimezone
    as_of: datetime


def _ownership_block(code: str, message: str) -> SimulatedTradeExecutionBlocked:
    """Create a stable failure for an incomplete ownership evidence set."""

    return SimulatedTradeExecutionBlocked(message, code=code)


def _require_aware_datetime(value: object, label: str) -> datetime:
    """Require a literal aware datetime at the ORM evidence boundary."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _ownership_block(
            "CORPORATE_ACTION_OWNERSHIP_INPUT_INVALID",
            f"{label} must be timezone-aware",
        )
    return value


def _bind_security_asset_pair(
    *,
    security_id: object,
    asset_code: object,
    security_to_asset: dict[str, str],
    asset_to_security: dict[str, str],
) -> tuple[str, str]:
    """Reject retained account history that aliases instrument identities."""

    if (
        type(security_id) is not str
        or not security_id
        or type(asset_code) is not str
        or not asset_code
    ):
        raise _ownership_block(
            "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
            "retained ownership evidence has an incomplete instrument identity",
        )
    known_asset = security_to_asset.get(security_id)
    known_security = asset_to_security.get(asset_code)
    if (known_asset is not None and known_asset != asset_code) or (
        known_security is not None and known_security != security_id
    ):
        raise _ownership_block(
            "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
            "retained ownership evidence aliases a security and asset code",
        )
    security_to_asset[security_id] = asset_code
    asset_to_security[asset_code] = security_id
    return security_id, asset_code


def _corporate_action_evidence_sha256(row: CorporateActionPostingModel) -> str:
    """Bind the ownership fact to all three immutable posting/source digests."""

    digests = (
        row.request_payload_sha256,
        row.source_payload_sha256,
        row.qualification_sha256,
    )
    if any(
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in digests
    ):
        raise _ownership_block(
            "CORPORATE_ACTION_OWNERSHIP_ACTION_REVISION_INVALID",
            "company-action evidence digest is malformed",
        )
    payload: dict[str, object] = {
        "request_payload_sha256": digests[0],
        "source_payload_sha256": digests[1],
        "qualification_sha256": digests[2],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


class DjangoCorporateActionOwnershipHistoryRepository:
    """Read complete anchored ledger history and replay a record-date balance."""

    def __init__(
        self,
        *,
        exchange_timezone_policy_reader: ExchangeTimezonePolicyReader,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind one versioned timezone reader and explicit database alias."""

        if (
            not callable(
                getattr(exchange_timezone_policy_reader, "read_exchange_timezone_policy", None)
            )
            or type(using) is not str
            or not using
        ):
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_INPUT_INVALID",
                "ownership repository dependencies are invalid",
            )
        self._exchange_timezone_policy_reader = exchange_timezone_policy_reader
        self._using = using

    def read_verified_zero_origin_date(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> date:
        """Return the sealed account origin in a qualified exchange-local calendar."""

        return self.read_verified_zero_origin_calendar(
            account_id=account_id,
            owner_user_id=owner_user_id,
            exchange=exchange,
            as_of=as_of,
        ).origin_on

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedSimulatedAccountOriginCalendar:
        """Read one account origin and action date under the same qualified timezone."""

        cutoff = _require_aware_datetime(as_of, "as_of")
        if (
            type(account_id) is not int
            or account_id <= 0
            or type(owner_user_id) is not int
            or owner_user_id <= 0
            or type(exchange) is not str
            or not exchange
        ):
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_INPUT_INVALID",
                "zero-origin query scope is invalid",
            )

        with transaction.atomic(using=self._using):
            account = (
                SimulatedAccountModel._base_manager.using(self._using)
                .filter(
                    pk=account_id,
                    user_id=owner_user_id,
                    account_type="simulated",
                    created_at__lte=cutoff,
                )
                .first()
            )
            if account is None:
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
                    "simulated account is missing, future, or belongs to another owner",
                )
            anchor = (
                SimulatedAccountOwnershipAnchorModel._base_manager.using(self._using)
                .filter(account_id=account_id, created_at__lte=cutoff)
                .first()
            )
            if anchor is None or not _anchor_matches_account(existing=anchor, account=account):
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE",
                    "simulated account lacks a cutoff-known immutable zero-origin anchor",
                )
            origin_at = _require_aware_datetime(account.created_at, "account.created_at")

        policy = self._exchange_timezone_policy_reader.read_exchange_timezone_policy(
            exchange=exchange, as_of=cutoff
        )
        if type(policy) is not QualifiedExchangeTimezone or policy.exchange != exchange:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE",
                "exchange timezone policy does not match the account origin scope",
            )
        exchange_timezone = ZoneInfo(policy.timezone_name)
        return VerifiedSimulatedAccountOriginCalendar(
            origin_on=origin_at.astimezone(exchange_timezone).date(),
            decision_on=cutoff.astimezone(exchange_timezone).date(),
            timezone_policy=policy,
            as_of=cutoff,
        )

    def read_record_date_ownership_proof(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        evidence_cutoff_at: datetime,
    ) -> RecordDateOwnershipProof:
        """Read-only replay of a retained account history through one record date.

        This method accepts the requested account and instrument scope, never
        caller-supplied fills or action rows. It authenticates the prospective
        zero-origin anchor, validates every retained V4 receipt prefix, proves
        every account Trade has exactly one receipt, checks all company-action
        account revisions, derives exchange from a known target V4 fill proof,
        and delegates the exact arithmetic to the pure replay domain.
        """

        return self.read_record_date_ownership_source_history(
            account_id=account_id,
            owner_user_id=owner_user_id,
            security_id=security_id,
            asset_code=asset_code,
            record_date=record_date,
            evidence_cutoff_at=evidence_cutoff_at,
        ).proof

    @property
    def database_alias(self) -> str:
        """Return the alias for the same-pass account, receipt, and action reads."""

        return self._using

    def read_record_date_ownership_source_history(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        evidence_cutoff_at: datetime,
    ) -> RecordDateOwnershipSourceRead:
        """Return the proof and exact decoded V4 source events from one ledger replay."""

        cutoff = _require_aware_datetime(evidence_cutoff_at, "evidence_cutoff_at")
        if (
            type(account_id) is not int
            or account_id <= 0
            or type(owner_user_id) is not int
            or owner_user_id <= 0
            or type(security_id) is not str
            or not security_id
            or type(asset_code) is not str
            or not asset_code
            or type(record_date) is not date
        ):
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_INPUT_INVALID",
                "record-date ownership query scope is invalid",
            )

        with transaction.atomic(using=self._using):
            account = (
                SimulatedAccountModel._base_manager.using(self._using)
                .select_for_update()
                .filter(
                    pk=account_id,
                    user_id=owner_user_id,
                    account_type="simulated",
                )
                .first()
            )
            if account is None:
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
                    "simulated account is missing or belongs to another owner",
                )
            if (
                type(account.pk) is not int
                or account.pk <= 0
                or type(account.user_id) is not int
                or account.user_id != owner_user_id
            ):
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
                    "simulated account owner identity is incomplete",
                )

            anchor_row = (
                SimulatedAccountOwnershipAnchorModel._base_manager.using(self._using)
                .select_for_update()
                .filter(account_id=account_id)
                .first()
            )
            if anchor_row is None or not _anchor_matches_account(
                existing=anchor_row,
                account=account,
            ):
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE",
                    "simulated account lacks a valid immutable zero-origin anchor",
                )
            anchor = OwnershipOpeningAnchor(
                account_id=account.pk,
                owner_user_id=account.user_id,
                anchor_id=anchor_row.anchor_id,
                anchor_kind=OwnershipAnchorKind(anchor_row.anchor_kind),
                quantity=anchor_row.quantity,
                effective_at=anchor_row.account_created_at,
                observed_at=anchor_row.created_at,
                evidence_sha256=anchor_row.evidence_sha256,
            )

            validate_account_v4_fill_history(
                account=account,
                intent=None,
                using=self._using,
            )
            source_fills, exchange, instrument_pairs = self._read_complete_account_fill_history(
                account=account,
                security_id=security_id,
                asset_code=asset_code,
                evidence_cutoff_at=cutoff,
            )
            actions = self._read_complete_action_history(
                account=account,
                security_id=security_id,
                asset_code=asset_code,
                known_instrument_pairs=instrument_pairs,
            )
            policy = self._exchange_timezone_policy_reader.read_exchange_timezone_policy(
                exchange=exchange,
                as_of=cutoff,
            )
            if type(policy) is not QualifiedExchangeTimezone or policy.exchange != exchange:
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE",
                    "exchange timezone evidence is not bound to the instrument exchange",
                )
            try:
                exchange_timezone = ZoneInfo(policy.timezone_name)
            except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_POLICY_UNAVAILABLE",
                    "qualified exchange timezone is unavailable",
                ) from error
            source_fills = tuple(
                replace(
                    source,
                    ownership_fill=replace(
                        source.ownership_fill,
                        execution_date=source.ownership_fill.occurred_at.astimezone(
                            exchange_timezone
                        ).date(),
                    ),
                )
                for source in source_fills
            )
            fills = tuple(source.ownership_fill for source in source_fills)
            record_date_end_exclusive = datetime.combine(
                record_date + timedelta(days=1),
                time.min,
                tzinfo=exchange_timezone,
            )
            proof = replay_record_date_ownership(
                OwnershipReplayRequest(
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                    security_id=security_id,
                    asset_code=asset_code,
                    record_date=record_date,
                    record_date_end_exclusive=record_date_end_exclusive,
                    exchange=exchange,
                    exchange_timezone_name=policy.timezone_name,
                    cutoff_policy_id=policy.policy_id,
                    cutoff_policy_sha256=policy.policy_sha256,
                    evidence_cutoff_at=cutoff,
                    opening_anchor=anchor,
                    fills=fills,
                    corporate_actions=actions,
                )
            )
            return RecordDateOwnershipSourceRead(
                proof=proof,
                opening_anchor=anchor,
                source_fills=source_fills,
                corporate_action_evidence=actions,
            )

    def _read_complete_account_fill_history(
        self,
        *,
        account: SimulatedAccountModel,
        security_id: str,
        asset_code: str,
        evidence_cutoff_at: datetime,
    ) -> tuple[tuple[OwnershipHistoryFillSource, ...], str, tuple[tuple[str, str], ...]]:
        """Return typed fills after proving every retained Trade is receipt-backed."""

        using = self._using
        owner_user_id = account.user_id
        if type(owner_user_id) is not int or owner_user_id <= 0:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
                "simulated account owner identity is incomplete",
            )
        trades = tuple(
            SimulatedTradeModel._base_manager.using(using)
            .select_for_update()
            .filter(account_id=account.pk)
            .order_by("pk")
        )
        trade_ids = {trade.pk for trade in trades if type(trade.pk) is int and trade.pk > 0}
        if len(trade_ids) != len(trades):
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED",
                "account contains a Trade with an invalid primary key",
            )

        receipt_rows = tuple(
            SimulatedOrderFillReceiptModel._base_manager.using(using)
            .select_for_update()
            .select_related("reservation", "trade")
            .filter(Q(reservation__account_id=account.pk) | Q(trade__account_id=account.pk))
            .order_by("pk")
        )
        receipt_trade_ids: set[int] = set()
        receipt_reservation_ids: set[int] = set()
        for receipt in receipt_rows:
            if (
                receipt.reservation.account_id != account.pk
                or receipt.reservation.owner_user_id != owner_user_id
                or receipt.trade.account_id != account.pk
                or receipt.trade_id in receipt_trade_ids
                or type(receipt.reservation_id) is not int
                or receipt.reservation_id <= 0
                or type(receipt.trade_id) is not int
                or receipt.trade_id <= 0
            ):
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED",
                    "account contains a crossed or duplicate V4 receipt locator",
                )
            receipt_trade_ids.add(receipt.trade_id)
            receipt_reservation_ids.add(receipt.reservation_id)
        if receipt_trade_ids != trade_ids or len(receipt_rows) != len(trade_ids):
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED",
                "every retained account Trade must have exactly one complete V4 receipt",
            )
        if not receipt_rows:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_EXCHANGE_UNAVAILABLE",
                "exchange identity cannot be derived without a retained V4 fill proof",
            )

        reservations = tuple(
            SimulatedOrderReservationModel._base_manager.using(using)
            .select_for_update()
            .filter(
                pk__in=tuple(sorted(receipt_reservation_ids)),
                account_id=account.pk,
                owner_user_id=owner_user_id,
            )
            .order_by("pk")
        )
        if {row.pk for row in reservations} != receipt_reservation_ids:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED",
                "V4 fill receipts reference a missing or cross-owner reservation",
            )

        security_to_asset: dict[str, str] = {}
        asset_to_security: dict[str, str] = {}
        source_fills: list[OwnershipHistoryFillSource] = []
        known_exchange_by_instrument: dict[tuple[str, str], set[str]] = {}
        for reservation in reservations:
            chain = _locked_fill_chain(reservation_row=reservation, using=using)
            for receipt, decoded in chain.rows:
                event = decoded.event
                pair = _bind_security_asset_pair(
                    security_id=event.security_id,
                    asset_code=event.asset_code,
                    security_to_asset=security_to_asset,
                    asset_to_security=asset_to_security,
                )
                exchange_value = decoded.proof.settlement_exchange
                if type(exchange_value) is not str or not exchange_value:
                    raise _ownership_block(
                        "CORPORATE_ACTION_OWNERSHIP_EXCHANGE_UNAVAILABLE",
                        "V4 fill proof lacks an exact exchange identity",
                    )
                recorded_at = max(
                    (
                        _require_aware_datetime(event.recorded_at, "fill.recorded_at"),
                        _require_aware_datetime(receipt.created_at, "receipt.created_at"),
                        _require_aware_datetime(receipt.trade.created_at, "trade.created_at"),
                    ),
                    key=lambda value: value.astimezone(UTC),
                )
                occurred_at = _require_aware_datetime(event.occurred_at, "fill.occurred_at")
                if recorded_at <= evidence_cutoff_at and occurred_at <= evidence_cutoff_at:
                    known_exchange_by_instrument.setdefault(pair, set()).add(exchange_value)
                try:
                    side = OwnershipFillSide(event.side.value)
                except (AttributeError, TypeError, ValueError) as error:
                    raise _ownership_block(
                        "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED",
                        "V4 fill receipt has an unknown trade side",
                    ) from error
                if pair == (security_id, asset_code):
                    # The record-date boundary policy is loaded after an exact
                    # exchange is selected; the local execution date is bound
                    # immediately before invoking the pure Domain replay.
                    source_fills.append(
                        OwnershipHistoryFillSource(
                            ownership_fill=OwnershipFillFact(
                                account_id=account.pk,
                                owner_user_id=owner_user_id,
                                security_id=event.security_id,
                                asset_code=event.asset_code,
                                trade_id=decoded.trade_id,
                                reservation_id=decoded.reservation_id,
                                fill_sequence=decoded.fill_sequence,
                                side=side,
                                quantity=decoded.economics.quantity,
                                execution_date=occurred_at.date(),
                                occurred_at=occurred_at,
                                recorded_at=recorded_at,
                                binding_version=receipt.trade.settlement_plan_binding_version,
                                receipt_version=receipt.receipt_version,
                                receipt_sha256=decoded.receipt_hash,
                            ),
                            source_event=event,
                            order_idempotency_key=reservation.idempotency_key,
                        )
                    )

        target_pair = (security_id, asset_code)
        target_exchanges = known_exchange_by_instrument.get(target_pair, set())
        if not target_exchanges:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_EXCHANGE_UNAVAILABLE",
                "no cutoff-known V4 fill proves the target exchange identity",
            )
        if len(target_exchanges) != 1:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
                "target V4 fills disagree on the sealed exchange identity",
            )
        instrument_pairs = tuple(sorted(security_to_asset.items()))
        return tuple(source_fills), next(iter(target_exchanges)), instrument_pairs

    def _read_complete_action_history(
        self,
        *,
        account: SimulatedAccountModel,
        security_id: str,
        asset_code: str,
        known_instrument_pairs: tuple[tuple[str, str], ...],
    ) -> tuple[CorporateActionOwnershipEvidence, ...]:
        """Read every immutable account-action revision and retain target stages."""

        owner_user_id = account.user_id
        if type(owner_user_id) is not int or owner_user_id <= 0:
            raise _ownership_block(
                "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID",
                "simulated account owner identity is incomplete",
            )
        rows = tuple(
            CorporateActionPostingModel._base_manager.using(self._using)
            .select_for_update()
            .filter(account_id=account.pk)
            .order_by("account_revision", "pk")
        )
        for expected_revision, row in enumerate(rows, start=1):
            if (
                row.account_id != account.pk
                or row.account_revision != expected_revision
                or type(row.pk) is not int
                or row.pk <= 0
            ):
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_ACTION_REVISION_INVALID",
                    "company-action account revision history is incomplete",
                )

        security_to_asset = dict(known_instrument_pairs)
        asset_to_security = {asset: security for security, asset in known_instrument_pairs}
        evidence: list[CorporateActionOwnershipEvidence] = []
        for row in rows:
            pair = _bind_security_asset_pair(
                security_id=row.security_id,
                asset_code=row.asset_code,
                security_to_asset=security_to_asset,
                asset_to_security=asset_to_security,
            )
            if pair != (security_id, asset_code):
                continue
            try:
                evidence.append(
                    CorporateActionOwnershipEvidence(
                        account_id=account.pk,
                        owner_user_id=owner_user_id,
                        security_id=row.security_id,
                        asset_code=row.asset_code,
                        account_revision=row.account_revision,
                        entry_id=row.pk,
                        source_event_id=row.source_event_id,
                        source_revision_id=row.source_revision_id,
                        supersedes_revision_id=row.supersedes_revision_id,
                        action_kind=CorporateActionKind(row.action_kind),
                        stage_key=row.stage_key,
                        stage=CorporateActionStage(row.stage),
                        entry_kind=CorporateActionEntryKind(row.entry_kind),
                        stage_date=row.stage_date,
                        posted_at=row.posted_at,
                        recorded_at=max(
                            (
                                _require_aware_datetime(
                                    row.source_observed_at, "action.source_observed_at"
                                ),
                                _require_aware_datetime(row.qualified_at, "action.qualified_at"),
                                _require_aware_datetime(row.posted_at, "action.posted_at"),
                                _require_aware_datetime(row.created_at, "action.created_at"),
                            ),
                            key=lambda value: value.astimezone(UTC),
                        ),
                        share_delta=row.share_delta,
                        share_receivable_delta=row.share_receivable_delta,
                        reversal_of_entry_id=row.reversal_of_id,
                        evidence_sha256=_corporate_action_evidence_sha256(row),
                    )
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise _ownership_block(
                    "CORPORATE_ACTION_OWNERSHIP_ACTION_REVISION_INVALID",
                    "company-action row cannot be represented as typed ownership evidence",
                ) from error
        return tuple(evidence)


@contextmanager
def _activate_new_account_creation_uow(*, using: str) -> Iterator[object]:
    """Activate a private non-nestable capability for one account insertion."""

    if _ACTIVE_ACCOUNT_CREATION_UOW.get() is not None or not using:
        raise BusinessLogicError(
            "模拟账户创建 UOW 无效或重复",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_UOW_INVALID",
        )
    token = object()
    reset = _ACTIVE_ACCOUNT_CREATION_UOW.set(token)
    try:
        yield token
    finally:
        _ACTIVE_ACCOUNT_CREATION_UOW.reset(reset)


@contextmanager
def _claim_new_account_for_anchor(
    *,
    token: object,
    account: SimulatedAccountModel,
    using: str,
) -> Iterator[None]:
    """Bind anchor insertion to the exact row just inserted by this UOW."""

    if (
        _ACTIVE_ACCOUNT_CREATION_UOW.get() is not token
        or _ACTIVE_NEW_ACCOUNT.get() is not None
        or type(account.pk) is not int
        or account.pk <= 0
        or type(account.user_id) is not int
        or account.user_id <= 0
        or account.account_type != "simulated"
        or account.created_at is None
        or not using
    ):
        raise BusinessLogicError(
            "模拟账户创建声明与权属锚不匹配",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_UOW_INVALID",
        )
    claim = _NewAccountClaim(
        token=token,
        account_id=account.pk,
        owner_user_id=account.user_id,
        created_at=account.created_at,
        using=using,
    )
    reset = _ACTIVE_NEW_ACCOUNT.set(claim)
    try:
        yield
    finally:
        _ACTIVE_NEW_ACCOUNT.reset(reset)


def create_simulated_account_with_zero_origin_anchor(
    *,
    user: Any,
    account_name: str,
    initial_capital: Decimal | int | float | str,
    current_cash: Decimal | int | float | str | None = None,
    current_market_value: Decimal | int | float | str = Decimal("0.00"),
    total_value: Decimal | int | float | str | None = None,
    auto_trading_enabled: bool = True,
    using: str = DEFAULT_DB_ALIAS,
) -> SimulatedAccountModel:
    """Create a fresh simulated account and its zero-origin anchor atomically.

    This API is intentionally for account insertion, not existing-account
    repair. Both account-creation entry points call it only after their
    account-existence decision; any anchor failure rolls back the new account.
    """

    user_id = getattr(user, "pk", None)
    if (
        type(user_id) is not int
        or user_id <= 0
        or type(account_name) is not str
        or not account_name
        or account_name != account_name.strip()
        or type(auto_trading_enabled) is not bool
        or type(using) is not str
        or not using
        or any(
            type(value) not in (Decimal, int, float, str)
            for value in (initial_capital, current_market_value)
        )
        or (current_cash is not None and type(current_cash) not in (Decimal, int, float, str))
        or (total_value is not None and type(total_value) not in (Decimal, int, float, str))
    ):
        raise BusinessLogicError(
            "新模拟账户权属锚输入无效",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_INPUT_INVALID",
        )
    effective_cash = initial_capital if current_cash is None else current_cash
    effective_total_value = initial_capital if total_value is None else total_value
    with transaction.atomic(using=using):
        with _activate_new_account_creation_uow(using=using) as token:
            account = SimulatedAccountModel._default_manager.using(using).create(
                user=user,
                account_name=account_name,
                account_type="simulated",
                initial_capital=initial_capital,
                current_cash=effective_cash,
                cash_known=True,
                cash_reconciliation_status="simulated_ledger",
                current_market_value=current_market_value,
                total_value=effective_total_value,
                auto_trading_enabled=auto_trading_enabled,
            )
            with _claim_new_account_for_anchor(token=token, account=account, using=using):
                _create_zero_origin_anchor_for_inserted_account(account=account, using=using)
            return account


def _create_zero_origin_anchor_for_inserted_account(
    *,
    account: SimulatedAccountModel,
    using: str,
) -> SimulatedAccountOwnershipAnchorModel:
    """Write exactly one immutable zero anchor after a fresh account insert."""

    if (
        type(account) is not SimulatedAccountModel
        or type(account.pk) is not int
        or account.pk <= 0
        or account.account_type != "simulated"
        or type(account.user_id) is not int
        or account.user_id <= 0
        or account.created_at is None
        or account.created_at.tzinfo is None
        or account.created_at.utcoffset() is None
        or type(using) is not str
        or not using
    ):
        raise BusinessLogicError(
            "新模拟账户不能证明所有者与创建时钟",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE",
        )
    claim = _ACTIVE_NEW_ACCOUNT.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_ACCOUNT_CREATION_UOW.get()
        or claim.account_id != account.pk
        or claim.owner_user_id != account.user_id
        or claim.created_at != account.created_at
        or claim.using != using
    ):
        raise BusinessLogicError(
            "不能为已存在模拟账户补造零起点权属锚",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_BACKFILL_BLOCKED",
        )

    locked_account = (
        SimulatedAccountModel._base_manager.using(using)
        .select_for_update()
        .filter(pk=account.pk)
        .first()
    )
    if (
        locked_account is None
        or locked_account.user_id != account.user_id
        or locked_account.account_type != "simulated"
        or locked_account.created_at != account.created_at
    ):
        raise BusinessLogicError(
            "新模拟账户的已保存身份与创建记录不匹配",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE",
        )

    has_prior_history = (
        PositionModel._base_manager.using(using).filter(account_id=locked_account.pk).exists()
        or SimulatedTradeModel._base_manager.using(using)
        .filter(account_id=locked_account.pk)
        .exists()
        or SimulatedOrderReservationModel._base_manager.using(using)
        .filter(account_id=locked_account.pk)
        .exists()
        or CorporateActionPostingModel._base_manager.using(using)
        .filter(account_id=locked_account.pk)
        .exists()
    )
    if has_prior_history:
        raise BusinessLogicError(
            "模拟账户创建时已存在权属历史，不能声明零起点",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_HISTORY_CONFLICT",
        )

    existing = (
        SimulatedAccountOwnershipAnchorModel._base_manager.using(using)
        .filter(account_id=account.pk)
        .first()
    )
    if existing is not None:
        if not _anchor_matches_account(existing=existing, account=locked_account):
            raise BusinessLogicError(
                "模拟账户已有的零起点锚与账户身份不匹配",
                code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_CONFLICT",
            )
        return existing

    observed_at = timezone.now()
    if observed_at < locked_account.created_at:
        raise BusinessLogicError(
            "账户锚观察时钟早于账户创建时钟",
            code="CORPORATE_ACTION_OWNERSHIP_ANCHOR_CLOCK_INVALID",
        )
    anchor_id = f"{_ZERO_ORIGIN_ANCHOR_ID_PREFIX}{locked_account.pk}"
    evidence_sha256 = simulated_account_ownership_anchor_sha256(
        account_id=locked_account.pk,
        owner_user_id=locked_account.user_id,
        anchor_id=anchor_id,
        account_created_at=locked_account.created_at,
        observed_at=observed_at,
        anchor_kind=SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN,
        quantity=_ZERO_SHARES,
    )
    values: dict[str, object] = {
        "account_id": locked_account.pk,
        "owner_user_id": locked_account.user_id,
        "anchor_id": anchor_id,
        "anchor_kind": SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN,
        "quantity": _ZERO_SHARES,
        "account_created_at": locked_account.created_at,
        "evidence_sha256": evidence_sha256,
        "created_at": observed_at,
    }
    with _activate_ownership_anchor_uow() as token:
        with _claim_ownership_anchor_insert(
            token=token,
            model_type=SimulatedAccountOwnershipAnchorModel,
            expected_values=values,
        ):
            return SimulatedAccountOwnershipAnchorModel._default_manager.using(using).create(
                account_id=locked_account.pk,
                owner_user_id=locked_account.user_id,
                anchor_id=anchor_id,
                anchor_kind=SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN,
                quantity=_ZERO_SHARES,
                account_created_at=locked_account.created_at,
                evidence_sha256=evidence_sha256,
                created_at=observed_at,
            )


def _anchor_matches_account(
    *,
    existing: SimulatedAccountOwnershipAnchorModel,
    account: SimulatedAccountModel,
) -> bool:
    """Verify one existing row is the exact zero-origin anchor for its account."""

    expected_id = f"{_ZERO_ORIGIN_ANCHOR_ID_PREFIX}{account.pk}"
    if (
        existing.account_id != account.pk
        or existing.owner_user_id != account.user_id
        or existing.anchor_id != expected_id
        or existing.anchor_kind != SimulatedAccountOwnershipAnchorModel.ZERO_ORIGIN
        or existing.quantity != _ZERO_SHARES
        or existing.account_created_at != account.created_at
        or existing.created_at < existing.account_created_at
    ):
        return False
    return existing.evidence_sha256 == simulated_account_ownership_anchor_sha256(
        account_id=existing.account_id,
        owner_user_id=existing.owner_user_id,
        anchor_id=existing.anchor_id,
        account_created_at=existing.account_created_at,
        observed_at=existing.created_at,
        anchor_kind=existing.anchor_kind,
        quantity=existing.quantity,
    )


__all__: tuple[str, ...] = (
    "DjangoCorporateActionOwnershipHistoryRepository",
    "ExchangeTimezonePolicyReader",
    "QualifiedExchangeTimezone",
    "VerifiedSimulatedAccountOriginCalendar",
    "create_simulated_account_with_zero_origin_anchor",
)
