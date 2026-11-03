"""Typed, opt-in admission of explicit Risk Center source facts to RawPayload."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, TypedDict, cast

from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SinaQuoteCapture,
)
from apps.risk_center.application.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskETFReportPublicationCapture,
)
from apps.risk_center.application.portfolio_risk_source_codec import (
    PortfolioRiskSourcePayload,
    decode_portfolio_risk_source_payload,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision

PortfolioRiskInputKind = Literal[
    "valuation",
    "industry_membership",
    "etf_report",
    "capacity_window",
    "execution_session_state",
]


class PortfolioRiskValuationFacts(TypedDict):
    """Explicit normalized valuation fields; missing source facts stay null."""

    price: str | None
    asset_kind: str | None
    quantity_unit: str | None
    price_unit: str | None


class PortfolioRiskIndustryMembershipFacts(TypedDict):
    """Explicit taxonomy and membership window supplied by a qualified source."""

    taxonomy_id: str
    taxonomy_kind: str
    provider_id: str
    provider_version: str
    industry_code: str
    effective_from: str | None
    effective_end_state: str
    effective_until: str | None


class PortfolioRiskETFConstituentFacts(TypedDict):
    """One explicitly disclosed constituent; no undisclosed rows are inferred."""

    asset_code: str
    weight_fraction: str
    kind: Literal["equity", "cash", "other"]


class PortfolioRiskETFReportFacts(TypedDict):
    """Explicit report date and disclosed constituents for one ETF source."""

    report_date: str
    constituents: list[PortfolioRiskETFConstituentFacts]


class PortfolioRiskCapacityValueFacts(TypedDict):
    """One source value and its source-declared unit, both nullable."""

    value: str | None
    unit: str | None


class PortfolioRiskCapacityWindowFacts(TypedDict):
    """Explicit source window; values and units are never defaulted."""

    window_kind: Literal["session_cumulative", "rolling_sessions"]
    start: str
    end: str
    sessions: int
    volume: PortfolioRiskCapacityValueFacts
    amount: PortfolioRiskCapacityValueFacts


class PortfolioRiskExecutionSessionStateFacts(TypedDict):
    """Source-provided session state with unknown date/status left null."""

    session_date: str | None
    suspended: bool | None


class PortfolioRiskSinaQuoteCaptureMetadata(TypedDict):
    """Original HTTP transport facts needed to rebuild a retained Sina capture."""

    asset_code: str
    requested_url: str
    final_url: str
    request_started_at: str
    response_completed_at: str
    http_status: int
    http_date: str | None
    content_type: str | None
    charset: str | None
    content_encoding: str | None


PortfolioRiskAdmissionFacts = (
    PortfolioRiskValuationFacts
    | PortfolioRiskIndustryMembershipFacts
    | PortfolioRiskETFReportFacts
    | PortfolioRiskCapacityWindowFacts
    | PortfolioRiskExecutionSessionStateFacts
)


class PortfolioRiskSourceAdmissionDocument(TypedDict):
    """Operator document shape kept separate from the retained output manifest."""

    schema_version: str
    kind: PortfolioRiskInputKind
    asset_code: str
    security_id: str
    source_record_id: str
    original_url: str | None
    captured_at: str
    source_evidence: Mapping[str, object]
    facts: PortfolioRiskAdmissionFacts


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourceAdmissionRequest:
    """Original response bytes and explicitly normalized source facts."""

    kind: PortfolioRiskInputKind
    asset_code: str
    security_id: str
    source_record_id: str
    original_url: str | None
    captured_at: datetime
    source_evidence: PortfolioRiskSourcePayload
    facts: PortfolioRiskAdmissionFacts
    original_body: bytes = field(repr=False)
    capture_receipt: PortfolioRiskCaptureReceipt | None = None
    sina_capture: SinaQuoteCapture | None = field(default=None, repr=False)
    etf_publication_capture: PortfolioRiskETFReportPublicationCapture | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Reject inconsistent identity or an untrustworthy local capture clock."""

        if self.kind not in (
            "valuation",
            "industry_membership",
            "etf_report",
            "capacity_window",
            "execution_session_state",
        ):
            raise ValueError("risk_input_kind_unsupported")
        for field_name, value in (
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_record_id", self.source_record_id),
        ):
            if (
                type(value) is not str
                or not value
                or value.strip() != value
                or any(character.isspace() for character in value)
            ):
                raise ValueError(f"{field_name}_invalid")
        if type(self.source_evidence) is not PortfolioRiskSourcePayload:
            raise TypeError("source_evidence_must_be_portfolio_risk_source_payload")
        if self.source_evidence.source_record_id != self.source_record_id:
            raise ValueError("risk_input_source_record_identity_mismatch")
        if self.original_url is not None and type(self.original_url) is not str:
            raise TypeError("original_url_must_be_text_or_none")
        if (
            type(self.captured_at) is not datetime
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
        ):
            raise ValueError("captured_at_must_be_aware_datetime")
        if type(self.original_body) is not bytes or not self.original_body:
            raise ValueError("original_body_must_be_nonempty_bytes")
        if self.capture_receipt is not None:
            capture_receipt = self.capture_receipt
            if type(capture_receipt) is not PortfolioRiskCaptureReceipt:
                raise TypeError("capture_receipt_must_be_a_typed_capture_receipt")
            if (
                capture_receipt.source_id != self.source_evidence.source_id
                or capture_receipt.source_record_id != self.source_record_id
                or capture_receipt.original_body_sha256
                != self.source_evidence.original_payload_sha256
            ):
                raise ValueError("capture_receipt_identity_or_hash_mismatch")
            if capture_receipt.response_completed_at != self.captured_at:
                raise ValueError("capture_receipt_clock_must_match_captured_at")
            if (
                capture_receipt.body_size_bytes != len(self.original_body)
                or not capture_receipt.body_complete
            ):
                raise ValueError("capture_receipt_body_must_match_complete_original")
            if not 200 <= capture_receipt.http_status < 300:
                raise ValueError("capture_receipt_http_status_must_be_successful")
        if self.sina_capture is not None:
            capture = self.sina_capture
            capture.__post_init__()
            sina_receipt = self.capture_receipt
            quote = capture.quote
            if (
                self.kind != "execution_session_state"
                or type(sina_receipt) is not PortfolioRiskCaptureReceipt
                or self.source_evidence.source_id != SINA_QUOTE_SOURCE_ID
                or self.asset_code != capture.asset_code
                or self.original_url != capture.requested_url
                or capture.body != self.original_body
                or capture.body_sha256 != sina_receipt.original_body_sha256
                or capture.body_size_bytes != sina_receipt.body_size_bytes
                or capture.http_status != sina_receipt.http_status
                or capture.response_completed_at != sina_receipt.response_completed_at
                or capture.response_completed_at != self.captured_at
                or quote is None
                or quote.source_observed_at is None
                or self.source_evidence.observed_at != quote.source_observed_at
            ):
                raise ValueError("sina_capture_must_match_session_source_and_receipt")
        if self.etf_publication_capture is not None:
            publication_capture = self.etf_publication_capture
            if type(publication_capture) is not PortfolioRiskETFReportPublicationCapture:
                raise TypeError("etf_publication_capture_must_use_the_typed_capture_dto")
            publication_capture.__post_init__()
            publication_receipt = publication_capture.receipt
            if self.kind != "etf_report" or self.capture_receipt is None:
                raise ValueError("etf_publication_capture_requires_an_etf_report_pdf_receipt")
            if publication_receipt.capture_id == self.capture_receipt.capture_id:
                raise ValueError("ETF PDF and publication page need distinct capture IDs")
            if (
                self.source_evidence.observation_precision is not SourceObservationPrecision.DATE
                or self.source_evidence.observed_on != publication_capture.publication_on
                or self.source_evidence.observed_at is not None
            ):
                raise ValueError("etf_publication_date_must_match_the_original_DATE_observation")
            if (
                publication_receipt.original_body_sha256
                != hashlib.sha256(publication_capture.original_body).hexdigest()
                or publication_receipt.body_size_bytes != len(publication_capture.original_body)
                or not publication_receipt.body_complete
                or not 200 <= publication_receipt.http_status < 300
            ):
                raise ValueError("etf_publication_receipt_must_match_its_complete_page_body")
        if not isinstance(self.facts, Mapping) or any(type(key) is not str for key in self.facts):
            raise TypeError("facts_must_be_a_string_keyed_mapping")


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourceAdmissionResult:
    """Candidate RawPayload and whether the explicit write option was used."""

    payload: RawPayload
    stored: bool


