"""Tushare stock_basic and listing-date metadata provider for A-share assets."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.protocols import ProviderConfigRepositoryProtocol
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.tushare_client import create_tushare_pro_client

from .a_share_universe_contracts import (
    AShareCodeNameRow,
    AShareUniverseSyncError,
    _EmptyProviderSegment,
    _Frame,
    _normalize_provider_listing_date,
    _parse_provider_frame,
    _provider_text,
)

logger = logging.getLogger(__name__)


class TushareAshareCodeNameProvider:
    """Load current listed A-shares and listing-date evidence from Tushare."""

    source_name = "tushare.stock_basic"

    def __init__(self, config_repo: ProviderConfigRepositoryProtocol | None = None) -> None:
        self._config_repo = config_repo or ProviderConfigRepository()
        self.list_date_enrichment_status = "not_started"

    def load_code_names(self) -> list[AShareCodeNameRow]:
        """Request all current-listed A-shares and normalize their listing dates."""

        configs = self._config_repo.get_active_by_type("tushare")
        if not configs:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_UNAVAILABLE",
                category="failover_unavailable",
                source=self.source_name,
                details={"provider": "tushare", "reason": "no_active_configuration"},
            )
        config = configs[0]
        if config.id is None:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_CONFIG_INVALID",
                category="failover_configuration",
                source=self.source_name,
                details={"reason": "provider_id_missing"},
            )
        source = (
            f"tushare.stock_basic[provider_id={config.id};" "exchanges=SSE,SZSE,BSE;list_status=L]"
        )
        self.source_name = source
        request_mode_value = config.extra_config.get("tushare_request_mode")
        request_mode = request_mode_value.strip() if isinstance(request_mode_value, str) else None
        deployment_region = (
            (
                os.environ.get("DATA_CENTER_DEPLOYMENT_REGION")
                or os.environ.get("AGOMTRADEPRO_DEPLOYMENT_REGION")
                or "unknown"
            )
            .strip()
            .lower()
        )
        client = self._create_client(
            config=config,
            request_mode=request_mode,
            deployment_region=deployment_region,
            dataset_key="tushare.stock_basic",
            source=source,
        )

        rows: list[AShareCodeNameRow] = []
        for exchange in ("SSE", "SZSE", "BSE"):
            try:
                frame_value = client.stock_basic(
                    exchange=exchange,
                    list_status="L",
                    fields="ts_code,name,exchange,list_status,list_date",
                )
                if frame_value is None:
                    raise _EmptyProviderSegment(exchange)
                frame = cast(_Frame, frame_value)
                if frame.empty:
                    raise _EmptyProviderSegment(exchange)
                rows.extend(
                    _parse_provider_frame(
                        frame,
                        source=source,
                        segment=exchange,
                        code_column="ts_code",
                        name_column="name",
                        expected_exchange=exchange,
                        include_list_date=True,
                    )
                )
            except AShareUniverseSyncError:
                raise
            except Exception as exc:
                error_code = (
                    "A_SHARE_UNIVERSE_FAILOVER_EMPTY_SEGMENT"
                    if isinstance(exc, _EmptyProviderSegment)
                    else "A_SHARE_UNIVERSE_FAILOVER_UNAVAILABLE"
                )
                raise AShareUniverseSyncError(
                    error_code,
                    category="failover_provider",
                    source=source,
                    details={"segment": exchange, "exception_type": type(exc).__name__},
                ) from exc
        if not rows:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_EMPTY",
                category="failover_provider",
                source=source,
            )
        return self._enrich_unverified_listing_dates(
            rows,
            config=config,
            request_mode=request_mode,
            deployment_region=deployment_region,
        )

    def _create_client(
        self,
        *,
        config: ProviderConfig,
        request_mode: str | None,
        deployment_region: str,
        dataset_key: str,
        source: str,
    ) -> Any:
        """Create one provider client whose route identity matches its dataset."""

        try:
            return cast(
                Any,
                create_tushare_pro_client(
                    token=config.api_key,
                    http_url=config.http_url,
                    request_mode=request_mode,
                    provider_id=config.id,
                    deployment_region=deployment_region or "unknown",
                    dataset_key=dataset_key,
                ),
            )
        except Exception as exc:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_UNAVAILABLE",
                category="failover_unavailable",
                source=source,
                details={"exception_type": type(exc).__name__, "dataset_key": dataset_key},
            ) from exc

    def _enrich_unverified_listing_dates(
        self,
        rows: list[AShareCodeNameRow],
        *,
        config: ProviderConfig,
        request_mode: str | None,
        deployment_region: str,
    ) -> list[AShareCodeNameRow]:
        """Correct missing stock_basic dates from Tushare's listing-date issue_date field."""

        unverified_rows = [row for row in rows if row.get("list_date_status") != "verified"]
        if not unverified_rows:
            self.list_date_enrichment_status = "complete"
            return rows

        source = f"tushare.new_share[provider_id={config.id}]"
        try:
            client = self._create_client(
                config=config,
                request_mode=request_mode,
                deployment_region=deployment_region,
                dataset_key="tushare.new_share",
                source=source,
            )
            today = datetime.now(UTC).date()
            start_date = today - timedelta(days=90)
            # `new_share.issue_date` is the listing date; `ipo_date` is the
            # subscription date. Date filters select records from the recent IPO window.
            frame_value = client.new_share(
                start_date=start_date.strftime("%Y%m%d"),
                end_date=today.strftime("%Y%m%d"),
                fields="ts_code,issue_date",
            )
            if frame_value is None:
                raise ValueError("new_share response is unavailable")
            issue_dates = self._parse_new_share_issue_dates(cast(_Frame, frame_value), source)
        except Exception as exc:
            self.list_date_enrichment_status = "unavailable"
            logger.warning(
                "A-share listing-date enrichment unavailable source=%s error=%s",
                source,
                type(exc).__name__,
            )
            for row in unverified_rows:
                row["list_date_status"] = "unverified"
            return rows

        corrected_count = 0
        for row in unverified_rows:
            issue_date = issue_dates.get(row["code"].strip().upper())
            if issue_date is None:
                row["list_date_status"] = "unknown"
                continue
            row["list_date"] = issue_date
            row["list_date_status"] = "verified"
            row["list_date_source"] = f"{source}.issue_date"
            corrected_count += 1
        self.list_date_enrichment_status = (
            "complete" if corrected_count == len(unverified_rows) else "partial"
        )
        return rows

    @staticmethod
    def _parse_new_share_issue_dates(frame: _Frame, source: str) -> dict[str, str]:
        """Normalize new_share.issue_date values as listing dates, ignoring conflicts."""

        columns = {str(column) for column in cast(Iterable[object], frame.columns)}
        required = {"ts_code", "issue_date"}
        if not required.issubset(columns):
            raise ValueError("new_share response schema is incomplete")
        records = cast(list[object], frame.to_dict("records"))
        result: dict[str, str] = {}
        conflicts: set[str] = set()
        for index, raw_record in enumerate(records):
            if not isinstance(raw_record, Mapping):
                raise ValueError("new_share response contains an invalid row")
            record = cast(Mapping[str, object], raw_record)
            code = _provider_text(record.get("ts_code")).upper()
            issue_date, status = _normalize_provider_listing_date(
                record.get("issue_date"),
                source=source,
                segment="new_share",
                row_index=index,
            )
            if not code or status != "verified" or issue_date is None:
                continue
            if code in result and result[code] != issue_date:
                conflicts.add(code)
                result.pop(code, None)
                continue
            if code not in conflicts:
                result[code] = issue_date
        return result
