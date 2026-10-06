"""Infrastructure route and governed budget loader for AKShare slice sync."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from django.conf import settings

from apps.data_center.akshare_financial_capture_composition import (
    MAX_AKSHARE_FINANCIAL_PAGE_SIZE,
    AkshareFinancialCaptureGateway,
    build_akshare_financial_capture_gateway,
)
from apps.data_center.application.financial_slice_sync import (
    FinancialSliceFetcherProtocol,
    FinancialSliceSyncBudget,
)
from apps.data_center.domain.entities import FinancialFact, ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import UnifiedDataProviderProtocol
from apps.data_center.infrastructure._provider_adapter_akshare import (
    AkshareUnifiedProviderAdapter,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    akshare_notice_date_match_contract,
)
from core.exceptions import DataFetchError

_BUDGET_PATH = Path("governance") / "financial_sync_request_budgets.json"


class _BoundAkshareFinancialSliceFetcher:
    """Bind one exact AKShare adapter row to one preflighted capture gateway."""

    def __init__(
        self,
        provider: AkshareUnifiedProviderAdapter,
        gateway: AkshareFinancialCaptureGateway,
    ) -> None:
        """Keep the row-specific adapter and checked gateway together."""

        self._provider = provider
        self._gateway = gateway

    def fetch_financials_for_announcement_date(
        self,
        asset_code: str,
        announcement_date: date,
        periods: int,
    ) -> list[FinancialFact]:
        """Use only the retained dual-capture AKShare adapter path."""

        return self._provider.fetch_financials_for_announcement_date(
            asset_code,
            announcement_date,
            periods,
            capture_gateway=self._gateway,
        )


def build_akshare_financial_slice_fetcher(
    config: ProviderConfig,
    provider: UnifiedDataProviderProtocol,
    *,
    artifact_storage_root: Path | None = None,
) -> FinancialSliceFetcherProtocol:
    """Preflight the exact adapter row and approved dual-capture capability."""

    provider_id = config.id
    if (
        config.source_type != "akshare"
        or config.is_active is not True
        or provider_id is None
        or isinstance(provider_id, bool)
        or provider_id <= 0
        or not isinstance(provider, AkshareUnifiedProviderAdapter)
        or provider.provider_id() != provider_id
        or not provider.supports(DataCapability.FINANCIAL)
    ):
        raise DataFetchError(
            "AKShare financial slice route does not match the exact active provider row",
            code="AKSHARE_FINANCIAL_PROVIDER_IDENTITY_INVALID",
        )
    if artifact_storage_root is None:
        gateway = build_akshare_financial_capture_gateway(
            config,
            deployment_region=_deployment_region(),
        )
    else:
        gateway = build_akshare_financial_capture_gateway(
            config,
            deployment_region=_deployment_region(),
            artifact_storage_root=artifact_storage_root,
        )
    return _BoundAkshareFinancialSliceFetcher(provider, gateway)


def load_akshare_financial_slice_sync_budget(
    path: Path | None = None,
) -> FinancialSliceSyncBudget | None:
    """Load a strict request ceiling bound to the checked-in AKShare contract."""

    budget_path = path or (Path(settings.BASE_DIR) / _BUDGET_PATH)
    try:
        payload: object = json.loads(budget_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    contract = akshare_notice_date_match_contract()
    if (
        payload.get("schema_version") != "akshare-financial-sync-request-budget.v1"
        or payload.get("status") != "enforced"
        or payload.get("provider_name") != contract.provider_name
        or payload.get("contract_id") != contract.contract_id
        or payload.get("contract_version") != contract.contract_version
        or payload.get("contract_sha256") != contract.contract_sha256
        or payload.get("does_not_authorize_provider_access") is not True
    ):
        return None
    try:
        max_slices = _positive_int(payload.get("max_asset_announcement_slices_per_invocation"))
        requests_per_slice = _positive_int(
            payload.get("provider_requests_per_asset_announcement_slice")
        )
        max_requests = _positive_int(payload.get("max_provider_requests_per_invocation"))
        max_rows = _positive_int(payload.get("max_period_rows_per_capture"))
    except ValueError:
        return None
    if max_rows != MAX_AKSHARE_FINANCIAL_PAGE_SIZE:
        return None
    try:
        return FinancialSliceSyncBudget(
            max_slices=max_slices,
            provider_requests_per_slice=requests_per_slice,
            max_provider_requests=max_requests,
            max_period_rows_per_capture=max_rows,
        )
    except ValueError:
        return None


def _deployment_region() -> str:
    """Return the configured, non-secret egress region label."""

    return (
        str(
            os.environ.get("DATA_CENTER_DEPLOYMENT_REGION")
            or os.environ.get("AGOMTRADEPRO_DEPLOYMENT_REGION")
            or "unknown"
        )
        .strip()
        .lower()
        or "unknown"
    )


def _positive_int(value: object) -> int:
    """Narrow one JSON number to a positive integer without bool coercion."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("financial slice request budget value is invalid")
    return value


__all__ = [
    "build_akshare_financial_slice_fetcher",
    "load_akshare_financial_slice_sync_budget",
]
