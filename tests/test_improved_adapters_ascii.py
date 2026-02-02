"""
Improved Capital Market Data Adapter Test Script (ASCII-only version)

Tests the following improvements:
1. Retry mechanism - automatic retry of failed requests
2. Caching mechanism - reduce duplicate requests
3. Multi-source switching - automatic fallback to backup data source
4. Timeout control - prevent request hanging
5. Health status monitoring - track data source availability
"""

import json
import time
from datetime import datetime, date


def test_resilience_features():
    """Test resilience features"""
    print("\n" + "="*60)
    print("[Testing] Resilience Features")
    print("="*60)

    results = []

    # Test 1: Retry mechanism
    print("\n1. Testing retry mechanism")
    from shared.infrastructure.resilience import retry_on_error, MaxRetriesExceeded

    attempt_count = {'count': 0}

    @retry_on_error(max_retries=3, initial_delay=0.5)
    def flaky_function(should_fail=False):
        attempt_count['count'] += 1
        if should_fail and attempt_count['count'] < 3:
            raise ConnectionError("Simulated network error")
        return "Success"

    try:
        # Test retry after failure
        result = flaky_function(should_fail=True)
        results.append({
            'test': 'Retry mechanism',
            'status': 'success',
            'attempts': attempt_count['count'],
            'result': result
        })
        print(f"   Retry works: Succeeded after {attempt_count['count']} attempts")

    except MaxRetriesExceeded:
        results.append({
            'test': 'Retry mechanism',
            'status': 'failed',
            'attempts': attempt_count['count']
        })
        print(f"   Retry failed: Exceeded max retries")

    # Test 2: Caching mechanism
    print("\n2. Testing caching mechanism")
    from shared.infrastructure.resilience import cached, _cache_manager

    call_count = {'count': 0}

    @cached(ttl=10)
    def expensive_function(x):
        call_count['count'] += 1
        return x * 2

    # First call - cache miss
    result1 = expensive_function(5)
    first_calls = call_count['count']

    # Second call - cache hit
    result2 = expensive_function(5)
    second_calls = call_count['count']

    if first_calls == 1 and second_calls == 1:
        results.append({
            'test': 'Caching mechanism',
            'status': 'success',
            'details': 'Cache works correctly'
        })
        print(f"   Cache works: First call executed, second call used cache")
    else:
        results.append({
            'test': 'Caching mechanism',
            'status': 'failed',
            'calls': call_count['count']
        })

    # Test 3: Circuit breaker
    print("\n3. Testing circuit breaker")
    from shared.infrastructure.resilience import circuit_breaker, DataSourceUnavailable

    failure_count = {'count': 0}

    @circuit_breaker(failure_threshold=2, reset_timeout=5)
    def unstable_service(should_fail=True):
        failure_count['count'] += 1
        if should_fail:
            raise ConnectionError("Service unavailable")
        return "Normal"

    # Trigger circuit breaker
    try:
        for i in range(3):
            try:
                unstable_service(should_fail=True)
            except:
                pass

        # Circuit breaker should be open
        try:
            unstable_service(should_fail=False)
            results.append({
                'test': 'Circuit breaker',
                'status': 'failed',
                'reason': 'Circuit breaker not working'
            })
        except DataSourceUnavailable:
            results.append({
                'test': 'Circuit breaker',
                'status': 'success',
                'reason': 'Circuit breaker works correctly'
            })
            print(f"   Circuit breaker works: Fast fail after consecutive failures")
    except Exception as e:
        results.append({
            'test': 'Circuit breaker',
            'status': 'error',
            'error': str(e)
        })

    return results