class PortfolioRiskAdmissionManifestFactory(Protocol):
    """Build the exact retained-input manifest from typed request values."""

    def build_payload(self, request: PortfolioRiskSourceAdmissionRequest) -> RawPayload:
        """Validate normalized facts and build a hash-bound RawPayload candidate."""
        ...


class PortfolioRiskRawPayloadWriter(Protocol):
    """Write through Data Center's public RawPayload application boundary."""

    def land(self, payload: RawPayload) -> RawPayload:
        """Persist one already validated immutable raw payload."""
        ...


class PortfolioRiskSourceAdmissionError(ValueError):
    """Input or immutable-store result did not satisfy the admission contract."""

    def __init__(self, code: str) -> None:
        """Keep an operator-safe stable admission error code."""

        self.code = code
        super().__init__(code)


class PortfolioRiskSourceAdmissionUseCase:
    """Create a dry-run candidate by default and write only on explicit request."""

    def __init__(
        self,
        *,
        manifest_factory: PortfolioRiskAdmissionManifestFactory,
        writer: PortfolioRiskRawPayloadWriter,
    ) -> None:
        """Inject the source-manifest codec and public RawPayload write adapter."""

        self._manifest_factory = manifest_factory
        self._writer = writer

    def execute(
        self,
        request: PortfolioRiskSourceAdmissionRequest,
        *,
        persist: bool = False,
    ) -> PortfolioRiskSourceAdmissionResult:
        """Validate/build a candidate and persist it only when ``persist`` is true."""

        if type(request) is not PortfolioRiskSourceAdmissionRequest:
            raise TypeError("request_must_be_portfolio_risk_source_admission_request")
        if type(persist) is not bool:
            raise TypeError("persist_must_be_boolean")
        payload = self._manifest_factory.build_payload(request)
        if type(payload) is not RawPayload:
            raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_PAYLOAD_INVALID")
        if not persist:
            return PortfolioRiskSourceAdmissionResult(payload=payload, stored=False)
        stored = self._writer.land(payload)
        if type(stored) is not RawPayload or stored != payload:
            raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_STORE_CONFLICT")
        return PortfolioRiskSourceAdmissionResult(payload=stored, stored=True)


