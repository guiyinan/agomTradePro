"""Test-only helpers for one source-bound 510050 partial look-through case."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from apps.data_center.domain.sina_quote_capture import (
    SinaQuoteCapture,
    parse_sina_quote_capture,
)
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionRequest,
    parse_portfolio_risk_source_admission_request,
)
from apps.risk_center.domain.portfolio_exposure_types import PortfolioAssetKind
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_snapshot import exact_decimal_product
from apps.risk_center.infrastructure.portfolio_risk_etf_publication_capture_manifest import (
    decode_etf_publication_capture_manifest,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FACTS_SCHEMA = "ash07.owner-etf-partial-source-facts.v1"
_Q3_OVERRIDES = frozenset({"600036", "601398"})
_QUOTE_KINDS = ("valuation", "capacity_window", "execution_session_state")
_FORBIDDEN_RESTRICTIONS = frozenset({"research_only", "observation_only"})


@dataclass(frozen=True, slots=True)
class Q3ConstituentFact:
    """One explicitly transcribed top-ten row from the retained quarterly report."""

    row_number: int
    source_stock_code: str
    source_stock_name: str
    quantity_shares_text: str
    fair_value_yuan_text: str
    weight_percent_text: str
    weight_fraction: Decimal


@dataclass(frozen=True, slots=True)
class RetainedQ3ReportFacts:
    """Hash-bound facts transcribed from the disclosed ETF report rows."""

    report_date: date
    publication_on: date
    source_section: str
    transcription_locator: str
    quantity_source_unit: str
    fair_value_source_unit: str
    reported_weight_fraction: Decimal
    constituents: tuple[Q3ConstituentFact, ...]
    source_body_path: Path
    source_capture_metadata_path: Path
    publication_body_path: Path
    publication_capture_metadata_path: Path


@dataclass(frozen=True, slots=True)
class RetainedSinaSupplementalCapture:
    """One exact current supplemental quote capture and its receipt."""

    provider_asset_code: str
    capture: SinaQuoteCapture
    receipt: PortfolioRiskCaptureReceipt
    business_date: date


def load_q3_report_facts(
    *,
    facts_path: Path,
    expected_facts_sha256: str,
    repository_root: Path,
) -> RetainedQ3ReportFacts:
    """Load only externally hash-bound ten-row facts and retained source bytes."""

    if (
        type(expected_facts_sha256) is not str
        or len(expected_facts_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_facts_sha256)
    ):
        raise ValueError("expected facts SHA-256 must be 64 lowercase hexadecimal characters")
    facts_bytes = facts_path.read_bytes()
    actual_facts_sha256 = hashlib.sha256(facts_bytes).hexdigest()
    if actual_facts_sha256 != expected_facts_sha256:
        raise ValueError("Q3 facts file SHA-256 differs from the externally bound digest")
    document = _json_bytes_object(facts_bytes, str(facts_path))
    if document.get("schema") != _FACTS_SCHEMA:
        raise ValueError("Q3 fact document schema is unsupported")
    report_date = _parse_date(document.get("report_date"), "report_date")
    publication_on = _parse_date(document.get("publication_on"), "publication_on")
    source_section = _require_text(document.get("source_section"), "source_section")
    transcription_locator = _require_text(
        document.get("transcription_locator"), "transcription_locator"
    )
    if not source_section.strip() or not transcription_locator.strip():
        raise ValueError("Q3 source section and transcription locator must be explicit")
    quantity_source_unit = _require_token(
        document.get("quantity_source_unit"), "quantity_source_unit"
    )
    fair_value_source_unit = _require_token(
        document.get("fair_value_source_unit"), "fair_value_source_unit"
    )
    expected_weight = _decimal_text(document.get("reported_weight_fraction"))
    raw_rows = document.get("constituents")
    if type(raw_rows) is not list or len(raw_rows) != 10:
        raise ValueError("the Q3 report facts must contain the ten disclosed rows")
    rows: list[Q3ConstituentFact] = []
    for expected_row_number, raw_row in enumerate(raw_rows, start=1):
        row = _require_mapping(raw_row, "constituent row")
        row_number = _require_int(row.get("row_number"), "row_number")
        if row_number != expected_row_number:
            raise ValueError("Q3 constituent row numbers must preserve report order")
        source_code = _require_token(row.get("source_stock_code"), "source_stock_code")
        source_name = _require_text(row.get("source_stock_name"), "source_stock_name")
        quantity_text = _require_decimal_string(
            row.get("quantity_shares_text"), "quantity_shares_text"
        )
        fair_value_text = _require_decimal_string(
            row.get("fair_value_yuan_text"), "fair_value_yuan_text"
        )
        quantity = Decimal(quantity_text)
        fair_value = Decimal(fair_value_text)
        if quantity <= 0 or quantity != quantity.to_integral_value() or fair_value <= 0:
            raise ValueError(
                "Q3 quantity must be positive whole shares and fair value must be positive"
            )
        percent_text = _require_decimal_string(
            row.get("weight_percent_text"), "weight_percent_text"
        )
        percent = Decimal(percent_text)
        if percent <= 0 or percent >= Decimal("100"):
            raise ValueError("Q3 constituent percentage is outside its valid range")
        rows.append(
            Q3ConstituentFact(
                row_number=row_number,
                source_stock_code=source_code,
                source_stock_name=source_name,
                quantity_shares_text=quantity_text,
                fair_value_yuan_text=fair_value_text,
                weight_percent_text=percent_text,
                weight_fraction=percent / Decimal("100"),
            )
        )
    if len({row.source_stock_code for row in rows}) != len(rows):
        raise ValueError("Q3 report contains duplicate source stock codes")
    total_weight = sum((row.weight_fraction for row in rows), Decimal("0"))
    if total_weight != expected_weight:
        raise ValueError("Q3 rows do not reconcile to the declared disclosed fraction")

    source_body_path = _resolve_path(
        document.get("source_body_path"), repository_root, "source_body_path"
    )
    source_meta_path = _resolve_path(
        document.get("source_capture_metadata_path"),
        repository_root,
        "source_capture_metadata_path",
    )
    publication_body_path = _resolve_path(
        document.get("publication_body_path"), repository_root, "publication_body_path"
    )
    publication_meta_path = _resolve_path(
        document.get("publication_capture_metadata_path"),
        repository_root,
        "publication_capture_metadata_path",
    )
    transcription_path = _resolve_path(
        document.get("transcription_source_path"),
        repository_root,
        "transcription_source_path",
    )
    _verify_sha256(source_body_path, document.get("source_body_sha256"))
    _verify_sha256(source_meta_path, document.get("source_capture_metadata_sha256"))
    _verify_sha256(publication_body_path, document.get("publication_body_sha256"))
    _verify_sha256(publication_meta_path, document.get("publication_capture_metadata_sha256"))
    _verify_sha256(transcription_path, document.get("transcription_source_sha256"))
    return RetainedQ3ReportFacts(
        report_date=report_date,
        publication_on=publication_on,
        source_section=source_section,
        transcription_locator=transcription_locator,
        quantity_source_unit=quantity_source_unit,
        fair_value_source_unit=fair_value_source_unit,
        reported_weight_fraction=expected_weight,
        constituents=tuple(rows),
        source_body_path=source_body_path,
        source_capture_metadata_path=source_meta_path,
        publication_body_path=publication_body_path,
        publication_capture_metadata_path=publication_meta_path,
    )


def load_supplemental_sina_capture(
    *,
    supplemental_manifest_path: Path,
    repository_root: Path,
    expected_provider_asset_code: str,
    source_id: str,
    source_record_namespace: str,
    business_date: date,
) -> RetainedSinaSupplementalCapture:
    """Rebuild the exact 510050 capture from Root's supplemental raw archive."""

    if expected_provider_asset_code != "510050.SH":
        raise ValueError("this supplemental helper is reserved for the explicit 510050 quote")
    manifest_value = json.loads(supplemental_manifest_path.read_text(encoding="utf-8-sig"))
    if type(manifest_value) is not list:
        raise ValueError("supplemental quote archive must be a JSON array")
    matching = tuple(
        _require_mapping(item, "supplemental quote row")
        for item in manifest_value
        if isinstance(item, Mapping) and item.get("asset_code") == expected_provider_asset_code
    )
    if len(matching) != 1:
        raise ValueError("supplemental quote archive must contain exactly one requested quote")
    entry = matching[0]
    if "retained raw facts only" not in _require_text(entry.get("scope"), "scope"):
        raise ValueError("supplemental quote was not retained as raw facts")
    metadata_path = _resolve_path(entry.get("metadata_path"), repository_root, "metadata_path")
    metadata_bytes = metadata_path.read_bytes()
    metadata_hash = hashlib.sha256(metadata_bytes).hexdigest()
    if metadata_hash != entry.get("metadata_sha256"):
        raise ValueError("supplemental quote metadata hash differs from the archive index")
    metadata = _json_bytes_object(metadata_bytes, "supplemental quote metadata")
    if metadata.get("asset_code") != expected_provider_asset_code:
        raise ValueError("supplemental quote metadata has a different provider asset code")
    if (
        metadata.get("source_availability_at") is not None
        or metadata.get("source_valid_until") is not None
    ):
        raise ValueError("the supplemental capture cannot invent vendor availability or expiry")
    raw_file = _require_token(metadata.get("raw_file"), "raw_file")
    raw_body_path = (metadata_path.parent / raw_file).resolve()
    body = raw_body_path.read_bytes()
    body_hash = hashlib.sha256(body).hexdigest()
    if (
        body_hash != metadata.get("raw_file_sha256")
        or body_hash != entry.get("body_sha256")
        or len(body) != metadata.get("body_size_bytes")
    ):
        raise ValueError("supplemental quote original bytes differ from their capture metadata")
    status = _require_int(metadata.get("http_status"), "http_status")
    request_started_at = _parse_datetime(metadata.get("request_started_at"), "request_started_at")
    response_completed_at = _parse_datetime(
        metadata.get("response_completed_at"), "response_completed_at"
    )
    capture = parse_sina_quote_capture(
        asset_code=expected_provider_asset_code,
        requested_url=_require_text(metadata.get("requested_url"), "requested_url"),
        final_url=_require_text(metadata.get("final_url"), "final_url"),
        request_started_at=request_started_at,
        response_completed_at=response_completed_at,
        http_status=status,
        http_date=_optional_text(metadata.get("http_date"), "http_date"),
        content_type=_optional_text(metadata.get("content_type"), "content_type"),
        charset=_optional_text(metadata.get("charset"), "charset"),
        content_encoding=_optional_text(metadata.get("content_encoding"), "content_encoding"),
        body=body,
    )
    quote = capture.quote
    if status != 200 or not capture.usable_parse or quote is None:
        raise ValueError("supplemental Sina quote did not parse as a successful capture")
    if quote.source_observed_at is None or quote.last_price is None:
        raise ValueError("supplemental quote lacks its source timestamp or price")
    if quote.vendor_status_code != "00" or quote.reported_trading_state.value != "trading":
        raise ValueError("supplemental quote is not vendor-reported as trading")
    observed_local = quote.source_observed_at.astimezone(_SHANGHAI)
    received_local = capture.response_completed_at.astimezone(_SHANGHAI)
    if (
        observed_local.date() != business_date
        or observed_local.time() < time(15)
        or received_local.date() != business_date
        or response_completed_at < request_started_at
    ):
        raise ValueError("supplemental quote is not from the explicit current close session")
    record_id = (
        f"{source_record_namespace}:{expected_provider_asset_code}:{business_date.isoformat()}"
    )
    receipt = PortfolioRiskCaptureReceipt(
        capture_id=f"supplemental-sina-{metadata_hash[:20]}",
        source_id=source_id,
        source_record_id=record_id,
        original_body_sha256=body_hash,
        response_completed_at=capture.response_completed_at,
        http_status=status,
        body_size_bytes=len(body),
        body_complete=True,
    )
    return RetainedSinaSupplementalCapture(
        provider_asset_code=expected_provider_asset_code,
        capture=capture,
        receipt=receipt,
        business_date=business_date,
    )


