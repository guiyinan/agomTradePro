"""
用户信号处理器

当用户创建或注册时，自动为用户创建实仓和模拟仓账户。
"""

import logging
import os
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.account.application.simulated_trading_gateway import (
    provision_default_trading_accounts,
)
from apps.account.infrastructure.models import AccountProfileModel

logger = logging.getLogger(__name__)


def _user_provisioning_signals_disabled() -> bool:
    """Return whether a controlled fixture import disabled provisioning."""

    return os.environ.get(
        "AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS",
        "",
    ).strip().lower() in {"1", "true", "yes"}


@receiver(post_save, sender=User)
def create_user_accounts(
    sender: type[User],
    instance: User,
    created: bool,
    **kwargs: object,
) -> None:
    """
    当用户创建时，自动创建实仓和模拟仓

    Args:
        sender: User模型
        instance: 用户实例
        created: 是否为新创建
    """
    if created and not _user_provisioning_signals_disabled():
        initial_capital = Decimal("1000000.00")

        with transaction.atomic():
            AccountProfileModel._default_manager.get_or_create(
                user=instance,
                defaults={
                    "display_name": instance.username,
                    "initial_capital": initial_capital,
                },
            )

            provision_default_trading_accounts(instance, initial_capital)

        logger.info("Provisioned default accounts for user %s", instance.username)
