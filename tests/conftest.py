"""
Pytest configuration and shared fixtures.
"""

from datetime import date
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from tests.support.pyqlib_guardrail import resolve_pyqlib_status


@pytest.fixture
def sample_date():
    """Sample date for testing"""
    return date(2024, 1, 1)


@pytest.fixture
def sample_macro_data():
    """Sample macro indicator data"""
    from apps.macro.domain.entities import MacroIndicator

    return [
        MacroIndicator(
            code="CN_PMI_MANUFACTURING",
            value=50.1,
            observed_at=date(2024, 1, 1),
            source="test"
        ),
        MacroIndicator(
            code="CN_CPI_YOY",
            value=2.1,
            observed_at=date(2024, 1, 1),
            source="test"
        ),
    ]


@pytest.fixture
def test_user(db):
    """Create a test user"""
    User = get_user_model()
    return User.objects.create_user(
        username='testuser',
        password='testpass123',
        email='test@example.com'
    )


@pytest.fixture
def authenticated_client(db, test_user):
    """Create an authenticated test client"""
    from django.test import Client

    client = Client()
    client.force_login(test_user)
    return client


@pytest.fixture
def alpha_cache_data(db):
    """Create sample Alpha cache data for testing"""
    from apps.alpha.infrastructure.models import AlphaScoreCacheModel

    today = date.today()
    cache = AlphaScoreCacheModel.objects.create(
        universe_id="csi300",
        intended_trade_date=today,
        provider_source="cache",
        asof_date=today,
        model_id="test_model",
        model_artifact_hash="test_hash_001",
        feature_set_id="v1",
        label_id="return_5d",
        data_version="2026.02.05",
        scores=[
            {
                "code": "600519.SH",
                "score": 0.95,
                "rank": 1,
                "factors": {"momentum": 0.9},
                "confidence": 0.95
            },
            {
                "code": "000333.SH",
                "score": 0.87,
                "rank": 2,
                "factors": {"value": 0.92},
                "confidence": 0.90
            },
        ],
        status="available"
    )
    return cache


@pytest.fixture
def qlib_model(db):
    """Create a sample Qlib model for testing"""
    from apps.alpha.infrastructure.models import QlibModelRegistryModel

    model = QlibModelRegistryModel.objects.create(
        model_name="test_model",
        artifact_hash="test_hash_001",
        model_type="LGBModel",
        universe="csi300",
        train_config={"learning_rate": 0.01},
        feature_set_id="v1",
        label_id="return_5d",
        data_version="2026.02.05",
        model_path="/models/test.pkl",
        ic=0.06,
        icir=0.85,
        is_active=True
    )
    return model




# Skip tests that require Qlib if it's not installed
def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, isolated)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (database required)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests (full system flow)"
    )
    config.addinivalue_line(
        "markers", "slow: Slow running tests"
    )
    config.addinivalue_line(
        "markers", "qlib: Tests that require Qlib to be installed"
    )


def pytest_collection_modifyitems(config, items):
    """Only enforce the pyqlib gate when qlib-marked tests are actually collected."""
    qlib_items = [item for item in items if "qlib" in item.keywords]
    if not qlib_items:
        return

    status = resolve_pyqlib_status(Path(__file__).resolve().parents[1])

    if status.misconfigured:
        raise pytest.UsageError(status.reason)

    if not status.available:
        skip_qlib = pytest.mark.skip(reason=status.reason)
        for item in qlib_items:
            item.add_marker(skip_qlib)


# ---------------------------------------------------------------------------
# Test-isolation guards for the Data Center provider runtime.
#
# 1) Akshare seam pinning: several suites monkeypatch
#    ``apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module``.
#    The gateway modules below bind that name at import time and are imported
#    lazily inside application code. If such a module is imported for the
#    first time while a monkeypatch is active, it captures the fake callable
#    permanently (the module stays in ``sys.modules``) and every later test
#    that needs the real binding fails in an order-dependent way. Importing
#    the modules once, before any test runs, pins the real binding.
#
# 2) Provider-registry reset: ``apps.data_center.provider_runtime`` holds a
#    process-wide ``_global_registry`` singleton built lazily from database
#    configuration. A registry built on one test's database would otherwise
#    leak into later tests running on a different test database, so it is
#    reset around every test.
# ---------------------------------------------------------------------------

_PATCHABLE_AKSHARE_SEAM_MODULES = (
    "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway",
    "apps.data_center.infrastructure.gateways.akshare_general_gateway",
)


@pytest.fixture(autouse=True, scope="session")
def _pin_akshare_seam_modules_before_patching() -> None:
    """Eagerly import modules that bind the patchable akshare seam."""
    import importlib

    for module_name in _PATCHABLE_AKSHARE_SEAM_MODULES:
        importlib.import_module(module_name)


@pytest.fixture(autouse=True)
def _reset_data_center_provider_registry():
    """Isolate the process-wide provider registry between tests."""
    from apps.data_center.provider_runtime import reset_registry

    reset_registry()
    yield
    reset_registry()
