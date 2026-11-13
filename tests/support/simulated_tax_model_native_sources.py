"""Native-test fixture helpers for synthetic, unqualified tax source evidence."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from celery import current_app as celery_current_app
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from requests import PreparedRequest, Response, Session
from urllib3.response import HTTPResponse

from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceMappingUseCase,
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.statutory_source_documents import (
    AppendStatutorySourceDocumentBundleUseCase,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDocumentBundle,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.egress_models import EgressRoutingRuleModel
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.statutory_source_body_store import StatutorySourceBodyStore
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
    TushareInstrumentReferenceSource,
)
from apps.data_center.statutory_source_capture_composition import (
    ConfiguredStatutorySourceCaptureService,
)
from apps.simulated_trading.corporate_action_tax_statutory_qualification import (
    tax_assessment_source_bundle,
)
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

_PUBLISHER_CODE = "ASH05-SYNTHETIC-UNQUALIFIED"
_REGION = "ash05-native-qa"
_RATE_LEGAL_NUMBER = "SYNTHETIC-NONLEGAL-RATE"
_MECHANICS_LEGAL_NUMBER = "SYNTHETIC-NONLEGAL-MECHANICS"

_RATE_PARAGRAPHS = (
    "一、个人从公开发行和转让市场取得的上市公司股票，持股期限超过1年的，股息红利所得暂免征收个人所得税。",
    "个人从公开发行和转让市场取得的上市公司股票，持股期限在1个月以内（含1个月）的，其股息红利所得全额计入应纳税所得额；持股期限在1个月以上至1年（含1年）的，暂减按50%计入应纳税所得额；上述所得统一适用20%的税率计征个人所得税。",
    "二、上市公司派发股息红利时，对个人持股1年以内（含1年）的，上市公司暂不扣缴个人所得税；待个人转让股票时，证券登记结算公司根据其持股期限计算应纳税额，由证券公司等股份托管机构从个人资金账户中扣收并划付证券登记结算公司，后续划转程序依明示通知执行。",
    f"三、上市公司股息红利差别化个人所得税政策其他有关操作事项，按照《合成操作通知》（{_MECHANICS_LEGAL_NUMBER}）的相关规定执行。",
    "五、本通知自2015年9月8日起施行。",
    "上市公司派发股息红利，股权登记日在2015年9月8日之后的，股息红利所得按照本通知的规定执行。本通知实施之日个人投资者证券账户已持有的上市公司股票，其持股时间自取得之日起计算。",
)
_MECHANICS_PARAGRAPHS = (
    "前款所称上市公司是指在上海证券交易所、深圳证券交易所挂牌交易的上市公司；持股期限是指个人从公开发行和转让市场取得上市公司股票之日至转让交割该股票之日前一日的持有时间。",
    "三、个人转让股票时，按照先进先出的原则计算持股期限，即证券账户中先取得的股票视为先转让。",
    "应纳税所得额以个人投资者证券账户为单位计算，持股数量以每日日终结算后个人投资者证券账户的持有记录为准，证券账户取得或转让的股份数为每日日终结算后的净增（减）股份数。",
    "八、本通知所称年（月）是指自然年（月），即持股一年是指从上一年某月某日至本年同月同日的前一日连续持股，持股一个月是指从上月某日至本月同日的前一日连续持股。",
)


def _html(legal_number: str, paragraphs: tuple[str, ...]) -> bytes:
    """Build a clearly synthetic parser fixture with exact UTF-8 source bytes."""

    return (
        "<html><meta charset='utf-8'><h1>"
        + legal_number
        + "</h1>"
        + "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        + "</html>"
    ).encode("utf-8")


def synthetic_statutory_bodies() -> dict[str, bytes]:
    """Return two expressly synthetic legal-clause payloads, not source claims."""

    return {
        "https://example.com/ash05/synthetic-rate": _html(
            _RATE_LEGAL_NUMBER,
            _RATE_PARAGRAPHS,
        ),
        "https://example.com/ash05/synthetic-mechanics": _html(
            _MECHANICS_LEGAL_NUMBER,
            _MECHANICS_PARAGRAPHS,
        ),
    }


def synthetic_szse_distribution_pdf(*, security_code: str, lines: tuple[str, ...]) -> bytes:
    """Build a tiny Unicode PDF so the real disclosure parser reads synthetic text."""
    rendered_lines = (f"证券代码：{security_code}", *lines)
    characters = sorted({character for line in rendered_lines for character in line})
    if any(ord(character) > 0xFFFF for character in characters):
        raise ValueError("synthetic disclosure fixture supports BMP characters only")
    codes = {character: ord(character) for character in characters}
    cmap_lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /ASH05SyntheticUTF16 def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
        f"{len(characters)} beginbfchar",
    ]
    cmap_lines.extend(
        f"<{codes[character]:04X}> <{codes[character]:04X}>" for character in characters
    )
    cmap_lines.extend(
        ("endbfchar", "endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end")
    )
    cmap = "\n".join(cmap_lines).encode("ascii")
    text_commands = ["BT", "/F1 10 Tf", "40 760 Td"]
    for index, line in enumerate(rendered_lines):
        encoded = "".join(f"{codes[character]:04X}" for character in line)
        text_commands.append(f"<{encoded}> Tj")
        if index < len(lines):
            text_commands.append("0 -18 Td")
    text_commands.append("ET")
    content = "\n".join(text_commands).encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /ASH05Synthetic "
        b"/Encoding /Identity-H /DescendantFonts [5 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ASH05Synthetic "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 8 0 R /CIDToGIDMap /Identity /DW 1000 >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Length " + str(len(cmap)).encode("ascii") + b" >>\nstream\n" + cmap + b"\nendstream",
        b"<< /Type /FontDescriptor /FontName /ASH05Synthetic /Flags 4 "
        b"/FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 900 /Descent -100 "
        b"/CapHeight 700 /StemV 80 >>",
    )
    output = bytearray(b"%PDF-1.4\n%ASH05 synthetic fixture\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def install_synthetic_document_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, bytes]:
    """Stub only Session.send while retaining the real egress planning and audit path."""

    bodies = synthetic_statutory_bodies()

    def send(
        session: Session,
        request: PreparedRequest,
        **kwargs: object,
    ) -> Response:
        del session, kwargs
        try:
            prepared = urlsplit(request.url or "")
            pinned_address = ipaddress.ip_address(prepared.hostname or "")
        except ValueError as error:
            raise AssertionError("synthetic document URL is not a pinned IP target") from error
        matching_bodies = [
            body
            for canonical_url, body in bodies.items()
            if urlsplit(canonical_url).path == prepared.path
        ]
        if (
            request.method != "GET"
            or prepared.scheme != "https"
            or prepared.port not in {None, 443}
            or prepared.query
            or prepared.fragment
            or prepared.username is not None
            or prepared.password is not None
            or not pinned_address.is_global
            or request.headers.get("Host") != "example.com"
            or len(matching_bodies) != 1
        ):
            raise AssertionError("unexpected synthetic document transport target")
        if request.headers.get("Accept-Encoding") != "identity":
            raise AssertionError("document transport must request identity encoding")
        body = matching_bodies[0]
        response = Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers.update(
            {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(body)),
            }
        )
        response.raw = HTTPResponse(
            body=BytesIO(body),
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(body)),
            },
            preload_content=False,
            decode_content=False,
        )
        response._content_consumed = False
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return bodies


def append_synthetic_statutory_bundle(
    *,
    body_store_root: Path,
    provider: ProviderConfigModel | None = None,
) -> tuple[ProviderConfigModel, StatutorySourceDocumentBundle, str]:
    """Capture and append two explicit synthetic revisions using real Data Center paths."""

    bodies = synthetic_statutory_bodies()
    if provider is None:
        PublisherCatalogModel._default_manager.create(
            code=_PUBLISHER_CODE,
            canonical_name="Synthetic test publisher; no legal status",
            publisher_class="system",
            website="https://example.com/",
            is_active=True,
        )
        now_date = timezone.now().date().isoformat()
        revisions = []
        for document_id, source_version, url, title, legal_number, body, effective in (
            (
                "synthetic-rate",
                "fixture-v1",
                "https://example.com/ash05/synthetic-rate",
                "Synthetic rate clauses; no legal authority",
                _RATE_LEGAL_NUMBER,
                bodies["https://example.com/ash05/synthetic-rate"],
                "2015-09-08",
            ),
            (
                "synthetic-mechanics",
                "fixture-v1",
                "https://example.com/ash05/synthetic-mechanics",
                "Synthetic mechanics clauses; no legal authority",
                _MECHANICS_LEGAL_NUMBER,
                bodies["https://example.com/ash05/synthetic-mechanics"],
                now_date,
            ),
        ):
            revisions.append(
                {
                    "revision": {
                        "document_id": document_id,
                        "source_version": source_version,
                        "canonical_url": url,
                        "issuer": "Synthetic fixture issuer; not a government body",
                        "title": title,
                        "legal_number": legal_number,
                        "publication_date": {"precision": "date", "value": now_date},
                        "effective_date": {"precision": "date", "value": effective},
                        "body_sha256": sha256(body).hexdigest(),
                        "body_size_bytes": len(body),
                    },
                    "max_bytes": 32768,
                    "allowed_media_types": ["text/html"],
                }
            )
        provider = ProviderConfigModel._default_manager.create(
            name="ASH05 synthetic unqualified document capture",
            source_type="public_document",
            is_active=True,
            http_url="",
            api_endpoint="",
            extra_config={
                "statutory_source_catalog": {
                    "schema_version": "data_center.statutory_source_catalog.v1",
                    "profile_id": "ash05-synthetic-unqualified",
                    "version": "fixture-v1",
                    "publisher_code": _PUBLISHER_CODE,
                    "enabled": True,
                    "allowed_hosts": ["example.com"],
                    "max_capture_age_seconds": 3600,
                    "documents": revisions,
                }
            },
        )
    if type(provider.pk) is not int:
        raise RuntimeError("synthetic statutory document provider has no database identity")
    EgressRoutingRuleModel._default_manager.create(
        provider_id=provider.pk,
        dataset_key="statutory_source_documents",
        domain_pattern="example.com",
        deployment_region=_REGION,
        strategy="direct",
        fixed_egress_id=None,
        priority=1,
        enabled=True,
    )
    service = ConfiguredStatutorySourceCaptureService(
        provider_id=provider.pk,
        body_store_root=body_store_root,
        deployment_region=_REGION,
        using="default",
    )
    rate = service.capture_document(
        issuer="Synthetic fixture issuer; not a government body",
        document_id="synthetic-rate",
        source_version="fixture-v1",
    )
    mechanics = service.capture_document(
        issuer="Synthetic fixture issuer; not a government body",
        document_id="synthetic-mechanics",
        source_version="fixture-v1",
    )
    bundle = StatutorySourceDocumentBundle(
        bundle_id=f"ash05-synthetic-tax-documents-{uuid4().hex}",
        version="fixture-v1",
        captures=(rate.capture, mechanics.capture),
    )
    body_store = StatutorySourceBodyStore(body_store_root, max_body_bytes=32768)
    repository = DjangoStatutorySourceRepository(body_store=body_store, using="default")
    saved = AppendStatutorySourceDocumentBundleUseCase(repository).execute(bundle).record
    if saved != bundle:
        raise AssertionError("retained synthetic statutory source bundle differs")
    source_set = tax_assessment_source_bundle(saved)
    return provider, saved, source_set.source_revision_set_sha256


class _SyntheticStockBasicSession(_Session):
    """Return exact synthetic Tushare rows through the real source decoder."""

    def __init__(self) -> None:
        super().__init__(_Response(b"{}"))
        self.closed = False

    def mount(self, _scheme: str, _adapter: object) -> None:
        """Accept the production retry adapter without opening a socket."""

    def close(self) -> None:
        """Record the production client cleanup call."""
        self.closed = True

    def post(self, _url: str, **kwargs: object) -> _Response:
        """Return the exact list-status requests needed by the source contract."""
        request = kwargs.get("json")
        params = request.get("params") if type(request) is dict else None
        status = params.get("list_status") if type(params) is dict else None
        if status not in {"L", "D"}:
            raise AssertionError("stock-basic request omitted exact list-status scope")
        rows = (
            [
                [
                    "000001.SZ",
                    "Synthetic listed equity",
                    "SZSE",
                    "ash05-synthetic-main",
                    "L",
                    "20000104",
                    "",
                    "CNY",
                ]
            ]
            if status == "L"
            else []
        )
        body = json.dumps(
            {
                "code": 0,
                "msg": None,
                "data": {
                    "fields": [
                        "ts_code",
                        "name",
                        "exchange",
                        "market",
                        "list_status",
                        "list_date",
                        "delist_date",
                        "curr_type",
                    ],
                    "items": rows,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return _Response(body)


def retain_synthetic_current_cny_instrument(
    *, monkeypatch: pytest.MonkeyPatch
) -> InstrumentReferenceSnapshotRecord:
    """Persist one explicitly synthetic CNY source snapshot and mapping."""
    from uuid import uuid4

    if connection.vendor != "postgresql":
        raise RuntimeError("native CNY instrument retention requires PostgreSQL")
    monkeypatch.setattr(tushare_client, "_create_requests_session", _SyntheticStockBasicSession)
    payloads = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(payloads)
    client = tushare_client.create_tushare_pro_client(
        token="ash05-synthetic-provider-token",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key="ash05.synthetic.stock-basic",
        provider_response_handler=retainer.execute,
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="ash05.synthetic.szse-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SZSE", "SZ"),),
    )
    contract = InstrumentReferenceProviderContract(
        contract_id="ash05.synthetic.stock-basic",
        contract_version="fixture-cny-v1",
        provider_name="tushare",
        dataset_key="ash05.synthetic.stock-basic",
        api_name="stock_basic",
        fields=(
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
            "curr_type",
        ),
        exchange_scope=("SZSE",),
        list_status_scope=("L", "D"),
    )
    source = TushareInstrumentReferenceSource(
        client,
        payloads,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(RawAuditRepository()),
        provider_contract=contract,
        exchange_suffix_crosswalk=crosswalk,
    )
    run_id = uuid4()
    candidate = source.fetch_candidate(run_id=run_id, ingested_run_id=uuid4())
    repository = DjangoInstrumentReferenceSnapshotRepository(
        RawAuditRepository(), payloads, clock=timezone.now
    )
    mapping = SaveInstrumentReferenceMappingUseCase(repository).execute(
        InstrumentReferenceMappingContent(
            mapping_id=f"ash05.synthetic.szse-map-{uuid4().hex}",
            mapping_version="fixture-v1",
            source_crosswalk=crosswalk,
            exchange_rule_market_pairs=(("SZSE", "SZ"),),
            exchange_source_market_board_pairs=(("SZSE", "ash05-synthetic-main", "MAIN"),),
        )
    )
    snapshot = SaveInstrumentReferenceSnapshotUseCase(repository).execute(
        InstrumentReferenceSnapshotContent(
            run_id=run_id,
            mapping_record=mapping,
            fetch_rounds=(InstrumentReferenceFetchRound(uuid4(), candidate),),
        )
    )
    facts = snapshot.content.classify_security("000001.SZ")
    if facts is None or facts.source_currency != "CNY" or facts.rule_market != "SZ":
        raise AssertionError("the exact retained synthetic source is not explicit CNY/SZ")
    return snapshot


@contextmanager
def isolated_task_channels() -> Iterator[None]:
    """Keep this native test on process-local cache and in-memory task channels."""

    app = celery_current_app._get_current_object()
    previous = {
        "broker_url": app.conf.broker_url,
        "result_backend": app.conf.result_backend,
        "task_always_eager": app.conf.task_always_eager,
    }
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": f"ash05_tax_model_qa:{uuid4().hex}",
            }
        },
        CELERY_BROKER_URL="memory://",
        CELERY_RESULT_BACKEND="cache+memory://",
        CELERY_TASK_ALWAYS_EAGER=False,
    ):
        app.conf.update(
            broker_url="memory://",
            result_backend="cache+memory://",
            task_always_eager=False,
        )
        cache = caches["default"]
        if type(cache) is not LocMemCache:
            raise RuntimeError("native tax model test must use process-local LocMem cache")
        try:
            yield
        finally:
            caches.close_all()
            app.conf.update(previous)
