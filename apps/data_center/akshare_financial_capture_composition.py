"""Fail-closed AKShare capture and dual-artifact retention composition."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID, uuid4

from django.conf import settings

from apps.data_center.application.egress_service import (
    FinancialResponseCaptureProtocol,
    execute_financial_response_request,
)
from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactRetention,
)
from apps.data_center.application.financial_source_time_artifact import (
    FinancialSourceTimeArtifactRetention,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
    raw_body_sha256,
    with_provider_verified_response_scope,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    FinancialResponseArtifactRuntimeConfig,
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseArtifactConfigurationError,
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.financial_response_capture import decode_json_bytes
from apps.data_center.infrastructure.financial_source_time_artifact_repository import (
    FinancialSourceTimeArtifactRepository,
)
from apps.data_center.infrastructure.financial_source_time_audit import (
    StrictFinancialSourceTimeAuditLinkVerifier,
)
from apps.data_center.infrastructure.financial_source_time_audit_repository import (
    DjangoFinancialSourceTimeArtifactAuditRepository,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)
from apps.data_center.infrastructure.financial_source_time_contract_registry import (
    FinancialSourceTimeContractRegistryError,
    load_financial_source_time_contract_registry,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_NOTICE_DATE_CONTRACT_ID,
    AKSHARE_NOTICE_DATE_CONTRACT_VERSION,
    AKSHARE_NOTICE_DATE_PARSER_VERSION,
    AKSHARE_PROVIDER_NAME,
    akshare_notice_date_match_contract,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataFetchError

AKSHARE_FINANCIAL_DATASET_KEY = "equity.financial.fact"
AKSHARE_SOURCE_TIME_DATASET_KEY = "equity.financial.source-time"
AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL = (
    "https://" + AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT.split("?", maxsplit=1)[0]
)
_AKSHARE_QUERY_TYPE = "RPT_F10_FINANCE_MAINFINADATA"
MAX_AKSHARE_FINANCIAL_PAGE_SIZE = 200
_AKSHARE_ASSET_FIELD = "SECUCODE"
_AKSHARE_PERIOD_END_FIELD = "REPORT_DATE"
_AKSHARE_ANNOUNCEMENT_DATE_FIELD = "NOTICE_DATE"
_ASSET_CODE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class AkshareFinancialCaptureError(DataFetchError):
    """Reject an unbound, empty, or malformed AKShare financial response pair."""

    default_message = "AKShare 财务响应原件无法验证。"
    default_code = "AKSHARE_FINANCIAL_CAPTURE_INVALID"


class FinancialResponseRequestRunner(Protocol):
    """Run one financial request through the configured Data Center egress."""

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        request_id: UUID,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        request_scope: FinancialRequestScope,
        response_scope: FinancialResponseScope,
        max_attempts: int = 2,
    ) -> FinancialResponseCaptureProtocol:
        """Return the successful response's exact body and transport evidence."""
        ...


class CaptureIdFactory(Protocol):
    """Generate one capture UUID per independent provider response."""

    def __call__(self) -> UUID:
        """Return a fresh UUID."""
        ...


@dataclass(frozen=True, slots=True)
class AkshareFinancialArtifactPair:
    """Successful dual retention of financial and source-time provider bytes."""

    financial: FinancialResponseArtifactRetention
    source_time: FinancialSourceTimeArtifactRetention


