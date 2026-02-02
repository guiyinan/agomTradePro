"""
AgomSAAF 数据更新脚本

独立脚本，用于从 AKShare 获取最新宏观数据并更新系统。
不依赖 Django，可直接运行。
"""

import sys
from datetime import date, timedelta
from typing import List, Dict, Optional
import json


# ==================== AKShare 适配器 ====================

class AKShareFetcher:
    """AKShare 数据获取器"""

    def __init__(self):
        try:
            import akshare as ak
            self.ak = ak
            self.available = True
        except ImportError:
            self.available = False
            print("警告: 未安装 akshare 库")
            print("安装命令: pip install akshare")

    def fetch_pmi(self, years: int = 3) -> List[Dict]:
        """获取 PMI 数据"""
        if not self.available:
            return []

        try:
            # 获取制造业 PMI
            df = self.ak.macro_china_pmi()

            # 正确的列名
            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '制造业-指数' if '制造业-指数' in df.columns else (
                '制造业PMI' if '制造业PMI' in df.columns else df.columns[1]
            )

            # 解析中文日期
            def parse_chinese_date(date_str):
                """解析中文日期格式: '2010年12月份' -> datetime"""
                import re
                from datetime import datetime
                match = re.match(r'(\d{4})年(\d{1,2})月份?', str(date_str))
                if match:
                    return datetime(int(match.group(1)), int(match.group(2)), 1)
                return None

            df['parsed_date'] = df[date_col].apply(parse_chinese_date)
            df = df[['parsed_date', value_col]].dropna()
            # 按日期排序
            df = df.sort_values('parsed_date')

            data = []
            # 取最新的 N 条数据
            for _, row in df.tail(years * 12).iterrows():
                val = row[value_col]
                # 处理可能的空值或无效值
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    continue

                data.append({
                    'indicator': 'CN_PMI',
                    'value': val,
                    'date': str(row['parsed_date'].date()),
                    'source': 'akshare'
                })
            return data
        except Exception as e:
            print(f"获取 PMI 数据失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def fetch_cpi(self, years: int = 3) -> List[Dict]:
        """获取 CPI 数据"""
        if not self.available:
            return []

        try:
            # 获取 CPI 同比数据
            df = self.ak.macro_china_cpi()

            # 解析中文日期
            def parse_chinese_date(date_str):
                """解析中文日期格式: '2025年12月份' -> datetime"""
                import re
                from datetime import datetime
                match = re.match(r'(\d{4})年(\d{1,2})月份?', str(date_str))
                if match:
                    return datetime(int(match.group(1)), int(match.group(2)), 1)
                return None

            # 使用列索引而不是列名（避免编码问题）
            date_col = df.columns[0]  # 月份
            value_col = df.columns[2]  # 全国-当月同比 (第3列)

            df['parsed_date'] = df[date_col].apply(parse_chinese_date)
            df = df[['parsed_date', value_col]].dropna()
            # 按日期排序
            df = df.sort_values('parsed_date')

            data = []
            # 取最新的 N 条数据
            for _, row in df.tail(years * 12).iterrows():
                val = row[value_col]
                # 处理百分比值（已经是小数形式）
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    continue

                data.append({
                    'indicator': 'CN_CPI',
                    'value': val,
                    'date': str(row['parsed_date'].date()),
                    'source': 'akshare'
                })
            return data
        except Exception as e:
            print(f"获取 CPI 数据失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def fetch_ppi(self, years: int = 3) -> List[Dict]:
        """获取 PPI 数据"""
        if not self.available:
            return []

        try:
            # 获取 PPI 同比数据
            df = self.ak.macro_china_ppi()

            # 解析中文日期
            def parse_chinese_date(date_str):
                """解析中文日期格式: '2025年12月份' -> datetime"""
                import re
                from datetime import datetime
                match = re.match(r'(\d{4})年(\d{1,2})月份?', str(date_str))
                if match:
                    return datetime(int(match.group(1)), int(match.group(2)), 1)
                return None

            # 使用列索引（避免编码问题）
            date_col = df.columns[0]  # 月份
            value_col = df.columns[2]  # 当月同比 (第3列)

            df['parsed_date'] = df[date_col].apply(parse_chinese_date)
            df = df[['parsed_date', value_col]].dropna()
            # 按日期排序
            df = df.sort_values('parsed_date')

            data = []
            # 取最新的 N 条数据
            for _, row in df.tail(years * 12).iterrows():
                val = row[value_col]
                # 处理百分比值（已经是小数形式）
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    continue

                data.append({
                    'indicator': 'CN_PPI',
                    'value': val,
                    'date': str(row['parsed_date'].date()),
                    'source': 'akshare'
                })
            return data
        except Exception as e:
            print(f"获取 PPI 数据失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def fetch_shibor(self, years: int = 3) -> List[Dict]:
        """获取 SHIBOR 数据"""
        if not self.available:
            return []

        try:
            # 获取 SHIBOR 利率
            df = self.ak.shibor_data()

            # 取最近的数据
            end_date = date.today()
            start_date = end_date - timedelta(days=years * 365)

            df['date'] = pd.to_datetime(df['date'])
            df_filtered = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

            data = []
            for _, row in df_filtered.tail(years * 12).iterrows():
                data.append({
                    'indicator': 'CN_SHIBOR',
                    'value': float(row.get('1周', 0)) / 100,  # 转为小数
                    'date': str(row['date'].date()),
                    'source': 'akshare'
                })
            return data
        except Exception as e:
            print(f"获取 SHIBOR 数据失败: {e}")
            return []


# ==================== Regime 计算 ====================

def calculate_regime_from_data(growth_data: List[Dict], inflation_data: List[Dict]):
    """从宏观数据计算 Regime"""
    from apps.regime.domain.services import (
        RegimeCalculator,
        calculate_regime_distribution
    )

    # 提取序列
    growth_series = [d['value'] for d in sorted(growth_data, key=lambda x: x['date'])]
    inflation_series = [d['value'] for d in sorted(inflation_data, key=lambda x: x['date'])]

    if len(growth_series) < 12 or len(inflation_series) < 12:
        print("  数据不足，无法计算 Regime")
        return None

    # 创建计算器
    calculator = RegimeCalculator(
        momentum_period=3,
        zscore_window=24,
        zscore_min_periods=12,
        sigmoid_k=2.0,
        use_absolute_inflation_momentum=True,
        correlation=0.3
    )

    # 计算
    result = calculator.calculate(
        growth_series,
        inflation_series,
        date.today()
    )

    return result


# ==================== 数据保存 ====================

def save_to_json(data: Dict, filename: str):
    """保存数据到 JSON 文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_from_json(filename: str) -> Optional[Dict]:
    """从 JSON 文件加载数据"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


# ==================== 主程序 ====================

def main():
    """主程序"""
    print("=" * 60)
    print("AgomSAAF 数据更新工具")
    print("=" * 60)

    # 初始化数据获取器
    fetcher = AKShareFetcher()
    if not fetcher.available:
        print("\n错误: AKShare 不可用，请安装 akshare 库")
        print("安装命令: pip install akshare")
        return 1

    # 获取数据
    print("\n[1/4] 获取宏观数据...")

    all_data = {}

    # PMI
    print("  - 获取 PMI...")
    pmi_data = fetcher.fetch_pmi(years=3)
    print(f"    PMI: {len(pmi_data)} 条")
    if pmi_data:
        print(f"    最新: {pmi_data[-1]['date']} = {pmi_data[-1]['value']}")
    all_data['CN_PMI'] = pmi_data

    # CPI
    print("  - 获取 CPI...")
    cpi_data = fetcher.fetch_cpi(years=3)
    print(f"    CPI: {len(cpi_data)} 条")
    if cpi_data:
        print(f"    最新: {cpi_data[-1]['date']} = {cpi_data[-1]['value']:.2%}")
    all_data['CN_CPI'] = cpi_data

    # PPI
    print("  - 获取 PPI...")
    ppi_data = fetcher.fetch_ppi(years=3)
    print(f"    PPI: {len(ppi_data)} 条")
    if ppi_data:
        print(f"    最新: {ppi_data[-1]['date']} = {ppi_data[-1]['value']:.2%}")
    all_data['CN_PPI'] = ppi_data

    # 保存原始数据
    print("\n[2/4] 保存原始数据...")
    save_to_json(all_data, 'data/macro_data_latest.json')
    print("  已保存到 data/macro_data_latest.json")

    # 计算 Regime
    print("\n[3/4] 计算 Regime...")
    if pmi_data and cpi_data:
        try:
            regime_result = calculate_regime_from_data(pmi_data, cpi_data)

            if regime_result:
                snapshot = regime_result.snapshot
                print(f"  主导 Regime: {snapshot.dominant_regime}")
                print(f"  置信度: {snapshot.confidence:.1%}")
                print(f"  增长动量 Z: {snapshot.growth_momentum_z:+.3f}")
                print(f"  通胀动量 Z: {snapshot.inflation_momentum_z:+.3f}")
                print(f"  分布:")
                for regime, prob in snapshot.distribution.items():
                    print(f"    {regime}: {prob:.2%}")

                # 保存 Regime 结果
                regime_data = {
                    'date': str(snapshot.observed_at),
                    'dominant_regime': snapshot.dominant_regime,
                    'confidence': snapshot.confidence,
                    'growth_momentum_z': snapshot.growth_momentum_z,
                    'inflation_momentum_z': snapshot.inflation_momentum_z,
                    'distribution': snapshot.distribution,
                    'warnings': regime_result.warnings
                }

                save_to_json(regime_data, 'data/regime_latest.json')
                print("  已保存到 data/regime_latest.json")

        except Exception as e:
            print(f"  计算失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("  数据不足，跳过 Regime 计算")

    # 生成摘要
    print("\n[4/4] 生成数据摘要...")

    summary = {
        'update_date': str(date.today()),
        'data_points': {
            'CN_PMI': len(pmi_data),
            'CN_CPI': len(cpi_data),
            'CN_PPI': len(ppi_data),
        },
        'latest_values': {
            'CN_PMI': pmi_data[-1] if pmi_data else None,
            'CN_CPI': cpi_data[-1] if cpi_data else None,
            'CN_PPI': ppi_data[-1] if ppi_data else None,
        }
    }

    save_to_json(summary, 'data/update_summary.json')
    print("  已保存到 data/update_summary.json")

    print("\n" + "=" * 60)
    print("数据更新完成！")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
