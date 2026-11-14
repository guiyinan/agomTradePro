"""Read a complete, current owner corporate-action stage head without writes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import InvalidOperation
from zoneinfo import ZoneInfoNotFoundError

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, DatabaseError, transaction
from django.utils import timezone

from apps.simulated_trading.application.corporate_action_owner_posting_read import (
    OwnerCorporateActionActivePostingHead,
)
from apps.simulated_trading.corporate_action_owner_event_support import (
    _OFFICIAL_NAMESPACE,
    CorporateActionOwnerEventPreparationBlocked,
    _blocked,
    _read_owned_account,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    read_locked_owner_corporate_action_revision_history,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    read_owner_corporate_action_revision_head,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionInputValidationError,
    CorporateActionKind,
)
from core.exceptions import AgomTradeProException


def read_current_owner_corporate_action_active_postings(
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
    using: str = DEFAULT_DB_ALIAS,
) -> OwnerCorporateActionActivePostingHead:
    """Return current active entries after full account audit and Domain history replay.

    This continuation reader is used only when an event's raw posting rows include
    an older source revision or a correction entry. It verifies the complete owner
    account ledger before filtering the logical event, replays all correction rows,
    and requires the retained head to equal the selected current disclosure.
    """

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(owner_user_id) is not int
        or owner_user_id <= 0
        or type(canonical_account_id) is not str
        or not canonical_account_id
        or canonical_account_id != canonical_account_id.strip()
        or len(canonical_account_id) > 192
        or any(character.isspace() for character in canonical_account_id)
        or type(source_namespace) is not str
        or source_namespace != _OFFICIAL_NAMESPACE
        or type(source_event_id) is not str
        or not source_event_id
        or source_event_id != source_event_id.strip()
        or type(source_record_id) is not str
        or not source_record_id
        or source_record_id != source_record_id.strip()
        or type(source_revision_id) is not str
        or not source_revision_id
        or source_revision_id != source_revision_id.strip()
        or type(security_id) is not str
        or not security_id
        or type(asset_code) is not str
        or not asset_code
        or type(action_kind) is not CorporateActionKind
        or action_kind
        not in {CorporateActionKind.CASH_DIVIDEND, CorporateActionKind.SHARE_DISTRIBUTION}
        or type(record_date) is not date
        or type(effective_date) is not date
        or type(as_of) is not datetime
        or not timezone.is_aware(as_of)
        or type(using) is not str
        or not using.strip()
    ):
        _blocked(
            "a canonical owner and current-source scope is required for correction replay",
            "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED",
        )
    try:
        account = _read_owned_account(
            account_id=account_id,
            owner_user_id=owner_user_id,
            using=using,
            as_of=as_of,
        )
        if account is None:
            _blocked(
                "the current simulated account does not match the correction owner",
                "CORPORATE_ACTION_OWNER_ACCOUNT_SCOPE_INVALID",
            )
        with transaction.atomic(using=using):
            history = read_locked_owner_corporate_action_revision_history(
                account=account,
                canonical_account_id=canonical_account_id,
                source_namespace=source_namespace,
                source_event_id=source_event_id,
                as_of=as_of,
                using=using,
            )
            if not history:
                _blocked(
                    "the complete correction history is unavailable",
                    "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID",
                )
            retained_head_revision_id = history[-1].request.source_revision_id
            try:
                active_entries = read_owner_corporate_action_revision_head(
                    history,
                    expected_head_revision_id=retained_head_revision_id,
                )
            except (CorporateActionInputValidationError, TypeError, ValueError) as error:
                _blocked(
                    "the retained event correction history is incomplete or inconsistent",
                    "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID",
                    cause=error,
                )
            if retained_head_revision_id != source_revision_id:
                _blocked(
                    "the current disclosure is newer than the verified ledger head; correction is required",
                    "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED",
                )
            try:
                return OwnerCorporateActionActivePostingHead(
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                    canonical_account_id=canonical_account_id,
                    source_namespace=source_namespace,
                    source_event_id=source_event_id,
                    source_record_id=source_record_id,
                    source_revision_id=source_revision_id,
                    security_id=security_id,
                    asset_code=asset_code,
                    action_kind=action_kind,
                    record_date=record_date,
                    effective_date=effective_date,
                    active_entries=active_entries,
                )
            except (TypeError, ValueError) as error:
                _blocked(
                    "the active posting stages do not match the selected source facts",
                    "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID",
                    cause=error,
                )
    except CorporateActionOwnerEventPreparationBlocked:
        raise
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        DatabaseError,
        InvalidOperation,
        ObjectDoesNotExist,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        ZoneInfoNotFoundError,
    ) as error:
        _blocked(
            "complete retained account correction evidence is unavailable",
            "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID",
            cause=error,
        )


__all__ = ("read_current_owner_corporate_action_active_postings",)
