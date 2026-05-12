"""
AgomTradePro 资本市场数据连接测试脚本

测试股票、基金、板块等资本市场数据的接入能力。
"""

import json
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.skip(reason="script-style diagnostic module, not managed by pytest")


def test_stock_data_adapters():
    """测试股票数据适配器"""
    print("\n" + "="*60)
    print("📈 测试股票数据适配器")
    print("="*60)

    results = []

    # 测试 AKShare 股票适配器
    print("\n--- 测试 AKShare 股票适配器 ---")
    try:
        from apps.equity.infrastructure.adapters.akshare_stock_adapter import AKShareStockAdapter

        adapter = AKShareStockAdapter()

        # 测试1: 获取A股列表
        print("\n1. 获取A股列表...")
        df = adapter.fetch_stock_list_a()
        if not df.empty:
            print(f"   ✓ 成功获取 {len(df)} 只A股")
            results.append({
                'test': 'AKShare A股列表',
                'status': 'success',
                'count': len(df),
                'sample': df.head(3)[['stock_code', 'name', 'market']].to_dict('records') if 'stock_code' in df.columns else []
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare A股列表', 'status': 'failed'})

        # 测试2: 获取单个股票信息
        print("\n2. 获取平安银行(000001)信息...")
        info = adapter.fetch_stock_info('000001')
        if info:
            print("   ✓ 成功获取股票信息")
            results.append({
                'test': 'AKShare 股票信息',
                'status': 'success',
                'sample': list(info.keys())[:5]
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 股票信息', 'status': 'failed'})

        # 测试3: 获取历史数据
        print("\n3. 获取平安银行日线数据...")
        df = adapter.fetch_daily_data('000001', '2024-01-01', '2024-12-31')
        if not df.empty:
            print(f"   ✓ 成功获取 {len(df)} 条K线数据")
            results.append({
                'test': 'AKShare 日线数据',
                'status': 'success',
                'count': len(df),
                'columns': list(df.columns)
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 日线数据', 'status': 'failed'})

        # 测试4: 获取实时行情
        print("\n4. 获取A股实时行情...")
        df = adapter.fetch_stock_list_a()
        if not df.empty:
            print(f"   ✓ 成功获取实时行情，共 {len(df)} 只股票")
            results.append({
                'test': 'AKShare 实时行情',
                'status': 'success',
                'count': len(df)
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 实时行情', 'status': 'failed'})

        # 测试5: 获取指数数据
        print("\n5. 获取上证指数数据...")
        df = adapter.fetch_index_data('000001')
        if not df.empty:
            print(f"   ✓ 成功获取上证指数数据，{len(df)} 条记录")
            results.append({
                'test': 'AKShare 指数数据',
                'status': 'success',
                'count': len(df)
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 指数数据', 'status': 'failed'})

    except Exception as e:
        print(f"   ✗ AKShare 适配器错误: {e}")
        results.append({
            'test': 'AKShare 适配器',
            'status': 'error',
            'error': str(e)
        })

    # 测试 Tushare 股票适配器
    print("\n--- 测试 Tushare 股票适配器 ---")
    try:
        from apps.equity.infrastructure.adapters import TushareStockAdapter

        adapter = TushareStockAdapter()

        # 检查是否配置了 token
        try:
            _ = adapter.pro
            print("   ✓ Tushare token 已配置")

            # 测试获取股票列表
            print("\n6. 获取Tushare股票列表...")
            df = adapter.fetch_stock_list()
            if not df.empty:
                print(f"   ✓ 成功获取 {len(df)} 只股票")
                results.append({
                    'test': 'Tushare 股票列表',
                    'status': 'success',
                    'count': len(df)
                })
            else:
                print("   ✗ 获取失败")
                results.append({'test': 'Tushare 股票列表', 'status': 'failed'})

        except ValueError as e:
            print(f"   ⚠ Tushare token 未配置: {e}")
            results.append({
                'test': 'Tushare 配置',
                'status': 'skipped',
                'reason': 'Token未配置'
            })

    except Exception as e:
        print(f"   ✗ Tushare 适配器错误: {e}")
        results.append({
            'test': 'Tushare 适配器',
            'status': 'error',
            'error': str(e)
        })

    return results


def test_fund_data_adapters():
    """测试基金数据适配器"""
    print("\n" + "="*60)
    print("💰 测试基金数据适配器")
    print("="*60)

    results = []

    # 测试 AKShare 基金适配器
    print("\n--- 测试 AKShare 基金适配器 ---")
    try:
        from apps.fund.infrastructure.adapters.akshare_fund_adapter import AkShareFundAdapter

        adapter = AkShareFundAdapter()

        # 测试1: 获取基金列表
        print("\n1. 获取基金列表...")
        df = adapter.fetch_fund_list_em()
        if df is not None and not df.empty:
            print(f"   ✓ 成功获取 {len(df)} 只基金")
            results.append({
                'test': 'AKShare 基金列表',
                'status': 'success',
                'count': len(df)
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 基金列表', 'status': 'failed'})

        # 测试2: 获取单个基金信息
        print("\n2. 获取易方达蓝筹精选(005827)信息...")
        df = adapter.fetch_fund_info_em('005827')
        if df is not None and not df.empty:
            print("   ✓ 成功获取基金信息")
            results.append({
                'test': 'AKShare 基金信息',
                'status': 'success'
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 基金信息', 'status': 'failed'})

        # 测试3: 获取基金净值
        print("\n3. 获取基金净值数据...")
        df = adapter.fetch_fund_nav_em('005827')
        if df is not None and not df.empty:
            print(f"   ✓ 成功获取 {len(df)} 条净值记录")
            results.append({
                'test': 'AKShare 基金净值',
                'status': 'success',
                'count': len(df)
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 基金净值', 'status': 'failed'})

    except Exception as e:
        print(f"   ✗ AKShare 基金适配器错误: {e}")
        results.append({
            'test': 'AKShare 基金适配器',
            'status': 'error',
            'error': str(e)
        })

    return results


def test_sector_data_adapters():
    """测试板块数据适配器"""
    print("\n" + "="*60)
    print("📊 测试板块数据适配器")
    print("="*60)

    results = []

    # 测试 AKShare 板块适配器
    print("\n--- 测试 AKShare 板块适配器 ---")
    try:
        from apps.sector.infrastructure.adapters.akshare_sector_adapter import AKShareSectorAdapter

        adapter = AKShareSectorAdapter()

        # 测试1: 获取申万行业分类
        print("\n1. 获取申万一级行业分类...")
        df = adapter.fetch_sw_industry_classify(level='SW1')
        if df is not None and not df.empty:
            print(f"   ✓ 成功获取 {len(df)} 个一级行业")
            results.append({
                'test': 'AKShare 行业分类',
                'status': 'success',
                'count': len(df)
            })

            # 显示部分行业
            if 'sector_name' in df.columns:
                print(f"   示例行业: {', '.join(df['sector_name'].head(5).tolist())}")
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 行业分类', 'status': 'failed'})

        # 测试2: 获取板块列表
        print("\n2. 获取板块列表...")
        df = adapter.fetch_sector_list()
        if df is not None and not df.empty:
            print(f"   ✓ 成功获取 {len(df)} 个板块")
            results.append({
                'test': 'AKShare 板块列表',
                'status': 'success',
                'count': len(df)
            })
        else:
            print("   ✗ 获取失败")
            results.append({'test': 'AKShare 板块列表', 'status': 'failed'})

    except Exception as e:
        print(f"   ✗ AKShare 板块适配器错误: {e}")
        results.append({
            'test': 'AKShare 板块适配器',
            'status': 'error',
            'error': str(e)
        })

    return results


def test_database_operations():
    """测试数据库操作"""
    print("\n" + "="*60)
    print("💾 测试数据库操作")
    print("="*60)

    results = []

    # 测试股票数据保存
    print("\n--- 测试股票数据保存 ---")
    try:
        from apps.equity.infrastructure.adapters.akshare_stock_adapter import AKShareStockAdapter

        from apps.equity.infrastructure.models import StockInfoModel

        adapter = AKShareStockAdapter()

        # 获取股票列表并保存
        print("\n1. 保存A股股票列表到数据库...")
        df = adapter.fetch_stock_list_a()

        if not df.empty:
            saved_count = 0
            for _, row in df.head(100).iterrows():  # 只保存前100只作为测试
                stock_code = row.get('stock_code', '')
                if not stock_code:
                    continue

                defaults = {
                    'name': row.get('name', ''),
                    'sector': row.get('industry', '未知'),
                    'market': row.get('market', 'SZ'),
                    'list_date': date(2000, 1, 1),  # 默认日期
                }

                obj, created = StockInfoModel.objects.update_or_create(
                    stock_code=stock_code,
                    defaults=defaults
                )
                if created:
                    saved_count += 1

            print(f"   ✓ 成功保存/更新 {saved_count} 只股票")
            results.append({
                'test': '股票数据保存',
                'status': 'success',
                'count': saved_count
            })
        else:
            print("   ✗ 无法获取股票数据")
            results.append({'test': '股票数据保存', 'status': 'failed'})

        # 检查数据库中的股票数量
        total_count = StockInfoModel.objects.count()
        print(f"   数据库中共有 {total_count} 只股票")
        results.append({
            'test': '股票数据统计',
            'status': 'success',
            'count': total_count
        })

    except Exception as e:
        print(f"   ✗ 数据库操作错误: {e}")
        results.append({
            'test': '数据库操作',
            'status': 'error',
            'error': str(e)
        })

    # 测试基金数据保存
    print("\n--- 测试基金数据保存 ---")
    try:
        from apps.fund.infrastructure.adapters.akshare_fund_adapter import AkShareFundAdapter
        from apps.fund.infrastructure.models import FundInfoModel

        adapter = AkShareFundAdapter()

        print("\n2. 保存基金列表到数据库...")
        df = adapter.fetch_fund_list_em()

        if df is not None and not df.empty:
            # 获取代码列名
            code_col = None
            for col in df.columns:
                if '代码' in col or 'code' in col.lower():
                    code_col = col
                    break

            if code_col:
                saved_count = 0
                for _, row in df.head(50).iterrows():  # 只保存前50只作为测试
                    fund_code = str(row.get(code_col, ''))
                    if not fund_code or fund_code == 'nan':
                        continue

                    defaults = {
                        'fund_name': row.get('名称', row.get('name', '')),
                        'fund_type': '开放式基金',
                        'management_company': '未知',
                    }

                    obj, created = FundInfoModel.objects.update_or_create(
                        fund_code=fund_code,
                        defaults=defaults
                    )
                    if created:
                        saved_count += 1

                print(f"   ✓ 成功保存/更新 {saved_count} 只基金")
                results.append({
                    'test': '基金数据保存',
                    'status': 'success',
                    'count': saved_count
                })
            else:
                print("   ⚠ 无法找到基金代码列")
                results.append({'test': '基金数据保存', 'status': 'partial'})
        else:
            print("   ✗ 无法获取基金数据")
            results.append({'test': '基金数据保存', 'status': 'failed'})

        # 检查数据库中的基金数量
        total_count = FundInfoModel.objects.count()
        print(f"   数据库中共有 {total_count} 只基金")
        results.append({
            'test': '基金数据统计',
            'status': 'success',
            'count': total_count
        })

    except Exception as e:
        print(f"   ✗ 基金数据库操作错误: {e}")
        results.append({
            'test': '基金数据库操作',
            'status': 'error',
            'error': str(e)
        })

    return results


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*70)
    print("🚀 AgomTradePro 资本市场数据连接综合测试")
    print("="*70)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = {
        'timestamp': datetime.now().isoformat(),
        'tests': []
    }

    # 运行各类测试
    test_functions = [
        ("股票数据适配器", test_stock_data_adapters),
        ("基金数据适配器", test_fund_data_adapters),
        ("板块数据适配器", test_sector_data_adapters),
        ("数据库操作", test_database_operations),
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
    skipped_count = len([r for r in all_results['tests'] if r.get('status') == 'skipped'])
    total_count = len(all_results['tests'])

    print(f"✓ 成功: {success_count}")
    print(f"✗ 失败: {failed_count}")
    print(f"⚠ 错误: {error_count}")
    print(f"⊘ 跳过: {skipped_count}")
    print(f"∑ 总计: {total_count}")

    # 保存结果
    results_file = 'docs/capital_market_test_results.json'
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