def parse_portfolio_risk_source_admission_request(
    document: object,
    *,
    original_body: bytes,
    capture_receipt: PortfolioRiskCaptureReceipt | None = None,
    sina_capture: SinaQuoteCapture | None = None,
    etf_publication_capture: PortfolioRiskETFReportPublicationCapture | None = None,
) -> PortfolioRiskSourceAdmissionRequest:
    """Narrow admission fields and verify supplied typed response captures."""

    if not isinstance(document, Mapping) or any(type(key) is not str for key in document):
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_DOCUMENT_INVALID")
    expected = frozenset(
        {
            "schema_version",
            "kind",
            "asset_code",
            "security_id",
            "source_record_id",
            "original_url",
            "captured_at",
            "source_evidence",
            "facts",
        }
    )
    if set(document) != expected:
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_DOCUMENT_FIELDS_INVALID")
    if document["schema_version"] != "ash07.source_admission_request.v1":
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_SCHEMA_UNSUPPORTED")
    raw_kind = document["kind"]
    if type(raw_kind) is not str or raw_kind not in (
        "valuation",
        "industry_membership",
        "etf_report",
        "capacity_window",
        "execution_session_state",
    ):
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_KIND_UNSUPPORTED")
    raw_evidence = document["source_evidence"]
    if not isinstance(raw_evidence, Mapping) or any(type(key) is not str for key in raw_evidence):
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_SOURCE_INVALID")
    try:
        evidence = decode_portfolio_risk_source_payload(cast(Mapping[str, object], raw_evidence))
        captured_at = _aware_datetime(document["captured_at"], "captured_at")
    except (TypeError, ValueError) as exc:
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_SOURCE_INVALID") from exc
    facts = document["facts"]
    if not isinstance(facts, Mapping) or any(type(key) is not str for key in facts):
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_FACTS_INVALID")
    original_url = document["original_url"]
    if original_url is not None and type(original_url) is not str:
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_URL_INVALID")
    try:
        return PortfolioRiskSourceAdmissionRequest(
            kind=cast(PortfolioRiskInputKind, raw_kind),
            asset_code=_required_identity(document["asset_code"], "asset_code"),
            security_id=_required_identity(document["security_id"], "security_id"),
            source_record_id=_required_identity(
                document["source_record_id"],
                "source_record_id",
            ),
            original_url=original_url,
            captured_at=captured_at,
            source_evidence=evidence,
            facts=cast(PortfolioRiskAdmissionFacts, facts),
            original_body=original_body,
            capture_receipt=capture_receipt,
            sina_capture=sina_capture,
            etf_publication_capture=etf_publication_capture,
        )
    except (TypeError, ValueError) as exc:
        raise PortfolioRiskSourceAdmissionError("RISK_INPUT_ADMISSION_DOCUMENT_INVALID") from exc


def _required_identity(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name}_invalid")
    return value


def _aware_datetime(value: object, field_name: str) -> datetime:
    if type(value) is not str:
        raise TypeError(f"{field_name}_must_be_iso_datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}_must_be_iso_datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name}_must_retain_timezone")
    return parsed


__all__ = (
    "PortfolioRiskAdmissionFacts",
    "PortfolioRiskAdmissionManifestFactory",
    "PortfolioRiskInputKind",
    "PortfolioRiskRawPayloadWriter",
    "PortfolioRiskSourceAdmissionDocument",
    "PortfolioRiskSourceAdmissionError",
    "PortfolioRiskSourceAdmissionRequest",
    "PortfolioRiskSourceAdmissionResult",
    "PortfolioRiskSourceAdmissionUseCase",
    "PortfolioRiskSinaQuoteCaptureMetadata",
    "PortfolioRiskCaptureReceipt",
    "parse_portfolio_risk_source_admission_request",
)