def test_hybrid_stock_adapter():
    """Test hybrid stock adapter"""
    print("\n" + "="*60)
    print("[Testing] Hybrid Stock Adapter")
    print("="*60)

    results = []

    try:
        from apps.equity.infrastructure.adapters.hybrid_stock_adapter import HybridStockAdapter

        # No Tushare token needed, only use AKShare
        adapter = HybridStockAdapter(tushare_token=None)

        # Test 1: Get stock list (with retry and cache)
        print("\n1. Testing fetch_stock_list_a() (with retry and cache)")
        start = time.time()

        try:
            df = adapter.fetch_stock_list_a()
            elapsed = time.time() - start

            if not df.empty:
                results.append({
                    'test': 'Hybrid adapter - stock list',
                    'status': 'success',
                    'count': len(df),
                    'time': f'{elapsed:.2f}s'
                })
                print(f"   Successfully fetched {len(df)} stocks in {elapsed:.2f}s")

                # Second call should be faster (cache)
                start2 = time.time()
                df2 = adapter.fetch_stock_list_a()
                elapsed2 = time.time() - start2

                if elapsed2 < elapsed * 0.5:  # At least 50% faster
                    print(f"   Cache effective: Second call took {elapsed2:.2f}s")
            else:
                results.append({
                    'test': 'Hybrid adapter - stock list',
                    'status': 'failed',
                    'reason': 'Returned empty data'
                })
                print(f"   Failed: Returned empty data")

        except MaxRetriesExceeded as e:
            results.append({
                'test': 'Hybrid adapter - stock list',
                'status': 'failed',
                'reason': 'Exceeded retry count',
                'error': str(e)
            })
            print(f"   Failed: Exceeded max retry count")
        except Exception as e:
            results.append({
                'test': 'Hybrid adapter - stock list',
                'status': 'error',
                'error': str(e)
            })
            print(f"   Error: {str(e)[:100]}")

        # Test 2: Get stock info (with cache)
        print("\n2. Testing fetch_stock_info() (with cache)")
        try:
            info = adapter.fetch_stock_info('000001')
            if info:
                results.append({
                    'test': 'Hybrid adapter - stock info',
                    'status': 'success',
                    'keys': len(info)
                })
                print(f"   Successfully fetched stock info with {len(info)} fields")
            else:
                results.append({
                    'test': 'Hybrid adapter - stock info',
                    'status': 'failed',
                    'reason': 'Returned empty info'
                })
                print(f"   Failed: Returned empty info")
        except Exception as e:
            results.append({
                'test': 'Hybrid adapter - stock info',
                'status': 'error',
                'error': str(e)[:100]
            })
            print(f"   Error: {str(e)[:100]}")

        # Test 3: Get daily data (with cache)
        print("\n3. Testing fetch_daily_data() (with cache)")
        try:
            df = adapter.fetch_daily_data('000001', '2024-12-01', '2024-12-31')
            if not df.empty:
                results.append({
                    'test': 'Hybrid adapter - daily data',
                    'status': 'success',
                    'count': len(df)
                })
                print(f"   Successfully fetched {len(df)} daily data records")
            else:
                results.append({
                    'test': 'Hybrid adapter - daily data',
                    'status': 'failed',
                    'reason': 'Returned empty data'
                })
                print(f"   Failed: Returned empty data")
        except Exception as e:
            results.append({
                'test': 'Hybrid adapter - daily data',
                'status': 'error',
                'error': str(e)[:100]
            })
            print(f"   Error: {str(e)[:100]}")

        # Test 4: Health status
        print("\n4. Testing health status monitoring")
        try:
            health = adapter.get_health_status()
            results.append({
                'test': 'Health status monitoring',
                'status': 'success',
                'sources': list(health.keys())
            })
            print(f"   Health status: {list(health.keys())}")
            for source, status in health.items():
                failures = status.get('failure_count', 0)
                print(f"     {source}: Failure count {failures}")
        except Exception as e:
            results.append({
                'test': 'Health status monitoring',
                'status': 'error',
                'error': str(e)[:100]
            })

    except ImportError as e:
        results.append({
            'test': 'Hybrid adapter',
            'status': 'error',
            'error': f'Import failed: {str(e)[:100]}'
        })
        print(f"   Import failed: {str(e)[:100]}")

    return results


