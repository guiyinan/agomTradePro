"""
投资组合数据迁移脚本

将 PortfolioModel 数据迁移到统一的 SimulatedAccountModel

执行方式:
    python manage.py shell < scripts/migrate_portfolio_to_investment_account.py

或直接运行:
    python scripts/migrate_portfolio_to_investment_account.py
"""
import os
import sys

import django

# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction

from apps.account.infrastructure.models import AccountProfileModel, PortfolioModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@transaction.atomic
def migrate_portfolios_to_investment_accounts():
    """
    将 Portfolio 数据迁移到 SimulatedAccount

    迁移规则：
    1. 每个用户的所有 Portfolio 迁移为 SimulatedAccount
    2. 默认标记为 real（实仓）
    3. 使用 AccountProfile.initial_capital 作为初始资金
    """
    print("=" * 60)
    print("开始迁移 Portfolio 到 SimulatedAccount")
    print("=" * 60)

    # 统计信息
    total_users = 0
    total_portfolios = 0
    total_created = 0
    total_skipped = 0

    # 获取所有有 Portfolio 的用户
    users_with_portfolios = User.objects.filter(
        portfolios__isnull=False
    ).distinct()

    total_users = users_with_portfolios.count()
    print(f"\n找到 {total_users} 个有投资组合的用户")

    for user in users_with_portfolios:
        print(f"\n处理用户: {user.username}")

        # 获取用户配置
        try:
            profile = user.account_profile
        except AccountProfileModel.DoesNotExist:
            print(f"  ⚠️  用户 {user.username} 没有 AccountProfile，跳过")
            continue

        # 获取用户的所有 Portfolio
        portfolios = user.portfolios.all()
        total_portfolios += portfolios.count()

        for idx, portfolio in enumerate(portfolios, 1):
            print(f"  [{idx}/{portfolios.count()}] 迁移: {portfolio.name}")

            # 检查是否已经存在同名投资组合
            existing = SimulatedAccountModel.objects.filter(
                user=user,
                account_name=portfolio.name
            ).first()

            if existing:
                print("    ⚠️  已存在同名投资组合，跳过")
                total_skipped += 1
                continue

            # 创建 SimulatedAccount
            account = SimulatedAccountModel.objects.create(
                user=user,
                account_name=portfolio.name,
                account_type='real',  # 默认标记为实仓
                initial_capital=profile.initial_capital,
                current_cash=profile.initial_capital,
                total_value=profile.initial_capital,
                is_active=portfolio.is_active,
            )

            total_created += 1
            print(f"    ✅ 创建成功: {account.account_name} (ID={account.id})")

    # 输出统计
    print("\n" + "=" * 60)
    print("迁移完成！")
    print("=" * 60)
    print(f"总用户数: {total_users}")
    print(f"总Portfolio数: {total_portfolios}")
    print(f"成功创建: {total_created}")
    print(f"跳过: {total_skipped}")
    print("=" * 60)


@transaction.atomic
def migrate_real_simulated_accounts():
    """
    将 AccountProfile.real_account 和 simulated_account 迁移到新的系统

    注意：这是一个过渡性的迁移，确保旧数据不丢失
    """
    print("\n" + "=" * 60)
    print("迁移 AccountProfile 关联的投资组合")
    print("=" * 60)

    profiles_with_real = AccountProfileModel.objects.filter(
        real_account__isnull=False
    )
    profiles_with_simulated = AccountProfileModel.objects.filter(
        simulated_account__isnull=False
    )

    print(f"\n找到 {profiles_with_real.count()} 个有实仓的用户")
    print(f"找到 {profiles_with_simulated.count()} 个有模拟仓的用户")

    migrated_real = 0
    migrated_simulated = 0

    # 迁移实仓
    for profile in profiles_with_real:
        old_account = profile.real_account
        print(f"迁移实仓: {profile.user.username} - {old_account.account_name}")

        # 更新 user 字段
        old_account.user = profile.user
        old_account.save()

        migrated_real += 1
        print("  ✅ 实仓迁移成功")

    # 迁移模拟仓
    for profile in profiles_with_simulated:
        old_account = profile.simulated_account
        print(f"迁移模拟仓: {profile.user.username} - {old_account.account_name}")

        # 更新 user 字段
        old_account.user = profile.user
        old_account.save()

        migrated_simulated += 1
        print("  ✅ 模拟仓迁移成功")

    print("\n" + "=" * 60)
    print(f"实仓迁移: {migrated_real}")
    print(f"模拟仓迁移: {migrated_simulated}")
    print("=" * 60)


def verify_migration():
    """验证迁移结果"""
    print("\n" + "=" * 60)
    print("验证迁移结果")
    print("=" * 60)

    # 统计投资组合数量
    total_accounts = SimulatedAccountModel.objects.count()
    real_accounts = SimulatedAccountModel.objects.filter(account_type='real').count()
    simulated_accounts = SimulatedAccountModel.objects.filter(account_type='simulated').count()
    accounts_with_user = SimulatedAccountModel.objects.exclude(user__isnull=True).count()

    print(f"\n总投资组合数: {total_accounts}")
    print(f"实仓数: {real_accounts}")
    print(f"模拟仓数: {simulated_accounts}")
    print(f"已关联用户的投资组合: {accounts_with_user}")

    # 检查是否有投资组合没有 user
    orphan_accounts = SimulatedAccountModel.objects.filter(user__isnull=True)
    if orphan_accounts.exists():
        print(f"\n⚠️  警告: {orphan_accounts.count()} 个投资组合没有关联用户")
        for account in orphan_accounts:
            print(f"  - {account.account_name} (ID={account.id})")
    else:
        print("\n✅ 所有投资组合都已关联用户")

    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="迁移投资组合数据")
    parser.add_argument(
        "--skip-portfolio",
        action="store_true",
        help="跳过 Portfolio 迁移"
    )
    parser.add_argument(
        "--skip-profile",
        action="store_true",
        help="跳过 AccountProfile 关联迁移"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="仅验证，不执行迁移"
    )

    args = parser.parse_args()

    try:
        if not args.verify_only:
            # 执行迁移
            if not args.skip_portfolio:
                migrate_portfolios_to_investment_accounts()

            if not args.skip_profile:
                migrate_real_simulated_accounts()

        # 验证结果
        verify_migration()

        print("\n✅ 所有操作完成！")

    except Exception as e:
        print(f"\n❌ 迁移失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
