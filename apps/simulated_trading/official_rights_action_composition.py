"""Qualify an explicit unexercised-rights record from one retained official result."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.domain.szse_rights_terms import SzseRightsCompletionTerms
from apps.data_center.security_disclosure_body_composition import (
    read_verified_szse_rights_completion,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    _find_current_event_with_complete_lineage,
)
from core.exceptions import AgomTradeProException

SZSE_RIGHTS_QUALIFIER_ID = "szse_official_rights_pdf.v1"


def szse_rights_terms_sha256(terms: SzseRightsCompletionTerms) -> str:
    """Bind announced and actual terms separately without inventing holder allocations."""
    terms.__post_init__()
    payload = {
        "schema": "szse_rights_completion_terms.v1",
        "source_security_code": terms.source_security_code,
        "record_date": terms.record_date.isoformat(),
        "subscription_end_date": terms.subscription_end_date.isoformat(),
        "offered_rights_per_ten": str(terms.offered_rights_per_ten),
        "subscription_price_cny_per_share": str(terms.subscription_price_cny_per_share),
        "actual_aggregate_rights_per_ten": str(terms.actual_aggregate_rights_per_ten),
        "actual_ex_rights_date": terms.actual_ex_rights_date.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def szse_rights_qualification_sha256(
    event: SecurityDisclosureEvent,
    terms: SzseRightsCompletionTerms,
) -> str:
    """Bind the exact retained source manifest and successful-result terms."""
    payload = {
        "parser": SZSE_RIGHTS_QUALIFIER_ID,
        "event_content_hash": event.content_hash,
        "rights_terms_sha256": szse_rights_terms_sha256(terms),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class VerifiedSzseRightsSourceQualifier:
    """Prove only source facts for a zero-effect no-exercise entry, never permission."""

    def __init__(
        self,
        *,
        body_store_root: Path,
        runtime_environment: str,
        using: str = "default",
    ) -> None:
        """Bind public retained-body/event and configured account-calendar readers."""
        if not isinstance(body_store_root, Path) or not runtime_environment or not using:
            raise ValueError("rights source readers require explicit store, environment and alias")
        self._body_store_root = body_store_root
        self._reader = make_security_disclosure_event_reader(using=using)
        self._calendar_reader = build_corporate_action_ownership_history_repository(
            runtime_environment=runtime_environment,
            using=using,
        )

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        """Require current original result, reached dates and exact no-exercise identity.

        Current complete-window evidence, historical account ownership and the
        independent V3 rights capability remain separate mandatory consumers.
        This method cannot qualify subscriptions, cash payments or new shares.
        """
        if type(request) is not CorporateActionStageRequest:
            return False
        try:
            request.__post_init__()
            now = timezone.now()
            if (
                request.action_kind is not CorporateActionKind.RIGHTS_ISSUE
                or request.stage is not CorporateActionStage.RIGHTS_NOT_EXERCISED
                or request.entry_kind is not CorporateActionEntryKind.NO_EFFECT
                or request.source_namespace != "exchange_official_disclosure"
                or request.qualifier_identity != SZSE_RIGHTS_QUALIFIER_ID
                or request.security_id != request.asset_code
                or not request.asset_code.endswith(".SZ")
                or request.qualified_at > now
                or request.posted_at > now
            ):
                return False
            records = self._reader.execute(
                SecurityDisclosureEventReadScope(
                    as_of=now,
                    exchange=SecurityDisclosureExchange.SZSE,
                    asset_code=request.asset_code,
                )
            )
            event = _find_current_event_with_complete_lineage(request, records, verification_at=now)
            if (
                event is None
                or event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
                or event.event_type is not SecurityDisclosureEventType.RIGHTS_ISSUE
                or event.source_body_sha256 != request.source_payload_sha256
                or event.source_revision_id != f"sha256:{event.source_body_sha256}"
                or event.first_seen_at != request.source_observed_at
                or type(event.effective_at) is not date
                or event.effective_at != request.effective_date
            ):
                return False
            terms = read_verified_szse_rights_completion(
                event, body_store_root=self._body_store_root
            )
            if terms is None:
                return False
            calendar = self._calendar_reader.read_verified_zero_origin_calendar(
                account_id=request.account_id,
                owner_user_id=request.owner_user_id,
                exchange="SZSE",
                as_of=now,
            )
            if (
                calendar.as_of != now
                or calendar.timezone_policy.exchange != "SZSE"
                or calendar.decision_on
                != now.astimezone(ZoneInfo(calendar.timezone_policy.timezone_name)).date()
                or calendar.origin_on > calendar.decision_on
                or timezone.now() < now
            ):
                return False
            return (
                terms.source_security_code == event.source_security_code
                and terms.record_date == request.record_date
                and terms.actual_ex_rights_date == request.effective_date
                and terms.record_date
                <= terms.subscription_end_date
                < terms.actual_ex_rights_date
                <= request.stage_date
                <= calendar.decision_on
                and terms.actual_aggregate_rights_per_ten <= terms.offered_rights_per_ten
                and request.rights_terms_sha256 == szse_rights_terms_sha256(terms)
                and request.qualification_sha256 == szse_rights_qualification_sha256(event, terms)
            )
        except (
            AgomTradeProException,
            DatabaseError,
            OSError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            return False
