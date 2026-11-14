"""Synthetic transport fixtures that retain the real SZSE capture and Audit pipeline.

These responses are explicitly controlled test inputs.  They exercise the same
listing, PDF, parser, body-store, coverage, and Audit code as the owner workflow,
but they are not official-source evidence or a production-source acceptance.
"""

from __future__ import annotations

import html
import ipaddress
import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from django.utils import timezone
from requests import PreparedRequest, Response, Session
from urllib3.response import HTTPResponse

from apps.data_center.application.statutory_source_documents import (
    AppendStatutorySourceDocumentBundleUseCase,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceDocumentBundle
from apps.data_center.infrastructure.egress_models import EgressRoutingRuleModel
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from apps.data_center.infrastructure.statutory_source_body_store import StatutorySourceBodyStore
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from apps.data_center.statutory_source_capture_composition import (
    ConfiguredStatutorySourceCaptureService,
)
from apps.simulated_trading.corporate_action_tax_statutory_qualification import (
    tax_assessment_source_bundle,
)
from tests.support.simulated_tax_model_native_sources import (
    install_synthetic_document_transport,
    synthetic_statutory_bodies,
    synthetic_szse_distribution_pdf,
)

_LISTING_HOST = "www.szse.cn"
_PDF_HOST = "disc.static.szse.cn"
_LISTING_PATH = "/api/disc/announcement/annList"
_LANDING_PATH = "/disclosure/listed/notice/"
_TAX_SOURCE_HOST = "fgk.chinatax.gov.cn"
_TAX_PROFILE_CODE = "ASH05-OWNER-QA"
_TAX_REGION = "ash05-native-qa"
_TAX_1997_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193235/content.html"
_TAX_1998_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193247/content.html"
_TAX_1997_TITLE = "国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知"
_TAX_1998_TITLE = (
    "国家税务总局关于原城市信用社在转制为城市合作银行过程中个人股增值所得应纳个人所得税的批复"
)
_TAX_1997_NUMBER = "国税发〔1997〕198号"
_TAX_1998_NUMBER = "国税函〔1998〕289号"
_TAX_1994_REFERENCE = "《国家税务总局关于印发〈征收个人所得税若干问题的规定〉的通知》"
_TAX_1994_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100011/c5216297/content.html"
_TAX_1997_REFERENCE = f"《{_TAX_1997_TITLE}》"


def _capital_tax_page(
    *,
    title: str,
    legal_number: str,
    source_date: str,
    paragraphs: tuple[str, ...],
    reference: str,
    reference_url: str,
) -> bytes:
    """Build exact parser-layout HTML marked as a synthetic test source."""
    rendered: list[str] = []
    for paragraph in paragraphs:
        if reference in paragraph:
            before, after = paragraph.split(reference, maxsplit=1)
            rendered.append(
                f'<div>{html.escape(before)}<a href="{reference_url}">'
                f"{html.escape(reference)}</a>{html.escape(after)}</div>"
            )
        else:
            rendered.append(f"<div>{html.escape(paragraph)}</div>")
    body = (
        '<!doctype html><html><head><meta charset="utf-8"/>'
        f'<meta name="ArticleTitle" content="{html.escape(title, quote=True)}"/>'
        "</head><body><!-- SYNTHETIC TEST BODY; NOT OFFICIAL SOURCE CONTENT -->"
        '<div class="detials contentLeft">'
        f"<h3>{html.escape(title)}</h3><h5>{html.escape(legal_number)}</h5>"
        '<p class="arc_date"><span class="xg">全文有效</span>'
        f'<span class="date">成文日期：{source_date}</span></p>'
        f"<div class=\"arc_cont\">{''.join(rendered)}</div></div></body></html>"
    )
    return body.encode("utf-8")


def synthetic_capital_tax_bodies() -> dict[str, bytes]:
    """Return exact-shape but expressly synthetic SAT parser inputs.

    They are parser fixtures only and do not claim capture of official bytes,
    current law, or any holder's real tax eligibility.
    """
    first_paragraphs = (
        "近接一些地区和单位来文、来电请示，要求对股份制企业用资本公积金转增个人股本是否征收个人所得税的问题作出明确规定。经研究，现明确如下：",
        "一、股份制企业用资本公积金转增股本不属于股息、红利性质的分配，对个人取得的转增股本数额，不作为个人所得，不征收个人所得税。",
        "二、股份制企业用盈余公积金派发红股属于股息、红利性质的分配，对个人取得的红股数额，应作为个人所得征税。",
        f"各地要严格按照{_TAX_1994_REFERENCE}（国税发[1994]89号）的有关规定执行，没有执行的要尽快纠正。派发红股的股份制企业作为支付所得的单位应按照税法规定履行扣缴义务。",
    )
    second_paragraphs = (
        "重庆市地方税务局：",
        "你局《重庆市地方税务局关于重庆市信用社在转制为重庆城市合作银行过程中个人股增值所得应纳个人所得税问题的请示》（渝地税发[1998]88号）收悉。经研究，现批复如下：",
        "一、在城市信用社改制为城市合作银行过程中，个人以现金或股份及其他形式取得的资产评估增值数额，应当按“利息、股息、红利所得”项目计征个人所得税，税款由城市合作银行负责代扣代缴。",
        f"二、{_TAX_1997_REFERENCE}（国税发[1997]198号）中所表述的“资本公积金”是指股份制企业股票溢价发行收入所形成的资本公积金。将此转增股本由个人取得的数额，不作为应税所得征收个人所得税。而与此不相符合的其他资本公积金分配个人所得部分，应当依法征收个人所得税。",
    )
    return {
        _TAX_1997_URL: _capital_tax_page(
            title=_TAX_1997_TITLE,
            legal_number=_TAX_1997_NUMBER,
            source_date="1997-12-25",
            paragraphs=first_paragraphs,
            reference=_TAX_1994_REFERENCE,
            reference_url=_TAX_1994_URL,
        ),
        _TAX_1998_URL: _capital_tax_page(
            title=_TAX_1998_TITLE,
            legal_number=_TAX_1998_NUMBER,
            source_date="1998-05-15",
            paragraphs=second_paragraphs,
            reference=_TAX_1997_REFERENCE,
            reference_url=_TAX_1997_URL,
        ),
    }


def owner_workflow_statutory_bodies() -> dict[str, bytes]:
    """Combine synthetic cash-tax and capital-tax inputs on one explicit host."""
    cash = synthetic_statutory_bodies()
    return {
        f"https://{_TAX_SOURCE_HOST}/ash05/synthetic-rate": cash[
            "https://example.com/ash05/synthetic-rate"
        ],
        f"https://{_TAX_SOURCE_HOST}/ash05/synthetic-mechanics": cash[
            "https://example.com/ash05/synthetic-mechanics"
        ],
        **synthetic_capital_tax_bodies(),
    }


def append_owner_workflow_statutory_bundles(
    *, body_store_root: Path
) -> tuple[ProviderConfigModel, StatutorySourceDocumentBundle, str, StatutorySourceDocumentBundle]:
    """Capture two typed synthetic bundles through one real Data Center catalog.

    Cash-tax inputs retain the older qualified simulation helper's exact body
    grammar. Capital-law inputs are tagged in-body as synthetic and remain a
    simulation-model test only; neither bundle authenticates its publisher.
    """
    bodies = owner_workflow_statutory_bodies()
    rate_body = bodies[f"https://{_TAX_SOURCE_HOST}/ash05/synthetic-rate"]
    mechanics_body = bodies[f"https://{_TAX_SOURCE_HOST}/ash05/synthetic-mechanics"]
    capital_1997_body = bodies[_TAX_1997_URL]
    capital_1998_body = bodies[_TAX_1998_URL]
    today = timezone.now().date().isoformat()
    revisions = [
        {
            "document_id": "synthetic-rate",
            "source_version": "fixture-v1",
            "canonical_url": f"https://{_TAX_SOURCE_HOST}/ash05/synthetic-rate",
            "issuer": "Synthetic fixture issuer; not a government body",
            "title": "Synthetic rate clauses; no legal authority",
            "legal_number": "SYNTHETIC-NONLEGAL-RATE",
            "publication_date": {"precision": "date", "value": today},
            "effective_date": {"precision": "date", "value": "2015-09-08"},
            "body_sha256": sha256(rate_body).hexdigest(),
            "body_size_bytes": len(rate_body),
        },
        {
            "document_id": "synthetic-mechanics",
            "source_version": "fixture-v1",
            "canonical_url": f"https://{_TAX_SOURCE_HOST}/ash05/synthetic-mechanics",
            "issuer": "Synthetic fixture issuer; not a government body",
            "title": "Synthetic mechanics clauses; no legal authority",
            "legal_number": "SYNTHETIC-NONLEGAL-MECHANICS",
            "publication_date": {"precision": "date", "value": today},
            "effective_date": {"precision": "date", "value": today},
            "body_sha256": sha256(mechanics_body).hexdigest(),
            "body_size_bytes": len(mechanics_body),
        },
        {
            "document_id": "sat-1997-198-synthetic-test",
            "source_version": "synthetic-test-v1",
            "canonical_url": _TAX_1997_URL,
            "issuer": "国家税务总局",
            "title": _TAX_1997_TITLE,
            "legal_number": _TAX_1997_NUMBER,
            "publication_date": {"precision": "date", "value": "1997-12-25"},
            "effective_date": {"precision": "unknown", "value": None},
            "body_sha256": sha256(capital_1997_body).hexdigest(),
            "body_size_bytes": len(capital_1997_body),
        },
        {
            "document_id": "sat-1998-289-synthetic-test",
            "source_version": "synthetic-test-v1",
            "canonical_url": _TAX_1998_URL,
            "issuer": "国家税务总局",
            "title": _TAX_1998_TITLE,
            "legal_number": _TAX_1998_NUMBER,
            "publication_date": {"precision": "date", "value": "1998-05-15"},
            "effective_date": {"precision": "unknown", "value": None},
            "body_sha256": sha256(capital_1998_body).hexdigest(),
            "body_size_bytes": len(capital_1998_body),
        },
    ]
    publisher_code = f"{_TAX_PROFILE_CODE}-{uuid4().hex[:12]}"
    PublisherCatalogModel.objects.using("default").create(
        code=publisher_code,
        canonical_name="ASH05 synthetic source fixtures; not publisher authentication",
        publisher_class="system",
        website=f"https://{_TAX_SOURCE_HOST}/",
        is_active=True,
    )
    provider = ProviderConfigModel.objects.using("default").create(
        name="ASH05 synthetic owner workflow statutory parser sources",
        source_type="public_document",
        is_active=True,
        http_url="",
        api_endpoint="",
        extra_config={
            "statutory_source_catalog": {
                "schema_version": "data_center.statutory_source_catalog.v1",
                "profile_id": f"ash05-synthetic-owner-workflow-{uuid4().hex[:12]}",
                "version": "fixture-v1",
                "publisher_code": publisher_code,
                "enabled": True,
                "allowed_hosts": [_TAX_SOURCE_HOST],
                "max_capture_age_seconds": 3600,
                "documents": [
                    {"revision": revision, "max_bytes": 32768, "allowed_media_types": ["text/html"]}
                    for revision in revisions
                ],
            }
        },
    )
    if type(provider.pk) is not int:
        raise AssertionError("synthetic statutory provider did not receive its database identity")
    EgressRoutingRuleModel.objects.using("default").create(
        provider_id=provider.pk,
        dataset_key="statutory_source_documents",
        domain_pattern=_TAX_SOURCE_HOST,
        deployment_region=_TAX_REGION,
        strategy="direct",
        fixed_egress_id=None,
        priority=1,
        enabled=True,
    )
    service = ConfiguredStatutorySourceCaptureService(
        provider_id=provider.pk,
        body_store_root=body_store_root,
        deployment_region=_TAX_REGION,
        using="default",
    )
    captures = {
        document_id: service.capture_document(
            issuer=issuer, document_id=document_id, source_version=version
        ).capture
        for issuer, document_id, version in (
            ("Synthetic fixture issuer; not a government body", "synthetic-rate", "fixture-v1"),
            (
                "Synthetic fixture issuer; not a government body",
                "synthetic-mechanics",
                "fixture-v1",
            ),
            ("国家税务总局", "sat-1997-198-synthetic-test", "synthetic-test-v1"),
            ("国家税务总局", "sat-1998-289-synthetic-test", "synthetic-test-v1"),
        )
    }
    body_store = StatutorySourceBodyStore(body_store_root, max_body_bytes=32768)
    repository = DjangoStatutorySourceRepository(body_store=body_store, using="default")
    cash_bundle = StatutorySourceDocumentBundle(
        bundle_id=f"ash05-synthetic-cash-tax-{uuid4().hex}",
        version="fixture-v1",
        captures=(captures["synthetic-rate"], captures["synthetic-mechanics"]),
    )
    saved_cash = AppendStatutorySourceDocumentBundleUseCase(repository).execute(cash_bundle).record
    capital_bundle = StatutorySourceDocumentBundle(
        bundle_id=f"ash05-synthetic-capital-tax-{uuid4().hex}",
        version="fixture-v1",
        captures=(
            captures["sat-1997-198-synthetic-test"],
            captures["sat-1998-289-synthetic-test"],
        ),
    )
    saved_capital = (
        AppendStatutorySourceDocumentBundleUseCase(repository).execute(capital_bundle).record
    )
    if saved_cash != cash_bundle or saved_capital != capital_bundle:
        raise AssertionError("retained synthetic statutory bundle differs from its captures")
    cash_revision_set_sha256 = tax_assessment_source_bundle(saved_cash).source_revision_set_sha256
    return provider, saved_cash, cash_revision_set_sha256, saved_capital


@dataclass(slots=True)
class SyntheticSzseCapture:
    """One explicitly synthetic announcement served to the real capture stack."""

    asset_code: str
    published_on: date
    title: str
    pdf_body: bytes
    document_id: str = field(default_factory=lambda: str(uuid4()))
    listing_id: str = field(default_factory=lambda: str(uuid4()))
    announcement_id: int = 880_000_001
    listing_reads: int = 0
    pdf_reads: int = 0

    def __post_init__(self) -> None:
        """Reject malformed synthetic scope before installing any transport."""
        if (
            type(self.asset_code) is not str
            or len(self.asset_code) != 9
            or not self.asset_code[:6].isascii()
            or not self.asset_code[:6].isdecimal()
            or not self.asset_code.endswith(".SZ")
            or type(self.published_on) is not date
            or type(self.title) is not str
            or not self.title
            or type(self.pdf_body) is not bytes
            or not self.pdf_body.startswith(b"%PDF-")
        ):
            raise ValueError("synthetic SZSE capture scope is invalid")

    @property
    def source_url(self) -> str:
        """Return the source-native URL shape consumed by the PDF parser."""
        return (
            "https://disc.static.szse.cn/disc/disk03/finalpage/"
            f"{self.published_on.isoformat()}/{self.document_id}.PDF"
        )

    @property
    def attach_path(self) -> str:
        """Return the exact listed attachment path for the selected PDF."""
        return urlsplit(self.source_url).path

    def listing_row(self) -> dict[str, object]:
        """Return one exact JSON row accepted by the listing source decoder."""
        return {
            "id": self.listing_id,
            "annId": self.announcement_id,
            "title": self.title,
            "publishTime": f"{self.published_on.isoformat()} 00:00:00",
            "secCode": [self.asset_code[:6]],
            "attachFormat": "PDF",
            "attachPath": self.attach_path,
        }


def cash_distribution_capture(
    *,
    asset_code: str,
    published_on: date,
    record_date: date,
    ex_date: date,
    payment_date: date,
    cash_per_ten: str = "2.00",
    title_suffix: str = "",
) -> SyntheticSzseCapture:
    """Build a clearly synthetic cash notice that the real parser can read."""
    security_code = asset_code[:6]
    title = f"平安银行：2026年度权益分派实施公告{title_suffix}"
    lines = (
        title,
        f"股权登记日为：{record_date.year}年{record_date.month}月{record_date.day}日",
        f"除权日（除息日）为：{ex_date.year}年{ex_date.month}月{ex_date.day}日",
        f"每10股派发现金红利{cash_per_ten}元",
        f"现金红利将于{payment_date.year}年{payment_date.month}月{payment_date.day}日发放",
        "暂不扣缴个人所得税，待个人转让股票时计算。",
    )
    return SyntheticSzseCapture(
        asset_code=asset_code,
        published_on=published_on,
        title=title,
        pdf_body=synthetic_szse_distribution_pdf(security_code=security_code, lines=lines),
    )


def share_distribution_capture(
    *,
    asset_code: str,
    published_on: date,
    record_date: date,
    ex_date: date,
    delivery_date: date,
    sellable_date: date,
    shares_per_ten: str = "1.00",
    title_suffix: str = "",
) -> SyntheticSzseCapture:
    """Build synthetic share terms with separately stated delivery and sellable dates."""
    security_code = asset_code[:6]
    title = f"平安银行：2026年度权益分派实施公告{title_suffix}"
    lines = (
        title,
        f"股权登记日为：{record_date.year}年{record_date.month}月{record_date.day}日",
        f"除权日（除息日）为：{ex_date.year}年{ex_date.month}月{ex_date.day}日",
        f"每10股转增{shares_per_ten}股",
        f"新增股份到账日为：{delivery_date.year}年{delivery_date.month}月{delivery_date.day}日",
        f"新增股份上市流通日为：{sellable_date.year}年{sellable_date.month}月{sellable_date.day}日",
        "本次资本公积金来源于股票发行溢价收入所形成的资本公积金，本次转增不涉及扣税情形。",
        "本段为测试用合成公告内容，不代表发行人或任何真实来源。",
    )
    return SyntheticSzseCapture(
        asset_code=asset_code,
        published_on=published_on,
        title=title,
        pdf_body=synthetic_szse_distribution_pdf(security_code=security_code, lines=lines),
    )


def rights_issue_capture(
    *,
    asset_code: str,
    published_on: date,
    record_date: date,
    subscription_start_date: date,
    subscription_end_date: date,
    actual_ex_rights_date: date,
    offered_rights_per_ten: str = "4.00",
    actual_rights_per_ten: str = "3.75",
    price_cny_per_share: str = "3.00",
) -> SyntheticSzseCapture:
    """Build one successful, fully dated rights result for the real parser path."""
    security_code = asset_code[:6]

    def date_text(value: date) -> str:
        return f"{value.year}年{value.month}月{value.day}日"

    lines = (
        f"证券代码：{security_code} 证券简称：平安银行 公告编号：2026-050",
        "平安银行：配股发行结果公告",
        "元 指 人民币元",
        f"本次配股以股权登记日{date_text(record_date)}收市后发行人总股本为基数，",
        f"按每10股配售{offered_rights_per_ten}股的比例向全体A股股东配售。",
        f"本次配股价格为{price_cny_per_share}元/股。",
        f"配股缴款起止日期：{date_text(subscription_start_date)}至{date_text(subscription_end_date)}。",
        "本次配股发行成功。",
        f"截至认购缴款结束日（{date_text(subscription_end_date)}），本次配股发行成功。",
        f"本公告披露当日（{date_text(actual_ex_rights_date)}）即为发行成功的除权基准日",
        f"（配股除权日），实际配股比例相当于每10股配售{actual_rights_per_ten}股。",
        "本文件是明确标记的自动化测试合成材料，不代表发行人或真实发行结果。",
    )
    return SyntheticSzseCapture(
        asset_code=asset_code,
        published_on=published_on,
        title="平安银行：配股发行结果公告",
        pdf_body=synthetic_szse_distribution_pdf(security_code=security_code, lines=lines),
    )


def install_synthetic_szse_capture_transport(
    monkeypatch: pytest.MonkeyPatch,
    capture: SyntheticSzseCapture,
    *,
    statutory_documents: Mapping[str, bytes] | None = None,
    additional_captures: tuple[SyntheticSzseCapture, ...] = (),
) -> SyntheticSzseCapture:
    """Intercept only outbound HTTP while preserving all real source and Audit code.

    Existing tax-only tests keep their ``example.com`` fixture transport. A
    combined cash/share journey may instead provide all synthetic statutory
    bodies under one explicitly configured catalog host. No socket is opened.
    """
    install_synthetic_document_transport(monkeypatch)
    synthetic_document_send = requests.Session.send
    actual_getaddrinfo = socket.getaddrinfo
    captures = (capture, *additional_captures)
    if (
        type(additional_captures) is not tuple
        or any(type(item) is not SyntheticSzseCapture for item in captures)
        or any(item.asset_code != capture.asset_code for item in captures)
        or len({item.attach_path for item in captures}) != len(captures)
        or len({item.listing_id for item in captures}) != len(captures)
        or len({item.document_id for item in captures}) != len(captures)
    ):
        raise ValueError("synthetic SZSE captures must have one exact security and unique sources")
    captures_by_path = {item.attach_path: item for item in captures}

    def synthetic_statutory_dns(host: object, port: object, *args: Any, **kwargs: Any) -> Any:
        """Supply only this synthetic document host's transport address.

        The real DNS-result validation, public-IP checks, Host/SNI binding,
        source capture and Audit remain active. No real website is fetched.
        """
        if host == _TAX_SOURCE_HOST:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return actual_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", synthetic_statutory_dns)
    if statutory_documents is not None:
        if not statutory_documents or any(
            type(url) is not str
            or type(body) is not bytes
            or urlsplit(url).scheme != "https"
            or urlsplit(url).hostname != _TAX_SOURCE_HOST
            or not body
            for url, body in statutory_documents.items()
        ):
            raise ValueError("synthetic retained-source URLs and bodies must be explicit")
        statutory_by_path = {urlsplit(url).path: body for url, body in statutory_documents.items()}
        if len(statutory_by_path) != len(statutory_documents):
            raise ValueError("synthetic retained-source paths must be unique")
    else:
        statutory_by_path = {}

    def response_for(
        request: PreparedRequest,
        *,
        status: int,
        content_type: str,
        body: bytes,
    ) -> Response:
        """Return a bounded requests response backed by in-memory bytes."""
        response = Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.headers.update({"Content-Type": content_type, "Content-Length": str(len(body))})
        response.raw = HTTPResponse(
            body=BytesIO(body),
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
            preload_content=False,
            decode_content=False,
        )
        response._content_consumed = False
        return response

    def send(
        session: Session,
        request: PreparedRequest,
        **kwargs: Any,
    ) -> Response:
        """Serve only the exact synthetic SZSE listing and listed PDF."""
        del kwargs
        parsed = urlsplit(request.url or "")
        host_header = request.headers.get("Host", "")
        host = host_header.partition(":")[0].lower() or (parsed.hostname or "").lower()
        if host == _LISTING_HOST and parsed.path == _LANDING_PATH and request.method == "GET":
            return response_for(
                request,
                status=200,
                content_type="text/html; charset=utf-8",
                body=b"<!doctype html><title>synthetic SZSE listing fixture</title>",
            )
        if host == _LISTING_HOST and parsed.path == _LISTING_PATH and request.method == "POST":
            try:
                payload_value = json.loads(request.body or b"{}")
            except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AssertionError(
                    "SZSE source sent an invalid synthetic listing request"
                ) from error
            payload = payload_value if isinstance(payload_value, dict) else {}
            if (
                payload.get("stock") != [capture.asset_code[:6]]
                or payload.get("channelCode") != ["listedNotice_disc"]
                or payload.get("pageNum") != 1
                or type(payload.get("pageSize")) is not int
                or not isinstance(payload.get("seDate"), list)
                or len(payload["seDate"]) != 2
            ):
                raise AssertionError(
                    "SZSE capture request did not match the synthetic owner window"
                )
            capture.listing_reads += 1
            included = tuple(
                item
                for item in captures
                if payload["seDate"][0] <= item.published_on.isoformat() <= payload["seDate"][1]
            )
            body = json.dumps(
                {
                    "announceCount": len(included),
                    "data": [item.listing_row() for item in included],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            return response_for(
                request,
                status=200,
                content_type="application/json; charset=utf-8",
                body=body,
            )
        selected_capture = captures_by_path.get(parsed.path)
        if host == _PDF_HOST and selected_capture is not None and request.method == "GET":
            selected_capture.pdf_reads += 1
            return response_for(
                request,
                status=200,
                content_type="application/pdf",
                body=selected_capture.pdf_body,
            )
        if host == _TAX_SOURCE_HOST and parsed.path in statutory_by_path:
            try:
                address = ipaddress.ip_address(parsed.hostname or "")
            except ValueError as error:
                raise AssertionError("statutory capture must use a pinned IP target") from error
            if (
                request.method != "GET"
                or parsed.scheme != "https"
                or parsed.port not in {None, 443}
                or parsed.query
                or parsed.fragment
                or not address.is_global
                or request.headers.get("Accept-Encoding") != "identity"
            ):
                raise AssertionError("unexpected synthetic statutory request shape")
            return response_for(
                request,
                status=200,
                content_type="text/html; charset=utf-8",
                body=statutory_by_path[parsed.path],
            )
        if host == "example.com":
            return synthetic_document_send(session, request)
        raise AssertionError(
            "unexpected nonlocal HTTP request in owner workflow test: "
            f"{request.method} {host}{parsed.path}"
        )

    monkeypatch.setattr(requests.Session, "send", send)
    return capture


__all__ = (
    "SyntheticSzseCapture",
    "cash_distribution_capture",
    "install_synthetic_szse_capture_transport",
    "rights_issue_capture",
    "share_distribution_capture",
)
