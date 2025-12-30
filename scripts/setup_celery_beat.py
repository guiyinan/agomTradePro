"""
Celery Beat 定时任务配置脚本

自动配置常用的定时任务，避免手动在 Admin 中创建。
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from django_celery_beat.models import PeriodicTask, CrontabSchedule, IntervalSchedule
from django.db import transaction


def setup_periodic_tasks():
    """配置定时任务"""

    with transaction.atomic():
        # 1. 每日 00:00 同步宏观数据
        sync_crontab, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='0',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        sync_task, created = PeriodicTask.objects.get_or_create(
            task='apps.macro.application.tasks.sync_macro_data',
            defaults={
                'name': '每日同步宏观数据',
                'crontab': sync_crontab,
                'enabled': True,
                'args': '["akshare", null, 1]',  # source=akshare, indicator=None, days_back=1
            }
        )
        if created:
            print(f"✅ 创建任务: {sync_task.name}")
        else:
            print(f"⏭️  已存在: {sync_task.name}")

        # 2. 每日 00:30 计算 Regime
        regime_crontab, _ = CrontabSchedule.objects.get_or_create(
            minute='30',
            hour='0',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        regime_task, created = PeriodicTask.objects.get_or_create(
            task='apps.macro.application.tasks.calculate_regime',
            defaults={
                'name': '每日计算 Regime',
                'crontab': regime_crontab,
                'enabled': True,
                'args': '[null, true]',  # as_of_date=None, use_pit=True
            }
        )
        if created:
            print(f"✅ 创建任务: {regime_task.name}")
        else:
            print(f"⏭️  已存在: {regime_task.name}")

        # 3. 每 6 小时检查数据新鲜度
        freshness_interval, _ = IntervalSchedule.objects.get_or_create(
            every=6,
            period=IntervalSchedule.HOURS,
        )

        freshness_task, created = PeriodicTask.objects.get_or_create(
            task='apps.macro.application.tasks.check_data_freshness',
            defaults={
                'name': '检查数据新鲜度',
                'interval': freshness_interval,
                'enabled': True,
            }
        )
        if created:
            print(f"✅ 创建任务: {freshness_task.name}")
        else:
            print(f"⏭️  已存在: {freshness_task.name}")

        # 4. 每月 1 日 02:00 清理旧数据（可选，默认禁用）
        cleanup_crontab, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='2',
            day_of_week='*',
            day_of_month='1',
            month_of_year='*',
        )

        cleanup_task, created = PeriodicTask.objects.get_or_create(
            task='apps.macro.application.tasks.cleanup_old_data',
            defaults={
                'name': '每月清理旧数据',
                'crontab': cleanup_crontab,
                'enabled': False,  # 默认禁用
                'args': '[3650]',  # 保留 10 年
            }
        )
        if created:
            print(f"✅ 创建任务: {cleanup_task.name} (已禁用)")
        else:
            print(f"⏭️  已存在: {cleanup_task.name}")

    print("\n定时任务配置完成！")
    print("\n查看任务: python manage.py shell")
    print("  >>> from django_celery_beat.models import PeriodicTask")
    print("  >>> PeriodicTask.objects.all()")


if __name__ == '__main__':
    print("AgomSAAF Celery Beat 定时任务配置\n")
    print("=" * 50)
    setup_periodic_tasks()
    print("=" * 50)
