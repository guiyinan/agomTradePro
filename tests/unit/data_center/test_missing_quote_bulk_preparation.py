"""Offline integration proposals for missing-quote suspension verification."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

import pandas as pd
import pytest

from apps.data_center.application.market_publication_refresh import (
    refresh_market_price_inputs,
)
from apps.data_center.application.model_history_preparation import (
    ModelHistoryFetchAuditResult,
    ModelHistoryReferenceSnapshot,
)
from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.infrastructure.tushare_model_market_source import (
    TushareModelMarketSource,
)
from core.exceptions import DataFetchError

TARGET = date(2026, 9, 18)
HISTORY_START = TARGET - timedelta(days=120)
MISSING_CODES = ("000016.SZ", "002731.SZ")


class MissingQuoteClient:
    """Return empty target caches and auditable prior history through SDK-shaped methods."""

    def __init__(self, *, fail_history: bool = False) -> None:
        self.fail_history = fail_history
        self.calls: list[tuple[str, dict[str, object]]] = []

    def daily(self, **kwargs: object) -> pd.DataFrame:
        """Return no target-day rows, then either prior-day rows or a batch failure."""

        self.calls.append(("daily", dict(kwargs)))
        if kwargs.get("start_date") == TARGET.strftime("%Y%m%d"):
            return pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "pct_chg",
                    "amount",
                ]
            )
        if self.fail_history:
            raise DataFetchError(
                "synthetic audited history batch failure",
                code="EGRESS_PROVIDER_UNAVAILABLE",
            )
        prior_date = (TARGET - timedelta(days=1)).strftime("%Y%m%d")
        codes = tuple(str(kwargs["ts_code"]).split(","))
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_date": prior_date,
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "vol": 100,
                    "pct_chg": 0,
                    "amount": 50,
                }
                for code in codes
            ]
        )

    def adj_factor(self, **kwargs: object) -> pd.DataFrame:
        """Return no target factors and matching factors for historical rows."""

        self.calls.append(("adj_factor", dict(kwargs)))
        if kwargs.get("start_date") == TARGET.strftime("%Y%m%d"):
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
        prior_date = (TARGET - timedelta(days=1)).strftime("%Y%m%d")
        codes = tuple(str(kwargs["ts_code"]).split(","))
        return pd.DataFrame(
            [{"ts_code": code, "trade_date": prior_date, "adj_factor": 1} for code in codes]
        )

    def trade_cal(self, **kwargs: object) -> pd.DataFrame:
        """Return the target session for the exact stale-row check."""

        self.calls.append(("trade_cal", dict(kwargs)))
        return pd.DataFrame([{"cal_date": TARGET.strftime("%Y%m%d"), "is_open": "1"}])

    def suspend_d(self, **kwargs: object) -> pd.DataFrame:
        """Return no full-day suspension claim; callers must keep the scope blocked."""

        self.calls.append(("suspend_d", dict(kwargs)))
        return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"])


class RecordingFetchAudit:
    """Provide only the typed audit-result boundary used by the real service."""

    def __init__(self) -> None:
        self.references: list[RawAuditReference] = []

    def record_model_history_fetch_success(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        rows: tuple[ModelDailyBar, ...],
        request_details: Mapping[str, object],
        reference_snapshot: ModelHistoryReferenceSnapshot,
    ) -> ModelHistoryFetchAuditResult:
        """Return a distinct stable reference for each actual batch envelope."""

        sequence = len(self.references) + 1
        reference = RawAuditReference(
            raw_audit_id=f"batch-{sequence}",
            version="raw-audit-v1",
            content_hash=f"{sequence:064x}",
            run_id=f"run-{sequence}",
            ingested_run_id=f"ingest-{sequence}",
        )
        self.references.append(reference)
        return ModelHistoryFetchAuditResult(
            provider_name="tushare",
            stored_count=len(rows),
            stored_asset_codes=tuple(sorted({row.asset_code for row in rows})),
            raw_audit_reference=reference,
            source_type="tushare",
        )

    def record_model_history_fetch_failure(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        error: BaseException,
        request_details: Mapping[str, object],
    ) -> RawAuditReference:
        """Return an audit identity for a failed request without claiming stored rows."""

        sequence = len(self.references) + 1
        return RawAuditReference(
            raw_audit_id=f"failed-batch-{sequence}",
            version="raw-audit-v1",
            content_hash=f"{sequence:064x}",
            run_id=f"failed-run-{sequence}",
            ingested_run_id=f"failed-ingest-{sequence}",
        )


class NoPerAssetFallback:
    """Expose no single-fetch audit capability and detect any forbidden direct read."""

    def __init__(self) -> None:
        self.reads = 0

    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Fail if the application reaches this provider without its audited contract."""

        self.reads += 1
        raise AssertionError("scope-gated fallback must not issue per-asset I/O")

    def index_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        return ()

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        return (TARGET,)

    def index_members(self, index_code: str, target_date: date) -> tuple[str, ...]:
        return ()


def _service(
    client: MissingQuoteClient,
) -> tuple[ModelMarketDataService, NoPerAssetFallback]:
    """Build the real service around Tushare's batch cache and a blocked fallback."""

    audit = RecordingFetchAudit()
    tushare = TushareModelMarketSource(
        client,
        source="tushare",
        provider_id=17,
        history_fetch_audit=audit,
    )
    fallback = NoPerAssetFallback()
    service = ModelMarketDataService(
        (
            ModelMarketRoute("tushare-primary", tushare, source_type="tushare", provider_id=17),
            ModelMarketRoute("akshare-fallback", fallback, source_type="akshare", provider_id=29),
        ),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
        reference_history_snapshot=lambda codes, start, end: ModelHistoryReferenceSnapshot.from_bars(
            codes, start, end, dict.fromkeys(codes, ())
        ),
        history_fetch_audit=audit,
        max_per_asset_preparation_assets=1,
    )
    return service, fallback


