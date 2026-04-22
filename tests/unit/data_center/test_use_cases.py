"""
Unit tests for data_center application use cases.

Uses in-memory stub implementations — no DB or Django required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from apps.data_center.application.dtos import (
    CreateProviderRequest,
    DecisionReliabilityRepairRequest,
    LatestQuoteRequest,
    MacroSeriesRequest,
    UpdateProviderRequest,
)
from apps.data_center.application.use_cases import (
    ManageProviderConfigUseCase,
    QueryLatestQuoteUseCase,
    QueryMacroSeriesUseCase,
    RepairDecisionDataReliabilityUseCase,
    RunProviderConnectionTestUseCase,
)
from apps.data_center.domain.entities import (
    ConnectionTestResult,
    IndicatorCatalog,
    MacroFact,
    PriceBar,
    ProviderConfig,
    QuoteSnapshot,
    RawAudit,
)
from apps.data_center.domain.enums import DataQualityStatus

# ---------------------------------------------------------------------------
# In-memory stub repository
# ---------------------------------------------------------------------------


class _InMemoryRepo:
    def __init__(self) -> None:
        self._store: dict[int, ProviderConfig] = {}
        self._next_id = 1

    def list_all(self) -> list[ProviderConfig]:
        return list(self._store.values())

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        return self._store.get(provider_id)

    def get_by_name(self, name: str) -> ProviderConfig | None:
        for c in self._store.values():
            if c.name == name:
                return c
        return None

    def get_active_by_type(self, source_type: str) -> list[ProviderConfig]:
        return [c for c in self._store.values() if c.source_type == source_type and c.is_active]

    def save(self, config: ProviderConfig) -> ProviderConfig:
        pk = config.id if config.id is not None else self._next_id
        if config.id is None:
            self._next_id += 1

        # Build new frozen instance with assigned pk
        import dataclasses

        saved = dataclasses.replace(config, id=pk)
        self._store[pk] = saved
        return saved

    def delete(self, provider_id: int) -> None:
        self._store.pop(provider_id, None)


# ---------------------------------------------------------------------------
# Stub tester
# ---------------------------------------------------------------------------


class _OkTester:
    def test(self, config: ProviderConfig) -> ConnectionTestResult:
        return ConnectionTestResult(
            success=True,
            status="success",
            summary=f"OK for {config.name}",
            logs=["[INFO] probe passed"],
        )


class _FailTester:
    def test(self, config: ProviderConfig) -> ConnectionTestResult:
        return ConnectionTestResult(
            success=False,
            status="error",
            summary="probe failed",
            logs=["[ERROR] timeout"],
        )


class _MacroFactRepo:
    def __init__(self, facts: list[MacroFact] | None = None) -> None:
        self._facts = facts or []

    def get_series(
        self,
        indicator_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[MacroFact]:
        facts = [f for f in self._facts if f.indicator_code == indicator_code]
        if start is not None:
            facts = [f for f in facts if f.reporting_period >= start]
        if end is not None:
            facts = [f for f in facts if f.reporting_period <= end]
        return facts[:limit]

    def get_latest(self, indicator_code: str) -> MacroFact | None:
        facts = self.get_series(indicator_code=indicator_code, limit=1)
        return facts[0] if facts else None

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        self._facts.extend(facts)
        self._facts.sort(key=lambda item: item.reporting_period, reverse=True)
        return len(facts)


class _IndicatorCatalogRepo:
    def __init__(self, catalog: IndicatorCatalog | None = None) -> None:
        self._catalog = catalog

    def get_by_code(self, code: str) -> IndicatorCatalog | None:
        if self._catalog and self._catalog.code == code:
            return self._catalog
        return None


class _QuoteSnapshotRepo:
    def __init__(self, quote: QuoteSnapshot | None = None) -> None:
        self._quotes = [quote] if quote else []

    def get_latest(self, asset_code: str) -> QuoteSnapshot | None:
        matches = [quote for quote in self._quotes if quote.asset_code == asset_code]
        matches.sort(key=lambda item: item.snapshot_at, reverse=True)
        return matches[0] if matches else None

    def bulk_upsert(self, quotes: list[QuoteSnapshot]) -> int:
        self._quotes.extend(quotes)
        return len(quotes)


class _PriceBarRepo:
    def __init__(self) -> None:
        self._bars: list[PriceBar] = []

    def get_bars(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[PriceBar]:
        bars = [bar for bar in self._bars if bar.asset_code == asset_code]
        if start is not None:
            bars = [bar for bar in bars if bar.bar_date >= start]
        if end is not None:
            bars = [bar for bar in bars if bar.bar_date <= end]
        bars.sort(key=lambda item: item.bar_date, reverse=True)
        return bars[:limit]

    def get_latest(self, asset_code: str) -> PriceBar | None:
        bars = self.get_bars(asset_code=asset_code, limit=1)
        return bars[0] if bars else None

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        self._bars.extend(bars)
        return len(bars)


class _RawAuditRepo:
    def __init__(self) -> None:
        self.items: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        self.items.append(audit)
        return audit


class _ProviderFactory:
    def __init__(self, provider) -> None:
        self._provider = provider

    def get_by_id(self, provider_id: int):
        return self._provider


class _DecisionRepairProvider:
    def __init__(self, target_date: date) -> None:
        self.target_date = target_date

    def provider_name(self) -> str:
        return "AKShare Public"

    def fetch_macro_series(self, indicator_code: str, start_date: date, end_date: date):
        return [
            MacroFact(
                indicator_code=indicator_code,
                reporting_period=self.target_date,
                value=50.8,
                unit="指数",
                source="akshare",
                published_at=self.target_date,
            )
        ]

    def fetch_quote_snapshots(self, asset_codes: list[str]):
        return [
            QuoteSnapshot(
                asset_code=asset_code,
                snapshot_at=datetime.now(timezone.utc),
                current_price=3.95,
                source="akshare",
            )
            for asset_code in asset_codes
        ]

    def fetch_price_history(self, asset_code: str, start_date: date, end_date: date):
        return [
            PriceBar(
                asset_code=asset_code,
                bar_date=self.target_date,
                open=3.9,
                high=4.0,
                low=3.8,
                close=3.95,
                source="akshare",
            )
        ]


class _LegacyMacroFact:
    def __init__(
        self,
        code: str,
        reporting_period: date,
        value: float,
        unit: str,
        source: str,
        published_at: date | None,
    ) -> None:
        self.code = code
        self.reporting_period = reporting_period
        self.value = value
        self.unit = unit
        self.source = source
        self.published_at = published_at


class _LegacyMacroSeriesRepo:
    def __init__(self, facts: list[_LegacyMacroFact] | None = None) -> None:
        self._facts = facts or []

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        source: str | None = None,
    ) -> list[_LegacyMacroFact]:
        facts = [f for f in self._facts if f.code == code]
        if start_date is not None:
            facts = [f for f in facts if f.reporting_period >= start_date]
        if end_date is not None:
            facts = [f for f in facts if f.reporting_period <= end_date]
        if source is not None:
            facts = [f for f in facts if f.source == source]
        return facts


# ---------------------------------------------------------------------------
# ManageProviderConfigUseCase tests
# ---------------------------------------------------------------------------


class TestManageProviderConfigUseCase:
    def _make_uc(self) -> tuple[ManageProviderConfigUseCase, _InMemoryRepo]:
        repo = _InMemoryRepo()
        return ManageProviderConfigUseCase(repo), repo

    def test_create_and_list(self):
        uc, _ = self._make_uc()
        req = CreateProviderRequest(name="ts", source_type="tushare", api_key="tok")
        resp = uc.create(req)
        assert resp.name == "ts"
        assert resp.id is not None

        all_providers = uc.list_all()
        assert len(all_providers) == 1
        assert all_providers[0].name == "ts"

    def test_get_existing(self):
        uc, _ = self._make_uc()
        created = uc.create(CreateProviderRequest(name="ak", source_type="akshare"))
        found = uc.get(created.id)
        assert found is not None
        assert found.source_type == "akshare"

    def test_get_missing_returns_none(self):
        uc, _ = self._make_uc()
        assert uc.get(999) is None

    def test_partial_update(self):
        uc, _ = self._make_uc()
        created = uc.create(CreateProviderRequest(name="ts", source_type="tushare", priority=50))
        updated = uc.update(UpdateProviderRequest(provider_id=created.id, priority=10))
        assert updated is not None
        assert updated.priority == 10
        assert updated.name == "ts"  # untouched

    def test_update_missing_returns_none(self):
        uc, _ = self._make_uc()
        result = uc.update(UpdateProviderRequest(provider_id=999, priority=5))
        assert result is None

    def test_delete(self):
        uc, _ = self._make_uc()
        created = uc.create(CreateProviderRequest(name="del_me", source_type="qmt"))
        deleted = uc.delete(created.id)
        assert deleted is True
        assert uc.get(created.id) is None

    def test_delete_missing_returns_false(self):
        uc, _ = self._make_uc()
        assert uc.delete(999) is False

    def test_create_preserves_extra_config(self):
        uc, _ = self._make_uc()
        extra = {"client_path": "/opt/qmt", "data_dir": "/data"}
        resp = uc.create(
            CreateProviderRequest(name="qmt_local", source_type="qmt", extra_config=extra)
        )
        assert resp.extra_config == extra


# ---------------------------------------------------------------------------
# TestProviderConnectionUseCase tests
# ---------------------------------------------------------------------------


class TestRunProviderConnectionTestUseCase:
    def _create_provider(self, repo: _InMemoryRepo, name="ts") -> ProviderConfig:
        cfg = ProviderConfig(
            id=None,
            name=name,
            source_type="tushare",
            is_active=True,
            priority=10,
            api_key="tok",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )
        return repo.save(cfg)

    def test_test_success(self):
        repo = _InMemoryRepo()
        cfg = self._create_provider(repo)
        uc = RunProviderConnectionTestUseCase(repo, _OkTester())
        result = uc.execute(cfg.id)
        assert result is not None
        assert result.success is True
        saved = repo.get_by_id(cfg.id)
        assert saved is not None
        assert saved.extra_config["provider_last_status"] == "healthy"
        assert saved.extra_config["provider_last_success_at"]

    def test_test_failure(self):
        repo = _InMemoryRepo()
        cfg = self._create_provider(repo)
        uc = RunProviderConnectionTestUseCase(repo, _FailTester())
        result = uc.execute(cfg.id)
        assert result is not None
        assert result.success is False
        saved = repo.get_by_id(cfg.id)
        assert saved is not None
        assert saved.extra_config["provider_last_status"] == "degraded"
        assert saved.extra_config["provider_last_error"] == "probe failed"

    def test_missing_provider_returns_none(self):
        repo = _InMemoryRepo()
        uc = RunProviderConnectionTestUseCase(repo, _OkTester())
        assert uc.execute(999) is None


class TestQueryMacroSeriesUseCase:
    def test_prefers_data_center_facts_when_available(self):
        fact = MacroFact(
            indicator_code="CN_PMI",
            reporting_period=date(2025, 3, 1),
            value=50.9,
            unit="指数",
            source="akshare",
            revision_number=1,
            published_at=date(2025, 3, 2),
            quality=DataQualityStatus.VALID,
        )
        catalog = IndicatorCatalog(
            code="CN_PMI",
            name_cn="制造业PMI",
            default_unit="指数",
            default_period_type="M",
        )

        uc = QueryMacroSeriesUseCase(
            _MacroFactRepo([fact]),
            _IndicatorCatalogRepo(catalog),
            _LegacyMacroSeriesRepo(
                [
                    _LegacyMacroFact(
                        code="CN_PMI",
                        reporting_period=date(2025, 2, 1),
                        value=50.1,
                        unit="指数",
                        source="legacy",
                        published_at=date(2025, 2, 2),
                    )
                ]
            ),
        )

        result = uc.execute(MacroSeriesRequest(indicator_code="CN_PMI"))

        assert result.total == 1
        assert result.name_cn == "制造业PMI"
        assert result.data[0].value == 50.9
        assert result.data[0].quality == "valid"

    def test_blocks_legacy_repo_by_default_when_data_center_is_empty(self):
        uc = QueryMacroSeriesUseCase(
            _MacroFactRepo(),
            _IndicatorCatalogRepo(),
            _LegacyMacroSeriesRepo(
                [
                    _LegacyMacroFact(
                        code="CN_PMI",
                        reporting_period=date(2025, 3, 1),
                        value=50.9,
                        unit="指数",
                        source="akshare",
                        published_at=date(2025, 3, 2),
                    )
                ]
            ),
        )

        result = uc.execute(MacroSeriesRequest(indicator_code="CN_PMI"))

        assert result.total == 0
        assert result.name_cn == "CN_PMI"
        assert result.legacy_fallback_available is True
        assert result.legacy_fallback_used is False
        assert result.must_not_use_for_decision is True
        assert result.freshness_status == "legacy_blocked"

    def test_can_explicitly_enable_legacy_fallback_for_macro_series(self):
        uc = QueryMacroSeriesUseCase(
            _MacroFactRepo(),
            _IndicatorCatalogRepo(),
            _LegacyMacroSeriesRepo(
                [
                    _LegacyMacroFact(
                        code="CN_PMI",
                        reporting_period=date(2025, 3, 1),
                        value=50.9,
                        unit="指数",
                        source="akshare",
                        published_at=date(2025, 3, 2),
                    )
                ]
            ),
        )

        result = uc.execute(
            MacroSeriesRequest(
                indicator_code="CN_PMI",
                allow_legacy_fallback=True,
            )
        )

        assert result.total == 1
        assert result.data[0].value == 50.9
        assert result.data[0].quality == "legacy"
        assert result.legacy_fallback_used is True
        assert result.must_not_use_for_decision is True
        assert result.decision_grade == "degraded"


class TestQueryLatestQuoteUseCase:
    def test_marks_fresh_quote_as_decision_eligible(self):
        fresh_snapshot = QuoteSnapshot(
            asset_code="510300.SH",
            snapshot_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            current_price=3.91,
            source="test",
            volume=12345.0,
        )
        uc = QueryLatestQuoteUseCase(_QuoteSnapshotRepo(fresh_snapshot))

        result = uc.execute(LatestQuoteRequest(asset_code="510300.SH", max_age_hours=1.0))

        assert result is not None
        assert result.is_stale is False
        assert result.freshness_status == "fresh"
        assert result.must_not_use_for_decision is False
        assert result.blocked_reason == ""
        assert result.age_minutes >= 15

    def test_marks_stale_quote_as_non_decision_grade(self):
        stale_snapshot = QuoteSnapshot(
            asset_code="510300.SH",
            snapshot_at=datetime.now(timezone.utc) - timedelta(hours=6),
            current_price=3.88,
            source="test",
            volume=12345.0,
        )
        uc = QueryLatestQuoteUseCase(_QuoteSnapshotRepo(stale_snapshot))

        result = uc.execute(LatestQuoteRequest(asset_code="510300.SH", max_age_hours=1.0))

        assert result is not None
        assert result.is_stale is True
        assert result.freshness_status == "stale"
        assert result.must_not_use_for_decision is True
        assert "freshness 阈值" in result.blocked_reason
        assert result.max_age_hours == 1.0


class TestRepairDecisionDataReliabilityUseCase:
    def _make_use_case(
        self,
        *,
        provider_repo: _InMemoryRepo | None = None,
        target_date: date = date(2026, 4, 21),
    ) -> RepairDecisionDataReliabilityUseCase:
        repo = provider_repo or _InMemoryRepo()
        provider = _DecisionRepairProvider(target_date)
        return RepairDecisionDataReliabilityUseCase(
            provider_repo=repo,
            provider_factory=_ProviderFactory(provider),
            macro_fact_repo=_MacroFactRepo(),
            indicator_catalog_repo=_IndicatorCatalogRepo(
                IndicatorCatalog(
                    code="CN_PMI",
                    name_cn="制造业PMI",
                    default_unit="指数",
                    default_period_type="D",
                )
            ),
            price_bar_repo=_PriceBarRepo(),
            quote_snapshot_repo=_QuoteSnapshotRepo(),
            raw_audit_repo=_RawAuditRepo(),
            legacy_macro_repo=_LegacyMacroSeriesRepo(),
        )

    def test_bootstraps_akshare_and_repairs_fresh_macro_quote_price(self):
        target_date = date(2026, 4, 21)
        use_case = self._make_use_case(target_date=target_date)

        report = use_case.execute(
            DecisionReliabilityRepairRequest(
                target_date=target_date,
                asset_codes=["510300.SH"],
                macro_indicator_codes=["CN_PMI"],
                repair_pulse=False,
                repair_alpha=False,
            )
        )

        payload = report.to_dict()
        assert payload["provider_bootstrap"]["status"] == "created"
        assert payload["macro_status"]["status"] == "ready"
        assert (
            payload["macro_status"]["details"]["indicators"]["CN_PMI"]["provider_name"]
            == "AKShare Public"
        )
        assert payload["quote_status"]["status"] == "ready"
        assert payload["must_not_use_for_decision"] is False

    def test_existing_inactive_akshare_is_not_overwritten(self):
        repo = _InMemoryRepo()
        repo.save(
            ProviderConfig(
                id=None,
                name="AKShare Disabled",
                source_type="akshare",
                is_active=False,
                priority=10,
                api_key="",
                api_secret="",
                http_url="",
                api_endpoint="",
                extra_config={"user_owned": True},
                description="",
            )
        )
        use_case = self._make_use_case(provider_repo=repo)

        report = use_case.execute(
            DecisionReliabilityRepairRequest(
                target_date=date(2026, 4, 21),
                asset_codes=["510300.SH"],
                macro_indicator_codes=["CN_PMI"],
                repair_pulse=False,
                repair_alpha=False,
            )
        )

        assert report.provider_bootstrap["status"] == "inactive_exists"
        assert len([p for p in repo.list_all() if p.source_type == "akshare"]) == 1
