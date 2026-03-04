#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Prepare Qlib Training Data Script

准备 Qlib 训练数据的脚本。

功能:
    1. 从 Tushare/AKShare 获取股票数据
    2. 计算技术指标
    3. 生成预测标签（未来收益率）
    4. 转换为 Qlib 二进制格式
    5. 支持命令行参数配置

使用方式:
    # 准备 CSI300 数据
    python scripts/prepare_qlib_training_data.py --universe csi300 --start-date 2020-01-01

    # 准备 CSI500 数据，指定数据源
    python scripts/prepare_qlib_training_data.py --universe csi500 --source akshare

    # 查看帮助
    python scripts/prepare_qlib_training_data.py --help
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Prepare Qlib training data from Tushare/AKShare'
    )

    parser.add_argument(
        '--universe',
        type=str,
        default='csi300',
        choices=['csi300', 'csi500', 'sse50', 'csi1000'],
        help='Stock universe (default: csi300)'
    )

    parser.add_argument(
        '--start-date',
        type=str,
        default='2020-01-01',
        help='Start date (YYYY-MM-DD format, default: 2020-01-01)'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD format, default: yesterday)'
    )

    parser.add_argument(
        '--source',
        type=str,
        default='tushare',
        choices=['tushare', 'akshare'],
        help='Data source (default: tushare)'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        default='~/.qlib/qlib_data/cn_data',
        help='Output directory for Qlib data (default: ~/.qlib/qlib_data/cn_data)'
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to feature config YAML file'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force overwrite existing data'
    )

    parser.add_argument(
        '--check',
        action='store_true',
        help='Check existing data without downloading'
    )

    return parser.parse_args()


def check_qlib_data(output_dir: str) -> dict:
    """
    检查 Qlib 数据目录

    Args:
        output_dir: Qlib 数据目录路径

    Returns:
        检查结果字典
    """
    output_path = Path(output_dir).expanduser()
    result = {
        'exists': output_path.exists(),
        'has_stocks': False,
        'has_features': False,
        'stock_count': 0,
        'date_range': None,
    }

    if not result['exists']:
        return result

    # 检查 stocks 目录
    stocks_dir = output_path / 'stocks'
    if stocks_dir.exists():
        result['has_stocks'] = True
        result['stock_count'] = len(list(stocks_dir.glob('*.csv')))

    # 检查 features 目录
    features_dir = output_path / 'features'
    if features_dir.exists():
        result['has_features'] = True

    return result


def load_stock_codes(universe: str) -> list:
    """
    加载股票池代码

    Args:
        universe: 股票池标识

    Returns:
        股票代码列表
    """
    # 股票池映射
    universe_map = {
        'csi300': '000300.SH',
        'csi500': '000905.SH',
        'sse50': '000016.SH',
        'csi1000': '000852.SH',
    }

    index_code = universe_map.get(universe)
    if not index_code:
        raise ValueError(f"不支持的股票池: {universe}")

    try:
        from shared.config.secrets import get_secrets
        import tushare as ts

        ts.set_token(get_secrets().data_sources.tushare_token)
        pro = ts.pro_api()

        # 获取指数成分股
        df = pro.index_weight(
            index_code=index_code,
            start_date='20200101'
        )

        if df is None or df.empty:
            # 使用最新日期
            latest_date = datetime.now().strftime('%Y%m%d')
            df = pro.index_weight(
                index_code=index_code,
                start_date=latest_date
            )

        if df is not None and not df.empty:
            stock_codes = df['con_code'].unique().tolist()
            # 转换为 Qlib 格式 (例如: 000001.SZ)
            qlib_codes = []
            for code in stock_codes:
                if code.endswith('.SH'):
                    qlib_codes.append(code.replace('.SH', '.SH'))
                elif code.endswith('.SZ'):
                    qlib_codes.append(code.replace('.SZ', '.SZ'))

            logger.info(f"加载 {universe} 股票池: {len(qlib_codes)} 只股票")
            return qlib_codes

    except Exception as e:
        logger.error(f"加载股票池失败: {e}")

    # 返回默认股票池
    logger.warning(f"使用默认股票池配置: {universe}")
    return []