class AkshareFinancialCaptureGateway:
    """Capture the same governed endpoint twice before retaining either body.

    This boundary writes only immutable response bodies and their RawAudit
    links. It does not call the DataFrame adapter, create financial facts, or
    construct source-time witnesses. Each pair is scoped to one asset and one
    announcement date because ``FinancialSourceTimeArtifactRef`` binds a
    single date. A later adapter must measure per-asset/per-period request
    volume and provider capacity before broadening this producer to full-market
    work.
    """

    def __init__(
        self,
        provider: ProviderConfig,
        *,
        deployment_region: str,
        financial_repository: FinancialResponseArtifactRepository,
        source_time_repository: FinancialSourceTimeArtifactRepository,
        capture_runner: FinancialResponseRequestRunner = execute_financial_response_request,
        capture_id_factory: CaptureIdFactory = uuid4,
    ) -> None:
        """Bind provider, region, explicit stores, egress, and identity source."""

        self._provider = provider
        self._provider_id = _active_akshare_provider_id(provider)
        self._deployment_region = deployment_region
        self._financial_repository = financial_repository
        self._source_time_repository = source_time_repository
        self._capture_runner = capture_runner
        self._capture_id_factory = capture_id_factory

    def capture_and_retain(
        self,
        *,
        asset_code: str,
        period_limit: int,
        announcement_date: date,
    ) -> AkshareFinancialArtifactPair:
        """Capture two independent raw bodies and retain them only after validation.

        Both calls use the same fixed owner-contract endpoint and safe query
        projection, while each call has a distinct request UUID and dataset
        scope. The exact transport buffers are passed to the encrypted stores;
        decoded or reserialized JSON never becomes the retained body.
        """

        requested_asset = _required_text(asset_code, "asset_code", maximum=64)
        if _ASSET_CODE_PATTERN.fullmatch(requested_asset) is None:
            raise AkshareFinancialCaptureError("AKShare asset_code 含不支持的字符。")
        if (
            isinstance(period_limit, bool)
            or not isinstance(period_limit, int)
            or not 1 <= period_limit <= MAX_AKSHARE_FINANCIAL_PAGE_SIZE
        ):
            raise AkshareFinancialCaptureError("AKShare 财报周期上限无效。")
        if isinstance(announcement_date, datetime) or not isinstance(announcement_date, date):
            raise AkshareFinancialCaptureError("AKShare 公告日期无效。")
        _require_active_akshare_contract()
        safe_params = _akshare_request_params(
            asset_code=requested_asset,
            period_limit=period_limit,
            announcement_date=announcement_date,
        )
        financial_capture_id = self._capture_id_factory()
        source_time_capture_id = self._capture_id_factory()
        if (
            not isinstance(financial_capture_id, UUID)
            or not isinstance(source_time_capture_id, UUID)
            or financial_capture_id == source_time_capture_id
        ):
            raise AkshareFinancialCaptureError("AKShare 双响应捕获标识必须是两个不同 UUID。")

        financial = self._capture_one(
            capture_id=financial_capture_id,
            dataset_key=AKSHARE_FINANCIAL_DATASET_KEY,
            asset_code=requested_asset,
            period_limit=period_limit,
            announcement_date=announcement_date,
            request_params=dict(safe_params),
        )
        source_time = self._capture_one(
            capture_id=source_time_capture_id,
            dataset_key=AKSHARE_SOURCE_TIME_DATASET_KEY,
            asset_code=requested_asset,
            period_limit=period_limit,
            announcement_date=announcement_date,
            request_params=dict(safe_params),
        )

        audit_params: dict[str, object] = {
            "endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            "method": "GET",
            "params": safe_params,
        }
        financial_retention = self._financial_repository.retain(
            capture_id=financial_capture_id,
            evidence=financial.evidence,
            body=financial.raw_body,
            provider_name=AKSHARE_PROVIDER_NAME,
            request_params=audit_params,
            row_count=financial.row_count,
            provider_id=self._provider_id,
        )
        source_time_retention = self._source_time_repository.retain(
            capture_id=source_time_capture_id,
            provider_name=AKSHARE_PROVIDER_NAME,
            provider_id=self._provider_id,
            requested_asset_code=requested_asset,
            requested_announcement_date=announcement_date,
            body=source_time.raw_body,
            response_completed_at=source_time.evidence.response_completed_at,
            response_row_count=source_time.row_count,
            request_params=audit_params,
            parser_version=AKSHARE_NOTICE_DATE_PARSER_VERSION,
        )
        return AkshareFinancialArtifactPair(
            financial=financial_retention,
            source_time=source_time_retention,
        )

    def read_retained_bodies(
        self,
        pair: AkshareFinancialArtifactPair,
    ) -> tuple[bytes, bytes]:
        """Read both retained bodies and recheck their exact provider-row bindings."""

        if not isinstance(pair, AkshareFinancialArtifactPair):
            raise AkshareFinancialCaptureError("AKShare 财报原件对无效。")
        financial_reference = pair.financial.reference
        source_time_reference = pair.source_time.reference
        financial_evidence = financial_reference.evidence
        request_scope = financial_evidence.request_scope
        verifier = StrictFinancialSourceTimeAuditLinkVerifier(
            expected_provider_id=self._provider_id
        )
        try:
            financial_provider_id = verifier.verify_financial(
                pair.financial.audit, financial_reference
            )
            source_time_provider_id = verifier.verify_source_time(
                pair.source_time.audit, source_time_reference
            )
        except (KeyError, TypeError, ValueError):
            raise AkshareFinancialCaptureError("AKShare 财报 RawAudit 身份绑定无效。") from None
        if (
            financial_provider_id != self._provider_id
            or source_time_provider_id != self._provider_id
            or financial_reference.capture_id == source_time_reference.capture_id
            or request_scope.provider_name != AKSHARE_PROVIDER_NAME
            or request_scope.dataset_key != AKSHARE_FINANCIAL_DATASET_KEY
            or request_scope.asset_code != source_time_reference.requested_asset_code
            or source_time_reference.provider_name != AKSHARE_PROVIDER_NAME
            or source_time_reference.dataset_key != AKSHARE_SOURCE_TIME_DATASET_KEY
        ):
            raise AkshareFinancialCaptureError("AKShare 财报原件对范围或 provider 身份不匹配。")

        financial_body = self._financial_repository.read(financial_reference)
        source_time_body = self._source_time_repository.read(source_time_reference)
        if (
            type(financial_body) is not bytes
            or len(financial_body) != financial_reference.body_size_bytes
            or raw_body_sha256(financial_body) != financial_reference.body_sha256
            or type(source_time_body) is not bytes
            or len(source_time_body) != source_time_reference.body_size_bytes
            or raw_body_sha256(source_time_body) != source_time_reference.body_sha256
        ):
            raise AkshareFinancialCaptureError("AKShare 财报 retained body 无法精确回读。")
        return financial_body, source_time_body

    def _capture_one(
        self,
        *,
        capture_id: UUID,
        dataset_key: str,
        asset_code: str,
        period_limit: int,
        announcement_date: date,
        request_params: Mapping[str, object],
    ) -> _VerifiedAkshareCapture:
        """Capture and strictly validate one response without retaining it yet."""

        context = EgressRequestContext(
            provider_id=self._provider_id,
            dataset_key=dataset_key,
            target_url=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
            deployment_region=self._deployment_region,
        )
        request_scope = FinancialRequestScope(
            provider_name=AKSHARE_PROVIDER_NAME,
            dataset_key=dataset_key,
            asset_code=asset_code,
            period_limit=period_limit,
        )
        declared_scope = FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(),
            row_count=0,
        )
        captured = self._capture_runner(
            context,
            request_id=capture_id,
            method="GET",
            params=request_params,
            json_body=None,
            headers=None,
            request_scope=request_scope,
            response_scope=declared_scope,
            max_attempts=2,
        )
        body = captured.raw_body
        evidence = captured.evidence
        if (
            type(body) is not bytes
            or not body
            or evidence.request_scope != request_scope
            or evidence.response_scope != declared_scope
            or evidence.response_scope_basis is not FinancialResponseScopeBasis.CALLER_DECLARED
            or evidence.body_scope is not FinancialResponseBodyScope.BATCH
            or evidence.body_size_bytes != len(body)
            or evidence.body_sha256 != raw_body_sha256(body)
        ):
            raise AkshareFinancialCaptureError("AKShare 响应缺少有效的原始字节证据。")
        rows = _main_financial_rows(body)
        periods: set[date] = set()
        for row in rows:
            if row.get(_AKSHARE_ASSET_FIELD) != asset_code:
                raise AkshareFinancialCaptureError("AKShare 返回了请求范围之外的证券。")
            period_end = _strict_provider_date(row.get(_AKSHARE_PERIOD_END_FIELD))
            row_announcement = _strict_provider_date(row.get(_AKSHARE_ANNOUNCEMENT_DATE_FIELD))
            if period_end is None or row_announcement is None:
                raise AkshareFinancialCaptureError("AKShare 财报日期字段无效。")
            if row_announcement != announcement_date:
                raise AkshareFinancialCaptureError("AKShare 响应超出单公告日请求范围。")
            periods.add(period_end)
        verified_scope = FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=tuple(sorted(periods)),
            row_count=len(rows),
        )
        verified_evidence = with_provider_verified_response_scope(evidence, verified_scope)
        return _VerifiedAkshareCapture(
            raw_body=body,
            evidence=verified_evidence,
            row_count=len(rows),
        )