def test_empty_target_cache_keeps_primary_error_then_uses_one_history_batch():
    """Bulk history proceeds while target and prior successful audit bindings remain intact."""

    client = MissingQuoteClient()
    service, fallback = _service(client)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(service, list(MISSING_CODES), TARGET)

    # No full-day suspension proof was returned, so the stale history stays blocked.
    assert caught.value.code == "MODEL_MARKET_STALE"
    history_fetches = [
        kwargs
        for name, kwargs in client.calls
        if name in {"daily", "adj_factor"}
        and kwargs.get("start_date") == HISTORY_START.strftime("%Y%m%d")
        and kwargs.get("end_date") == TARGET.strftime("%Y%m%d")
    ]
    assert len(history_fetches) == 2
    assert {tuple(str(kwargs["ts_code"]).split(",")) for kwargs in history_fetches} == {
        MISSING_CODES
    }
    assert fallback.reads == 0
    assert tuple(
        binding.reference.raw_audit_id for binding in service.take_model_history_audit_bindings()
    ) == ("batch-1", "batch-2")


def test_failed_group_history_batch_never_excludes_missing_quotes():
    """An unavailable exact batch remains an error and creates no suspension result."""

    client = MissingQuoteClient(fail_history=True)
    service, fallback = _service(client)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(service, list(MISSING_CODES), TARGET)

    assert caught.value.code == "EGRESS_PROVIDER_UNAVAILABLE"
    history_fetches = [
        kwargs
        for name, kwargs in client.calls
        if name == "daily"
        and kwargs.get("start_date") == HISTORY_START.strftime("%Y%m%d")
        and kwargs.get("end_date") == TARGET.strftime("%Y%m%d")
    ]
    assert len(history_fetches) == 1
    assert tuple(str(history_fetches[0]["ts_code"]).split(",")) == MISSING_CODES
    assert fallback.reads == 0


def test_target_success_audit_bindings_survive_exact_missing_quote_batch():
    """A current member stays bound while only the exact misses enter history prep."""

    success_code = "600001.SH"
    all_codes = (success_code, *MISSING_CODES)

    class MixedTargetQuoteClient(MissingQuoteClient):
        def __init__(self) -> None:
            super().__init__()
            self.history_requested = False

        def daily(self, **kwargs: object) -> pd.DataFrame:
            if kwargs.get("start_date") != TARGET.strftime("%Y%m%d"):
                self.history_requested = True
                return super().daily(**kwargs)
            self.calls.append(("daily", dict(kwargs)))
            return pd.DataFrame(
                [
                    {
                        "ts_code": success_code,
                        "trade_date": TARGET.strftime("%Y%m%d"),
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10,
                        "vol": 100,
                        "pct_chg": 0,
                        "amount": 50,
                    }
                ]
            )

        def adj_factor(self, **kwargs: object) -> pd.DataFrame:
            if kwargs.get("start_date") != TARGET.strftime("%Y%m%d"):
                return super().adj_factor(**kwargs)
            self.calls.append(("adj_factor", dict(kwargs)))
            return pd.DataFrame(
                [
                    {
                        "ts_code": success_code,
                        "trade_date": TARGET.strftime("%Y%m%d"),
                        "adj_factor": 1,
                    }
                ]
            )

        def suspend_d(self, **kwargs: object) -> pd.DataFrame:
            self.calls.append(("suspend_d", dict(kwargs)))
            asset_code = str(kwargs.get("ts_code") or "")
            if self.history_requested and asset_code in MISSING_CODES:
                return pd.DataFrame(
                    [
                        {
                            "ts_code": asset_code,
                            "trade_date": TARGET.strftime("%Y%m%d"),
                            "suspend_type": "S",
                            "suspend_timing": None,
                        }
                    ]
                )
            return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"])

    client = MixedTargetQuoteClient()
    service, fallback = _service(client)

    result = refresh_market_price_inputs(service, list(all_codes), TARGET)

    assert result.suspended_codes == MISSING_CODES
    assert tuple(
        (item.asset_code, item.target_trade_date, item.evidence_source)
        for item in result.suspension_evidence
    ) == tuple((code, TARGET, "tushare") for code in MISSING_CODES)
    history_fetches = [
        (name, kwargs)
        for name, kwargs in client.calls
        if name in {"daily", "adj_factor"}
        and kwargs.get("start_date") == HISTORY_START.strftime("%Y%m%d")
        and kwargs.get("end_date") == TARGET.strftime("%Y%m%d")
    ]
    assert len(history_fetches) == 2
    assert {tuple(str(kwargs["ts_code"]).split(",")) for _, kwargs in history_fetches} == {
        MISSING_CODES
    }

    member_bindings = result.member_owning_raw_audit_bindings
    assert len(member_bindings) == 1
    assert member_bindings[0].source_type == "tushare"
    assert member_bindings[0].reference.raw_audit_id == "batch-1"
    assert tuple(binding.reference.raw_audit_id for binding in result.raw_audit_bindings) == (
        "batch-1",
        "batch-2",
    )
    assert fallback.reads == 0
