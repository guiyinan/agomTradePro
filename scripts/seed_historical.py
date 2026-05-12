"""
Historical Data Seeding Script.

Imports historical macro economic data from 2015-2024 for backtesting.

Usage:
    python scripts/seed_historical.py --all
    python scripts/seed_historical.py --indicator CN_PMI --start 2015-01-01 --end 2024-12-31
    python scripts/seed_historical.py --list
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime
from typing import List, Optional

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
import django

django.setup()

from apps.macro.domain.entities import MacroIndicator
from apps.macro.infrastructure.adapters import PUBLICATION_LAGS, create_default_adapter
from apps.macro.infrastructure.repositories import DjangoMacroRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# 指标元数据配置
INDICATOR_METADATA = {
    "CN_PMI": {
        "name": "制造业PMI",
        "description": "中国制造业采购经理指数",
        "frequency": "月度",
        "source": "国家统计局",
        "importance": "high",  # 增长指标
    },
    "CN_CPI": {
        "name": "CPI同比",
        "description": "居民消费价格指数同比",
        "frequency": "月度",
        "source": "国家统计局",
        "importance": "high",  # 通胀指标
    },
    "CN_PPI": {
        "name": "PPI同比",
        "description": "工业生产者出厂价格指数同比",
        "frequency": "月度",
        "source": "国家统计局",
        "importance": "medium",  # 通胀指标
    },
    "CN_M2": {
        "name": "M2同比",
        "description": "广义货币供应量同比增速",
        "frequency": "月度",
        "source": "中国人民银行",
        "importance": "medium",  # 流动性指标
    },
}

# 默认导入的指标（核心回测所需）
DEFAULT_INDICATORS = ["CN_PMI", "CN_CPI", "CN_PPI", "CN_M2"]


def seed_indicator(
    indicator_code: str,
    start_date: date,
    end_date: date,
    repository: DjangoMacroRepository,
    adapter,
    force_refresh: bool = False
) -> dict:
    """
    导入单个指标的历史数据

    Args:
        indicator_code: 指标代码
        start_date: 起始日期
        end_date: 结束日期
        repository: 数据仓储
        adapter: 数据适配器
        force_refresh: 是否强制刷新（覆盖已有数据）

    Returns:
        dict: 导入结果统计
    """
    metadata = INDICATOR_METADATA.get(indicator_code, {})
    logger.info(f"\n{'='*60}")
    logger.info(f"开始导入: {indicator_code} - {metadata.get('name', '')}")
    logger.info(f"{'='*60}")
    logger.info(f"描述: {metadata.get('description', '')}")
    logger.info(f"频率: {metadata.get('frequency', '')}")
    logger.info(f"来源: {metadata.get('source', '')}")
    logger.info(f"日期范围: {start_date} ~ {end_date}")

    try:
        # 1. 从数据源获取数据
        logger.info("正在从数据源获取数据...")
        data_points = adapter.fetch(indicator_code, start_date, end_date)

        if not data_points:
            logger.warning(f"无数据返回: {indicator_code}")
            return {
                "code": indicator_code,
                "success": False,
                "fetched": 0,
                "imported": 0,
                "skipped": 0,
                "error": "无数据返回"
            }

        logger.info(f"获取到 {len(data_points)} 条数据")

        # 2. 转换为 Domain 实体
        indicators = []
        skipped = 0

        for dp in data_points:
            # 检查是否已存在
            if not force_refresh:
                existing = repository.get_by_code_and_date(
                    code=dp.code,
                    observed_at=dp.observed_at
                )
                if existing is not None:
                    skipped += 1
                    continue

            indicator = MacroIndicator(
                code=dp.code,
                value=dp.value,
                observed_at=dp.observed_at,
                published_at=dp.published_at,
                source=dp.source
            )
            indicators.append(indicator)

        logger.info(f"新增 {len(indicators)} 条，跳过 {skipped} 条（已存在）")

        # 3. 批量保存到数据库
        if indicators:
            repository.save_indicators_batch(indicators)
            logger.info(f"成功保存 {len(indicators)} 条数据到数据库")
        else:
            logger.info("没有需要导入的新数据")

        # 4. 验证导入结果
        total_count = repository.get_indicator_count(indicator_code)
        logger.info(f"数据库中 {indicator_code} 总记录数: {total_count}")

        # 显示最新几条数据
        latest_indicators = repository.get_series(
            indicator_code,
            start_date=start_date,
            end_date=end_date
        )
        if latest_indicators:
            logger.info("最新 5 条数据:")
            for ind in latest_indicators[-5:]:
                pub_lag = ""
                if ind.published_at:
                    lag = (ind.published_at - ind.observed_at).days
                    pub_lag = f" [+{lag}天]"
                logger.info(f"  {ind.observed_at}: {ind.value:.2f}{pub_lag}")

        return {
            "code": indicator_code,
            "success": True,
            "fetched": len(data_points),
            "imported": len(indicators),
            "skipped": skipped,
            "total": total_count,
        }

    except Exception as e:
        logger.error(f"导入 {indicator_code} 失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "code": indicator_code,
            "success": False,
            "fetched": 0,
            "imported": 0,
            "skipped": 0,
            "error": str(e)
        }


def seed_all_indicators(
    start_date: date,
    end_date: date,
    force_refresh: bool = False
) -> list[dict]:
    """
    导入所有默认指标的历史数据

    Args:
        start_date: 起始日期
        end_date: 结束日期
        force_refresh: 是否强制刷新

    Returns:
        List[dict]: 所有指标的导入结果
    """
    repository = DjangoMacroRepository()
    adapter = create_default_adapter()

    results = []

    logger.info(f"\n{'#'*60}")
    logger.info("# 批量导入历史数据")
    logger.info(f"# 时间范围: {start_date} ~ {end_date}")
    logger.info(f"# 指标数量: {len(DEFAULT_INDICATORS)}")
    logger.info(f"{'#'*60}")

    for indicator_code in DEFAULT_INDICATORS:
        result = seed_indicator(
            indicator_code,
            start_date,
            end_date,
            repository,
            adapter,
            force_refresh
        )
        results.append(result)

    return results


def print_summary(results: list[dict]):
    """打印导入摘要"""
    logger.info(f"\n{'='*60}")
    logger.info("导入摘要")
    logger.info(f"{'='*60}")

    success_count = sum(1 for r in results if r["success"])
    total_fetched = sum(r.get("fetched", 0) for r in results)
    total_imported = sum(r.get("imported", 0) for r in results)
    total_skipped = sum(r.get("skipped", 0) for r in results)

    logger.info(f"成功: {success_count}/{len(results)} 个指标")
    logger.info(f"获取: {total_fetched} 条")
    logger.info(f"导入: {total_imported} 条")
    logger.info(f"跳过: {total_skipped} 条")

    logger.info("\n详细结果:")
    for r in results:
        status = "✅" if r["success"] else "❌"
        if r["success"]:
            logger.info(f"  {status} {r['code']}: 导入 {r['imported']} 条, 跳过 {r['skipped']} 条")
        else:
            logger.info(f"  {status} {r['code']}: 失败 - {r.get('error', '未知错误')}")


def list_indicators():
    """列出所有可用的指标"""
    logger.info(f"\n{'='*60}")
    logger.info("可用的宏观指标")
    logger.info(f"{'='*60}")

    for code, meta in INDICATOR_METADATA.items():
        logger.info(f"\n{code} - {meta['name']}")
        logger.info(f"  描述: {meta['description']}")
        logger.info(f"  频率: {meta['frequency']}")
        logger.info(f"  来源: {meta['source']}")
        logger.info(f"  重要性: {meta['importance']}")

        # 显示发布延迟
        if code in PUBLICATION_LAGS:
            lag = PUBLICATION_LAGS[code]
            logger.info(f"  发布延迟: {lag.days} 天 ({lag.description})")


def check_database():
    """检查数据库中的数据情况"""
    logger.info(f"\n{'='*60}")
    logger.info("数据库数据检查")
    logger.info(f"{'='*60}")

    repository = DjangoMacroRepository()

    for code in DEFAULT_INDICATORS:
        count = repository.get_indicator_count(code)
        logger.info(f"  {code}: {count} 条记录")

        if count > 0:
            # 获取日期范围
            indicators = repository.get_series(code)
            if indicators:
                first_date = indicators[0].observed_at
                last_date = indicators[-1].observed_at
                logger.info(f"    日期范围: {first_date} ~ {last_date}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="导入历史宏观数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --all                           # 导入所有指标（2015-2024）
  %(prog)s --all --force                   # 强制刷新所有数据
  %(prog)s --indicator CN_PMI              # 只导入 PMI
  %(prog)s --indicator CN_PMI --start 2020-01-01 --end 2024-12-31
  %(prog)s --list                          # 列出所有可用指标
  %(prog)s --check                         # 检查数据库状态
        """
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="导入所有默认指标"
    )

    parser.add_argument(
        "--indicator",
        type=str,
        help="指定要导入的指标代码"
    )

    parser.add_argument(
        "--start",
        type=str,
        default="2015-01-01",
        help="起始日期 (默认: 2015-01-01)"
    )

    parser.add_argument(
        "--end",
        type=str,
        default="2024-12-31",
        help="结束日期 (默认: 2024-12-31)"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="强制刷新（覆盖已有数据）"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用的指标"
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="检查数据库中的数据情况"
    )

    args = parser.parse_args()

    # 处理特殊命令
    if args.list:
        list_indicators()
        return 0

    if args.check:
        check_database()
        return 0

    # 解析日期
    try:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    except ValueError:
        logger.error("日期格式错误，请使用 YYYY-MM-DD 格式")
        return 1

    # 执行导入
    if args.all:
        results = seed_all_indicators(start_date, end_date, args.force)
        print_summary(results)
        return 0 if all(r["success"] for r in results) else 1

    elif args.indicator:
        if args.indicator not in INDICATOR_METADATA:
            logger.error(f"未知指标: {args.indicator}")
            logger.info("使用 --list 查看所有可用指标")
            return 1

        repository = DjangoMacroRepository()
        adapter = create_default_adapter()

        result = seed_indicator(
            args.indicator,
            start_date,
            end_date,
            repository,
            adapter,
            args.force
        )

        print_summary([result])
        return 0 if result["success"] else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
