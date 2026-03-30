"""
改进的资本市场数据适配器测试脚本

测试以下改进：
1. 重试机制 - 自动重试失败的请求
2. 缓存机制 - 减少重复请求
3. 多数据源切换 - 自动降级到备用数据源
4. 超时控制 - 防止请求卡死
5. 健康状态监控 - 跟踪数据源可用性
"""

import json
import time
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.skip(reason="script-style diagnostic module, not managed by pytest")


def test_resilience_features():
    """测试弹性功能"""
    print("\n" + "="*60)
    print("🛡️ 测试弹性功能")
    print("="*60)

    results = []

    # 测试1: 重试机制
    print("\n1. 测试重试机制")
    from shared.infrastructure.resilience import MaxRetriesExceeded, retry_on_error

    attempt_count = {'count': 0}

    @retry_on_error(max_retries=3, initial_delay=0.5)
    def flaky_function(should_fail=False):
        attempt_count['count'] += 1
        if should_fail and attempt_count['count'] < 3:
            raise ConnectionError("模拟网络错误")
        return "成功"

    try:
        # 测试失败后重试
        result = flaky_function(should_fail=True)
        results.append({
            'test': '重试机制',
            'status': 'success',
            'attempts': attempt_count['count'],
            'result': result
        })
        print(f"   重试机制正常: 尝试 {attempt_count['count']} 次后成功")

    except MaxRetriesExceeded:
        results.append({
            'test': '重试机制',
            'status': 'failed',
            'attempts': attempt_count['count']
        })
        print("   重试机制失败: 超过最大重试次数")

    # 测试2: 缓存机制
    print("\n2. 测试缓存机制")
    from shared.infrastructure.resilience import _cache_manager, cached

    call_count = {'count': 0}

    @cached(ttl=10)
    def expensive_function(x):
        call_count['count'] += 1
        return x * 2

    # 第一次调用 - 未命中缓存
    result1 = expensive_function(5)
    first_calls = call_count['count']

    # 第二次调用 - 命中缓存
    result2 = expensive_function(5)
    second_calls = call_count['count']

    if first_calls == 1 and second_calls == 1:
        results.append({
            'test': '缓存机制',
            'status': 'success',
            'details': '缓存正常工作'
        })
        print("   缓存机制正常: 第1次调用执行，第2次调用使用缓存")
    else:
        results.append({
            'test': '缓存机制',
            'status': 'failed',
            'calls': call_count['count']
        })

    # 测试3: 断路器
    print("\n3. 测试断路器")
    from shared.infrastructure.resilience import DataSourceUnavailable, circuit_breaker

    failure_count = {'count': 0}

    @circuit_breaker(failure_threshold=2, reset_timeout=5)
    def unstable_service(should_fail=True):
        failure_count['count'] += 1
        if should_fail:
            raise ConnectionError("服务不可用")
        return "正常"

    # 触发断路器
    try:
        for i in range(3):
            try:
                unstable_service(should_fail=True)
            except:
                pass

        # 断路器应该已打开
        try:
            unstable_service(should_fail=False)
            results.append({
                'test': '断路器',
                'status': 'failed',
                'reason': '断路器未生效'
            })
        except DataSourceUnavailable:
            results.append({
                'test': '断路器',
                'status': 'success',
                'reason': '断路器正常工作'
            })
            print("   断路器正常: 连续失败后快速失败")
    except Exception as e:
        results.append({
            'test': '断路器',
            'status': 'error',
            'error': str(e)
        })

    return results