def build_supplemental_etf_quote_admission_requests(
    *,
    retained_capture: RetainedSinaSupplementalCapture,
    asset_code: str,
    security_id: str,
    asset_kind: PortfolioAssetKind,
    quantity_unit: str,
    price_unit: str,
    source_evidence_templates: Mapping[str, Mapping[str, object]],
    capacity_window_template: Mapping[str, object],
) -> tuple[PortfolioRiskSourceAdmissionRequest, ...]:
    """Make valuation/capacity/close-state requests without inventing source clocks."""

    if asset_kind is not PortfolioAssetKind.ETF:
        raise ValueError("supplemental 510050 quote must be explicitly typed as ETF")
    _require_token(asset_code, "asset_code")
    _require_token(security_id, "security_id")
    _require_token(quantity_unit, "quantity_unit")
    _require_token(price_unit, "price_unit")
    if set(source_evidence_templates) != set(_QUOTE_KINDS):
        raise ValueError("all three exact quote source-evidence templates are required")
    quote = retained_capture.capture.quote
    if quote is None or quote.source_observed_at is None or quote.last_price is None:
        raise ValueError("retained supplemental quote is missing typed price or observation")
    local_session = quote.source_observed_at.astimezone(_SHANGHAI).date()
    if local_session != retained_capture.business_date:
        raise ValueError("quote session differs from the explicit Owner test business date")
    capacity_facts = _require_mapping(capacity_window_template, "capacity window template")
    if (
        capacity_facts.get("window_kind") != "session_cumulative"
        or capacity_facts.get("sessions") != 1
        or capacity_facts.get("start") != local_session.isoformat()
        or capacity_facts.get("end") != local_session.isoformat()
    ):
        raise ValueError("capacity template must describe only this exact cumulative session")
    volume_unit = _require_token(capacity_facts.get("volume_unit"), "volume_unit")
    amount_unit = _require_token(capacity_facts.get("amount_unit"), "amount_unit")

    requests: list[PortfolioRiskSourceAdmissionRequest] = []
    for kind in _QUOTE_KINDS:
        source_record_id = f"{retained_capture.receipt.source_record_id}:{kind}"
        template = _require_mapping(source_evidence_templates[kind], f"{kind} evidence template")
        evidence = _quote_source_evidence(
            template=template,
            retained_capture=retained_capture,
            source_record_id=source_record_id,
            effective_on=(
                retained_capture.business_date if kind == "execution_session_state" else None
            ),
        )
        if kind == "valuation":
            facts: dict[str, object] = {
                "price": str(quote.last_price),
                "asset_kind": asset_kind.value,
                "quantity_unit": quantity_unit,
                "price_unit": price_unit,
            }
            typed_capture = None
        elif kind == "capacity_window":
            facts = {
                "window_kind": "session_cumulative",
                "start": local_session.isoformat(),
                "end": local_session.isoformat(),
                "sessions": 1,
                "volume": {
                    "value": _decimal_or_none(quote.volume),
                    "unit": volume_unit,
                },
                "amount": {
                    "value": _decimal_or_none(quote.amount),
                    "unit": amount_unit,
                },
            }
            typed_capture = None
        else:
            facts = {"session_date": local_session.isoformat(), "suspended": None}
            typed_capture = retained_capture.capture
        document: dict[str, object] = {
            "schema_version": "ash07.source_admission_request.v1",
            "kind": kind,
            "asset_code": asset_code,
            "security_id": security_id,
            "source_record_id": source_record_id,
            "original_url": retained_capture.capture.requested_url,
            "captured_at": retained_capture.receipt.response_completed_at.isoformat(),
            "source_evidence": evidence,
            "facts": facts,
        }
        receipt = PortfolioRiskCaptureReceipt(
            capture_id=f"{retained_capture.receipt.capture_id}-{kind}",
            source_id=retained_capture.receipt.source_id,
            source_record_id=source_record_id,
            original_body_sha256=retained_capture.receipt.original_body_sha256,
            response_completed_at=retained_capture.receipt.response_completed_at,
            http_status=retained_capture.receipt.http_status,
            body_size_bytes=retained_capture.receipt.body_size_bytes,
            body_complete=True,
        )
        request = parse_portfolio_risk_source_admission_request(
            document,
            original_body=retained_capture.capture.body,
            capture_receipt=receipt,
            sina_capture=typed_capture,
        )
        requests.append(request)
    return tuple(requests)


