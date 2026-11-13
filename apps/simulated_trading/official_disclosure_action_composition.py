"""Verify simulated action stages against retained official SZSE source facts."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
    SzseDistributionTerms,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
    read_verified_szse_distribution,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionSourceQualificationVerifierProtocol,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    QualifiedCorporateActionTaxFacts,
)
from core.exceptions import DataFetchError, DataValidationError

_PARSER_ID = "szse_official_pdf.v1"


def _find_current_event_with_complete_lineage(
    request: CorporateActionStageRequest | QualifiedCorporateActionTaxFacts,
    facts: tuple[PersistedSecurityDisclosureEvent, ...],
    *,
    verification_at: datetime,
    qualified_at: datetime | None = None,
) -> SecurityDisclosureEvent | None:
    """Bind the exact current disclosure record to one unbranched logical source root."""

    if (
        type(request) not in {CorporateActionStageRequest, QualifiedCorporateActionTaxFacts}
        or type(facts) is not tuple
        or type(verification_at) is not datetime
        or verification_at.tzinfo is None
        or verification_at.utcoffset() is None
    ):
        return None
    known_cutoff = (
        request.qualified_at if isinstance(request, CorporateActionStageRequest) else qualified_at
    )
    if (
        type(known_cutoff) is not datetime
        or known_cutoff.tzinfo is None
        or known_cutoff.utcoffset() is None
        or known_cutoff > verification_at
    ):
        return None
    available: list[PersistedSecurityDisclosureEvent] = []
    by_identity: dict[tuple[str, str], PersistedSecurityDisclosureEvent] = {}
    for item in facts:
        if (
            type(item) is not PersistedSecurityDisclosureEvent
            or type(item.event) is not SecurityDisclosureEvent
            or item.event.asset_code != request.asset_code
            or item.event.exchange is not SecurityDisclosureExchange.SZSE
            or item.recorded_at > verification_at
            or item.event.first_seen_at > verification_at
        ):
            return None
        identity = (item.event.source_event_id, item.event.source_revision_id)
        if identity in by_identity:
            return None
        by_identity[identity] = item
        available.append(item)

    current_candidates = tuple(
        item
        for item in available
        if item.event.source_event_id == request.source_record_id
        and item.event.source_revision_id == request.source_revision_id
        and item.recorded_at <= known_cutoff
        and item.event.first_seen_at <= known_cutoff
    )
    if len(current_candidates) != 1:
        return None
    selected = current_candidates[0]
    selected_identity = (selected.event.source_event_id, selected.event.source_revision_id)

    child_counts: dict[tuple[str, str], int] = {}
    for item in available:
        parent_event_id = item.event.supersedes_source_event_id
        parent_revision_id = item.event.supersedes_source_revision_id
        if parent_event_id is None or parent_revision_id is None:
            continue
        parent_identity = (parent_event_id, parent_revision_id)
        child_counts[parent_identity] = child_counts.get(parent_identity, 0) + 1
    if child_counts.get(selected_identity, 0) != 0:
        return None

    visited: set[tuple[str, str]] = set()
    current = selected
    immediate_parent_revision: str | None = None
    while True:
        event = current.event
        identity = (event.source_event_id, event.source_revision_id)
        if identity in visited:
            return None
        visited.add(identity)
        parent_event_id = event.supersedes_source_event_id
        parent_revision_id = event.supersedes_source_revision_id
        if parent_event_id is None and parent_revision_id is None:
            if event.source_event_id != request.source_event_id:
                return None
            roots = tuple(
                item
                for item in available
                if item.event.source_event_id == request.source_event_id
                and item.event.supersedes_source_event_id is None
                and item.event.supersedes_source_revision_id is None
            )
            if len(roots) != 1 or roots[0] is not current:
                return None
            break
        if parent_event_id is None or parent_revision_id is None:
            return None
        parent_identity = (parent_event_id, parent_revision_id)
        if child_counts.get(parent_identity) != 1:
            return None
        parent = by_identity.get(parent_identity)
        if (
            parent is None
            or parent.recorded_at > known_cutoff
            or parent.event.first_seen_at > known_cutoff
            or parent.event.asset_code != event.asset_code
            or parent.event.exchange is not event.exchange
        ):
            return None
        if current is selected:
            immediate_parent_revision = parent.event.source_revision_id
        current = parent

    if (
        isinstance(request, CorporateActionStageRequest)
        and request.entry_kind
        in {
            CorporateActionEntryKind.REVERSAL,
            CorporateActionEntryKind.SUCCESSOR,
        }
        and (
            request.supersedes_revision_id is None
            or immediate_parent_revision != request.supersedes_revision_id
        )
    ):
        return None
    return selected.event


def szse_action_qualification_sha256(
    event: SecurityDisclosureEvent, terms: SzseDistributionTerms
) -> str:
    """Hash the exact retained event and parsed source terms for a stage request."""

    payload = {
        "parser": _PARSER_ID,
        "event_content_hash": event.content_hash,
        "record_date": terms.record_date.isoformat(),
        "ex_date": terms.ex_date.isoformat(),
        "payment_date": terms.payment_date.isoformat() if terms.payment_date else None,
        "cash_per_ten": str(terms.cash_per_ten) if terms.cash_per_ten else None,
        "shares_per_ten": str(terms.shares_per_ten) if terms.shares_per_ten else None,
        "tax_treatment": terms.tax_treatment,
    }
    if terms.share_delivery_date is not None or terms.share_sellable_date is not None:
        payload.update(
            {
                "share_delivery_date": (
                    terms.share_delivery_date.isoformat() if terms.share_delivery_date else None
                ),
                "share_sellable_date": (
                    terms.share_sellable_date.isoformat() if terms.share_sellable_date else None
                ),
            }
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class VerifiedSzseActionSourceQualifier(CorporateActionSourceQualificationVerifierProtocol):
    """Reject a stage unless its identity and economics match the retained PDF."""

    def __init__(self, *, body_store_root: Path, using: str = "default") -> None:
        """Bind an exact source body store and Data Center read alias."""

        self._body_store_root = body_store_root
        self._reader = make_security_disclosure_event_reader(using=using)

    def verify_tax_action(
        self, action: QualifiedCorporateActionTaxFacts, *, as_of: datetime
    ) -> bool:
        """Bind tax facts to the exact retained current event and parsed gross terms.

        The revision digest is the complete native event content hash; the
        payload digest separately binds original PDF bytes. This read confers
        neither tax-policy applicability nor account write authority.
        """

        if type(action) is not QualifiedCorporateActionTaxFacts:
            return False
        try:
            action.__post_init__()
            if (
                type(as_of) is not datetime
                or as_of.tzinfo is None
                or as_of.utcoffset() is None
                or action.source_namespace != "exchange_official_disclosure"
            ):
                return False
            verified_at = timezone.now()
            facts = self._reader.execute(
                SecurityDisclosureEventReadScope(
                    as_of=verified_at,
                    exchange=SecurityDisclosureExchange.SZSE,
                    asset_code=action.asset_code,
                )
            )
            event = _find_current_event_with_complete_lineage(
                action, facts, verification_at=verified_at, qualified_at=as_of
            )
            if (
                event is None
                or event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
                or event.event_type is not SecurityDisclosureEventType.CASH_DIVIDEND
                or action.source_revision_sha256 != event.content_hash
                or action.source_payload_sha256 != event.source_body_sha256
                or event.source_revision_id != f"sha256:{event.source_body_sha256}"
                or type(event.effective_at) is not type(action.effective_date)
                or event.effective_at != action.effective_date
            ):
                return False
            terms = read_verified_szse_distribution(event, body_store_root=self._body_store_root)
            if terms is None or terms.cash_per_ten is None:
                return False
            with localcontext() as context:
                context.prec = 80
                return (
                    terms.record_date == action.record_date
                    and terms.ex_date == action.effective_date
                    and terms.cash_per_ten / Decimal("10") == action.dividend_per_share
                )
        except (DataValidationError, DataFetchError, DatabaseError, ValueError):
            return False

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        """Verify official revision, dates, gross entitlement, and tax terms."""

        if request.stage is CorporateActionStage.TAX_WITHHOLDING:
            return False
        if (
            request.source_namespace != "exchange_official_disclosure"
            or request.qualifier_identity != _PARSER_ID
            or request.asset_code != request.security_id
            or not request.asset_code.endswith(".SZ")
        ):
            return False
        try:
            verification_at = timezone.now()
            if request.qualified_at > verification_at:
                return False
            if (
                request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION
                and request.stage_date
                > verification_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
            ):
                return False
            facts = self._reader.execute(
                SecurityDisclosureEventReadScope(
                    as_of=verification_at,
                    exchange=SecurityDisclosureExchange.SZSE,
                    asset_code=request.asset_code,
                )
            )
            event = _find_current_event_with_complete_lineage(
                request,
                facts,
                verification_at=verification_at,
            )
            if event is None:
                return False
            if (
                event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
                or event.source_body_sha256 != request.source_payload_sha256
                or event.source_revision_id != f"sha256:{event.source_body_sha256}"
                or event.first_seen_at != request.source_observed_at
                or type(event.effective_at) is not type(request.effective_date)
                or event.effective_at != request.effective_date
            ):
                return False
            terms = read_verified_szse_distribution(event, body_store_root=self._body_store_root)
            return terms is not None and self._matches_terms(request, event, terms)
        except (DataValidationError, DataFetchError, DatabaseError, ValueError):
            return False

    @staticmethod
    def _matches_terms(
        request: CorporateActionStageRequest,
        event: SecurityDisclosureEvent,
        terms: SzseDistributionTerms,
    ) -> bool:
        """Compare a stage with exact source terms, leaving tax basis to its owner."""

        if (
            request.record_date != terms.record_date
            or request.effective_date != terms.ex_date
            or request.qualification_sha256 != szse_action_qualification_sha256(event, terms)
        ):
            return False
        if request.action_kind is CorporateActionKind.CASH_DIVIDEND:
            if (
                event.event_type is not SecurityDisclosureEventType.CASH_DIVIDEND
                or terms.cash_per_ten is None
            ):
                return False
            if request.entry_kind is CorporateActionEntryKind.REVERSAL:
                return (
                    request.supersedes_revision_id is not None
                    and event.supersedes_source_revision_id == request.supersedes_revision_id
                    and request.tax_treatment is None
                )
            if request.tax_treatment != terms.tax_treatment:
                return False
            if request.stage is CorporateActionStage.CASH_ENTITLEMENT:
                if request.eligible_quantity is None or request.cash_amount is None:
                    return False
                gross = request.eligible_quantity * terms.cash_per_ten / Decimal("10")
                return gross == request.cash_amount
            if request.stage is CorporateActionStage.CASH_PAYMENT:
                return request.payment_date == terms.payment_date
            return False
        if request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION:
            if (
                event.event_type is not SecurityDisclosureEventType.STOCK_DIVIDEND
                or terms.shares_per_ten is None
            ):
                return False
            if request.entry_kind is CorporateActionEntryKind.REVERSAL:
                return (
                    request.supersedes_revision_id is not None
                    and event.supersedes_source_revision_id == request.supersedes_revision_id
                    and request.tax_treatment is None
                )
            if request.tax_treatment != terms.tax_treatment:
                return False
            if request.stage is CorporateActionStage.SHARE_ENTITLEMENT:
                return (
                    request.eligible_quantity is not None
                    and request.share_amount is not None
                    and request.odd_lot_policy == "whole_shares"
                    and Fraction(request.share_amount) * 10
                    == Fraction(request.eligible_quantity) * Fraction(terms.shares_per_ten)
                )
            if (
                terms.tax_treatment != "not_applicable"
                or type(terms.share_delivery_date) is not date
                or type(terms.share_sellable_date) is not date
                or terms.share_delivery_date < terms.ex_date
                or terms.share_sellable_date < terms.share_delivery_date
                or request.sellable_date != terms.share_sellable_date
                or request.odd_lot_policy != "whole_shares"
            ):
                return False
            if request.stage is CorporateActionStage.SHARE_DELIVERY:
                return request.stage_date == terms.share_delivery_date
            if request.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE:
                return request.stage_date >= terms.share_sellable_date
            return False
        return False
