"""
Management command to cleanup old operation logs.

Usage:
    python manage.py cleanup_operation_logs --days=90
    python manage.py cleanup_operation_logs --days=90 --dry-run
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.infrastructure.models import OperationLogModel


class Command(BaseCommand):
    help = 'Cleanup old operation logs from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=getattr(settings, 'AUDIT_RETENTION_DAYS', 90),
            help='Number of days to keep logs (default: 90)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of records to delete per batch (default: 1000)',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        batch_size = options['batch_size']

        cutoff_date = timezone.now() - timedelta(days=days)

        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Cleaning up operation logs older than {days} days "
            f"(before {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')})"
        )

        # 统计待删除记录数
        queryset = OperationLogModel._default_manager.filter(timestamp__lt=cutoff_date)
        total_to_delete = queryset.count()

        if total_to_delete == 0:
            self.stdout.write(self.style.SUCCESS('No logs to cleanup.'))
            return

        self.stdout.write(f"Found {total_to_delete} logs to cleanup.")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would delete {total_to_delete} logs."
                )
            )
            return

        # 分批删除
        deleted_total = 0
        while True:
            # 获取一批记录 ID
            log_ids = list(
                queryset.values_list('id', flat=True)[:batch_size]
            )

            if not log_ids:
                break

            # 删除这批记录
            deleted_count, _ = OperationLogModel._default_manager.filter(
                id__in=log_ids
            ).delete()

            deleted_total += deleted_count

            self.stdout.write(
                f"Deleted batch: {deleted_count} logs "
                f"(total: {deleted_total}/{total_to_delete})"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully deleted {deleted_total} logs."
            )
        )
