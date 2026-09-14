"""Composition root for opt-in Tushare financial response retention."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from apps.data_center.application.egress_service import (
    execute_financial_response_request,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseScope,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    build_financial_response_artifact_repository,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from core.exceptions import TushareError

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
        _validate_financial_payload(captured.payload)
        self._repository.retain(
            capture_id=request_id,
            evidence=captured.evidence,
            body=captured.raw_body,
            provider_name=self._provider_name,
            request_params={"api_name": api_name, "params": request_params},
            row_count=0,
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


def _validate_financial_payload(payload: object) -> None:
    """Require the provider table contract before recording a successful audit."""

    if not isinstance(payload, Mapping):
        raise TushareError("Tushare response payload is invalid", code="TUSHARE_INVALID_PAYLOAD")
    if payload.get("code") != 0:
        raise TushareError("Tushare provider rejected the read", code="TUSHARE_PROVIDER_REJECTED")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise TushareError("Tushare response is missing data", code="TUSHARE_INVALID_PAYLOAD")
    fields = data.get("fields")
    items = data.get("items")
    if (
        not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
        or len(set(fields)) != len(fields)
        or not isinstance(items, list)
        or not all(isinstance(item, list) and len(item) == len(fields) for item in items)
    ):
        raise TushareError("Tushare financial table is invalid", code="TUSHARE_INVALID_PAYLOAD")


__all__ = [
    "FINANCIAL_API_NAME",
    "FINANCIAL_DATASET_KEY",
    "TushareFinancialResponseHandler",
    "build_tushare_financial_response_handler",
    "get_financial_response_artifact_repository",
]