def test_hybrid_stock_adapter():
    """测试混合股票适配器"""
    print("\n" + "="*60)
    print("📈 测试混合股票适配器")
    print("="*60)

    results = []

    try:
        from apps.equity.infrastructure.adapters.hybrid_stock_adapter import HybridStockAdapter

        # 不需要 Tushare token，只使用 AKShare
        adapter = HybridStockAdapter(tushare_token=None)

        # 测试1: 获取股票列表（带重试和缓存）
        print("\n1. 测试 fetch_stock_list_a()（带重试和缓存）")
        start = time.time()

        try:
            df = adapter.fetch_stock_list_a()
            elapsed = time.time() - start

            if not df.empty:
                results.append({
                    'test': '混合适配器-股票列表',
                    'status': 'success',
                    'count': len(df),
                    'time': f'{elapsed:.2f}s'
                })
                print(f"   成功获取 {len(df)} 只股票，耗时 {elapsed:.2f}秒")

                # 第二次调用应该更快（缓存）
                start2 = time.time()
                df2 = adapter.fetch_stock_list_a()
                elapsed2 = time.time() - start2

                if elapsed2 < elapsed * 0.5:  # 至少快50%
                    print(f"   缓存生效: 第二次调用耗时 {elapsed2:.2f}秒")
            else:
                results.append({
                    'test': '混合适配器-股票列表',
                    'status': 'failed',
                    'reason': '返回空数据'
                })
                print("   失败: 返回空数据")

        except MaxRetriesExceeded as e:
            results.append({
                'test': '混合适配器-股票列表',
                'status': 'failed',
                'reason': '超过重试次数',
                'error': str(e)
            })
            print("   失败: 超过最大重试次数")
        except Exception as e:
            results.append({
                'test': '混合适配器-股票列表',
                'status': 'error',
                'error': str(e)
            })
            print(f"   错误: {str(e)[:100]}")

        # 测试2: 获取股票信息（带缓存）
        print("\n2. 测试 fetch_stock_info()（带缓存）")
        try:
            info = adapter.fetch_stock_info('000001')
            if info:
                results.append({
                    'test': '混合适配器-股票信息',
                    'status': 'success',
                    'keys': len(info)
                })
                print(f"   成功获取股票信息，包含 {len(info)} 个字段")
            else:
                results.append({
                    'test': '混合适配器-股票信息',
                    'status': 'failed',
                    'reason': '返回空信息'
                })
                print("   失败: 返回空信息")
        except Exception as e:
            results.append({
                'test': '混合适配器-股票信息',
                'status': 'error',
                'error': str(e)[:100]
            })
            print(f"   错误: {str(e)[:100]}")

        # 测试3: 获取日线数据（带缓存）
        print("\n3. 测试 fetch_daily_data()（带缓存）")
        try:
            df = adapter.fetch_daily_data('000001', '2024-12-01', '2024-12-31')
            if not df.empty:
                results.append({
                    'test': '混合适配器-日线数据',
                    'status': 'success',
                    'count': len(df)
                })
                print(f"   成功获取 {len(df)} 条日线数据")
            else:
                results.append({
                    'test': '混合适配器-日线数据',
                    'status': 'failed',
                    'reason': '返回空数据'
                })
                print("   失败: 返回空数据")
        except Exception as e:
            results.append({
                'test': '混合适配器-日线数据',
                'status': 'error',
                'error': str(e)[:100]
            })
            print(f"   错误: {str(e)[:100]}")

        # 测试4: 健康状态
        print("\n4. 测试健康状态监控")
        try:
            health = adapter.get_health_status()
            results.append({
                'test': '健康状态监控',
                'status': 'success',
                'sources': list(health.keys())
            })
            print(f"   健康状态: {list(health.keys())}")
            for source, status in health.items():
                failures = status.get('failure_count', 0)
                print(f"     {source}: 失败次数 {failures}")
        except Exception as e:
            results.append({
                'test': '健康状态监控',
                'status': 'error',
                'error': str(e)[:100]
            })

    except ImportError as e:
        results.append({
            'test': '混合适配器',
            'status': 'error',
            'error': f'导入失败: {str(e)[:100]}'
        })
        print(f"   导入失败: {str(e)[:100]}")

    return results


