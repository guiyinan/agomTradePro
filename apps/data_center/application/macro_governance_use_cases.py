"""Macro-governance action orchestration for Data Center."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.data_center.application.dtos import SyncMacroRequest, SyncResult
from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    MacroGovernanceRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
)

_SOURCE_TYPE_CAPABILITIES = SOURCE_TYPE_CAPABILITIES


class RunMacroGovernanceActionUseCase:
    """Execute macro governance repair actions through governed repositories/use cases."""

    DEFAULT_SCOPE = "macro_console"

    def __init__(
        self,
        governance_repo: MacroGovernanceRepositoryProtocol,
        provider_repo: ProviderConfigRepositoryProtocol,
        sync_macro_runner: Callable[[SyncMacroRequest], SyncResult],
    ) -> None:
        self._governance_repo = governance_repo
        self._provider_repo = provider_repo
        self._sync_macro_runner = sync_macro_runner

    def execute(self, action: str) -> dict[str, Any]:
        if action == "canonicalize_sources":
            repair = self._governance_repo.canonicalize_sources(scope=self.DEFAULT_SCOPE)
            return {
                "action": action,
                "label": "统一 source 别名",
                "status": "success",
                "details": repair,
            }

        if action == "normalize_units":
            details = self._normalize_units()
            return {
                "action": action,
                "label": "重跑单位标准化",
                "status": "success",
                "details": details,
            }

        if action == "sync_missing_series":
            details = self._sync_missing_series()
            return {
                "action": action,
                "label": "补同步缺失序列",
                "status": "success",
                "details": details,
            }

        if action == "run_full_repair":
            source_details = self._governance_repo.canonicalize_sources(scope=self.DEFAULT_SCOPE)
            normalize_details = self._normalize_units()
            sync_details = self._sync_missing_series()
            return {
                "action": action,
                "label": "执行完整治理",
                "status": "success",
                "details": {
                    "source": source_details,
                    "normalize": normalize_details,
                    "sync": sync_details,
                },
            }

        raise ValueError(f"Unsupported governance action: {action}")

    def _normalize_units(self) -> dict[str, Any]:
        indicator_codes = self._governance_repo.list_governed_indicator_codes(
            scope=self.DEFAULT_SCOPE
        )
        details = self._governance_repo.normalize_macro_fact_units(
            indicator_codes=indicator_codes,
            dry_run=False,
        )
        return {
            "indicator_codes": indicator_codes,
            **details,
        }

    def _sync_missing_series(self) -> dict[str, Any]:
        payload = self._governance_repo.build_snapshot(scope=self.DEFAULT_SCOPE)
        supported_sync_codes = set(payload.get("supported_sync_codes") or [])
        indicator_rows = payload.get("indicator_rows") or []
        target_rows = [
            row
            for row in indicator_rows
            if "missing_supported" in (row.get("tags") or [])
            and row.get("code") in supported_sync_codes
        ]
        if not target_rows:
            return {
                "indicator_codes": [],
                "sync_runs": [],
                "message": "No supported missing indicator codes to sync.",
            }

        target_date = datetime.now(UTC).date()
        start_date = target_date - timedelta(days=365 * 10)
        sync_runs: list[dict[str, Any]] = []

        for row in target_rows:
            indicator_code = str(row.get("code") or "").strip()
            source_type = str(row.get("sync_source_type") or "").strip()
            if not indicator_code:
                continue
            if not source_type:
                raise ValueError(
                    f"Governed indicator {indicator_code} is missing governance_sync_source_type"
                )

            provider_id = self._resolve_macro_provider_id(source_type)
            sync_result = self._sync_macro_runner(
                SyncMacroRequest(
                    provider_id=provider_id,
                    indicator_code=indicator_code,
                    start=start_date,
                    end=target_date,
                )
            )
            sync_runs.append(
                {
                    "indicator_code": indicator_code,
                    "source_type": source_type,
                    "provider_id": provider_id,
                    "provider_name": sync_result.provider_name,
                    "stored_count": sync_result.stored_count,
                    "status": sync_result.status,
                }
            )

        return {
            "indicator_codes": [
                str(row.get("code") or "").strip() for row in target_rows if row.get("code")
            ],
            "sync_runs": sync_runs,
        }

    def _resolve_macro_provider_id(self, source_type: str) -> int:
        providers = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.id is not None
            and provider.is_active
            and provider.source_type == source_type
            and DataCapability.MACRO.value
            in _SOURCE_TYPE_CAPABILITIES.get(provider.source_type, ())
        ]
        providers.sort(key=lambda provider: provider.priority)
        if not providers:
            raise ValueError(f"No active macro provider configured for source_type={source_type}")
        return int(providers[0].id)


__all__ = ["RunMacroGovernanceActionUseCase"]
