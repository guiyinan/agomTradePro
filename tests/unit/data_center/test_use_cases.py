"""
Unit tests for data_center application use cases.

Uses in-memory stub implementations — no DB or Django required.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_center.application.dtos import (
    CreateProviderRequest,
    MacroSeriesRequest,
    UpdateProviderRequest,
)
from apps.data_center.application.use_cases import (
    ManageProviderConfigUseCase,
    QueryMacroSeriesUseCase,
    RunProviderConnectionTestUseCase,
)
from apps.data_center.domain.entities import (
    ConnectionTestResult,
    IndicatorCatalog,
    MacroFact,
    ProviderConfig,
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


class _IndicatorCatalogRepo:
    def __init__(self, catalog: IndicatorCatalog | None = None) -> None:
        self._catalog = catalog

    def get_by_code(self, code: str) -> IndicatorCatalog | None:
        if self._catalog and self._catalog.code == code:
            return self._catalog
        return None


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
        created = uc.create(
            CreateProviderRequest(name="ts", source_type="tushare", priority=50)
        )
        updated = uc.update(
            UpdateProviderRequest(provider_id=created.id, priority=10)
        )
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
        import dataclasses
        cfg = ProviderConfig(
            id=None, name=name, source_type="tushare", is_active=True, priority=10,
            api_key="tok", api_secret="", http_url="", api_endpoint="",
            extra_config={}, description="",
        )
        return repo.save(cfg)

    def test_test_success(self):
        repo = _InMemoryRepo()
        cfg = self._create_provider(repo)
        uc = RunProviderConnectionTestUseCase(repo, _OkTester())
        result = uc.execute(cfg.id)
        assert result is not None
        assert result.success is True

    def test_test_failure(self):
        repo = _InMemoryRepo()
        cfg = self._create_provider(repo)
        uc = RunProviderConnectionTestUseCase(repo, _FailTester())
        result = uc.execute(cfg.id)
        assert result is not None
        assert result.success is False

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

    def test_falls_back_to_legacy_repo_when_data_center_is_empty(self):
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

        assert result.total == 1
        assert result.name_cn == "CN_PMI"
        assert result.data[0].value == 50.9
        assert result.data[0].quality == "legacy"
