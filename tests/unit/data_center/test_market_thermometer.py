"""Unit tests for market thermometer use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

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


class _RealDataProvider:
    def provider_name(self) -> str:
        return "Tushare Pro"

    def fetch_macro_series(self, indicator_code: str, start: date, end: date) -> list[MacroFact]:
        del start, end
        return [_macro_fact(indicator_code, date(2026, 5, 19), 123.0, "元")]


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

    successes = [item for item in payload["results"] if item["status"] == "success"]
    assert successes
    assert all(item["provider"] == "Tushare Pro" for item in successes)
    assert {fact.source for fact in macro_repo.stored} == {"tushare"}


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
