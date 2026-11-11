"""The simulated account accepts only exact retained exchange source terms."""

import hashlib
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone

from apps.data_center import security_disclosure_capture_composition as source_composition
from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    CapturedOfficialSzsePdf,
    OfficialSzsePdfBodyStore,
    SzseDistributionTerms,
)
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
)
from apps.simulated_trading import official_disclosure_action_composition as composition
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)


@pytest.mark.django_db
def test_exact_source_revision_and_gross_terms_are_qualified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = b"%PDF-1.4\nverified terms\n%%EOF"
    first_seen_at = timezone.now() - timedelta(seconds=2)
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        source_security_code="002727",
        source_event_id="37e23922-f64d-4203-9d27-9ed981a8f799",
        source_revision_id=f"sha256:{hashlib.sha256(body).hexdigest()}",
        raw_event_type="权益分派实施公告",
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
            "37e23922-f64d-4203-9d27-9ed981a8f799.PDF"
        ),
        source_document_body=body,
        first_seen_at=first_seen_at,
        effective_at=date(2026, 9, 24),
    )
    AppendSecurityDisclosureEventUseCase(DjangoSecurityDisclosureEventRepository()).execute(
        event, body
    )
    qualified_at = timezone.now()
    OfficialSzsePdfBodyStore(tmp_path).retain(
        CapturedOfficialSzsePdf(
            source_url=event.source_url,
            source_document_id=event.source_event_id,
            first_seen_at=first_seen_at,
            body_sha256=event.source_body_sha256,
            body=body,
        )
    )
    terms = SzseDistributionTerms(
        record_date=date(2026, 9, 23),
        ex_date=date(2026, 9, 24),
        payment_date=date(2026, 9, 23),
        cash_per_ten=Decimal("2"),
        shares_per_ten=None,
        tax_treatment="deferred_withholding",
    )
    monkeypatch.setattr(
        source_composition,
        "extract_szse_distribution_terms",
        lambda capture, code: terms,
    )
    request = CorporateActionStageRequest(
        account_id=11,
        owner_user_id=21,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="一心堂",
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=event.source_event_id,
        source_revision_id=event.source_revision_id,
        source_payload_sha256=event.source_body_sha256,
        qualification_sha256=composition.szse_action_qualification_sha256(event, terms),
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=first_seen_at,
        qualified_at=qualified_at,
        posted_at=timezone.now(),
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=terms.record_date,
        cash_amount=Decimal("200.00"),
        tax_treatment="deferred_withholding",
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id="snapshot:11:2026-09-23",
        ownership_snapshot_sha256="d" * 64,
        ownership_snapshot_as_of_date=terms.record_date,
        ownership_snapshot_observed_at=first_seen_at,
        eligible_quantity=Decimal("1000"),
        entitlement_calculation_sha256="e" * 64,
    )
    verifier = composition.VerifiedSzseActionSourceQualifier(body_store_root=tmp_path)

    assert request.tax_rule_id is None
    assert request.tax_rule_sha256 is None
    assert verifier.verify_source(request)
    assert not verifier.verify_source(replace(request, cash_amount=Decimal("201.00")))
    assert not verifier.verify_source(replace(request, source_revision_id="wrong-revision"))
    assert not verifier.verify_source(replace(request, asset_code="301237.SZ"))
    assert not verifier.verify_source(replace(request, tax_treatment="not_applicable"))
    payment = replace(
        request,
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=terms.payment_date,
        payment_date=terms.payment_date,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    assert verifier.verify_source(payment)
    assert not verifier.verify_source(
        replace(payment, payment_date=date(2026, 9, 24), stage_date=date(2026, 9, 24))
    )
    withholding = replace(
        request,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=date(2026, 10, 20),
        cash_amount=Decimal("20.00"),
        tax_rule_id="synthetic-statutory-rule-v1",
        tax_rule_sha256="c" * 64,
        tax_basis_record_id="assessment:disposition-1",
        tax_basis_sha256="d" * 64,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    assert not verifier.verify_source(withholding)
    future_cutoff = timezone.now() + timedelta(minutes=1)
    assert not verifier.verify_source(
        replace(
            request,
            qualified_at=future_cutoff,
            posted_at=future_cutoff + timedelta(seconds=1),
        )
    )

    corrected_body = b"%PDF-1.4\ncorrected terms\n%%EOF"
    successor = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        source_security_code="002727",
        source_event_id="78dc6344-f740-4c50-b4a0-7e9d5159f02e",
        source_revision_id=f"sha256:{hashlib.sha256(corrected_body).hexdigest()}",
        raw_event_type="权益分派实施公告（更正后）",
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-19/"
            "78dc6344-f740-4c50-b4a0-7e9d5159f02e.PDF"
        ),
        source_document_body=corrected_body,
        first_seen_at=timezone.now(),
        effective_at=date(2026, 9, 24),
        supersedes_source_event_id=event.source_event_id,
        supersedes_source_revision_id=event.source_revision_id,
    )
    AppendSecurityDisclosureEventUseCase(DjangoSecurityDisclosureEventRepository()).execute(
        successor, corrected_body
    )

    assert not verifier.verify_source(request)
