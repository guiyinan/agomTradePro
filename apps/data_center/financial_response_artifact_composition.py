"""Composition root for opt-in Tushare financial response retention."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from django.db import DatabaseError

from apps.data_center.application.egress_service import (
    execute_financial_response_request,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseScope,
    with_provider_verified_response_scope,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    build_financial_response_artifact_repository,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from core.exceptions import DataFetchError, TushareError

_PROVIDER_REJECTION_CODE = "TUSHARE_PROVIDER_REJECTED"

FINANCIAL_DATASET_KEY = "equity.financial.fact"
FINANCIAL_API_NAME = "fina_indicator"


class TushareFinancialResponseHandler(Protocol):
    """Structural port accepted by the Tushare client for one financial API."""

    def __call__(
        self,
        *,
        request_id: UUID,
        context: EgressRequestContext,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        api_name: str,
    ) -> object:
        """Capture, retain, and return one provider payload."""
        ...


class _ConfiguredTushareFinancialResponseHandler:
    """Bind one provider row to the explicit egress and retention ports."""

    def __init__(
        self,
        provider: ProviderConfig,
        repository: FinancialResponseArtifactRepository,
    ) -> None:
        """Bind provider identity to the injected retention repository."""

        self._provider_name = provider.name
        self._provider_id = provider.id
        self._repository = repository

    def __call__(
        self,
        *,
        request_id: UUID,
        context: EgressRequestContext,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        api_name: str,
    ) -> object:
        """Capture one typed financial response before returning its payload."""

        if api_name != FINANCIAL_API_NAME or context.dataset_key != FINANCIAL_DATASET_KEY:
            raise ValueError("financial response handler received an unsupported dataset")
        request_params = _request_params(params, json_body)
        asset_code = _required_text(request_params.get("ts_code"), "ts_code")
        period_limit = request_params.get("limit")
        if isinstance(period_limit, bool) or not isinstance(period_limit, int) or period_limit <= 0:
            raise ValueError("financial request limit must be positive")
        request_scope = FinancialRequestScope(
            provider_name=self._provider_name,
            dataset_key=context.dataset_key,
            asset_code=asset_code,
            period_limit=period_limit,
        )
        response_scope = FinancialResponseScope(
            asset_codes=(asset_code,),
            period_ends=(),
            row_count=0,
        )
        # The body decoder has not yet established row-level identity or
        # report periods.  Keep the caller declaration bounded to the request
        # asset and leave row_count/period_ends empty rather than claiming
        # parsed source coverage.
        captured = execute_financial_response_request(
            context,
            request_id=request_id,
            method=method,
            params=params,
            json_body=json_body,
            headers=headers,
            request_scope=request_scope,
            response_scope=response_scope,
            max_attempts=2,
        )
        try:
            verified_scope = _verified_financial_response_scope(
                captured.payload,
                requested_asset_code=asset_code,
            )
        except TushareError as exc:
            if exc.code == _PROVIDER_REJECTION_CODE and _is_provider_rejection_payload(
                captured.payload
            ):
                self._repository.retain_rejected(
                    capture_id=request_id,
                    evidence=captured.evidence,
                    body=captured.raw_body,
                    provider_name=self._provider_name,
                    request_params={"api_name": api_name, "params": request_params},
                    failure_code=_PROVIDER_REJECTION_CODE,
                    provider_id=self._provider_id,
                )
            raise
        if captured.evidence.request_scope != request_scope:
            raise TushareError(
                "Tushare capture request scope is inconsistent",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        verified_evidence = with_provider_verified_response_scope(
            captured.evidence,
            verified_scope,
        )
        self._repository.retain(
            capture_id=request_id,
            evidence=verified_evidence,
            body=captured.raw_body,
            provider_name=self._provider_name,
            request_params={"api_name": api_name, "params": request_params},
            row_count=verified_scope.row_count,
            provider_id=self._provider_id,
        )
        return captured.payload


def get_financial_response_artifact_repository(
    provider: ProviderConfig,
    *,
    environment: str | None = None,
) -> FinancialResponseArtifactRepository | None:
    """Return the explicitly configured artifact repository for one provider."""

    return build_financial_response_artifact_repository(provider, environment=environment)


def verify_retained_financial_response_artifact(
    provider: ProviderConfig,
    reference: FinancialResponseArtifactRef,
    *,
    environment: str | None = None,
) -> bool:
    """Verify the exact encrypted body and its matching successful audit link."""

    try:
        repository = get_financial_response_artifact_repository(
            provider,
            environment=environment,
        )
        if repository is None:
            return False
        inspection = repository.inspect_orphan(reference)
    except (DataFetchError, DatabaseError, OSError, TypeError, ValueError):
        return False
    return (
        inspection.body_verified
        and inspection.audit is not None
        and not inspection.is_orphan
        and inspection.reference == reference
    )


def build_tushare_financial_response_handler(
    provider: ProviderConfig,
    *,
    environment: str | None = None,
) -> TushareFinancialResponseHandler | None:
    """Build the opt-in financial handler, preserving legacy behavior when disabled."""

    repository = get_financial_response_artifact_repository(provider, environment=environment)
    if repository is None:
        return None
    return _ConfiguredTushareFinancialResponseHandler(provider, repository)


def _request_params(
    params: Mapping[str, object] | None,
    json_body: Mapping[str, object] | None,
) -> dict[str, object]:
    """Extract non-sensitive provider dimensions without copying the token."""

    if params is not None:
        return dict(params)
    if json_body is None:
        return {}
    nested = json_body.get("params")
    if not isinstance(nested, Mapping):
        return {}
    return {str(key): value for key, value in nested.items()}


def _required_text(value: object, field_name: str) -> str:
    """Require one unpadded text request dimension."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    if len(value) > 64 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _verified_financial_response_scope(
    payload: object,
    *,
    requested_asset_code: str,
) -> FinancialResponseScope:
    """Parse exact asset and period coverage from one successful provider body."""

    if not isinstance(payload, Mapping):
        raise _invalid_payload("Tushare response payload is invalid")
    provider_code = payload.get("code")
    if isinstance(provider_code, bool) or not isinstance(provider_code, int):
        raise _invalid_payload("Tushare response code is invalid")
    if provider_code != 0:
        raise TushareError("Tushare provider rejected the read", code="TUSHARE_PROVIDER_REJECTED")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise _invalid_payload("Tushare response is missing data")
    fields = data.get("fields")
    items = data.get("items")
    if (
        not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
        or len(set(fields)) != len(fields)
        or not isinstance(items, list)
        or not all(isinstance(item, list) and len(item) == len(fields) for item in items)
    ):
        raise _invalid_payload("Tushare financial table is invalid")
    if "ts_code" not in fields or "end_date" not in fields:
        raise _invalid_payload("Tushare financial table is missing scope fields")

    asset_index = fields.index("ts_code")
    period_index = fields.index("end_date")
    period_ends: list[date] = []
    for item in items:
        asset_code = item[asset_index]
        if asset_code != requested_asset_code:
            raise _invalid_payload("Tushare financial row asset is outside the request scope")
        period_end = _parse_period_end(item[period_index])
        if period_end not in period_ends:
            period_ends.append(period_end)
    return FinancialResponseScope(
        asset_codes=(requested_asset_code,) if items else (),
        period_ends=tuple(period_ends),
        row_count=len(items),
    )


