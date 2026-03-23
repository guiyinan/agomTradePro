"""
用户信号处理器

当用户创建或注册时，自动为用户创建实仓和模拟仓账户。
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@receiver(post_save, sender=User)
def create_user_accounts(sender, instance, created, **kwargs):
    """
    当用户创建时，自动创建实仓和模拟仓

    Args:
        sender: User模型
        instance: 用户实例
        created: 是否为新创建
    """
    if created:
        # 使用事务确保要么都成功，要么都失败
        try:
            with transaction.atomic():
                # 1. 创建实仓（账户类型为 real）
                real_account = SimulatedAccountModel._default_manager.create(
                    user=instance,
                    account_name=f"{instance.username}_实仓",
                    account_type="real",
                    initial_capital=0,  # 实仓初始资金为0，需要用户手动入金
                    current_cash=0,
                    current_market_value=0,
                    total_value=0,
                    auto_trading_enabled=False,  # 实仓默认不启用自动交易
                )

                # 2. 创建模拟仓（账户类型为 simulated）
                # 使用用户配置的初始资金，默认100万
                initial_capital = 1000000.00  # 默认100万
                simulated_account = SimulatedAccountModel._default_manager.create(
                    user=instance,
                    account_name=f"{instance.username}_模拟仓",
                    account_type="simulated",
                    initial_capital=initial_capital,
                    current_cash=initial_capital,
                    current_market_value=0,
                    total_value=initial_capital,
                    auto_trading_enabled=True,  # 模拟仓默认启用自动交易
                )

                # 3. 更新 AccountProfileModel 关联
                # 获取或创建 AccountProfileModel
                profile, created = AccountProfileModel._default_manager.get_or_create(
                    user=instance,
                    defaults={
                        'display_name': instance.username,
                        'initial_capital': initial_capital,
                    }
                )
                profile.real_account = real_account
                profile.simulated_account = simulated_account
                profile.save()

                print(f"[OK] User {instance.username} accounts created")
        except Exception as e:
            print(f"[ERROR] Failed to create user accounts: {e}")
            # 事务会自动回滚

