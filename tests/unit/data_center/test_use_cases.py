"""
Unit tests for data_center application use cases.

Uses in-memory stub implementations — no DB or Django required.
"""

from __future__ import annotations

import pytest

from apps.data_center.application.dtos import CreateProviderRequest, UpdateProviderRequest
from apps.data_center.application.use_cases import (
    ManageProviderConfigUseCase,
    RunProviderConnectionTestUseCase,
)
from apps.data_center.domain.entities import (
    ConnectionTestResult,
    ProviderConfig,
)


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
