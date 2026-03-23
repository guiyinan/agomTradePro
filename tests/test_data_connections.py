"""
AgomTradePro 综合数据连接测试脚本

从用户角度测试各个模块的数据连接和数据更新功能。
"""
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PositionModel,
)
from apps.macro.application.use_cases import SyncMacroDataUseCase

# Import models and repositories
from apps.macro.infrastructure.models import DataSourceConfig, MacroIndicator
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.policy.infrastructure.models import PolicyLog
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.use_cases import CalculateRegimeUseCase
from apps.regime.infrastructure.models import RegimeLog
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.infrastructure.repositories import DjangoSignalRepository

User = get_user_model()


class DataConnectionTester:
    """数据连接测试器"""

    def __init__(self):
        self.results = []
        self.errors = []

    def log_result(self, category, test_name, status, details=""):
        """记录测试结果"""
        result = {
            "category": category,
            "test": test_name,
            "status": status,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.results.append(result)
        icon = "✅" if status == "success" else "❌" if status == "error" else "⚠️"
        print(f"{icon} [{category}] {test_name}: {status}")
        if details:
            print(f"   {details}")

    def test_database_connection(self):
        """测试数据库连接"""
        print("\n" + "="*60)
        print("🔗 测试数据库连接")
        print("="*60)

        try:
            # Test basic query
            user_count = User.objects.count()
            self.log_result("Database", "用户表连接", "success", f"找到 {user_count} 个用户")

            # Test macro data table
            macro_count = MacroIndicator.objects.count()
            self.log_result("Database", "宏观数据表", "success", f"找到 {macro_count} 条记录")

            # Test regime table
            regime_count = RegimeLog.objects.count()
            self.log_result("Database", "Regime表", "success", f"找到 {regime_count} 条记录")

            # Test policy table
            policy_count = PolicyLog.objects.count()
            self.log_result("Database", "政策表", "success", f"找到 {policy_count} 条记录")

            # Test signal table
            signal_count = InvestmentSignalModel.objects.count()
            self.log_result("Database", "信号表", "success", f"找到 {signal_count} 条记录")

            return True
        except Exception as e:
            self.log_result("Database", "数据库连接", "error", str(e))
            return False

    def test_account_data(self):
        """测试账户数据"""
        print("\n" + "="*60)
        print("👤 测试账户数据")
        print("="*60)

        try:
            # Check currencies
            currency_count = CurrencyModel.objects.count()
            active_currencies = CurrencyModel.objects.filter(is_active=True).count()
            self.log_result("Account", "币种配置", "success",
                          f"共 {currency_count} 种，{active_currencies} 种激活")

            # Check asset categories
            category_count = AssetCategoryModel.objects.count()
            self.log_result("Account", "资产分类", "success", f"共 {category_count} 个分类")

            # Check user profiles
            profile_count = AccountProfileModel.objects.count()
            pending_users = AccountProfileModel.objects.filter(approval_status='pending').count()
            approved_users = AccountProfileModel.objects.filter(approval_status='approved').count()
            self.log_result("Account", "用户账户", "success",
                          f"共 {profile_count} 个，{approved_users} 已批准，{pending_users} 待审批")

            # Check portfolios
            portfolio_count = PortfolioModel.objects.count()
            active_portfolios = PortfolioModel.objects.filter(is_active=True).count()
            self.log_result("Account", "投资组合", "success",
                          f"共 {portfolio_count} 个，{active_portfolios} 个激活")

            # Check positions
            position_count = PositionModel.objects.count()
            open_positions = PositionModel.objects.filter(is_closed=False).count()
            if position_count > 0:
                total_value = PositionModel.objects.filter(is_closed=False).aggregate(
                    total=Sum('market_value')
                )['total'] or Decimal('0')
                total_pnl = PositionModel.objects.filter(is_closed=False).aggregate(
                    total=Sum('unrealized_pnl')
                )['total'] or Decimal('0')
                self.log_result("Account", "持仓数据", "success",
                              f"共 {position_count} 条，{open_positions} 个未平仓，"
                              f"总市值 ¥{total_value:.0f}，盈亏 ¥{total_pnl:.0f}")
            else:
                self.log_result("Account", "持仓数据", "warning", "暂无持仓记录")

            return True
        except Exception as e:
            self.log_result("Account", "账户数据测试", "error", str(e))
            return False

    def test_macro_data_update(self):
        """测试宏观数据更新"""
        print("\n" + "="*60)
        print("📊 测试宏观数据更新")
        print("="*60)

        try:
            repo = DjangoMacroRepository()

            # Check latest data dates
            latest_pmi = repo.get_latest_indicator_data('PMI')
            if latest_pmi:
                latest_date = latest_pmi[0].indicator_date
                days_ago = (timezone.now().date() - latest_date).days
                if days_ago <= 7:
                    self.log_result("Macro", "PMI数据新鲜度", "success",
                                  f"最新数据: {latest_date} ({days_ago} 天前)")
                else:
                    self.log_result("Macro", "PMI数据新鲜度", "warning",
                                  f"最新数据: {latest_date} ({days_ago} 天前，建议更新)")
            else:
                self.log_result("Macro", "PMI数据", "warning", "暂无PMI数据")

            # Check CPI
            latest_cpi = repo.get_latest_indicator_data('CPI')
            if latest_cpi:
                latest_date = latest_cpi[0].indicator_date
                self.log_result("Macro", "CPI数据", "success", f"最新数据: {latest_date}")
            else:
                self.log_result("Macro", "CPI数据", "warning", "暂无CPI数据")

            # Check data sources
            source_count = DataSourceConfig.objects.count()
            active_sources = DataSourceConfig.objects.filter(is_active=True).count()
            self.log_result("Macro", "数据源配置", "success",
                          f"共 {source_count} 个源，{active_sources} 个激活")

            # Try to fetch new data
            print("\n   🔄 尝试获取最新PMI数据...")
            try:
                use_case = SyncMacroDataUseCase()
                result = use_case.execute(
                    indicator_code='PMI',
                    source_name='akshare',
                    days_back=5
                )
                if result.success:
                    self.log_result("Macro", "PMI数据更新", "success",
                                  f"成功获取 {len(result.fetched)} 条新数据")
                else:
                    self.log_result("Macro", "PMI数据更新", "warning",
                                  f"更新失败: {result.error_message}")
            except Exception as e:
                self.log_result("Macro", "PMI数据更新", "error", str(e))

            return True
        except Exception as e:
            self.log_result("Macro", "宏观数据测试", "error", str(e))
            return False

    def test_regime_calculation(self):
        """测试Regime判定"""
        print("\n" + "="*60)
        print("🎯 测试Regime判定")
        print("="*60)

        try:
            repo = DjangoRegimeRepository()

            # Get latest regime
            latest = repo.get_latest_regime()
            if latest:
                self.log_result("Regime", "最新Regime状态", "success",
                              f"日期: {latest.date}, "
                              f"象限: {latest.quadrant}, "
                              f"置信度: {latest.confidence:.2%}")
            else:
                self.log_result("Regime", "最新Regime状态", "warning", "暂无Regime数据")

            # Check regime distribution
            all_regimes = repo.get_all_regimes()
            if all_regimes:
                distribution = {}
                for r in all_regimes:
                    distribution[r.quadrant] = distribution.get(r.quadrant, 0) + 1
                self.log_result("Regime", "Regime历史数据", "success",
                              f"共 {len(all_regimes)} 条记录，分布: {distribution}")

            # Try to calculate new regime
            print("\n   🔄 尝试计算最新Regime...")
            try:
                use_case = CalculateRegimeUseCase(regime_repo=repo)
                result = use_case.execute()
                if result.success:
                    self.log_result("Regime", "Regime计算", "success",
                                  f"计算成功 - {result.quadrant}, "
                                  f"增长Z: {result.growth_z:.2f}, "
                                  f"通胀Z: {result.inflation_z:.2f}")
                else:
                    self.log_result("Regime", "Regime计算", "error",
                                  f"计算失败: {result.error_message}")
            except Exception as e:
                self.log_result("Regime", "Regime计算", "error", str(e))

            return True
        except Exception as e:
            self.log_result("Regime", "Regime测试", "error", str(e))
            return False

    def test_policy_events(self):
        """测试政策事件"""
        print("\n" + "="*60)
        print("📰 测试政策事件")
        print("="*60)

        try:
            repo = DjangoPolicyRepository()

            # Get current policy status
            from apps.policy.application.use_cases import GetPolicyStatusUseCase
            use_case = GetPolicyStatusUseCase(event_store=repo)
            status = use_case.execute()

            self.log_result("Policy", "当前政策档位", "success",
                          f"档位: {status.current_level.value}, "
                          f"名称: {status.level_name}, "
                          f"干预激活: {status.is_intervention_active}")

            # Check policy events
            recent_events = PolicyLog.objects.order_by('-event_date')[:10]
            if recent_events:
                level_counts = recent_events.values('level').annotate(count=Count('id'))
                level_summary = {e['level']: e['count'] for e in level_counts}
                self.log_result("Policy", "近期政策事件", "success",
                              f"最近10条: {level_summary}")

                # Show latest event
                latest = recent_events.first()
                self.log_result("Policy", "最新政策", "success",
                              f"{latest.event_date} - {latest.level} - {latest.title[:30]}...")
            else:
                self.log_result("Policy", "政策事件", "warning", "暂无政策事件")

            # Check RSS sources
            from apps.policy.infrastructure.models import RSSSourceConfigModel
            rss_count = RSSSourceConfigModel.objects.count()
            active_rss = RSSSourceConfigModel.objects.filter(is_active=True).count()
            self.log_result("Policy", "RSS源配置", "success",
                          f"共 {rss_count} 个源，{active_rss} 个激活")

            return True
        except Exception as e:
            self.log_result("Policy", "政策测试", "error", str(e))
            return False

    def test_investment_signals(self):
        """测试投资信号"""
        print("\n" + "="*60)
        print("🎯 测试投资信号")
        print("="*60)

        try:
            # Check signals by status
            all_signals = InvestmentSignalModel.objects.all()
            active_count = all_signals.filter(status='active').count()
            invalidated_count = all_signals.filter(status='invalidated').count()
            closed_count = all_signals.filter(status='closed').count()

            self.log_result("Signal", "信号统计", "success",
                          f"共 {all_signals.count()} 条，"
                          f"活跃: {active_count}, "
                          f"失效: {invalidated_count}, "
                          f"已平仓: {closed_count}")

            # Check recent signals
            recent_signals = InvestmentSignalModel.objects.order_by('-created_at')[:5]
            if recent_signals:
                print("\n   📋 最近5条信号:")
                for sig in recent_signals:
                    print(f"      - {sig.asset_code} | {sig.direction} | "
                          f"{sig.status} | {sig.created_at.strftime('%Y-%m-%d')}")

            # Check signals by regime match
            regime_matched = all_signals.filter(regime_match_score__gte=0.7).count()
            if regime_matched > 0:
                self.log_result("Signal", "Regime匹配", "success",
                              f"{regime_matched} 条信号与当前Regime高度匹配")
            else:
                self.log_result("Signal", "Regime匹配", "warning",
                              "暂无与当前Regime匹配的信号")

            return True
        except Exception as e:
            self.log_result("Signal", "信号测试", "error", str(e))
            return False

    def test_dashboard_data(self):
        """测试仪表板数据"""
        print("\n" + "="*60)
        print("📈 测试仪表板数据")
        print("="*60)

        try:
            from apps.account.infrastructure.repositories import (
                AccountRepository,
                PortfolioRepository,
                PositionRepository,
            )
            from apps.dashboard.application.use_cases import GetDashboardDataUseCase

            # Get first user for testing
            user = User.objects.first()
            if not user:
                self.log_result("Dashboard", "用户数据", "error", "系统中没有用户")
                return False

            # Get dashboard data
            use_case = GetDashboardDataUseCase(
                account_repo=AccountRepository(),
                portfolio_repo=PortfolioRepository(),
                position_repo=PositionRepository(),
                regime_repo=DjangoRegimeRepository(),
                signal_repo=DjangoSignalRepository(),
            )

            data = use_case.execute(user.id)

            self.log_result("Dashboard", "用户基本信息", "success",
                          f"用户: {data.username or user.username}, "
                          f"显示名: {data.display_name}")

            self.log_result("Dashboard", "资产总览", "success",
                          f"总资产: ¥{data.total_assets:.0f}, "
                          f"收益率: {data.total_return_pct:.2f}%, "
                          f"仓位: {data.invested_ratio:.1f}%")

            self.log_result("Dashboard", "持仓信息", "success",
                          f"持仓数: {data.position_count}, "
                          f"Regime匹配度: {data.regime_match_score:.2f}")

            if data.current_regime:
                self.log_result("Dashboard", "宏观环境", "success",
                              f"当前Regime: {data.current_regime}, "
                              f"政策档位: {data.current_policy_level}")

            return True
        except Exception as e:
            self.log_result("Dashboard", "仪表板测试", "error", str(e))
            return False

    def test_data_consistency(self):
        """测试数据一致性"""
        print("\n" + "="*60)
        print("🔍 测试数据一致性")
        print("="*60)

        try:
            # Check if positions have valid portfolios
            orphan_positions = PositionModel.objects.filter(
                portfolio__isnull=True
            ).count()
            if orphan_positions > 0:
                self.log_result("Consistency", "孤立持仓", "error",
                              f"发现 {orphan_positions} 条没有投资组合的持仓")
            else:
                self.log_result("Consistency", "持仓-组合关联", "success", "正常")

            # Check if signals have asset metadata
            from apps.account.infrastructure.models import AssetMetadataModel
            signal_assets = InvestmentSignalModel.objects.values_list(
                'asset_code', flat=True).distinct()
            missing_metadata = 0
            for asset in signal_assets:
                if not AssetMetadataModel.objects.filter(asset_code=asset).exists():
                    missing_metadata += 1

            if missing_metadata > 0:
                self.log_result("Consistency", "信号资产元数据", "warning",
                              f"{missing_metadata} 个资产缺少元数据")
            else:
                self.log_result("Consistency", "信号资产元数据", "success", "正常")

            # Check if regime states have macro data
            latest_regime = RegimeLog.objects.order_by('-date').first()
            if latest_regime:
                macro_exists = MacroIndicator.objects.filter(
                    indicator_date__lte=latest_regime.date
                ).exists()
                if macro_exists:
                    self.log_result("Consistency", "Regime-宏观数据", "success", "正常")
                else:
                    self.log_result("Consistency", "Regime-宏观数据", "warning",
                                  "Regime日期之前无宏观数据")

            return True
        except Exception as e:
            self.log_result("Consistency", "一致性测试", "error", str(e))
            return False

    def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print("🚀 AgomTradePro 数据连接综合测试")
        print("="*60)
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        tests = [
            ("数据库连接", self.test_database_connection),
            ("账户数据", self.test_account_data),
            ("宏观数据", self.test_macro_data_update),
            ("Regime判定", self.test_regime_calculation),
            ("政策事件", self.test_policy_events),
            ("投资信号", self.test_investment_signals),
            ("仪表板数据", self.test_dashboard_data),
            ("数据一致性", self.test_data_consistency),
        ]

        passed = 0
        failed = 0

        for name, test_func in tests:
            try:
                if test_func():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"❌ {name} 测试异常: {e}")

        # Print summary
        print("\n" + "="*60)
        print("📊 测试总结")
        print("="*60)
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"⚠️ 总计: {passed + failed}")

        # Save results to file
        self.save_results()

        return failed == 0

    def save_results(self):
        """保存测试结果"""
        results_file = 'docs/data_test_results.json'
        os.makedirs(os.path.dirname(results_file), exist_ok=True)

        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "success": len([r for r in self.results if r["status"] == "success"]),
            "errors": len([r for r in self.results if r["status"] == "error"]),
            "warnings": len([r for r in self.results if r["status"] == "warning"]),
            "results": self.results
        }

        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n📄 测试结果已保存到: {results_file}")


if __name__ == '__main__':
    tester = DataConnectionTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