def fetch_daily_data(
    stock_codes: list,
    start_date: str,
    end_date: str,
    source: str = 'tushare'
) -> dict:
    """
    获取日线数据

    Args:
        stock_codes: 股票代码列表
        start_date: 开始日期
        end_date: 结束日期
        source: 数据源

    Returns:
        股票代码到数据的映射
    """
    data_map = {}

    logger.info(f"开始获取数据: {len(stock_codes)} 只股票, {start_date} 到 {end_date}")

    if source == 'tushare':
        data_map = _fetch_from_tushare(stock_codes, start_date, end_date)
    elif source == 'akshare':
        data_map = _fetch_from_akshare(stock_codes, start_date, end_date)
    else:
        raise ValueError(f"不支持的数据源: {source}")

    logger.info(f"数据获取完成: {len(data_map)} 只股票成功")
    return data_map


def _fetch_from_tushare(stock_codes: list, start_date: str, end_date: str) -> dict:
    """从 Tushare 获取数据"""
    try:
        from shared.config.secrets import get_secrets
        import tushare as ts
        import pandas as pd

        ts.set_token(get_secrets().data_sources.tushare_token)
        pro = ts.pro_api()

        # 转换日期格式
        start = start_date.replace('-', '')
        end = end_date.replace('-', '')

        data_map = {}
        total = len(stock_codes)

        for i, code in enumerate(stock_codes):
            try:
                df = pro.daily(
                    ts_code=code,
                    start_date=start,
                    end_date=end
                )

                if df is not None and not df.empty:
                    # 重命名列
                    df = df.rename(columns={
                        'trade_date': 'date',
                        'open': 'open',
                        'high': 'high',
                        'low': 'low',
                        'close': 'close',
                        'vol': 'volume',
                        'amount': 'amount'
                    })

                    # 转换日期格式
                    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

                    # 按日期排序
                    df = df.sort_values('date')

                    data_map[code] = df

                    if (i + 1) % 50 == 0:
                        logger.info(f"进度: {i + 1}/{total}")

            except Exception as e:
                logger.warning(f"获取 {code} 数据失败: {e}")
                continue

        return data_map

    except Exception as e:
        logger.error(f"Tushare 数据获取失败: {e}")
        return {}


def _fetch_from_akshare(stock_codes: list, start_date: str, end_date: str) -> dict:
    """从 AKShare 获取数据"""
    try:
        import akshare as ak
        import pandas as pd

        data_map = {}
        total = len(stock_codes)

        for i, code in enumerate(stock_codes):
            try:
                # 转换代码格式
                symbol = code.replace('.SH', '').replace('.SZ', '')
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''),
                    adjust="qfq"
                )

                if df is not None and not df.empty:
                    # 重命名列
                    df = df.rename(columns={
                        '日期': 'date',
                        '开盘': 'open',
                        '收盘': 'close',
                        '最高': 'high',
                        '最低': 'low',
                        '成交量': 'volume',
                        '成交额': 'amount'
                    })

                    # 选择需要的列
                    df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]

                    # 按日期排序
                    df = df.sort_values('date')

                    data_map[code] = df

                    if (i + 1) % 50 == 0:
                        logger.info(f"进度: {i + 1}/{total}")

            except Exception as e:
                logger.warning(f"获取 {code} 数据失败: {e}")
                continue

        return data_map

    except Exception as e:
        logger.error(f"AKShare 数据获取失败: {e}")
        return {}