def _parse_period_end(value: object) -> date:
    """Parse only the two provider date encodings accepted by the adapter."""

    if not isinstance(value, str) or value != value.strip():
        raise _invalid_payload("Tushare financial period is invalid")
    try:
        if len(value) == 8 and value.isascii() and value.isdigit():
            return datetime.strptime(value, "%Y%m%d").date()
        if (
            len(value) == 10
            and value[4] == "-"
            and value[7] == "-"
            and (value[:4] + value[5:7] + value[8:]).isascii()
            and (value[:4] + value[5:7] + value[8:]).isdigit()
        ):
            return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid_payload("Tushare financial period is invalid") from exc
    raise _invalid_payload("Tushare financial period is invalid")


def _invalid_payload(message: str) -> TushareError:
    """Return the stable error used for unprovable financial payload scope."""

    return TushareError(message, code="TUSHARE_INVALID_PAYLOAD")


def _is_provider_rejection_payload(payload: object) -> bool:
    """Return whether a validated capture contains an explicit non-zero code."""

    if not isinstance(payload, Mapping):
        return False
    code = payload.get("code")
    return isinstance(code, int) and not isinstance(code, bool) and code != 0


__all__ = [
    "FINANCIAL_API_NAME",
    "FINANCIAL_DATASET_KEY",
    "TushareFinancialResponseHandler",
    "build_tushare_financial_response_handler",
    "get_financial_response_artifact_repository",
    "verify_retained_financial_response_artifact",
]