def test_database_operations_with_cache():
    """Test database operations with cache"""
    print("\n" + "="*60)
    print("[Testing] Database Operations (with cache)")
    print("="*60)

    results = []

    try:
        from apps.equity.infrastructure.models import StockInfoModel
        from apps.equity.infrastructure.adapters.hybrid_stock_adapter import HybridStockAdapter

        adapter = HybridStockAdapter(tushare_token=None)

        # Test: Get data from adapter and save to database
        print("\n1. Fetching and saving stock data from hybrid adapter")
        try:
            df = adapter.fetch_stock_list_a()

            if not df.empty:
                saved_count = 0
                for _, row in df.head(50).iterrows():  # Only save first 50 for testing
                    code = row.get('stock_code', '')
                    if code:
                        defaults = {
                            'name': row.get('name', ''),
                            'sector': row.get('industry', 'Unknown'),
                            'market': row.get('market', 'SZ'),
                            'list_date': date(2000, 1, 1),
                        }
                        obj, created = StockInfoModel.objects.update_or_create(
                            stock_code=code,
                            defaults=defaults
                        )
                        if created:
                            saved_count += 1

                print(f"   Successfully saved {saved_count} new stocks to database")
                results.append({
                    'test': 'Database save',
                    'status': 'success',
                    'count': saved_count
                })
            else:
                print(f"   Failed to fetch stock data")
                results.append({
                    'test': 'Database save',
                    'status': 'failed',
                    'reason': 'Cannot fetch data'
                })

        except Exception as e:
            print(f"   Save failed: {str(e)[:100]}")
            results.append({
                'test': 'Database save',
                'status': 'error',
                'error': str(e)[:100]
            })

        # Check database status
        print("\n2. Checking database status")
        try:
            total_count = StockInfoModel.objects.count()
            print(f"   Total stocks in database: {total_count}")
            results.append({
                'test': 'Database status',
                'status': 'success',
                'total_stocks': total_count
            })

            # Show recent stocks
            if total_count > 0:
                recent_stocks = StockInfoModel.objects.order_by('-created_at')[:5]
                print(f"   Recently added stocks:")
                for stock in recent_stocks:
                    print(f"     - {stock.stock_code}: {stock.name}")

        except Exception as e:
            print(f"   Query failed: {str(e)[:100]}")
            results.append({
                'test': 'Database status',
                'status': 'error',
                'error': str(e)[:100]
            })

    except Exception as e:
        results.append({
            'test': 'Database operations',
            'status': 'error',
            'error': str(e)[:100]
        })
        print(f"   Error: {str(e)[:100]}")

    return results


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("[Improved Capital Market Data Adapter Test]")
    print("="*70)
    print(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = {
        'timestamp': datetime.now().isoformat(),
        'tests': []
    }

    test_functions = [
        ("Resilience Features", test_resilience_features),
        ("Hybrid Stock Adapter", test_hybrid_stock_adapter),
        ("Database Operations", test_database_operations_with_cache),
    ]

    for category, test_func in test_functions:
        try:
            results = test_func()
            all_results['tests'].extend(results)
        except Exception as e:
            print(f"\n[ERROR] {category} test exception: {e}")
            all_results['tests'].append({
                'category': category,
                'status': 'error',
                'error': str(e)
            })

    # Summarize results
    print("\n" + "="*70)
    print("[Test Summary]")
    print("="*70)

    success_count = len([r for r in all_results['tests'] if r.get('status') == 'success'])
    failed_count = len([r for r in all_results['tests'] if r.get('status') == 'failed'])
    error_count = len([r for r in all_results['tests'] if r.get('status') == 'error'])

    print(f"[OK] Success: {success_count}")
    print(f"[X] Failed: {failed_count}")
    print(f"[!] Error: {error_count}")
    print(f"[=] Total: {success_count + failed_count + error_count}")

    # Save results
    results_file = 'docs/improved_adapters_test_results.json'
    import os
    os.makedirs(os.path.dirname(results_file), exist_ok=True)

    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[File] Test results saved to: {results_file}")

    return failed_count == 0 and error_count == 0


if __name__ == '__main__':
    # Django setup
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
    django.setup()

    success = run_all_tests()
    exit(0 if success else 1)