def build_q3_report_admission_request(
    *,
    facts: RetainedQ3ReportFacts,
    repository_root: Path,
    asset_code: str,
    security_id: str,
    source_id: str,
    source_purpose: str,
    allowed_purposes: tuple[str, ...],
    restrictions: tuple[str, ...],
    coverage_precision_basis: str,
    business_date: date,
    same_day_bank_industry_requests: Sequence[PortfolioRiskSourceAdmissionRequest],
    source_code_to_asset_code: Mapping[str, str],
) -> PortfolioRiskSourceAdmissionRequest:
    """Build the retained Q3 report request and keep eight absent classifications unknown."""

    _require_token(asset_code, "asset_code")
    _require_token(security_id, "security_id")
    _require_token(source_id, "source_id")
    _require_token(source_purpose, "source_purpose")
    _require_token(coverage_precision_basis, "coverage_precision_basis")
    if type(business_date) is not date:
        raise TypeError("business_date must be an explicit date")
    if facts.report_date > business_date or facts.publication_on > business_date:
        raise ValueError("the retained ETF report and publication must not be from the future")
    if not allowed_purposes:
        raise ValueError("ETF report must retain explicit permitted consumer purposes")
    if any(
        restriction.startswith("must_not_") or restriction in _FORBIDDEN_RESTRICTIONS
        for restriction in restrictions
    ):
        raise ValueError("prohibited ETF evidence cannot be enabled by this test helper")
    if set(source_code_to_asset_code) != _Q3_OVERRIDES:
        raise ValueError("only the two explicitly pinned bank codes may be normalized here")
    bank_memberships = tuple(
        request
        for request in same_day_bank_industry_requests
        if request.kind == "industry_membership"
    )
    if len(bank_memberships) != 2:
        raise ValueError("the ETF overlap case requires the two typed bank membership requests")
    if set(source_code_to_asset_code.values()) != {
        request.asset_code for request in bank_memberships
    }:
        raise ValueError("overlap normalization must match the exact typed bank references")
    for request in bank_memberships:
        if (
            request.source_evidence.observation_precision.value != "date"
            or request.source_evidence.observed_on != business_date
            or request.source_evidence.effective_on != business_date
        ):
            raise ValueError(
                "bank overlap industry references must match the exact current observed/effective DATE"
            )

    pdf_body = facts.source_body_path.read_bytes()
    page_body = facts.publication_body_path.read_bytes()
    pdf_metadata = _read_capture_metadata(facts.source_capture_metadata_path)
    page_metadata = _read_capture_metadata(facts.publication_capture_metadata_path)
    pdf_receipt, report_record_id = _report_receipt(
        metadata=pdf_metadata,
        body=pdf_body,
        source_id=source_id,
        record_prefix=f"retained-chinaamc-510050-q3-{facts.report_date:%Y%m%d}",
        suffix="pdf",
    )
    page_receipt, _ = _report_receipt(
        metadata=page_metadata,
        body=page_body,
        source_id=source_id,
        record_prefix=f"{report_record_id}:publication",
        suffix="html",
    )
    publication_manifest: dict[str, object] = {
        "publication_on": facts.publication_on.isoformat(),
        "url": _require_text(page_metadata.get("final_url"), "publication final_url"),
        "body_base64": base64.b64encode(page_body).decode("ascii"),
        "receipt": _receipt_manifest(page_receipt),
    }
    original_url = _require_text(pdf_metadata.get("final_url"), "PDF final_url")
    publication_capture = decode_etf_publication_capture_manifest(
        publication_manifest,
        report_original_url=original_url,
        report_date=facts.report_date,
        source_effective_on=facts.report_date,
        source_observation_date=facts.publication_on,
    )
    known_at = max(pdf_receipt.response_completed_at, page_receipt.response_completed_at)
    source_evidence: dict[str, object] = {
        "source_id": source_id,
        "source_record_id": report_record_id,
        "original_payload_sha256": pdf_receipt.original_body_sha256,
        "observation_precision": "date",
        "observed_at": None,
        "observed_on": publication_capture.publication_on.isoformat(),
        "available_at": None,
        "known_at": known_at.isoformat(),
        "valid_until": None,
        "source_purpose": source_purpose,
        "allowed_purposes": list(allowed_purposes),
        "restrictions": list(restrictions),
        "must_not_use_for_decision": False,
        "coverage": {
            "status": "partial",
            "precision_basis": coverage_precision_basis,
            "reported_weight_fraction": str(facts.reported_weight_fraction),
            "expected_item_count": None,
            "observed_item_count": None,
        },
        "effective_on": facts.report_date.isoformat(),
        "effective_until": None,
    }
    constituent_facts: list[dict[str, object]] = []
    for item in facts.constituents:
        normalized_code = source_code_to_asset_code.get(item.source_stock_code)
        constituent_facts.append(
            {
                "asset_code": normalized_code or item.source_stock_code,
                "weight_fraction": str(item.weight_fraction),
                "kind": "equity",
            }
        )
    admission_document: dict[str, object] = {
        "schema_version": "ash07.source_admission_request.v1",
        "kind": "etf_report",
        "asset_code": asset_code,
        "security_id": security_id,
        "source_record_id": report_record_id,
        "original_url": original_url,
        "captured_at": pdf_receipt.response_completed_at.isoformat(),
        "source_evidence": source_evidence,
        "facts": {
            "report_date": facts.report_date.isoformat(),
            "constituents": constituent_facts,
        },
    }
    return parse_portfolio_risk_source_admission_request(
        admission_document,
        original_body=pdf_body,
        capture_receipt=pdf_receipt,
        etf_publication_capture=publication_capture,
    )


