"""
Windows 兼容的 Celery Worker 管理命令

Celery 在 Windows 上不支持 prefork pool（多进程），本命令自动使用 solo pool。

使用方式:
    python manage.py celery_worker_windows
    python manage.py celery_worker_windows --loglevel=debug
    python manage.py celery_worker_windows --queues=celery,qlib_infer,qlib_train
"""

import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run Celery worker with Windows-compatible settings (solo pool)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loglevel',
            type=str,
            default='info',
            help='Logging level (debug, info, warning, error, critical)',
        )
        parser.add_argument(
            '--concurrency',
            type=int,
            default=1,
            help='Concurrency level (default: 1 for solo pool)',
        )
        parser.add_argument(
            '-Q',
            '--queues',
            type=str,
            default=None,
            help='Comma-separated Celery queues to consume, for example: celery,qlib_infer,qlib_train',
        )
        parser.add_argument(
            '-n',
            '--hostname',
            type=str,
            default=None,
            help='Optional Celery worker hostname, for example: readiness@%%h',
        )

    def handle(self, *args, **options):
        # 检测操作系统
        is_windows = sys.platform == 'win32'

        if is_windows:
            self.stdout.write(self.style.WARNING('Running on Windows - using solo pool'))
            self.stdout.write(self.style.WARNING('Note: solo pool does not support multiple processes'))
            self.stdout.write(self.style.WARNING('For production, use Linux with prefork pool'))
        else:
            self.stdout.write(self.style.SUCCESS('Running on Linux - using prefork pool'))

        # 导入 Celery 应用
        from core.celery import app

        # 启动 worker
        loglevel = options['loglevel']
        queues = options.get('queues')
        hostname = options.get('hostname')

        if is_windows:
            # Windows: 使用 solo pool
            self.stdout.write(
                self.style.SUCCESS(
                    f'Starting Celery worker with solo pool (loglevel={loglevel})'
                )
            )

            # 使用 solo pool 启动
            argv = [
                'worker',
                '--loglevel=' + loglevel,
                '--pool=solo',
                '--concurrency=' + str(options['concurrency']),
            ]
        else:
            # Linux: 使用 prefork pool
            self.stdout.write(
                self.style.SUCCESS(
                    f'Starting Celery worker with prefork pool (loglevel={loglevel})'
                )
            )

            argv = [
                'worker',
                '--loglevel=' + loglevel,
                '--pool=prefork',
                '--concurrency=' + str(options['concurrency']),
            ]

        if queues:
            self.stdout.write(self.style.WARNING(f'Queues: {queues}'))
            argv.append('--queues=' + queues)

        if hostname:
            self.stdout.write(self.style.WARNING(f'Hostname: {hostname}'))
            argv.append('--hostname=' + hostname)

        app.worker_main(argv)
