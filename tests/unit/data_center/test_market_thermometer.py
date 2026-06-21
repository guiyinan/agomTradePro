"""Unit tests for market thermometer use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import time

from apps.data_center.application import market_thermometer as market_thermometer_module
from apps.data_center.application.market_thermometer import (
    CalculateMarketThermometerUseCase,
    ImportInvestorAccountsUseCase,
    SyncMarketThermometerInputsUseCase,
    build_market_thermometer_override_payload,
)
from apps.data_center.domain.entities import (
    MacroFact,
    MarketThermometerConfig,
    MarketThermometerSnapshot,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
    ProviderConfig,
)
from apps.data_center.domain.enums import DataQualityStatus
from apps.macro.infrastructure.adapters.base import DataSourceUnavailableError


@dataclass
class _FakeConfigRepo:
    config: MarketThermometerConfig = field(default_factory=MarketThermometerConfig)

    def load(self) -> MarketThermometerConfig:
        return self.config


@dataclass
class _FakeSnapshotRepo:
    snapshots: list[MarketThermometerSnapshot] = field(default_factory=list)

    def get_latest(self) -> MarketThermometerSnapshot | None:
        return max(self.snapshots, key=lambda item: item.observed_at) if self.snapshots else None

    def get_by_date(self, observed_at: date) -> MarketThermometerSnapshot | None:
        for snapshot in self.snapshots:
            if snapshot.observed_at == observed_at:
                return snapshot
        return None

    def list_history(self, days: int = 90) -> list[MarketThermometerSnapshot]:
        del days
        return sorted(self.snapshots, key=lambda item: item.observed_at, reverse=True)

    def save(self, snapshot: MarketThermometerSnapshot) -> MarketThermometerSnapshot:
        self.snapshots = [
            item for item in self.snapshots if item.observed_at != snapshot.observed_at
        ]
        self.snapshots.append(snapshot)
        return snapshot


@dataclass
class _FakeOverrideRepo:
    override: MarketThermometerUserOverride | None = None

    def get_by_user_id(self, user_id: int) -> MarketThermometerUserOverride | None:
        if self.override and self.override.user_id == user_id:
            return self.override
        return None


@dataclass
class _FakeMacroRepo:
    series_map: dict[str, list[MacroFact]]
    stored: list[MacroFact] = field(default_factory=list)

    def get_series(self, indicator_code: str, start=None, end=None, limit: int | None = None):
        del start, end, limit
        return list(self.series_map.get(indicator_code, []))

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        self.stored.extend(facts)
        return len(facts)


@dataclass
class _FakeProviderRepo:
    providers: list[ProviderConfig]

    def list_all(self) -> list[ProviderConfig]:
        return list(self.providers)


@dataclass
class _FakeProviderFactory:
    providers: dict[int, object]

    def get_by_id(self, provider_id: int):
        return self.providers.get(provider_id)


@dataclass
class _FakeRawAuditRepo:
    rows: list[object] = field(default_factory=list)

    def log(self, audit):
        self.rows.append(audit)
        return audit


@dataclass
class _FakeNewsRepo:
    def bulk_insert(self, items):
        return len(items)

    def aggregate_market_daily(self, start, end):
        del start, end
        return []


class _NoDataProvider:
    def provider_name(self) -> str:
        return "AKShare Public"

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del indicator_code, start, end
        return []

    def fetch_news(self, query: str, limit: int = 200):
        del query, limit
        return []


class _RealDataProvider:
    def __init__(self, value: float = 123.0, name: str = "Tushare Pro") -> None:
        self.value = value
        self.name = name

    def provider_name(self) -> str:
        return self.name

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del start, end
        return [_macro_fact(indicator_code, date(2026, 5, 19), self.value, "元")]


class _NamedRealDataProvider:
    def __init__(self, name: str, value: float) -> None:
        self.name = name
        self.value = value

    def provider_name(self) -> str:
        return self.name

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del start, end
        return [_macro_fact(indicator_code, date(2026, 5, 19), self.value, "元")]


class _SelectiveProvider:
    def __init__(self, name: str, values: dict[str, float]) -> None:
        self.name = name
        self.values = values

    def provider_name(self) -> str:
        return self.name

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del start, end
        if indicator_code not in self.values:
            return []
        return [_macro_fact(indicator_code, date(2026, 5, 19), self.values[indicator_code], "元")]


class _OriginalRealDataProvider:
    def provider_name(self) -> str:
        return "Tushare Pro"


class _UnavailableProvider:
    def provider_name(self) -> str:
        return "Unavailable Provider"

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del indicator_code, start, end
        raise DataSourceUnavailableError("provider unavailable")

    def fetch_news(self, query: str, limit: int = 200):
        del query, limit
        raise DataSourceUnavailableError("provider unavailable")


class _WindowAwareProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[str, date, date]] = []

    def provider_name(self) -> str:
        return "AKShare Public"

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        self.requests.append((indicator_code, start, end))
        if indicator_code == "CN_A_NEW_INVESTOR_ACCOUNTS":
            return [
                _macro_fact(indicator_code, date(2026, 3, 31), 100_000, "户"),
                _macro_fact(indicator_code, date(2026, 4, 30), 150_000, "户"),
            ]
        return [_macro_fact(indicator_code, end, 123.0, "元")]


class _SlowProvider:
    def provider_name(self) -> str:
        return "Slow Provider"

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del indicator_code, start, end
        time.sleep(0.05)
        return [_macro_fact("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), 321.0, "元")]

    def fetch_news(self, query: str, limit: int = 200):
        del query, limit
        time.sleep(0.05)
        return []


class _SlowEtfProvider:
    def provider_name(self) -> str:
        return "Slow ETF Provider"

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del start, end
        time.sleep(0.03)
        return [_macro_fact(indicator_code, date(2026, 6, 8), 456.0, "元")]


def _macro_fact(indicator_code: str, reporting_period: date, value: float, unit: str) -> MacroFact:
    return MacroFact(
        indicator_code=indicator_code,
        reporting_period=reporting_period,
        value=value,
        unit=unit,
        source="test",
        quality=DataQualityStatus.VALID,
        fetched_at=datetime(2026, 5, 19, tzinfo=UTC),
    )


def _provider_config(provider_id: int, source_type: str, priority: int) -> ProviderConfig:
    return ProviderConfig(
        id=provider_id,
        name=source_type,
        source_type=source_type,
        is_active=True,
        priority=priority,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def test_sync_market_thermometer_inputs_falls_back_to_next_real_provider():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "tushare", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _NoDataProvider(),
                2: _RealDataProvider(),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    successes = [
        item
        for item in payload["results"]
        if item["status"] == "success" and item["component"] != "etf_net_flow"
    ]
    assert successes
    assert all(item["provider"] == "Tushare Pro" for item in successes)
    assert {
        fact.source for fact in macro_repo.stored if fact.indicator_code != "CN_A_ETF_NET_FLOW"
    } == {"tushare"}


def test_sync_market_thermometer_inputs_continues_after_provider_unavailable():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "tushare", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _UnavailableProvider(),
                2: _RealDataProvider(name="Tushare Pro"),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    turnover_results = [item for item in payload["results"] if item["component"] == "turnover"]
    assert turnover_results[0]["status"] == "error"
    assert turnover_results[1]["status"] == "success"
    assert turnover_results[1]["provider"] == "Tushare Pro"
    assert any(fact.indicator_code == "CN_A_TOTAL_TURNOVER" for fact in macro_repo.stored)


def test_sync_market_thermometer_inputs_times_out_slow_provider_and_continues(monkeypatch):
    monkeypatch.setattr(
        market_thermometer_module,
        "MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        market_thermometer_module,
        "MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES",
        {},
    )
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "tushare", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _SlowProvider(),
                2: _RealDataProvider(name="Tushare Pro"),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    turnover_results = [item for item in payload["results"] if item["component"] == "turnover"]
    assert turnover_results[0]["status"] == "error"
    assert "timed out" in turnover_results[0]["error"]
    assert turnover_results[1]["status"] == "success"
    assert turnover_results[1]["provider"] == "Tushare Pro"


def test_sync_market_thermometer_inputs_applies_etf_timeout_override(monkeypatch):
    monkeypatch.setattr(
        market_thermometer_module,
        "MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        market_thermometer_module,
        "MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES",
        {"etf_net_flow": 0.05},
    )
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(providers=[_provider_config(1, "akshare", 1)]),
        provider_factory=_FakeProviderFactory(providers={1: _SlowEtfProvider()}),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 6, 8))

    consensus_rows = [
        item
        for item in payload["results"]
        if item["component"] == "etf_net_flow"
        and item["provider"] == "data_center_consensus"
        and item["status"] == "success"
    ]
    assert consensus_rows == [
        {
            "component": "etf_net_flow",
            "provider": "data_center_consensus",
            "stored_count": 1,
            "status": "success",
            "verification_status": "single_source",
        }
    ]


def test_sync_market_thermometer_inputs_marks_market_news_no_data_when_nothing_is_stored():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(providers=[_provider_config(1, "akshare", 1)]),
        provider_factory=_FakeProviderFactory(providers={1: _NoDataProvider()}),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    market_news_results = [
        item for item in payload["results"] if item["component"] == "market_news"
    ]
    assert market_news_results == [
        {
            "component": "market_news",
            "provider": "AKShare Public",
            "stored_count": 0,
            "status": "no_data",
        }
    ]


def test_sync_market_thermometer_inputs_fetches_investor_accounts_with_monthly_window():
    macro_repo = _FakeMacroRepo(series_map={})
    provider = _WindowAwareProvider()
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(providers=[_provider_config(1, "akshare", 1)]),
        provider_factory=_FakeProviderFactory(providers={1: provider}),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    success_by_component = {
        item["component"]: item for item in payload["results"] if item["status"] == "success"
    }
    assert success_by_component["new_investor_accounts"]["stored_count"] == 2
    investor_requests = [
        item for item in provider.requests if item[0] == "CN_A_NEW_INVESTOR_ACCOUNTS"
    ]
    assert investor_requests == [
        ("CN_A_NEW_INVESTOR_ACCOUNTS", date(2023, 5, 20), date(2026, 5, 19))
    ]
    assert [
        fact.reporting_period
        for fact in macro_repo.stored
        if fact.indicator_code == "CN_A_NEW_INVESTOR_ACCOUNTS"
    ] == [date(2026, 3, 31), date(2026, 4, 30)]


def test_sync_market_thermometer_inputs_fetches_turnover_and_margin_with_recent_window():
    macro_repo = _FakeMacroRepo(series_map={})
    provider = _WindowAwareProvider()
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(providers=[_provider_config(1, "akshare", 1)]),
        provider_factory=_FakeProviderFactory(providers={1: provider}),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 6, 20))

    success_by_component = {
        item["component"]: item for item in payload["results"] if item["status"] == "success"
    }
    assert success_by_component["turnover"]["stored_count"] == 1
    assert success_by_component["margin_balance"]["stored_count"] == 1
    turnover_request = [item for item in provider.requests if item[0] == "CN_A_TOTAL_TURNOVER"]
    margin_request = [item for item in provider.requests if item[0] == "CN_A_MARGIN_BALANCE"]
    assert turnover_request == [("CN_A_TOTAL_TURNOVER", date(2026, 6, 13), date(2026, 6, 20))]
    assert margin_request == [("CN_A_MARGIN_BALANCE", date(2026, 6, 13), date(2026, 6, 20))]


def test_sync_market_thermometer_inputs_fetches_etf_net_flow_with_recent_window():
    macro_repo = _FakeMacroRepo(series_map={})
    provider = _WindowAwareProvider()
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(providers=[_provider_config(1, "akshare", 1)]),
        provider_factory=_FakeProviderFactory(providers={1: provider}),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    use_case.execute(as_of_date=date(2026, 6, 8))

    etf_requests = [
        item
        for item in provider.requests
        if item[0] in {"CN_A_ETF_NET_FLOW_MAIN", "CN_A_ETF_SIZE_FLOW"}
    ]
    assert etf_requests == [("CN_A_ETF_NET_FLOW_MAIN", date(2026, 6, 1), date(2026, 6, 8))]


def test_sync_etf_net_flow_stores_consensus_when_sources_match():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "eastmoney", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _SelectiveProvider("AKShare Public", {"CN_A_ETF_NET_FLOW_MAIN": 100.0}),
                2: _SelectiveProvider("EastMoney", {"CN_A_ETF_NET_FLOW_MAIN": 100.5}),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    consensus_rows = [
        item
        for item in payload["results"]
        if item["component"] == "etf_net_flow" and item["provider"] == "data_center_consensus"
    ]
    assert consensus_rows == [
        {
            "component": "etf_net_flow",
            "provider": "data_center_consensus",
            "stored_count": 1,
            "status": "success",
            "verification_status": "verified",
        }
    ]
    stored = [fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW"]
    assert len(stored) == 1
    assert stored[0].source == "data_center_consensus"
    assert stored[0].value == 100.0
    assert stored[0].extra["verification_status"] == "verified"
    assert stored[0].extra["primary_indicator"] == "CN_A_ETF_NET_FLOW_MAIN"
    assert len(stored[0].extra["candidates"]) == 2
    atomic_rows = [
        fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW_MAIN"
    ]
    assert len(atomic_rows) == 2
    assert {fact.source for fact in atomic_rows} == {"akshare", "eastmoney"}


def test_sync_etf_net_flow_rejects_mismatched_sources():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "eastmoney", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _SelectiveProvider("AKShare Public", {"CN_A_ETF_NET_FLOW_MAIN": 100.0}),
                2: _SelectiveProvider("EastMoney", {"CN_A_ETF_NET_FLOW_MAIN": 130.0}),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    assert not [fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW"]
    atomic_rows = [
        fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW_MAIN"
    ]
    assert len(atomic_rows) == 2
    assert any(
        item["component"] == "etf_net_flow"
        and item["provider"] == "data_center_consensus"
        and item["status"] == "mismatch"
        for item in payload["results"]
    )


def test_sync_etf_net_flow_marks_single_source_when_only_one_provider_returns_data():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "eastmoney", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _SelectiveProvider("AKShare Public", {"CN_A_ETF_NET_FLOW_MAIN": 100.0}),
                2: _NoDataProvider(),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    stored = [fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW"]
    assert len(stored) == 1
    assert stored[0].extra["verification_status"] == "single_source"
    atomic_rows = [
        fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW_MAIN"
    ]
    assert len(atomic_rows) == 1
    assert atomic_rows[0].source == "akshare"
    assert any(
        item["component"] == "etf_net_flow"
        and item["provider"] == "data_center_consensus"
        and item["verification_status"] == "single_source"
        for item in payload["results"]
    )


def test_sync_etf_net_flow_falls_back_to_size_flow_proxy():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = SyncMarketThermometerInputsUseCase(
        provider_repo=_FakeProviderRepo(
            providers=[
                _provider_config(1, "akshare", 1),
                _provider_config(2, "tushare", 1),
            ]
        ),
        provider_factory=_FakeProviderFactory(
            providers={
                1: _NoDataProvider(),
                2: _SelectiveProvider("Tushare Pro", {"CN_A_ETF_SIZE_FLOW": 88.0}),
            }
        ),
        macro_repo=macro_repo,
        news_repo=_FakeNewsRepo(),
        raw_audit_repo=_FakeRawAuditRepo(),
    )

    payload = use_case.execute(as_of_date=date(2026, 5, 19))

    stored = [fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_NET_FLOW"]
    assert len(stored) == 1
    assert stored[0].value == 88.0
    assert stored[0].extra["verification_status"] == "fallback_proxy"
    assert stored[0].extra["proxy_indicator"] == "CN_A_ETF_SIZE_FLOW"
    proxy_rows = [fact for fact in macro_repo.stored if fact.indicator_code == "CN_A_ETF_SIZE_FLOW"]
    assert len(proxy_rows) == 1
    assert proxy_rows[0].source == "tushare"
    assert proxy_rows[0].value == 88.0
    assert any(
        item["component"] == "etf_net_flow"
        and item["provider"] == "data_center_consensus"
        and item["verification_status"] == "fallback_proxy"
        for item in payload["results"]
    )


def test_build_current_payload_applies_user_override_band():
    snapshot_repo = _FakeSnapshotRepo(
        snapshots=[
            MarketThermometerSnapshot(
                observed_at=date(2026, 5, 19),
                score=78.0,
                band="overheat",
                change_5d=6.0,
                change_20d=15.0,
            )
        ]
    )
    override_repo = _FakeOverrideRepo(
        override=MarketThermometerUserOverride(
            user_id=7,
            thresholds=MarketThermometerThresholds(
                warm_threshold=30.0,
                hot_threshold=50.0,
                overheat_threshold=70.0,
                extreme_threshold=90.0,
            ),
        )
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(),
        snapshot_repo=snapshot_repo,
        override_repo=override_repo,
        macro_repo=_FakeMacroRepo(series_map={}),
    )

    payload = use_case.build_current_payload(
        user_id=7, use_personal_thresholds=True, auto_calculate=False
    )

    assert payload["threshold_source"] == "user_override"
    assert payload["effective_band"] == "overheat"
    assert payload["thresholds"]["hot_threshold"] == 50.0


def test_market_thermometer_change_uses_previous_available_snapshot():
    history_repo = _FakeSnapshotRepo(
        snapshots=[
            MarketThermometerSnapshot(
                observed_at=date(2026, 5, 12),
                score=60.0,
                band="hot",
                change_5d=None,
                change_20d=None,
            ),
            MarketThermometerSnapshot(
                observed_at=date(2026, 5, 13),
                score=61.0,
                band="hot",
                change_5d=None,
                change_20d=None,
            ),
        ]
    )
    macro_repo = _FakeMacroRepo(
        series_map={
            "CN_A_NEW_INVESTOR_ACCOUNTS": [
                _macro_fact("CN_A_NEW_INVESTOR_ACCOUNTS", date(2026, 3, 31), 100_000, "户"),
                _macro_fact("CN_A_NEW_INVESTOR_ACCOUNTS", date(2026, 4, 30), 150_000, "户"),
            ],
            "CN_A_TOTAL_TURNOVER": [
                _macro_fact("CN_A_TOTAL_TURNOVER", date(2026, 4, 29), 500.0, "元"),
                _macro_fact("CN_A_TOTAL_TURNOVER", date(2026, 5, 13), 800.0, "元"),
                _macro_fact("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), 1_200.0, "元"),
            ],
            "CN_A_MARGIN_BALANCE": [
                _macro_fact("CN_A_MARGIN_BALANCE", date(2026, 4, 29), 100.0, "元"),
                _macro_fact("CN_A_MARGIN_BALANCE", date(2026, 5, 13), 115.0, "元"),
                _macro_fact("CN_A_MARGIN_BALANCE", date(2026, 5, 19), 130.0, "元"),
            ],
            "CN_A_ETF_NET_FLOW": [
                _macro_fact("CN_A_ETF_NET_FLOW", date(2026, 4, 29), 10.0, "元"),
                _macro_fact("CN_A_ETF_NET_FLOW", date(2026, 5, 13), 15.0, "元"),
                _macro_fact("CN_A_ETF_NET_FLOW", date(2026, 5, 19), 20.0, "元"),
            ],
            "CN_A_MARKET_NEWS_COUNT": [
                _macro_fact("CN_A_MARKET_NEWS_COUNT", date(2026, 4, 29), 40.0, "篇"),
                _macro_fact("CN_A_MARKET_NEWS_COUNT", date(2026, 5, 13), 50.0, "篇"),
                _macro_fact("CN_A_MARKET_NEWS_COUNT", date(2026, 5, 19), 80.0, "篇"),
            ],
            "CN_A_MARKET_NEWS_SENTIMENT": [
                _macro_fact("CN_A_MARKET_NEWS_SENTIMENT", date(2026, 4, 29), 0.1, "score"),
                _macro_fact("CN_A_MARKET_NEWS_SENTIMENT", date(2026, 5, 13), 0.2, "score"),
                _macro_fact("CN_A_MARKET_NEWS_SENTIMENT", date(2026, 5, 19), 0.4, "score"),
            ],
            "CN_A_MARKET_NEWS_POSITIVE_RATIO": [
                _macro_fact("CN_A_MARKET_NEWS_POSITIVE_RATIO", date(2026, 5, 19), 0.7, "ratio"),
            ],
        }
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(),
        snapshot_repo=history_repo,
        override_repo=_FakeOverrideRepo(),
        macro_repo=macro_repo,
    )

    snapshot = use_case.execute(as_of_date=date(2026, 5, 19))

    assert snapshot.change_5d is not None
    assert round(snapshot.change_5d, 2) == round(snapshot.score - 61.0, 2)


def test_market_thermometer_marks_degraded_when_valid_components_below_minimum():
    config = MarketThermometerConfig(min_valid_components=4)
    macro_repo = _FakeMacroRepo(
        series_map={
            "CN_A_TOTAL_TURNOVER": [
                _macro_fact("CN_A_TOTAL_TURNOVER", date(2026, 5, 15), 100.0, "元"),
                _macro_fact("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), 150.0, "元"),
            ],
            "CN_A_MARGIN_BALANCE": [
                _macro_fact("CN_A_MARGIN_BALANCE", date(2026, 5, 15), 100.0, "元"),
                _macro_fact("CN_A_MARGIN_BALANCE", date(2026, 5, 19), 130.0, "元"),
            ],
            "CN_A_MARKET_NEWS_SENTIMENT": [
                _macro_fact("CN_A_MARKET_NEWS_SENTIMENT", date(2026, 5, 19), 0.3, "score"),
            ],
            "CN_A_MARKET_NEWS_POSITIVE_RATIO": [
                _macro_fact("CN_A_MARKET_NEWS_POSITIVE_RATIO", date(2026, 5, 19), 0.6, "ratio"),
            ],
        }
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(config=config),
        snapshot_repo=_FakeSnapshotRepo(),
        override_repo=_FakeOverrideRepo(),
        macro_repo=macro_repo,
    )

    snapshot = use_case.execute(as_of_date=date(2026, 5, 19))

    assert snapshot.must_not_use_for_decision is True
    assert "有效组件数不足" in snapshot.blocked_reason


def test_build_current_payload_marks_score_unavailable_when_all_components_missing():
    snapshot_repo = _FakeSnapshotRepo(
        snapshots=[
            MarketThermometerSnapshot(
                observed_at=date(2026, 5, 22),
                score=0.0,
                band="cold",
                change_5d=None,
                change_20d=None,
                valid_component_count=0,
                data_source="degraded",
                must_not_use_for_decision=True,
                blocked_reason="有效组件数不足，当前仅 0 个，低于要求 4 个。",
            )
        ]
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(),
        snapshot_repo=snapshot_repo,
        override_repo=_FakeOverrideRepo(),
        macro_repo=_FakeMacroRepo(series_map={}),
    )

    payload = use_case.build_current_payload(auto_calculate=False)

    assert payload["score_available"] is False


def test_build_current_payload_falls_back_to_latest_score_snapshot_when_current_is_empty():
    snapshot_repo = _FakeSnapshotRepo(
        snapshots=[
            MarketThermometerSnapshot(
                observed_at=date(2026, 6, 20),
                score=0.0,
                band="cold",
                change_5d=None,
                change_20d=None,
                valid_component_count=0,
                data_source="degraded",
                must_not_use_for_decision=True,
                blocked_reason="有效组件数不足，当前仅 0 个，低于要求 4 个。",
            ),
            MarketThermometerSnapshot(
                observed_at=date(2026, 6, 5),
                score=51.95,
                band="warm",
                change_5d=1.0,
                change_20d=3.0,
                valid_component_count=4,
                data_source="calculated",
                must_not_use_for_decision=False,
                blocked_reason="",
            ),
        ]
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(),
        snapshot_repo=snapshot_repo,
        override_repo=_FakeOverrideRepo(),
        macro_repo=_FakeMacroRepo(series_map={}),
    )

    payload = use_case.build_current_payload(auto_calculate=False)

    assert payload["observed_at"] == "2026-06-05"
    assert payload["score"] == 51.95
    assert payload["score_available"] is True
    assert payload["fallback_used"] is True
    assert payload["latest_snapshot_observed_at"] == "2026-06-20"
    assert payload["must_not_use_for_decision"] is True
    assert "已回退展示最近有效快照 2026-06-05" in payload["blocked_reason"]


def test_build_current_payload_prefers_history_when_current_snapshot_is_more_degraded():
    snapshot_repo = _FakeSnapshotRepo(
        snapshots=[
            MarketThermometerSnapshot(
                observed_at=date(2026, 6, 20),
                score=50.0,
                band="warm",
                change_5d=-1.95,
                change_20d=-6.0,
                valid_component_count=1,
                data_source="degraded",
                must_not_use_for_decision=True,
                blocked_reason="有效组件数不足，当前仅 1 个，低于要求 4 个。",
            ),
            MarketThermometerSnapshot(
                observed_at=date(2026, 6, 5),
                score=51.95,
                band="warm",
                change_5d=1.0,
                change_20d=3.0,
                valid_component_count=3,
                data_source="degraded",
                must_not_use_for_decision=True,
                blocked_reason="有效组件数不足，当前仅 3 个，低于要求 4 个。",
            ),
        ]
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(),
        snapshot_repo=snapshot_repo,
        override_repo=_FakeOverrideRepo(),
        macro_repo=_FakeMacroRepo(series_map={}),
    )

    payload = use_case.build_current_payload(auto_calculate=False)

    assert payload["observed_at"] == "2026-06-05"
    assert payload["score"] == 51.95
    assert payload["fallback_used"] is True
    assert payload["latest_snapshot_observed_at"] == "2026-06-20"
    assert "当前仅 1 个" in payload["blocked_reason"]


def test_build_current_payload_recalculates_when_latest_snapshot_is_stale(monkeypatch):
    snapshot_repo = _FakeSnapshotRepo(
        snapshots=[
            MarketThermometerSnapshot(
                observed_at=date(2026, 6, 5),
                score=51.95,
                band="warm",
                change_5d=1.0,
                change_20d=3.0,
                valid_component_count=3,
                data_source="degraded",
                must_not_use_for_decision=True,
                blocked_reason="有效组件数不足，当前仅 3 个，低于要求 4 个。",
            )
        ]
    )
    use_case = CalculateMarketThermometerUseCase(
        config_repo=_FakeConfigRepo(),
        snapshot_repo=snapshot_repo,
        override_repo=_FakeOverrideRepo(),
        macro_repo=_FakeMacroRepo(series_map={}),
    )
    captured: dict[str, object] = {}
    fresh_snapshot = MarketThermometerSnapshot(
        observed_at=date(2026, 6, 20),
        score=63.2,
        band="hot",
        change_5d=4.1,
        change_20d=8.3,
        valid_component_count=4,
        data_source="calculated",
        must_not_use_for_decision=False,
        blocked_reason="",
    )

    class _FakeToday(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 20)

    def _fake_execute(*, as_of_date=None):
        captured["as_of_date"] = as_of_date
        snapshot_repo.save(fresh_snapshot)
        return fresh_snapshot

    monkeypatch.setattr(market_thermometer_module, "date", _FakeToday)
    monkeypatch.setattr(use_case, "execute", _fake_execute)

    payload = use_case.build_current_payload(auto_calculate=True)

    assert captured["as_of_date"] == date(2026, 6, 20)
    assert payload["observed_at"] == "2026-06-20"
    assert payload["score"] == 63.2
    assert payload["must_not_use_for_decision"] is False


def test_import_investor_accounts_use_case_parses_csv_rows():
    macro_repo = _FakeMacroRepo(series_map={})
    use_case = ImportInvestorAccountsUseCase(macro_repo)

    result = use_case.execute(
        "reporting_period,value\n2026-03-31,12345\n2026-04-30,23456\n",
        source="manual_import",
    )

    assert result["stored_count"] == 2
    assert macro_repo.stored[0].indicator_code == "CN_A_NEW_INVESTOR_ACCOUNTS"
    assert macro_repo.stored[1].value == 23456.0


def test_build_market_thermometer_override_payload_prefers_override():
    payload = build_market_thermometer_override_payload(
        config=MarketThermometerConfig(),
        override=MarketThermometerUserOverride(
            user_id=1,
            thresholds=MarketThermometerThresholds(
                warm_threshold=28.0,
                hot_threshold=52.0,
                overheat_threshold=70.0,
                extreme_threshold=90.0,
            ),
        ),
    )

    assert payload["source"] == "user_override"
    assert payload["effective"]["hot_threshold"] == 52.0