@dataclass(frozen=True, slots=True)
class _VerifiedAkshareCapture:
    """Validated exact bytes and provider-derived coverage, not a fact row."""

    raw_body: bytes
    evidence: FinancialResponseEvidence
    row_count: int


def build_akshare_financial_capture_gateway(
    provider: ProviderConfig,
    *,
    deployment_region: str,
    environment: str | None = None,
) -> AkshareFinancialCaptureGateway:
    """Build the AKShare pair producer from approved policy and explicit runtime config.

    The builder requires the checked-in owner-approved contract and the
    existing enabled Config Center retention configuration. It creates two
    independent encrypted stores, one shared RawAudit repository, and the
    guarded source-time audit adapter before exposing any egress-capable
    producer.
    """

    _active_akshare_provider_id(provider)
    _require_active_akshare_contract()
    runtime = resolve_financial_response_artifact_config(environment=environment)
    if runtime is None:
        raise FinancialResponseArtifactConfigurationError(
            "AKShare 财务原件保留配置未启用。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    raw_audits = RawAuditRepository()
    financial_store, source_time_store = _build_dual_stores(runtime)
    return AkshareFinancialCaptureGateway(
        provider,
        deployment_region=deployment_region,
        financial_repository=FinancialResponseArtifactRepository(
            financial_store,
            raw_audits,
            failure_audit_repository=raw_audits,
        ),
        source_time_repository=FinancialSourceTimeArtifactRepository(
            source_time_store,
            DjangoFinancialSourceTimeArtifactAuditRepository(raw_audits),
        ),
    )


def _build_dual_stores(
    runtime: FinancialResponseArtifactRuntimeConfig,
) -> tuple[FinancialResponseBodyStore, FinancialSourceTimeBodyStore]:
    """Create separate authenticated envelopes from the same explicit key."""

    financial_store = FinancialResponseBodyStore(
        runtime.root,
        encryption_key=runtime.encryption_key,
        encryption_key_ref=runtime.encryption_key_ref,
        encryption_key_version=runtime.encryption_key_version,
        max_body_bytes=runtime.max_body_bytes,
    )
    source_time_store = FinancialSourceTimeBodyStore(
        runtime.root,
        encryption_key=runtime.encryption_key,
        encryption_key_ref=runtime.encryption_key_ref,
        encryption_key_version=runtime.encryption_key_version,
        max_body_bytes=runtime.max_body_bytes,
    )
    return financial_store, source_time_store


def _require_active_akshare_contract() -> None:
    """Refuse capture unless the current owner-approved registry matches code."""

    registry_path = (
        Path(settings.BASE_DIR) / "governance" / "financial_source_time_match_contracts.json"
    )
    try:
        registry = load_financial_source_time_contract_registry(registry_path)
    except (FinancialSourceTimeContractRegistryError, OSError) as exc:
        raise FinancialResponseArtifactConfigurationError(
            "AKShare 财务来源时间批准契约不可用。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        ) from exc
    expected = akshare_notice_date_match_contract()
    contract = registry.get(
        provider_name=AKSHARE_PROVIDER_NAME,
        contract_id=AKSHARE_NOTICE_DATE_CONTRACT_ID,
        contract_version=AKSHARE_NOTICE_DATE_CONTRACT_VERSION,
        contract_sha256=expected.contract_sha256,
    )
    if contract != expected or contract.endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT:
        raise FinancialResponseArtifactConfigurationError(
            "AKShare 财务来源时间批准契约与生产代码不匹配。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )


def _akshare_request_params(
    *,
    asset_code: str,
    period_limit: int,
    announcement_date: date,
) -> dict[str, object]:
    """Build the bounded EastMoney query from typed dimensions only."""

    if _ASSET_CODE_PATTERN.fullmatch(asset_code) is None:
        raise AkshareFinancialCaptureError("AKShare asset_code 含不支持的字符。")
    if (
        isinstance(period_limit, bool)
        or not isinstance(period_limit, int)
        or not 1 <= period_limit <= MAX_AKSHARE_FINANCIAL_PAGE_SIZE
    ):
        raise AkshareFinancialCaptureError("AKShare 财报周期上限无效。")
    if isinstance(announcement_date, datetime) or not isinstance(announcement_date, date):
        raise AkshareFinancialCaptureError("AKShare 公告日期无效。")
    return {
        "type": _AKSHARE_QUERY_TYPE,
        "sty": "APP_F10_MAINFINADATA",
        "quoteColumns": "",
        "filter": (f'(SECUCODE="{asset_code}")' f'(NOTICE_DATE="{announcement_date.isoformat()}")'),
        "p": "1",
        "ps": str(period_limit),
        "sr": "-1",
        "st": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }


def _active_akshare_provider_id(provider: ProviderConfig) -> int:
    """Require one active provider row matching the exact contract identity."""

    if (
        not isinstance(provider, ProviderConfig)
        or provider.source_type != AKSHARE_PROVIDER_NAME
        or provider.is_active is not True
        or provider.id is None
        or isinstance(provider.id, bool)
        or provider.id <= 0
    ):
        raise AkshareFinancialCaptureError("AKShare 财报 provider 配置无效或已停用。")
    return provider.id


def _main_financial_rows(body: bytes) -> tuple[Mapping[str, object], ...]:
    """Decode raw bytes and validate EastMoney's success envelope and row count."""

    try:
        payload = decode_json_bytes(body)
    except ValueError as exc:
        raise AkshareFinancialCaptureError("AKShare 响应原始字节不是有效 JSON。") from exc
    if not isinstance(payload, Mapping):
        raise AkshareFinancialCaptureError("AKShare 响应结构无效。")
    code = payload.get("code")
    if (
        payload.get("success") is not True
        or isinstance(code, bool)
        or not isinstance(code, int)
        or code != 0
    ):
        raise DataFetchError(
            "AKShare provider rejected the financial read",
            code="AKSHARE_FINANCIAL_PROVIDER_REJECTED",
        )
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise AkshareFinancialCaptureError("AKShare 响应缺少 result 对象。")
    raw_rows = result.get("data")
    row_count = result.get("count")
    if (
        not isinstance(raw_rows, list)
        or not raw_rows
        or not all(isinstance(row, Mapping) for row in raw_rows)
        or isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or row_count != len(raw_rows)
    ):
        raise AkshareFinancialCaptureError("AKShare 响应行数或 data 结构无效。")
    return tuple(cast(Mapping[str, object], row) for row in raw_rows)


def _strict_provider_date(value: object) -> date | None:
    """Parse only the two date encodings approved by the AKShare matcher."""

    if not isinstance(value, str) or value != value.strip():
        return None
    if len(value) == 10:
        date_text = value
    elif len(value) == 19 and value.endswith(" 00:00:00"):
        date_text = value[:10]
    else:
        return None
    if date_text[4] != "-" or date_text[7] != "-":
        return None
    try:
        return date.fromisoformat(date_text)
    except ValueError:
        return None


def _required_text(value: object, field_name: str, *, maximum: int) -> str:
    """Validate a bounded identifier without trimming or rewriting it."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise AkshareFinancialCaptureError(f"AKShare {field_name} 无效。")
    return value


__all__ = [
    "AKSHARE_FINANCIAL_DATASET_KEY",
    "AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL",
    "AKSHARE_SOURCE_TIME_DATASET_KEY",
    "MAX_AKSHARE_FINANCIAL_PAGE_SIZE",
    "AkshareFinancialArtifactPair",
    "AkshareFinancialCaptureError",
    "AkshareFinancialCaptureGateway",
    "FinancialResponseRequestRunner",
    "build_akshare_financial_capture_gateway",
]
