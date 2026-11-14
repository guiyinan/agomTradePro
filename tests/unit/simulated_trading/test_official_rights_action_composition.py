"""Rights no-exercise source proof stays separate from financial permission."""

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.domain.szse_rights_terms import SzseRightsCompletionTerms
from apps.simulated_trading import official_rights_action_composition as composition
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)

_NOW = datetime(2026, 11, 13, 4, tzinfo=UTC)
_SEEN = _NOW - timedelta(minutes=2)


def _source() -> tuple[SecurityDisclosureEvent, SzseRightsCompletionTerms]:
    """Build explicitly synthetic retained-source boundaries, without official claims."""
    body = b"%PDF-1.4\nsynthetic result\n%%EOF"
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="300176.SZ",
        source_security_code="300176",
        source_event_id="cb0747e3-9f77-42a0-b221-ed1e5d3316ba",
        source_revision_id="sha256:" + hashlib.sha256(body).hexdigest(),
        raw_event_type="配股发行结果公告",
        event_type=SecurityDisclosureEventType.RIGHTS_ISSUE,
        source_url="https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-08-21/cb0747e3-9f77-42a0-b221-ed1e5d3316ba.PDF",
        source_document_body=body,
        first_seen_at=_SEEN,
        effective_at=date(2026, 8, 21),
    )
    terms = SzseRightsCompletionTerms(
        source_security_code="300176",
        record_date=date(2026, 8, 12),
        subscription_end_date=date(2026, 8, 19),
        offered_rights_per_ten=Decimal("4"),
        subscription_price_cny_per_share=Decimal("3.36"),
        actual_aggregate_rights_per_ten=Decimal("3.722702"),
        actual_ex_rights_date=date(2026, 8, 21),
    )
    return event, terms


def _request(
    event: SecurityDisclosureEvent, terms: SzseRightsCompletionTerms
) -> CorporateActionStageRequest:
    """Provide a valid source-bound no-effect request with separate synthetic ownership."""
    return CorporateActionStageRequest(
        account_id=11,
        owner_user_id=21,
        security_id=event.asset_code,
        asset_code=event.asset_code,
        asset_name="Synthetic source proof",
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=event.source_event_id,
        source_revision_id=event.source_revision_id,
        source_payload_sha256=event.source_body_sha256,
        qualification_sha256=composition.szse_rights_qualification_sha256(event, terms),
        qualifier_identity=composition.SZSE_RIGHTS_QUALIFIER_ID,
        source_observed_at=event.first_seen_at,
        qualified_at=_NOW - timedelta(seconds=1),
        posted_at=_NOW,
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        record_date=terms.record_date,
        effective_date=terms.actual_ex_rights_date,
        stage_date=terms.actual_ex_rights_date,
        ownership_snapshot_id="synthetic-record-proof",
        ownership_snapshot_sha256="d" * 64,
        ownership_snapshot_as_of_date=terms.record_date,
        ownership_snapshot_observed_at=_SEEN,
        eligible_quantity=Decimal("1000"),
        entitlement_calculation_sha256="e" * 64,
        rights_terms_sha256=composition.szse_rights_terms_sha256(terms),
        rights_election="not_exercised",
    )


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "missing",
        "wrong_digest",
        "wrong_terms",
        "offering_only",
        "future_stage",
        "still_open",
        "wrong_calendar",
        "superseded",
    ],
)
def test_rights_source_requires_actual_closed_result_and_exact_current_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str | None,
) -> None:
    """The source proof cannot exercise rights, infer an ex-date or confer permission."""
    event, terms = _source()
    request = _request(event, terms)
    if failure == "wrong_digest":
        request = replace(request, qualification_sha256="f" * 64)
    elif failure == "wrong_terms":
        request = replace(request, rights_terms_sha256="f" * 64)
    elif failure == "future_stage":
        request = replace(request, stage_date=date(2026, 11, 14))
    elif failure == "still_open":
        terms = replace(terms, subscription_end_date=date(2026, 8, 21))
        request = _request(event, terms)
    facts = (PersistedSecurityDisclosureEvent(event, _SEEN + timedelta(seconds=1)),)
    if failure == "missing":
        facts = ()
    elif failure == "superseded":
        later = replace(
            event,
            source_revision_id="sha256:" + "f" * 64,
            supersedes_source_event_id=event.source_event_id,
            supersedes_source_revision_id=event.source_revision_id,
        )
        facts += (PersistedSecurityDisclosureEvent(later, _NOW),)

    class Reader:
        def execute(self, scope: object) -> tuple[PersistedSecurityDisclosureEvent, ...]:
            return facts

    class Calendar:
        def read_verified_zero_origin_calendar(self, **kwargs: object) -> object:
            return SimpleNamespace(
                as_of=_NOW,
                decision_on=date(2026, 11, 13),
                origin_on=date(2026, 8, 1),
                timezone_policy=SimpleNamespace(
                    exchange="SSE" if failure == "wrong_calendar" else "SZSE",
                    timezone_name="Asia/Shanghai",
                ),
            )

    monkeypatch.setattr(
        composition, "make_security_disclosure_event_reader", lambda **kwargs: Reader()
    )
    monkeypatch.setattr(
        composition,
        "build_corporate_action_ownership_history_repository",
        lambda **kwargs: Calendar(),
    )
    monkeypatch.setattr(composition.timezone, "now", lambda: _NOW)
    monkeypatch.setattr(
        composition,
        "read_verified_szse_rights_completion",
        lambda *args, **kwargs: None if failure == "offering_only" else terms,
    )
    qualifier = composition.VerifiedSzseRightsSourceQualifier(
        body_store_root=tmp_path, runtime_environment="test"
    )
    assert qualifier.verify_source(request) is (failure is None)
