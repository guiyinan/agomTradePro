"""
Unit tests for data_center domain entities.

Domain layer only — no Django ORM, no external libraries.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from apps.data_center.domain.entities import (
    ConnectionTestResult,
    DataProviderSettings,
    ProviderConfig,
    ProviderHealthSnapshot,
)
from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus


class TestProviderConfig:
    def _make(self, **overrides) -> ProviderConfig:
        defaults = {
            "id": 1,
            "name": "tushare_main",
            "source_type": "tushare",
            "is_active": True,
            "priority": 10,
            "api_key": "tok123",
            "api_secret": "",
            "http_url": "",
            "api_endpoint": "",
            "extra_config": {},
            "description": "",
        }
        defaults.update(overrides)
        return ProviderConfig(**defaults)

    def test_valid_creation(self):
        cfg = self._make()
        assert cfg.name == "tushare_main"
        assert cfg.source_type == "tushare"
        assert cfg.priority == 10

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._make(name="")

    def test_empty_source_type_raises(self):
        with pytest.raises(ValueError, match="source_type"):
            self._make(source_type="")

    def test_frozen(self):
        cfg = self._make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.priority = 99  # type: ignore[misc]

    def test_extra_config_default_is_dict(self):
        cfg = self._make(extra_config={"client_path": "/some/path"})
        assert cfg.extra_config["client_path"] == "/some/path"


class TestDataProviderSettings:
    def test_valid(self):
        s = DataProviderSettings(
            default_source="akshare",
            enable_failover=True,
            failover_tolerance=0.01,
        )
        assert s.failover_tolerance == 0.01

    def test_tolerance_out_of_range(self):
        with pytest.raises(ValueError, match="failover_tolerance"):
            DataProviderSettings(
                default_source="akshare",
                enable_failover=True,
                failover_tolerance=1.5,
            )

    def test_zero_tolerance_allowed(self):
        s = DataProviderSettings("tushare", False, 0.0)
        assert s.failover_tolerance == 0.0

    def test_one_tolerance_allowed(self):
        s = DataProviderSettings("tushare", False, 1.0)
        assert s.failover_tolerance == 1.0


class TestConnectionTestResult:
    def test_to_dict_success(self):
        r = ConnectionTestResult(
            success=True,
            status="success",
            summary="OK",
            logs=["[INFO] connected"],
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["status"] == "success"
        assert "[INFO] connected" in d["logs"]
        assert "tested_at" in d

    def test_to_dict_failure(self):
        r = ConnectionTestResult(
            success=False,
            status="error",
            summary="Token missing",
            logs=["[ERROR] no token"],
        )
        d = r.to_dict()
        assert d["success"] is False


class TestProviderHealthSnapshot:
    def test_to_dict(self):
        snap = ProviderHealthSnapshot(
            provider_name="tushare_main",
            capability=DataCapability.MACRO,
            status=ProviderHealthStatus.HEALTHY,
            consecutive_failures=0,
            last_success_at=datetime(2026, 4, 1, tzinfo=UTC),
            avg_latency_ms=42.5,
        )
        d = snap.to_dict()
        assert d["provider_name"] == "tushare_main"
        assert d["capability"] == "macro"
        assert d["status"] == "healthy"
        assert d["avg_latency_ms"] == 42.5

    def test_to_dict_null_fields(self):
        snap = ProviderHealthSnapshot(
            provider_name="akshare_backup",
            capability=DataCapability.HISTORICAL_PRICE,
            status=ProviderHealthStatus.UNKNOWN,
        )
        d = snap.to_dict()
        assert d["last_success_at"] is None
        assert d["avg_latency_ms"] is None