def add_isolated_etf_position(
    *,
    account: SimulatedAccountModel,
    asset_code: str,
    asset_name: str,
    quantity: Decimal,
    price: Decimal,
    business_date: date,
    first_buy_date: date,
) -> PositionModel:
    """Add one explicitly test-only ETF/fund holding to the isolated account."""

    if account.account_type != "simulated" or account.pk is None:
        raise ValueError("ETF test positions can only be added to a persisted simulated account")
    if asset_code != "510050.SH":
        raise ValueError("this isolated position helper is reserved for the 510050 test holding")
    _require_token(asset_code, "asset_code")
    _require_token(asset_name, "asset_name")
    for value, label in ((quantity, "quantity"), (price, "price")):
        if type(value) is not Decimal or not value.is_finite() or value <= 0:
            raise ValueError(f"test ETF {label} must be a finite positive Decimal")
    if type(business_date) is not date or type(first_buy_date) is not date:
        raise TypeError("business_date and first_buy_date must be dates")
    if first_buy_date > business_date:
        raise ValueError("test ETF first-buy date cannot be after the report business date")
    market_value = (price * quantity).quantize(Decimal("0.01"))
    position = PositionModel.objects.create(
        account=account,
        asset_code=asset_code,
        asset_name=asset_name,
        asset_type="fund",
        quantity=quantity,
        available_quantity=quantity,
        available_quantity_known=True,
        avg_cost=price.quantize(Decimal("0.0001")),
        total_cost=market_value,
        cost_basis_known=True,
        current_price=price,
        market_value=market_value,
        valuation_known=True,
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=first_buy_date,
        first_buy_date_known=True,
        entry_reason="ASH07 isolated test fixture; not a real-account holding",
        invalidation_description="test-only partial ETF position",
    )
    account.current_market_value = account.current_market_value + market_value
    account.total_value = account.current_cash + account.current_market_value
    account.save(update_fields=("current_market_value", "total_value"))
    return position


