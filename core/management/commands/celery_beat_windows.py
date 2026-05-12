"""
Windows 兼容的 Celery Beat 管理命令

使用方式:
    python manage.py celery_beat_windows
    python manage.py celery_beat_windows --loglevel=debug
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run Celery beat scheduler (Windows-compatible)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loglevel',
            type=str,
            default='info',
            help='Logging level (debug, info, warning, error, critical)',
        )
        parser.add_argument(
            '--scheduler',
            type=str,
            default='django_celery_beat.schedulers:DatabaseScheduler',
            help='Scheduler class to use',
        )

    def handle(self, *args, **options):
        from core.celery import app

        loglevel = options['loglevel']
        scheduler = options['scheduler']

        self.stdout.write(self.style.SUCCESS(f'Starting Celery beat scheduler (loglevel={loglevel})'))
        self.stdout.write(self.style.WARNING(f'Scheduler: {scheduler}'))
        self.stdout.write(self.style.WARNING('Press Ctrl+C to stop'))

        # 启动 beat
        app.worker_main([
            'beat',
            '--loglevel=' + loglevel,
            '--scheduler=' + scheduler,
        ])
