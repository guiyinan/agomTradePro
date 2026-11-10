"""Capture exact public SZSE disclosure bytes without inventing publication clocks."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import requests
from django.utils import timezone
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventType,
    SzseDistributionTerms,
)
from core.exceptions import DataFetchError
from shared.numeric import safe_float

_PATH = re.compile(
    r"^/(?:download/)?disc/disk[0-9]+/finalpage/[0-9]{4}-[0-9]{2}-[0-9]{2}/"
    r"(?P<document_id>[0-9a-fA-F-]{36})\.PDF$"
)
_MAX_BODY_BYTES = 16 * 1024 * 1024
_HEADER_SECURITY_CODE = re.compile(r"(?:证券|股票)代码\s*[:：]\s*([0-9]{6})")
_CHINESE_DATE = r"([0-9]{4})\s*年\s*([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日"
_RECORD_DATE = re.compile(r"股权登记日为\s*[:：]\s*" + _CHINESE_DATE)
_EX_DATE = re.compile(r"(?:除权日（除息日）|除权除息日)为\s*[:：]\s*" + _CHINESE_DATE)
_PAYMENT_DATE = re.compile(r"现金红利将于\s*" + _CHINESE_DATE)
_CASH_PER_TEN = re.compile(r"每\s*10\s*股\s*派发现金(?:红利|股利)\s*([0-9]+(?:\.[0-9]+)?)\s*元")
_SHARES_PER_TEN = re.compile(r"每\s*10\s*股\s*转增\s*([0-9]+(?:\.[0-9]+)?)\s*股")


class OfficialDisclosureCaptureError(DataFetchError):
    """The official disclosure URL or returned PDF cannot be trusted."""

    default_message = "交易所公告原文无法核验。"
    default_code = "OFFICIAL_DISCLOSURE_CAPTURE_INVALID"


@dataclass(frozen=True, slots=True)
class CapturedOfficialSzsePdf:
    """Verified body and capture clock; the URL date is not a publication timestamp."""

    source_url: str
    source_document_id: str
    first_seen_at: datetime
    body_sha256: str
    body: bytes


def capture_official_szse_pdf(source_url: str) -> CapturedOfficialSzsePdf:
    """Fetch an exact official PDF with a bounded response and no redirect."""

    if type(source_url) is not str:
        raise OfficialDisclosureCaptureError("SZSE PDF URL is invalid")
    try:
        parsed = urlsplit(source_url)
        port = parsed.port
    except ValueError as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF URL is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "disc.static.szse.cn"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise OfficialDisclosureCaptureError("unapproved SZSE PDF URL")
    match = _PATH.fullmatch(parsed.path)
    if match is None:
        raise OfficialDisclosureCaptureError("SZSE PDF path is not source-native")
    try:
        document_id = str(UUID(match.group("document_id")))
    except ValueError as exc:
        raise OfficialDisclosureCaptureError("SZSE document identity is invalid") from exc
    try:
        response = requests.get(
            source_url,
            timeout=(5, 20),
            allow_redirects=False,
            stream=True,
            headers={"Accept": "application/pdf"},
        )
    except requests.RequestException as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF request failed") from exc
    try:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        chunks: list[bytes] = []
        size = 0
        if response.status_code == 200 and content_type == "application/pdf":
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > _MAX_BODY_BYTES:
                    raise OfficialDisclosureCaptureError("SZSE PDF exceeds size limit")
                chunks.append(chunk)
        body = b"".join(chunks)
        first_seen_at = timezone.now()
    except requests.RequestException as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF body read failed") from exc
    finally:
        response.close()
    if (
        response.status_code != 200
        or content_type != "application/pdf"
        or type(body) is not bytes
        or len(body) < 8
        or len(body) > _MAX_BODY_BYTES
        or not body.startswith(b"%PDF-")
        or b"%%EOF" not in body[-1024:]
    ):
        raise OfficialDisclosureCaptureError("SZSE response is not a complete PDF")
    return CapturedOfficialSzsePdf(
        source_url=source_url,
        source_document_id=document_id,
        first_seen_at=first_seen_at,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body=body,
    )


def verify_szse_pdf_security_code(
    capture: CapturedOfficialSzsePdf, expected_security_code: str
) -> str:
    """Confirm the exact security from the official PDF header before event mapping."""

    if type(expected_security_code) is not str or not re.fullmatch(
        r"[0-9]{6}", expected_security_code
    ):
        raise OfficialDisclosureCaptureError("expected security code is invalid")
    if hashlib.sha256(capture.body).hexdigest() != capture.body_sha256:
        raise OfficialDisclosureCaptureError("PDF body hash mismatch")
    try:
        reader = PdfReader(BytesIO(capture.body), strict=True)
        if not reader.pages or len(reader.pages) > 100:
            raise OfficialDisclosureCaptureError("SZSE PDF page count is invalid")
        header = reader.pages[0].extract_text()[:512]
    except OfficialDisclosureCaptureError:
        raise
    except (OSError, TypeError, ValueError, KeyError, PdfReadError) as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF text cannot be verified") from exc
    codes = set(_HEADER_SECURITY_CODE.findall(header))
    if codes != {expected_security_code}:
        raise OfficialDisclosureCaptureError("SZSE PDF security code does not match")
    return expected_security_code


def classify_szse_pdf_disclosure(
    capture: CapturedOfficialSzsePdf, expected_security_code: str
) -> tuple[str, SecurityDisclosureEventType]:
    """Classify only unambiguous cash or share distributions from verified PDF text."""

    verify_szse_pdf_security_code(capture, expected_security_code)
    try:
        reader = PdfReader(BytesIO(capture.body), strict=True)
        pages = tuple(page.extract_text() for page in reader.pages)
    except (OSError, TypeError, ValueError, KeyError, PdfReadError) as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF text cannot be classified") from exc
    if any(type(page) is not str for page in pages):
        raise OfficialDisclosureCaptureError("SZSE PDF page text is unavailable")
    text = "\n".join(pages)
    title = next(
        (
            line.strip()
            for line in pages[0].splitlines()
            if (line.strip().endswith(("公告", "公告（更正后）")) and "公告编号" not in line)
        ),
        "",
    )
    if not title or len(title) > 120:
        raise OfficialDisclosureCaptureError("SZSE PDF announcement title is unavailable")
    if "权益分派实施的更正公告" in title:
        return title, SecurityDisclosureEventType.CORRECTION_NOTICE
    if "权益分派实施公告" not in title:
        return title, SecurityDisclosureEventType.UNKNOWN
    cash = bool(re.search(r"每\s*10\s*股\s*派发现金(?:红利|股利)\s*[0-9]", text))
    shares = bool(re.search(r"每\s*10\s*股\s*转增\s*[0-9]", text))
    if cash == shares:
        return title, SecurityDisclosureEventType.UNKNOWN
    return (
        title,
        (
            SecurityDisclosureEventType.CASH_DIVIDEND
            if cash
            else SecurityDisclosureEventType.STOCK_DIVIDEND
        ),
    )


def extract_szse_distribution_dates(
    capture: CapturedOfficialSzsePdf, expected_security_code: str
) -> tuple[date | None, date | None]:
    """Retain date-only record/ex clocks only when the PDF states them unambiguously."""

    verify_szse_pdf_security_code(capture, expected_security_code)
    try:
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(capture.body)).pages)
    except (OSError, TypeError, ValueError, KeyError, PdfReadError) as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF dates cannot be read") from exc

    def unique_date(pattern: re.Pattern[str]) -> date | None:
        values = set(pattern.findall(text))
        if len(values) != 1:
            return None
        try:
            return date(*(int(part) for part in next(iter(values))))
        except ValueError:
            return None

    return unique_date(_RECORD_DATE), unique_date(_EX_DATE)


def extract_szse_distribution_terms(
    capture: CapturedOfficialSzsePdf, expected_security_code: str
) -> SzseDistributionTerms | None:
    """Extract only exact, unambiguous terms from one verified implementation notice."""

    _, event_type = classify_szse_pdf_disclosure(capture, expected_security_code)
    record_date, ex_date = extract_szse_distribution_dates(capture, expected_security_code)
    if (
        event_type
        not in (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            SecurityDisclosureEventType.STOCK_DIVIDEND,
        )
        or record_date is None
        or ex_date is None
    ):
        return None
    try:
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(capture.body)).pages)
    except (OSError, TypeError, ValueError, KeyError, PdfReadError) as exc:
        raise OfficialDisclosureCaptureError("SZSE PDF economic terms cannot be read") from exc

    def unique_amount(pattern: re.Pattern[str]) -> Decimal | None:
        values = set(pattern.findall(text))
        if len(values) != 1:
            return None
        raw = next(iter(values))
        if safe_float(raw) is None:
            return None
        amount = Decimal(raw)
        return amount if amount.is_finite() and amount > 0 else None

    cash_per_ten = unique_amount(_CASH_PER_TEN)
    shares_per_ten = unique_amount(_SHARES_PER_TEN)
    if event_type is SecurityDisclosureEventType.CASH_DIVIDEND:
        payment_matches = set(_PAYMENT_DATE.findall(text))
        if cash_per_ten is None or shares_per_ten is not None or len(payment_matches) != 1:
            return None
        try:
            payment_date = date(*(int(part) for part in next(iter(payment_matches))))
        except ValueError:
            return None
        tax_treatment = (
            "deferred_withholding"
            if "暂不扣缴个人所得税" in text and "待个人转让股票时" in text
            else None
        )
        return SzseDistributionTerms(
            record_date=record_date,
            ex_date=ex_date,
            payment_date=payment_date,
            cash_per_ten=cash_per_ten,
            shares_per_ten=None,
            tax_treatment=tax_treatment,
        )
    if shares_per_ten is None or cash_per_ten is not None:
        return None
    return SzseDistributionTerms(
        record_date=record_date,
        ex_date=ex_date,
        payment_date=None,
        cash_per_ten=None,
        shares_per_ten=shares_per_ten,
        tax_treatment="not_applicable" if "不涉及扣税情形" in text else None,
    )


class OfficialSzsePdfBodyStore:
    """Retain public PDF bytes by content hash with atomic first-writer semantics."""

    def __init__(self, root: Path) -> None:
        """Bind a caller-configured artifact directory."""

        if not isinstance(root, Path):
            raise OfficialDisclosureCaptureError("PDF store root must be a Path")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve(strict=True)

    def retain(self, capture: CapturedOfficialSzsePdf) -> Path:
        """Store exact bytes once and reject a mismatching existing artifact."""

        if hashlib.sha256(capture.body).hexdigest() != capture.body_sha256:
            raise OfficialDisclosureCaptureError("PDF body hash mismatch")
        target = self._root / f"{capture.body_sha256}.pdf"
        temporary = self._root / f".{uuid4().hex}.partial"
        try:
            with temporary.open("xb") as stream:
                stream.write(capture.body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        except OSError as exc:
            raise OfficialDisclosureCaptureError("PDF body retention failed") from exc
        finally:
            temporary.unlink(missing_ok=True)
        if (
            not target.is_file()
            or hashlib.sha256(target.read_bytes()).hexdigest() != capture.body_sha256
        ):
            raise OfficialDisclosureCaptureError("retained PDF failed integrity check")
        return target

    def read(self, body_sha256: str) -> bytes:
        """Read one stored body only after validating its exact hash."""

        if not re.fullmatch(r"[0-9a-f]{64}", body_sha256):
            raise OfficialDisclosureCaptureError("PDF body hash is invalid")
        target = self._root / f"{body_sha256}.pdf"
        try:
            body = target.read_bytes()
        except OSError as exc:
            raise OfficialDisclosureCaptureError("PDF body is unavailable") from exc
        if hashlib.sha256(body).hexdigest() != body_sha256:
            raise OfficialDisclosureCaptureError("stored PDF body hash mismatch")
        return body
