"""AKShare-native scope discovery through governed egress and raw retention."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.conf import settings

from apps.data_center.application.egress_service import (
    FinancialResponseAttemptBudget,
    execute_financial_response_request,
    preview_route,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    with_provider_verified_response_scope,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCapture,
    FinancialScopeDiscoveryError,
    FinancialScopeDiscoveryRow,
    build_asset_item,
    latest_source_time,
)
from apps.data_center.domain.financial_source_evidence import FINANCIAL_FACT_DATASET_KEY
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_response_capture import decode_json_bytes
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
)
from apps.data_center.infrastructure.rehearsal_identity import (
    configured_akshare_financial_identity,
)
from core.exceptions import DataFetchError

_CONTRACT_PATH = Path("governance/financial_scope_discovery_contract.json")
_ASSET_FIELD = "SECUCODE"
_PERIOD_FIELD = "REPORT_DATE"
_ANNOUNCEMENT_FIELD = "NOTICE_DATE"
_DATA_QUERY_TYPE = "RPT_F10_FINANCE_MAINFINADATA"
_PARSER_ID = "akshare-financial-scope-parser.v1"
_PARSER_SOURCE_TIMEZONE = "Asia/Shanghai"
_PAGE_NUMBER = 1
_DATASET_KEYS = (
    FINANCIAL_FACT_DATASET_KEY,
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
)


@dataclass(frozen=True, slots=True)
class _PendingCapture:
    """Typed in-memory provider response before encrypted artifact retention."""

    capture_id: UUID
    body: bytes
    evidence: FinancialResponseEvidence
    rows: tuple[FinancialScopeDiscoveryRow, ...]
    physical_request_attempts: int


class AkshareFinancialScopeDiscoveryReader:
    """Read complete single-asset provider pages and retain exact audited bodies."""

    def __init__(
        self,
        provider: ProviderConfig,
        *,
        deployment_region: str,
        artifact_repository: FinancialResponseArtifactRepository,
        run_id: UUID | None = None,
        maximum_body_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        """Bind a real provider row, region, encrypted artifact store, and run identity."""

        if provider.id is None or isinstance(provider.id, bool) or provider.id <= 0:
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
            )
        if not isinstance(artifact_repository, FinancialResponseArtifactRepository):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID")
        if run_id is not None and not isinstance(run_id, UUID):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        if type(maximum_body_bytes) is not int or maximum_body_bytes <= 0:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        self._provider = provider
        self._deployment_region = deployment_region
        self._repository = artifact_repository
        self._run_id = run_id or uuid4()
        self._maximum_body_bytes = maximum_body_bytes
        build_identity_path = Path(settings.AGOM_BUILD_IDENTITY_PATH)
        self._candidate_sha = FileFinancialCapacityBuildIdentitySource(
            build_identity_path
        ).source_commit()

    def preflight(self, *, binding: FinancialScopeDiscoveryBinding) -> None:
        """Fail before egress unless all frozen identities and both routes match."""

        if (
            self._provider.id != binding.provider_id
            or self._provider.source_type.casefold() != "akshare"
            or self._provider.is_active is not True
            or binding.candidate_sha != self._candidate_sha
            or binding.deployment_region != self._deployment_region
        ):
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
            )
        identity = configured_akshare_financial_identity(provider_id=binding.provider_id)
        identity_bytes = json.dumps(
            {
                "role": identity.role,
                "provider_id": identity.provider_id,
                "source": identity.source,
                "version": identity.version,
                "endpoint_id": identity.endpoint_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        identity_sha256 = hashlib.sha256(identity_bytes).hexdigest()
        contract = _load_scope_discovery_contract()
        parser_sha256 = financial_scope_discovery_parser_sha256()
        if (
            identity_sha256 != binding.provider_identity_sha256
            or binding.contract_id != contract["contract_id"]
            or binding.contract_version != contract["contract_version"]
            or binding.contract_sha256 != contract["contract_sha256"]
            or binding.parser_id != _PARSER_ID
            or binding.parser_sha256 != parser_sha256
        ):
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID"
            )
        for dataset_key in _DATASET_KEYS:
            route = preview_route(
                EgressRequestContext(
                    provider_id=binding.provider_id,
                    dataset_key=dataset_key,
                    target_url=_endpoint_url(),
                    deployment_region=binding.deployment_region,
                )
            )
            if route.rule_id is None:
                raise FinancialScopeDiscoveryError(
                    "FINANCIAL_SCOPE_DISCOVERY_EGRESS_ROUTE_REQUIRED"
                )

    def capture_pair(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_code: str,
        maximum_rows: int,
        attempt_budget: FinancialResponseAttemptBudget,
    ) -> tuple[FinancialScopeDiscoveryCapture, FinancialScopeDiscoveryCapture]:
        """Capture two matching provider-native row pages and retain each exact body."""

        if (
            type(maximum_rows) is not int
            or maximum_rows != 200
            or not isinstance(attempt_budget, FinancialResponseAttemptBudget)
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_BUDGET_EXCEEDED")
        raw_financial = self._capture_one(
            binding=binding,
            asset_code=asset_code,
            dataset_key=FINANCIAL_FACT_DATASET_KEY,
            maximum_rows=maximum_rows,
            attempt_budget=attempt_budget,
        )
        raw_source_time = self._capture_one(
            binding=binding,
            asset_code=asset_code,
            dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
            maximum_rows=maximum_rows,
            attempt_budget=attempt_budget,
        )
        if raw_financial.rows != raw_source_time.rows:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_CONFLICT")
        financial = self._retain(
            binding=binding,
            asset_code=asset_code,
            dataset_key=FINANCIAL_FACT_DATASET_KEY,
            captured=raw_financial,
        )
        try:
            source_time = self._retain(
                binding=binding,
                asset_code=asset_code,
                dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
                captured=raw_source_time,
            )
        except FinancialScopeDiscoveryError as exc:
            raise FinancialScopeDiscoveryError(
                exc.code,
                artifact_writes=1 + exc.artifact_writes,
                audit_writes=1 + exc.audit_writes,
            ) from None
        return financial, source_time

    def _capture_one(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_code: str,
        dataset_key: str,
        maximum_rows: int,
        attempt_budget: FinancialResponseAttemptBudget,
    ) -> _PendingCapture:
        """Return typed rows and exact transport bytes without writing business data."""

        context = EgressRequestContext(
            provider_id=binding.provider_id,
            dataset_key=dataset_key,
            target_url=_endpoint_url(),
            deployment_region=binding.deployment_region,
        )
        capture_id = uuid4()
        request_scope = FinancialRequestScope(
            provider_name=AKSHARE_PROVIDER_NAME,
            dataset_key=dataset_key,
            asset_code=asset_code,
            period_limit=maximum_rows,
        )
        declared_scope = FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(),
            row_count=0,
        )
        params: dict[str, object] = {
            "type": _DATA_QUERY_TYPE,
            "sty": f"{_ASSET_FIELD},{_PERIOD_FIELD},{_ANNOUNCEMENT_FIELD}",
            "filter": f"({_ASSET_FIELD}='{asset_code}')",
            "p": _PAGE_NUMBER,
            "ps": maximum_rows,
            "st": _ANNOUNCEMENT_FIELD,
            "sr": -1,
        }
        try:
            captured = execute_financial_response_request(
                context,
                request_id=capture_id,
                method="GET",
                params=params,
                json_body=None,
                headers=None,
                request_scope=request_scope,
                response_scope=declared_scope,
                max_attempts=2,
                attempt_budget=attempt_budget,
            )
            if len(captured.raw_body) > self._maximum_body_bytes:
                raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
            rows = _parse_provider_rows(
                captured.raw_body,
                asset_code=asset_code,
                maximum_rows=maximum_rows,
            )
        except FinancialScopeDiscoveryError:
            raise
        except (DataFetchError, OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED"
            ) from None
        periods = tuple(sorted({row.period_end for row in rows}))
        verified_scope = FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=periods,
            row_count=len(rows),
        )
        evidence = with_provider_verified_response_scope(captured.evidence, verified_scope)
        return _PendingCapture(
            capture_id=capture_id,
            body=captured.raw_body,
            evidence=evidence,
            rows=rows,
            physical_request_attempts=captured.physical_request_attempts,
        )

    def _retain(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_code: str,
        dataset_key: str,
        captured: _PendingCapture,
    ) -> FinancialScopeDiscoveryCapture:
        """Persist one exact body and RawAudit, then verify the stored reference."""

        rows = captured.rows
        capture_id = captured.capture_id
        body = captured.body
        evidence = captured.evidence
        attempts = captured.physical_request_attempts
        try:
            retained = self._repository.retain(
                capture_id=capture_id,
                evidence=evidence,
                body=body,
                provider_name=AKSHARE_PROVIDER_NAME,
                request_params={
                    "endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                    "method": "GET",
                    "params": {
                        "type": _DATA_QUERY_TYPE,
                        "sty": f"{_ASSET_FIELD},{_PERIOD_FIELD},{_ANNOUNCEMENT_FIELD}",
                        "filter": f"({_ASSET_FIELD}='{asset_code}')",
                        "p": _PAGE_NUMBER,
                        "ps": 200,
                        "st": _ANNOUNCEMENT_FIELD,
                        "sr": -1,
                    },
                },
                row_count=len(rows),
                provider_id=binding.provider_id,
                run_id=self._run_id,
            )
        except Exception as exc:
            if getattr(exc, "reference", None) is not None:
                raise FinancialScopeDiscoveryError(
                    "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
                    artifact_writes=1,
                ) from None
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID"
            ) from None
        try:
            orphan = self._repository.inspect_orphan(retained.reference)
            retained_body = self._repository.read(retained.reference)
        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError):
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
                artifact_writes=1,
                audit_writes=1,
            ) from None
        if not orphan.body_verified or orphan.audit != retained.audit or orphan.audit is None:
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
                artifact_writes=1,
                audit_writes=1,
            )
        audit_link = retained.audit.extra.get("financial_response_artifact")
        if (
            retained.audit.capability != "financial"
            or retained.audit.status != "ok"
            or retained.audit.redacted is not True
            or not isinstance(audit_link, Mapping)
            or audit_link.get("provider_id") != binding.provider_id
            or audit_link.get("capture_id") != str(capture_id)
            or audit_link.get("body_sha256") != retained.reference.body_sha256
            or audit_link.get("dataset_key") != dataset_key
        ):
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
                artifact_writes=1,
                audit_writes=1,
            )
        if int(retained.audit.raw_audit_id) <= 0:
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
                artifact_writes=1,
                audit_writes=1,
            )
        if hashlib.sha256(retained_body).hexdigest() != retained.reference.body_sha256:
            raise FinancialScopeDiscoveryError(
                "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
                artifact_writes=1,
                audit_writes=1,
            )
        return FinancialScopeDiscoveryCapture(
            asset_code=asset_code,
            provider_id=binding.provider_id,
            provider_identity_sha256=binding.provider_identity_sha256,
            candidate_sha=binding.candidate_sha,
            contract_id=binding.contract_id,
            contract_version=binding.contract_version,
            contract_sha256=binding.contract_sha256,
            parser_id=binding.parser_id,
            parser_sha256=binding.parser_sha256,
            deployment_region=binding.deployment_region,
            capture_id=str(capture_id),
            body_sha256=retained.reference.body_sha256,
            raw_audit_id=int(retained.audit.raw_audit_id),
            dataset_key=dataset_key,
            response_completed_at=retained.reference.evidence.response_completed_at,
            rows=rows,
            physical_request_attempts=attempts,
        )


def _endpoint_url() -> str:
    """Return the existing AKShare contract's host/path without a query string."""

    parsed = urlsplit(f"https://{AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT}")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _load_scope_discovery_contract() -> dict[str, object]:
    """Load and hash-check the checked-in native query contract."""

    path = Path(settings.BASE_DIR) / _CONTRACT_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID") from None
    if not isinstance(raw, dict):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    digest = raw.get("contract_sha256")
    unsigned = dict(raw)
    unsigned.pop("contract_sha256", None)
    calculated = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    expected = _expected_contract_payload()
    if (
        set(raw) != set(expected) | {"contract_sha256"}
        or type(digest) is not str
        or digest != calculated
        or any(raw.get(key) != value for key, value in expected.items())
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
    return cast(dict[str, object], raw)


def _expected_contract_payload() -> dict[str, object]:
    """Return the complete checked-in query contract required by this parser."""

    return {
        "schema_version": "akshare-financial-scope-discovery-contract.v1",
        "status": "enforced",
        "provider_name": AKSHARE_PROVIDER_NAME,
        "provider_source": "akshare",
        "contract_id": "akshare.financial-scope.latest-notice",
        "contract_version": "2026-10-09.v1",
        "endpoint": AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        "datasets": list(_DATASET_KEYS),
        "request": {
            "method": "GET",
            "query_type": _DATA_QUERY_TYPE,
            "filter_field": _ASSET_FIELD,
            "filter_operator": "exact",
            "announcement_date_filter": False,
            "page_number": _PAGE_NUMBER,
            "maximum_rows_per_asset": 200,
            "sort_field": _ANNOUNCEMENT_FIELD,
            "sort_direction": "descending",
            "projected_fields": [
                _ASSET_FIELD,
                _PERIOD_FIELD,
                _ANNOUNCEMENT_FIELD,
            ],
        },
        "response": {
            "provider_count_must_match_rows": True,
            "provider_count_above_row_ceiling": "fail_closed",
            "empty_asset_scope": "fail_closed",
            "duplicate_native_rows": "fail_closed",
            "pair_drift": "fail_closed",
        },
        "parser": {
            "parser_id": _PARSER_ID,
            "parser_sha256": financial_scope_discovery_parser_sha256(),
            "asset_field": _ASSET_FIELD,
            "period_field": _PERIOD_FIELD,
            "announcement_date_field": _ANNOUNCEMENT_FIELD,
            "source_timezone": _PARSER_SOURCE_TIMEZONE,
        },
        "evidence": {
            "retention": "two exact encrypted raw response bodies",
            "audit": "one RawAudit per retained body",
            "typed_source_time": "provider-native NOTICE_DATE only",
            "availability_rule": "Asia/Shanghai date plus one day at 00:00",
            "business_fact_writes": 0,
            "publication_writes": 0,
        },
        "authorization": {
            "pre_egress_owner_event_required": True,
            "post_manifest_owner_and_independent_reviewer_required": True,
            "approved_scope": "exact active dynamic universe hash and count",
            "logical_requests_per_asset": 2,
            "physical_attempts_per_logical_request_maximum": 2,
        },
        "authentication": "none",
    }


def financial_scope_discovery_parser_sha256() -> str:
    """Hash parsing and typed source-time projection code in this source tree."""

    source_bundle = "\n".join(
        (
            inspect.getsource(_parse_provider_rows),
            inspect.getsource(FinancialScopeDiscoveryRow),
            inspect.getsource(latest_source_time),
            inspect.getsource(build_asset_item),
        )
    )
    return hashlib.sha256(source_bundle.encode("utf-8")).hexdigest()


def load_financial_scope_discovery_contract() -> dict[str, object]:
    """Expose the checked-in contract to the composition root after digest validation."""

    return _load_scope_discovery_contract()


def _parse_provider_rows(
    body: bytes,
    *,
    asset_code: str,
    maximum_rows: int,
) -> tuple[FinancialScopeDiscoveryRow, ...]:
    """Parse the exact EastMoney envelope and reject truncation or scope drift."""

    try:
        payload: object = decode_json_bytes(body)
    except ValueError:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID") from None
    if not isinstance(payload, Mapping):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
    if (
        payload.get("success") is not True
        or type(payload.get("code")) is not int
        or payload.get("code") != 0
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
    raw_rows = result.get("data")
    reported_count = result.get("count")
    if (
        not isinstance(raw_rows, list)
        or type(reported_count) is not int
        or reported_count < 0
        or reported_count != len(raw_rows)
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
    if reported_count == 0:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE")
    if reported_count > maximum_rows:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_RESPONSE_TRUNCATED")
    rows: list[FinancialScopeDiscoveryRow] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping) or raw_row.get(_ASSET_FIELD) != asset_code:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        period_end = _strict_date(raw_row.get(_PERIOD_FIELD))
        announcement_date = _strict_date(raw_row.get(_ANNOUNCEMENT_FIELD))
        if period_end is None or announcement_date is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        rows.append(
            FinancialScopeDiscoveryRow(
                asset_code=asset_code,
                period_end=period_end,
                announcement_date=announcement_date,
            )
        )
    return tuple(rows)


def _strict_date(value: object) -> date | None:
    """Accept the date-only forms already declared by the AKShare matcher."""

    if type(value) is not str or value != value.strip():
        return None
    date_text = value if len(value) == 10 else value[:10] if value.endswith(" 00:00:00") else ""
    if (
        len(date_text) != 10
        or date_text[4] != "-"
        or date_text[7] != "-"
        or not (date_text[:4] + date_text[5:7] + date_text[8:]).isascii()
        or not (date_text[:4] + date_text[5:7] + date_text[8:]).isdigit()
    ):
        return None
    try:
        parsed = date.fromisoformat(date_text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == date_text else None


__all__ = [
    "AkshareFinancialScopeDiscoveryReader",
    "financial_scope_discovery_parser_sha256",
    "load_financial_scope_discovery_contract",
]