def assert_public_etf_partial_risk_report(
    payload: PortfolioRiskReportPayload,
    *,
    etf_asset_code: str,
    etf_market_value: Decimal,
    expected_portfolio_nav: Decimal,
    expected_money_unit: str,
    minimum_lookthrough_coverage: Decimal,
    facts: RetainedQ3ReportFacts,
    source_code_to_asset_code: Mapping[str, str],
    direct_holding_market_values: Mapping[str, Decimal],
    industry_codes_by_asset: Mapping[str, str],
) -> None:
    """Check the public ETF result against exact NAV, overlap, and unknown bounds."""

    if set(source_code_to_asset_code) != _Q3_OVERRIDES:
        raise AssertionError("the partial case may map only the two exact bank report codes")
    if (
        type(etf_market_value) is not Decimal
        or not etf_market_value.is_finite()
        or etf_market_value <= 0
        or type(expected_portfolio_nav) is not Decimal
        or not expected_portfolio_nav.is_finite()
        or expected_portfolio_nav <= 0
        or type(minimum_lookthrough_coverage) is not Decimal
        or not minimum_lookthrough_coverage.is_finite()
        or minimum_lookthrough_coverage <= 0
        or minimum_lookthrough_coverage > 1
    ):
        raise AssertionError(
            "public-report expectations need explicit finite positive NAV and policy values"
        )
    _require_token(expected_money_unit, "expected_money_unit")
    if set(industry_codes_by_asset) != set(direct_holding_market_values):
        raise AssertionError("industry source codes must cover each direct bank holding exactly")
    if set(source_code_to_asset_code.values()) != set(industry_codes_by_asset):
        raise AssertionError("ETF bank rows and direct holdings must share exact identities")
    for industry_code in industry_codes_by_asset.values():
        _require_token(industry_code, "industry_code")
    if payload.get("outcome") != "blocked" or payload.get("must_not_execute") is not True:
        raise AssertionError("partial Q3 ETF risk report must remain blocked from execution")
    if facts.reported_weight_fraction >= minimum_lookthrough_coverage:
        raise AssertionError("selected ETF policy does not reject this partial report coverage")
    check = _one_mapping(
        payload.get("checks"),
        predicate=lambda item: item.get("dimension") == "industry_and_security_exposure",
        label="industry_and_security_exposure check",
    )
    if check.get("status") != "blocked":
        raise AssertionError("ETF coverage rejection must be visible on the exposure check")
    reasons = _string_list(check.get("reason_codes"), "exposure reason codes")
    if "ETF_LOOKTHROUGH_COVERAGE_BELOW_POLICY_MINIMUM" not in reasons:
        raise AssertionError("the report did not expose the Q3 coverage-floor reason")
    details = _require_mapping(check.get("details"), "exposure details")
    if _decimal_text(details.get("portfolio_market_value")) != expected_portfolio_nav:
        raise AssertionError("exposure denominator differs from actual cash plus holdings NAV")
    nav_check = _one_mapping(
        payload.get("checks"),
        predicate=lambda item: item.get("dimension") == "pre_trade_gross_nav",
        label="pre_trade_gross_nav check",
    )
    nav_details = _require_mapping(nav_check.get("details"), "pre-trade NAV details")
    if (
        nav_check.get("status") != "allowed"
        or nav_details.get("basis")
        != "actual_cash_plus_settled_holdings_at_qualified_current_price"
        or _decimal_text(nav_details.get("pre_trade_gross_nav")) != expected_portfolio_nav
        or nav_details.get("money_unit") != expected_money_unit
    ):
        raise AssertionError("public NAV must use the exact cash, holdings, and declared currency")
    coverage = _decimal_text(details.get("etf_lookthrough_coverage_fraction"))
    if coverage != facts.reported_weight_fraction:
        raise AssertionError("public ETF look-through fraction differs from the ten rows")

    mapped_fraction = sum(
        (
            row.weight_fraction
            for row in facts.constituents
            if row.source_stock_code in source_code_to_asset_code
        ),
        Decimal("0"),
    )
    unknown_industry_fraction = Decimal("1") - mapped_fraction
    unknown_security_fraction = Decimal("1") - facts.reported_weight_fraction
    expected_unknown_industry = exact_decimal_product(etf_market_value, unknown_industry_fraction)
    expected_unknown_security = exact_decimal_product(etf_market_value, unknown_security_fraction)
    if _decimal_text(details.get("unknown_industry_market_value")) != expected_unknown_industry:
        raise AssertionError("public unknown industry amount does not retain unclassified rows")
    if _decimal_text(details.get("unknown_security_market_value")) != expected_unknown_security:
        raise AssertionError(
            "public unknown security amount does not retain the undisclosed remainder"
        )

    industry_known_values: dict[str, Decimal] = {}
    for asset_code, direct_value in direct_holding_market_values.items():
        industry_code = industry_codes_by_asset[asset_code]
        industry_known_values[industry_code] = (
            industry_known_values.get(industry_code, Decimal("0")) + direct_value
        )
    for row in facts.constituents:
        asset_code = source_code_to_asset_code.get(row.source_stock_code)
        if asset_code is None:
            continue
        industry_code = industry_codes_by_asset[asset_code]
        row_value = exact_decimal_product(etf_market_value, row.weight_fraction)
        industry_known_values[industry_code] = (
            industry_known_values.get(industry_code, Decimal("0")) + row_value
        )
    industry_bounds = _string_list(details.get("industry_bounds"), "industry bounds")
    if len(industry_bounds) != len(industry_known_values):
        raise AssertionError("public industry bounds do not match the exact source-bound sectors")
    for industry_code, known_value in industry_known_values.items():
        lower_weight, upper_weight = _weight_bounds_for_code(
            industry_bounds,
            code=industry_code,
            label="industry bound",
        )
        if lower_weight != known_value / expected_portfolio_nav:
            raise AssertionError(
                "industry lower weight does not use exact known value over full NAV"
            )
        if upper_weight != (known_value + expected_unknown_industry) / expected_portfolio_nav:
            raise AssertionError(
                "industry upper weight does not use full NAV and unknown remainder"
            )

    security_known_values = dict(direct_holding_market_values)
    for row in facts.constituents:
        asset_code = source_code_to_asset_code.get(row.source_stock_code, row.source_stock_code)
        security_known_values[asset_code] = security_known_values.get(
            asset_code, Decimal("0")
        ) + exact_decimal_product(etf_market_value, row.weight_fraction)
    security_bounds = _string_list(details.get("security_bounds"), "security bounds")
    if len(security_bounds) != len(security_known_values):
        raise AssertionError(
            "public security bounds do not match the disclosed constituent identities"
        )
    for asset_code, known_value in security_known_values.items():
        lower_weight, upper_weight = _weight_bounds_for_code(
            security_bounds,
            code=asset_code,
            label="security bound",
        )
        if lower_weight != known_value / expected_portfolio_nav:
            raise AssertionError(
                "security lower weight does not use exact known value over full NAV"
            )
        if upper_weight != (known_value + expected_unknown_security) / expected_portfolio_nav:
            raise AssertionError(
                "security upper weight does not use full NAV and unknown remainder"
            )

    etf_detail = _one_text(
        details.get("etf_bounds"),
        predicate=lambda item: item.startswith(f"{etf_asset_code}:"),
        label="ETF bound",
    )
    bound_values = _parse_colon_detail(etf_detail)
    if _decimal_text(bound_values.get("coverage")) != facts.reported_weight_fraction:
        raise AssertionError("ETF bound coverage differs from the source facts")
    if _decimal_text(bound_values.get("unknown")) != expected_unknown_industry:
        raise AssertionError("ETF industry unknown amount differs from the two-map case")
    if _decimal_text(bound_values.get("unknown_security")) != expected_unknown_security:
        raise AssertionError("ETF security unknown amount differs from the unreported residual")

    overlap_rows = _string_list(details.get("repeated_underlyings"), "repeated underlyings")
    if set(source_code_to_asset_code.values()) != set(direct_holding_market_values):
        raise AssertionError("overlap assertions must match the two exact bank positions")
    for source_code, asset_code in source_code_to_asset_code.items():
        row = _one_text(
            overlap_rows,
            predicate=lambda item, asset_code=asset_code: item.startswith(f"{asset_code}:"),
            label=f"{asset_code} repeated underlying",
        )
        values = _parse_colon_detail(row)
        fact = next(item for item in facts.constituents if item.source_stock_code == source_code)
        expected_etf_value = exact_decimal_product(etf_market_value, fact.weight_fraction)
        if _decimal_text(values.get("direct")) != direct_holding_market_values[asset_code]:
            raise AssertionError(f"direct {asset_code} notional differs from the account fixture")
        if _decimal_text(values.get("etf")) != expected_etf_value:
            raise AssertionError(f"ETF {asset_code} look-through does not match the Q3 row")
        if values.get("etfs") != etf_asset_code:
            raise AssertionError(f"{asset_code} overlap is not bound to the 510050 position")


