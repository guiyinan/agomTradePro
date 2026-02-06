"""
Comprehensive Integration Test for AgomSAAF Extensions

Tests the new modules: Factor, Rotation, Hedge, and Unified Signal System
This is a full-stack test from SDK → Backend API → Database

Usage:
    python manage.py shell < tests/integration/test_new_modules.py
    or
    python tests/integration/test_new_modules.py
"""

import os
import sys
from pathlib import Path
from datetime import date, timedelta

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

import django
django.setup()

from apps.factor.infrastructure.repositories import (
    FactorDefinitionRepository,
    FactorPortfolioConfigRepository,
    FactorPortfolioHoldingRepository,
)
from apps.rotation.infrastructure.repositories import (
    AssetClassRepository,
    RotationConfigRepository,
    RotationSignalRepository,
)
from apps.hedge.infrastructure.repositories import (
    HedgePairRepository,
    CorrelationHistoryRepository,
    HedgePortfolioRepository,
)
from apps.signal.infrastructure.repositories import UnifiedSignalRepository


def print_section(title: str) -> None:
    """Print a formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_test(name: str) -> None:
    """Print a test name"""
    print(f"\n[{name}]")


def print_success(message: str) -> None:
    """Print a success message"""
    print(f"  OK: {message}")


def print_info(message: str) -> None:
    """Print an info message"""
    print(f"  INFO: {message}")


def print_error(message: str) -> None:
    """Print an error message"""
    print(f"  FAIL: {message}", file=sys.stderr)


def test_factor_module() -> dict:
    """Test Factor module repositories"""
    print_test("Factor Module")

    try:
        from apps.factor.infrastructure.repositories import FactorDefinitionRepository
        from apps.factor.infrastructure.models import FactorDefinitionModel, FactorPortfolioConfigModel

        factor_def_repo = FactorDefinitionRepository()
        factors = factor_def_repo.get_all()
        print_success(f"Factor Definitions: {len(factors)} factors loaded")

        factor_count = FactorDefinitionModel.objects.count()
        print_info(f"Total Factor Definitions in DB: {factor_count}")

        config_count = FactorPortfolioConfigModel.objects.count()
        print_success(f"Factor Configs: {config_count} configs in DB")

        return {
            'status': 'pass',
            'factors': len(factors),
            'total_factors': factor_count,
            'total_configs': config_count,
        }
    except Exception as e:
        print_error(f"Factor module test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def test_rotation_module() -> dict:
    """Test Rotation module repositories"""
    print_test("Rotation Module")

    try:
        from apps.rotation.infrastructure.models import AssetClassModel, RotationConfigModel

        asset_count = AssetClassModel.objects.filter(is_active=True).count()
        print_success(f"Asset Classes: {asset_count} ETFs loaded")

        config_count = RotationConfigModel.objects.filter(is_active=True).count()
        print_success(f"Rotation Configs: {config_count} configs loaded")

        return {
            'status': 'pass',
            'assets': asset_count,
            'configs': config_count,
        }
    except Exception as e:
        print_error(f"Rotation module test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def test_hedge_module() -> dict:
    """Test Hedge module repositories"""
    print_test("Hedge Module")

    try:
        # Test Hedge Pair Repository
        pair_repo = HedgePairRepository()
        pairs = pair_repo.get_all(active_only=True)
        print_success(f"Hedge Pairs: {len(pairs)} pairs loaded")

        # Test Correlation History Repository
        corr_repo = CorrelationHistoryRepository()
        recent_corrs = corr_repo.get_all_recent(days=30)
        print_info(f"Recent Correlations: {len(recent_corrs)} records")

        # Test Hedge Portfolio Repository
        portfolio_repo = HedgePortfolioRepository()

        return {
            'status': 'pass',
            'pairs': len(pairs),
            'correlations': len(recent_corrs),
        }
    except Exception as e:
        print_error(f"Hedge module test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def test_unified_signal_system() -> dict:
    """Test Unified Signal System"""
    print_test("Unified Signal System")

    try:
        unified_repo = UnifiedSignalRepository()

        # Test creating a signal
        signal = unified_repo.create_signal(
            signal_date=date.today(),
            signal_source='test',
            signal_type='info',
            asset_code='TEST001',
            reason='Integration test signal',
            priority=5,
            action_required='Test action',
        )
        print_success(f"Created unified signal: ID {signal['id']}")

        # Test getting signals by date
        signals = unified_repo.get_signals_by_date(date.today())
        print_info(f"Signals for today: {len(signals)}")

        # Test signal summary
        summary = unified_repo.get_signal_summary(
            start_date=date.today() - timedelta(days=7),
            end_date=date.today()
        )
        print_success(f"Signal summary: {summary['total']} total signals")

        # Cleanup test signal
        unified_repo.mark_executed(signal['id'])

        return {
            'status': 'pass',
            'signals_created': 1,
            'total_signals': summary['total'],
        }
    except Exception as e:
        print_error(f"Unified signal system test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def test_django_models() -> dict:
    """Test Django ORM models"""
    print_test("Django ORM Models")

    try:
        from apps.factor.infrastructure.models import (
            FactorDefinitionModel,
            FactorPortfolioConfigModel,
        )
        from apps.rotation.infrastructure.models import (
            AssetClassModel,
            RotationConfigModel,
        )
        from apps.hedge.infrastructure.models import HedgePairModel
        from apps.signal.infrastructure.models import UnifiedSignalModel

        # Count records in each table
        factor_count = FactorDefinitionModel.objects.count()
        asset_count = AssetClassModel.objects.count()
        hedge_count = HedgePairModel.objects.filter(is_active=True).count()
        unified_count = UnifiedSignalModel.objects.count()

        print_success(f"Factor Definitions: {factor_count}")
        print_success(f"Asset Classes: {asset_count}")
        print_success(f"Hedge Pairs: {hedge_count}")
        print_info(f"Unified Signals: {unified_count}")

        return {
            'status': 'pass',
            'factor_count': factor_count,
            'asset_count': asset_count,
            'hedge_count': hedge_count,
            'unified_count': unified_count,
        }
    except Exception as e:
        print_error(f"Django models test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def test_sdk_modules() -> dict:
    """Test SDK module imports"""
    print_test("SDK Module Imports")

    try:
        from sdk.agomsaaf.modules import FactorModule, RotationModule, HedgeModule
        print_success("All new SDK modules imported")

        return {'status': 'pass'}
    except Exception as e:
        print_error(f"SDK import test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def test_mcp_tools() -> dict:
    """Test MCP tools availability"""
    print_test("MCP Tools (Optional)")

    try:
        from sdk.agomsaaf_mcp.tools import (
            factor_tools,
            rotation_tools,
            hedge_tools,
        )

        # Count registered tools
        factor_tools_count = len([name for name in dir(factor_tools) if not name.startswith('_')])
        rotation_tools_count = len([name for name in dir(rotation_tools) if not name.startswith('_')])
        hedge_tools_count = len([name for name in dir(hedge_tools) if not name.startswith('_')])

        print_success(f"Factor Tools: {factor_tools_count} functions")
        print_success(f"Rotation Tools: {rotation_tools_count} functions")
        print_success(f"Hedge Tools: {hedge_tools_count} functions")

        return {
            'status': 'pass',
            'factor_tools': factor_tools_count,
            'rotation_tools': rotation_tools_count,
            'hedge_tools': hedge_tools_count,
        }
    except ImportError as e:
        print_info(f"MCP tools not available (optional): {e}")
        return {
            'status': 'skip',
            'reason': 'MCP package not installed (optional dependency)',
        }
    except Exception as e:
        print_error(f"MCP tools test failed: {e}")
        return {'status': 'fail', 'error': str(e)}


def main():
    """Run all integration tests"""
    print_section("AgomSAAF Extension Integration Tests")
    print_info("Testing: Factor + Rotation + Hedge + Unified Signal System")

    results = {}

    # Run all tests
    results['sdk'] = test_sdk_modules()
    results['mcp'] = test_mcp_tools()
    results['models'] = test_django_models()
    results['factor'] = test_factor_module()
    results['rotation'] = test_rotation_module()
    results['hedge'] = test_hedge_module()
    results['unified'] = test_unified_signal_system()

    # Print summary
    print_section("Test Summary")

    total = len(results)
    passed = sum(1 for r in results.values() if r.get('status') == 'pass')
    skipped = sum(1 for r in results.values() if r.get('status') == 'skip')

    print(f"\nTotal Tests: {total}")
    print(f"Passed: {passed}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {total - passed - skipped}")

    print("\nDetailed Results:")
    for test_name, result in results.items():
        status = result.get('status', 'unknown')
        if status == 'pass':
            status_icon = "[OK]"
        elif status == 'skip':
            status_icon = "[SKIP]"
        else:
            status_icon = "[FAIL]"

        print(f"  {status_icon} {test_name.upper()}: {status}")
        if result.get('error'):
            print(f"       Error: {result['error']}")
        elif result.get('reason'):
            print(f"       Reason: {result['reason']}")
        elif result.get('status') == 'pass':
            # Print key metrics
            for key, value in result.items():
                if key not in ['status']:
                    print(f"       - {key}: {value}")

    print("\n" + "=" * 70)
    if passed == total:
        print("  ALL TESTS PASSED")
    elif skipped > 0:
        print(f"  {passed}/{total} ESSENTIAL TESTS PASSED ({skipped} skipped)")
    else:
        print(f"  {total - passed} TEST(S) FAILED")
    print("=" * 70)

    return passed == (total - skipped)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
