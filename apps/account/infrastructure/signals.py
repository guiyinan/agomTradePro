"""
用户信号处理器

当用户创建或注册时，自动为用户创建实仓和模拟仓账户。
"""
import logging
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

logger = logging.getLogger(__name__)


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
        initial_capital = Decimal("1000000.00")

        with transaction.atomic():
            AccountProfileModel._default_manager.get_or_create(
                user=instance,
                defaults={
                    'display_name': instance.username,
                    'initial_capital': initial_capital,
                },
            )

            if not SimulatedAccountModel._default_manager.filter(
                user=instance,
                account_type="real",
            ).exists():
                SimulatedAccountModel._default_manager.create(
                    user=instance,
                    account_name=f"{instance.username}_实仓",
                    account_type="real",
                    initial_capital=Decimal("0"),
                    current_cash=Decimal("0"),
                    current_market_value=Decimal("0"),
                    total_value=Decimal("0"),
                    auto_trading_enabled=False,
                )

            if not SimulatedAccountModel._default_manager.filter(
                user=instance,
                account_type="simulated",
            ).exists():
                SimulatedAccountModel._default_manager.create(
                    user=instance,
                    account_name=f"{instance.username}_模拟仓",
                    account_type="simulated",
                    initial_capital=initial_capital,
                    current_cash=initial_capital,
                    current_market_value=Decimal("0"),
                    total_value=initial_capital,
                    auto_trading_enabled=True,
                )

        logger.info("Provisioned default accounts for user %s", instance.username)