def _quote_source_evidence(
    *,
    template: Mapping[str, object],
    retained_capture: RetainedSinaSupplementalCapture,
    source_record_id: str,
    effective_on: date | None,
) -> dict[str, object]:
    required = {
        "source_purpose",
        "allowed_purposes",
        "restrictions",
        "must_not_use_for_decision",
        "coverage",
    }
    if not required.issubset(template):
        raise ValueError("quote evidence template is missing source qualification fields")
    evidence = dict(template)
    _require_token(evidence.get("source_purpose"), "source_purpose")
    allowed_purposes = _string_list(evidence.get("allowed_purposes"), "allowed_purposes")
    if not allowed_purposes:
        raise ValueError("quote source must retain explicit permitted consumer purposes")
    if evidence.get("must_not_use_for_decision") is not False:
        raise ValueError("globally prohibited quote evidence cannot be admitted")
    quote = retained_capture.capture.quote
    if quote is None or quote.source_observed_at is None:
        raise ValueError("quote timestamp is missing")
    evidence.update(
        {
            "source_id": retained_capture.receipt.source_id,
            "source_record_id": source_record_id,
            "original_payload_sha256": retained_capture.receipt.original_body_sha256,
            "observation_precision": "timestamp",
            "observed_at": quote.source_observed_at.isoformat(),
            "observed_on": None,
            "available_at": None,
            "known_at": retained_capture.receipt.response_completed_at.isoformat(),
            "valid_until": None,
            "effective_on": effective_on.isoformat() if effective_on is not None else None,
            "effective_until": None,
        }
    )
    return evidence


