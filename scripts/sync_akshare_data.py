#!/usr/bin/env python
"""
AkShare 数据同步脚本

从 AkShare 获取中国宏观数据并保存到数据库
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

# 设置 Windows 控制台 UTF-8 编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

import django

django.setup()

from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.macro.infrastructure.adapters.akshare_adapter import AKShareAdapter
from apps.macro.infrastructure.repositories import DjangoMacroRepository


def sync_data(
    indicator_code: str,
    start_date: date,
    end_date: date,
    adapter: AKShareAdapter,
    repository: DjangoMacroRepository
):
    """
    同步单个指标数据

    Args:
        indicator_code: 指标代码
        start_date: 起始日期
        end_date: 结束日期
        adapter: AkShare 适配器
        repository: 数据仓储
    """
    print(f"\n{'='*60}")
    print(f"开始同步: {indicator_code}")
    print(f"日期范围: {start_date} 到 {end_date}")
    print(f"{'='*60}")

    try:
        # 从 AkShare 获取数据
        data_points = adapter.fetch(indicator_code, start_date, end_date)

        if not data_points:
            print(f"[WARN] 未获取到 {indicator_code} 数据")
            return

        print(f"[OK] 获取到 {len(data_points)} 条数据")

        # 转换为 Domain 实体并保存
        saved_count = 0
        for dp in data_points:
            # 确定周期类型
            if 'GDP' in indicator_code:
                period_type = PeriodType.QUARTER
            else:
                period_type = PeriodType.MONTH

            indicator = MacroIndicator(
                code=dp.code,
                value=dp.value,
                reporting_period=dp.observed_at,
                period_type=period_type,
                published_at=dp.published_at or dp.observed_at,
                source=dp.source
            )

            try:
                repository.save_indicator(indicator, revision_number=1)
                saved_count += 1
            except Exception as e:
                print(f"[WARN] 保存失败 {dp.observed_at}: {e}")

        print(f"[OK] 成功保存 {saved_count}/{len(data_points)} 条数据")

    except Exception as e:
        print(f"[ERROR] 同步失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    print("\n" + "="*60)
    print("AkShare 宏观数据同步工具")
    print("="*60)

    # 初始化适配器和仓储
    adapter = AKShareAdapter()
    repository = DjangoMacroRepository()

    # 设置日期范围（最近 10 年）
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * 10)

    # 同步核心指标
    indicators = [
        "CN_PMI",      # PMI
        "CN_CPI",      # CPI
        "CN_PPI",      # PPI
        # "CN_M2",       # M2（可选）
        # "CN_GDP",      # GDP（可选）
    ]

    for indicator_code in indicators:
        sync_data(indicator_code, start_date, end_date, adapter, repository)

    print("\n" + "="*60)
    print("[DONE] 数据同步完成！")
    print("="*60)
    print("\n查看数据:")
    print("  - Admin 后台: http://127.0.0.1:8000/admin/macro/macroindicator/")
    print("  - Regime Dashboard: http://127.0.0.1:8000/regime/dashboard/")
    print()


if __name__ == "__main__":
    main()