def test_database_operations_with_cache():
    """测试带缓存的数据库操作"""
    print("\n" + "="*60)
    print("💾 测试数据库操作（带缓存）")
    print("="*60)

    results = []

    try:
        from apps.equity.infrastructure.adapters.hybrid_stock_adapter import HybridStockAdapter

        from apps.equity.infrastructure.models import StockInfoModel

        adapter = HybridStockAdapter(tushare_token=None)

        # 测试：从适配器获取数据并保存到数据库
        print("\n1. 从混合适配器获取并保存股票数据")
        try:
            df = adapter.fetch_stock_list_a()

            if not df.empty:
                saved_count = 0
                for _, row in df.head(50).iterrows():  # 只保存前50只作为测试
                    code = row.get('stock_code', '')
                    if code:
                        defaults = {
                            'name': row.get('name', ''),
                            'sector': row.get('industry', '未知'),
                            'market': row.get('market', 'SZ'),
                            'list_date': date(2000, 1, 1),
                        }
                        obj, created = StockInfoModel.objects.update_or_create(
                            stock_code=code,
                            defaults=defaults
                        )
                        if created:
                            saved_count += 1

                print(f"   成功保存 {saved_count} 只新股票到数据库")
                results.append({
                    'test': '数据库保存',
                    'status': 'success',
                    'count': saved_count
                })
            else:
                print("   未能获取股票数据")
                results.append({
                    'test': '数据库保存',
                    'status': 'failed',
                    'reason': '无法获取数据'
                })

        except Exception as e:
            print(f"   保存失败: {str(e)[:100]}")
            results.append({
                'test': '数据库保存',
                'status': 'error',
                'error': str(e)[:100]
            })

        # 检查数据库状态
        print("\n2. 检查数据库状态")
        try:
            total_count = StockInfoModel.objects.count()
            print(f"   数据库中共有 {total_count} 只股票")
            results.append({
                'test': '数据库状态',
                'status': 'success',
                'total_stocks': total_count
            })

            # 显示最近的股票
            if total_count > 0:
                recent_stocks = StockInfoModel.objects.order_by('-created_at')[:5]
                print("   最近添加的股票:")
                for stock in recent_stocks:
                    print(f"     - {stock.stock_code}: {stock.name}")

        except Exception as e:
            print(f"   查询失败: {str(e)[:100]}")
            results.append({
                'test': '数据库状态',
                'status': 'error',
                'error': str(e)[:100]
            })

    except Exception as e:
        results.append({
            'test': '数据库操作',
            'status': 'error',
            'error': str(e)[:100]
        })
        print(f"   错误: {str(e)[:100]}")

    return results


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*70)
    print("🚀 改进的资本市场数据适配器测试")
    print("="*70)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = {
        'timestamp': datetime.now().isoformat(),
        'tests': []
    }

    test_functions = [
        ("弹性功能", test_resilience_features),
        ("混合股票适配器", test_hybrid_stock_adapter),
        ("数据库操作", test_database_operations_with_cache),
    ]

    for category, test_func in test_functions:
        try:
            results = test_func()
            all_results['tests'].extend(results)
        except Exception as e:
            print(f"\n❌ {category} 测试异常: {e}")
            all_results['tests'].append({
                'category': category,
                'status': 'error',
                'error': str(e)
            })

    # 汇总结果
    print("\n" + "="*70)
    print("📊 测试总结")
    print("="*70)

    success_count = len([r for r in all_results['tests'] if r.get('status') == 'success'])
    failed_count = len([r for r in all_results['tests'] if r.get('status') == 'failed'])
    error_count = len([r for r in all_results['tests'] if r.get('status') == 'error'])

    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {failed_count}")
    print(f"⚠️ 错误: {error_count}")
    print(f"∑ 总计: {success_count + failed_count + error_count}")

    # 保存结果
    results_file = 'docs/improved_adapters_test_results.json'
    import os
    os.makedirs(os.path.dirname(results_file), exist_ok=True)

    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n📄 测试结果已保存到: {results_file}")

    return failed_count == 0 and error_count == 0


if __name__ == '__main__':
    # Django setup
    import os

    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
    django.setup()

    success = run_all_tests()
    exit(0 if success else 1)