def _report_receipt(
    *,
    metadata: Mapping[str, object],
    body: bytes,
    source_id: str,
    record_prefix: str,
    suffix: str,
) -> tuple[PortfolioRiskCaptureReceipt, str]:
    status = _require_int(metadata.get("http_status"), "http_status")
    if not 200 <= status < 300 or metadata.get("transport_error") is not None:
        raise ValueError("report/publication capture did not complete successfully")
    expected_sha = hashlib.sha256(body).hexdigest()
    expected_size = len(body)
    if (
        metadata.get("body_sha256") != expected_sha
        or metadata.get("body_size_bytes") != expected_size
    ):
        raise ValueError("report/publication original bytes differ from capture metadata")
    request_at = _utc_key_datetime(metadata.get("request_at_utc"), "request_at_utc")
    received_at = _utc_key_datetime(metadata.get("received_at_utc"), "received_at_utc")
    if received_at < request_at:
        raise ValueError("capture receipt precedes its request")
    record_id = f"{record_prefix}:{suffix}:{expected_sha[:12]}"
    receipt = PortfolioRiskCaptureReceipt(
        capture_id=f"owner-etf-{suffix}-{expected_sha[:20]}",
        source_id=source_id,
        source_record_id=record_id,
        original_body_sha256=expected_sha,
        response_completed_at=received_at,
        http_status=status,
        body_size_bytes=expected_size,
        body_complete=True,
    )
    return receipt, record_id