def calculate_features(df):
    """
    计算技术指标特征

    Args:
        df: 原始日线数据

    Returns:
        包含特征的数据框
    """
    import pandas as pd
    import numpy as np

    df = df.copy()

    # 收益率
    df['return_1d'] = df['close'].pct_change(1)
    df['return_5d'] = df['close'].pct_change(5)
    df['return_10d'] = df['close'].pct_change(10)
    df['return_20d'] = df['close'].pct_change(20)

    # 移动平均
    df['ma5'] = df['close'] / df['close'].rolling(5).mean() - 1
    df['ma10'] = df['close'] / df['close'].rolling(10).mean() - 1
    df['ma20'] = df['close'] / df['close'].rolling(20).mean() - 1
    df['ma60'] = df['close'] / df['close'].rolling(60).mean() - 1

    # 波动率
    df['volatility_5d'] = df['close'].rolling(5).std() / df['close']
    df['volatility_20d'] = df['close'].rolling(20).std() / df['close']

    # 振幅
    df['amplitude_20d'] = df['close'].rolling(20).max() / df['close'].rolling(20).min() - 1

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
    exp1 = df['close'].ewm(span=12).mean()
    exp2 = df['close'].ewm(span=26).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9).mean()

    # 动量
    df['momentum_5d'] = df['close'] / df['close'].shift(5) - 1
    df['momentum_10d'] = df['close'] / df['close'].shift(10) - 1

    return df


def calculate_labels(df, horizon: int = 5):
    """
    计算预测标签（未来收益率）

    Args:
        df: 原始日线数据
        horizon: 预测周期

    Returns:
        标签序列
    """
    # 未来收益率
    labels = df['close'].shift(-horizon) / df['close'] - 1
    return labels


def convert_to_qlib_format(data_map: dict, output_dir: str):
    """
    转换为 Qlib 二进制格式

    Args:
        data_map: 股票数据映射
        output_dir: 输出目录
    """
    try:
        import qlib

        # 初始化 Qlib
        qlib.init(provider_uri=output_dir, region="CN")

        # TODO: 使用 Qlib API 转换数据
        # 这里需要根据 Qlib 版本调整
        raise NotImplementedError(
            "Qlib 格式转换尚未实现。请参考 Qlib 文档完成数据转换。"
            "当前版本仅支持检查模式。请使用 --check 参数验证现有数据。"
        )

    except Exception as e:
        logger.error(f"Qlib 格式转换失败: {e}")
        raise


def main():
    """主函数"""
    args = parse_arguments()

    # 设置结束日期
    if args.end_date is None:
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        end_date = args.end_date

    logger.info("=" * 60)
    logger.info("Qlib 训练数据准备")
    logger.info("=" * 60)
    logger.info(f"股票池: {args.universe}")
    logger.info(f"时间范围: {args.start_date} 到 {end_date}")
    logger.info(f"数据源: {args.source}")
    logger.info(f"输出目录: {args.output_dir}")

    # 检查模式
    if args.check:
        logger.info("\n检查现有数据...")
        result = check_qlib_data(args.output_dir)
        logger.info(f"  目录存在: {result['exists']}")
        logger.info(f"  股票数据: {result['has_stocks']} ({result['stock_count']} 只)")
        logger.info(f"  特征数据: {result['has_features']}")
        return

    # 加载股票池
    stock_codes = load_stock_codes(args.universe)
    if not stock_codes:
        logger.error("股票池为空，退出")
        return

    # 获取数据
    data_map = fetch_daily_data(
        stock_codes=stock_codes,
        start_date=args.start_date,
        end_date=end_date,
        source=args.source
    )

    if not data_map:
        logger.error("未获取到任何数据，退出")
        return

    # 计算特征和标签
    logger.info("计算技术指标...")
    for code, df in data_map.items():
        df = calculate_features(df)
        data_map[code] = df

    # 转换为 Qlib 格式
    logger.info("转换为 Qlib 格式...")
    convert_to_qlib_format(data_map, args.output_dir)

    logger.info("\n数据准备完成!")
    logger.info(f"  输出目录: {args.output_dir}")
    logger.info(f"  股票数量: {len(data_map)}")


if __name__ == '__main__':
    main()
