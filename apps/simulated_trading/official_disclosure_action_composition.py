"""Verify simulated action stages against retained official SZSE source facts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from django.db import DatabaseError

from apps.data_center.domain.security_disclosure_event import (
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
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from core.exceptions import DataFetchError, DataValidationError

_PARSER_ID = "szse_official_pdf.v1"


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
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class VerifiedSzseActionSourceQualifier(CorporateActionSourceQualificationVerifierProtocol):
    """Reject a stage unless its identity and economics match the retained PDF."""

    def __init__(self, *, body_store_root: Path, using: str = "default") -> None:
        """Bind an exact source body store and Data Center read alias."""

        self._body_store_root = body_store_root
        self._reader = make_security_disclosure_event_reader(using=using)

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        """Verify official revision, dates, gross entitlement, and tax terms."""

        if (
            request.source_namespace != "exchange_official_disclosure"
            or request.qualifier_identity != _PARSER_ID
            or request.asset_code != request.security_id
            or not request.asset_code.endswith(".SZ")
            or request.source_record_id != request.source_event_id
        ):
            return False
        try:
            facts = self._reader.execute(
                SecurityDisclosureEventReadScope(
                    as_of=request.qualified_at,
                    exchange=SecurityDisclosureExchange.SZSE,
                    asset_code=request.asset_code,
                )
            )
            matched = tuple(
                item.event
                for item in facts
                if item.recorded_at <= request.qualified_at
                and item.event.source_event_id == request.source_event_id
                and item.event.source_revision_id == request.source_revision_id
            )
            if len(matched) != 1:
                return False
            event = matched[0]
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
            or request.tax_treatment != terms.tax_treatment
            or request.tax_rule_id != f"szse:{event.source_event_id}"
            or request.tax_rule_sha256 != event.source_body_sha256
        ):
            return False
        if request.action_kind is CorporateActionKind.CASH_DIVIDEND:
            if (
                event.event_type is not SecurityDisclosureEventType.CASH_DIVIDEND
                or terms.cash_per_ten is None
            ):
                return False
            if request.stage is CorporateActionStage.CASH_ENTITLEMENT:
                if request.eligible_quantity is None or request.cash_amount is None:
                    return False
                gross = request.eligible_quantity * terms.cash_per_ten / Decimal("10")
                return gross == request.cash_amount
            if request.stage is CorporateActionStage.CASH_PAYMENT:
                return request.payment_date == terms.payment_date
            return request.stage is CorporateActionStage.TAX_WITHHOLDING
        if request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION:
            if (
                event.event_type is not SecurityDisclosureEventType.STOCK_DIVIDEND
                or terms.shares_per_ten is None
            ):
                return False
            if request.stage is CorporateActionStage.SHARE_ENTITLEMENT:
                return (
                    request.eligible_quantity is not None
                    and request.share_amount
                    == request.eligible_quantity * terms.shares_per_ten / Decimal("10")
                )
            return request.stage in (
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            )
        return False