def _receipt_manifest(receipt: PortfolioRiskCaptureReceipt) -> dict[str, object]:
    return {
        "capture_id": receipt.capture_id,
        "source_id": receipt.source_id,
        "source_record_id": receipt.source_record_id,
        "original_body_sha256": receipt.original_body_sha256,
        "response_completed_at": receipt.response_completed_at.isoformat(),
        "http_status": receipt.http_status,
        "body_size_bytes": receipt.body_size_bytes,
        "body_complete": receipt.body_complete,
    }


def _read_capture_metadata(path: Path) -> dict[str, object]:
    """Load one capture metadata object without changing the original bytes."""

    return _json_bytes_object(path.read_bytes(), "capture metadata")


def _read_json_object(path: Path) -> dict[str, object]:
    return _json_bytes_object(path.read_bytes(), str(path))


def _json_bytes_object(value: bytes, label: str) -> dict[str, object]:
    parsed = json.loads(value.decode("utf-8-sig"))
    if type(parsed) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, object], parsed)


def _resolve_path(value: object, repository_root: Path, label: str) -> Path:
    text = _require_token(value, label)
    path = Path(text)
    resolved = path if path.is_absolute() else repository_root / path
    if not resolved.is_file():
        raise FileNotFoundError(f"retained {label} is absent: {resolved}")
    return resolved.resolve()


def _verify_sha256(path: Path, expected: object) -> None:
    expected_hash = _require_token(expected, "expected_sha256")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"retained file hash differs: {path}")


def _parse_datetime(value: object, label: str) -> datetime:
    text = _require_text(value, label)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must retain its timezone offset")
    return parsed


def _utc_key_datetime(value: object, label: str) -> datetime:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text, "%Y/%m/%d %H:%M:%S")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if not label.endswith("_utc"):
            raise ValueError(f"{label} does not declare UTC for its naive text")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_date(value: object, label: str) -> date:
    if type(value) is not str:
        raise TypeError(f"{label} must be ISO date text")
    return date.fromisoformat(value)


def _decimal_text(value: object) -> Decimal:
    if type(value) is not str:
        raise TypeError("decimal input must be exact text")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("decimal input must be finite")
    return result


def _require_decimal_string(value: object, label: str) -> str:
    text = _require_text(value, label)
    decimal_value = Decimal(text)
    if not decimal_value.is_finite():
        raise ValueError(f"{label} must be finite")
    return text


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(f"{label} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _require_text(value: object, label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be text")
    return value


def _require_token(value: object, label: str) -> str:
    text = _require_text(value, label)
    if not text or text.strip() != text or any(character.isspace() for character in text):
        raise ValueError(f"{label} must be a nonempty canonical token")
    return text


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _require_text(value, label)


def _require_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError(f"{label} must be a list of strings")
    return cast(list[str], value)


def _one_mapping(
    value: object,
    *,
    predicate: Callable[[Mapping[str, object]], bool],
    label: str,
) -> Mapping[str, object]:
    if type(value) is not list:
        raise TypeError(f"{label} collection must be a list")
    matches: list[Mapping[str, object]] = []
    for item in cast(list[object], value):
        mapping = _require_mapping(item, label)
        if predicate(mapping):
            matches.append(mapping)
    if len(matches) != 1:
        raise AssertionError(f"public report must contain exactly one {label}")
    return matches[0]


def _one_text(
    value: object,
    *,
    predicate: Callable[[str], bool],
    label: str,
) -> str:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError(f"{label} collection must be a list of strings")
    matches = [item for item in cast(list[str], value) if predicate(item)]
    if len(matches) != 1:
        raise AssertionError(f"public report must contain exactly one {label}")
    return matches[0]


def _parse_colon_detail(value: str) -> dict[str, str]:
    parts = value.split(":")
    result: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, content = part.partition("=")
        if separator:
            result[key] = content
    return result


def _weight_bounds_for_code(
    values: list[str],
    *,
    code: str,
    label: str,
) -> tuple[Decimal, Decimal]:
    """Parse one public lower/upper weight detail for an exact report identity."""

    value = _one_text(
        values,
        predicate=lambda item: item.startswith(f"{code}:"),
        label=f"{label} for {code}",
    )
    range_text = value[len(code) + 1 :].partition("/")[0]
    lower_text, separator, upper_text = range_text.partition("..")
    if not separator or not lower_text or not upper_text:
        raise AssertionError(f"{label} for {code} has no explicit lower/upper weights")
    return _decimal_text(lower_text), _decimal_text(upper_text)


__all__ = (
    "Q3ConstituentFact",
    "RetainedQ3ReportFacts",
    "RetainedSinaSupplementalCapture",
    "add_isolated_etf_position",
    "assert_public_etf_partial_risk_report",
    "build_q3_report_admission_request",
    "build_supplemental_etf_quote_admission_requests",
    "load_q3_report_facts",
    "load_supplemental_sina_capture",
)
