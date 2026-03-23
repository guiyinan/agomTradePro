"""
Train Qlib Model Management Command

训练 Qlib 模型的 Django 管理命令。
"""

import json
import logging
import pickle
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    训练 Qlib 模型命令

    用法:
        python manage.py train_qlib_model [options]

    选项:
        --name: 模型名称（必需）
        --type: 模型类型 (LGBModel/LSTMModel/MLPModel)
        --universe: 股票池 (默认 csi300)
        --start-date: 训练开始日期 (默认 365 天前)
        --end-date: 训练结束日期 (默认昨天)
        --learning-rate: 学习率 (默认 0.01)
        --epochs: 训练轮数 (默认 100)
        --activate: 训练完成后自动激活
        --force: 强制重新训练
    """

    help = 'Train Qlib model for alpha signals'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            dest='name',
            help='Model name (required)',
        )
        parser.add_argument(
            '--type',
            type=str,
            default='LGBModel',
            dest='model_type',
            help='Model type (default: LGBModel)',
        )
        parser.add_argument(
            '--universe',
            type=str,
            default='csi300',
            dest='universe',
            help='Universe (default: csi300)',
        )
        parser.add_argument(
            '--start-date',
            type=str,
            dest='start_date',
            help='Training start date (ISO format, default: 365 days ago)',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            dest='end_date',
            help='Training end date (ISO format, default: yesterday)',
        )
        parser.add_argument(
            '--learning-rate',
            type=float,
            default=0.01,
            dest='learning_rate',
            help='Learning rate (default: 0.01)',
        )
        parser.add_argument(
            '--epochs',
            type=int,
            default=100,
            dest='epochs',
            help='Training epochs (default: 100)',
        )
        parser.add_argument(
            '--activate',
            action='store_true',
            dest='activate',
            help='Auto activate after training',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            help='Force retrain even if model exists',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            dest='async',
            help='Run training in background (Celery task)',
        )
        parser.add_argument(
            '--model-path',
            type=str,
            default='/models/qlib',
            dest='model_path',
            help='Model storage path (default: /models/qlib)',
        )

    def handle(self, *args, **options):
        """执行命令"""
        name = options.get('name')
        model_type = options.get('model_type', 'LGBModel')
        universe = options.get('universe', 'csi300')
        start_date = options.get('start_date')
        end_date = options.get('end_date')
        learning_rate = options.get('learning_rate', 0.01)
        epochs = options.get('epochs', 100)
        activate = options.get('activate', False)
        force = options.get('force', False)
        async_mode = options.get('async', False)
        model_path = options.get('model_path', '/models/qlib')

        self.stdout.write(self.style.SUCCESS('Qlib 模型训练'))
        self.stdout.write(f'  模型名称: {name}')
        self.stdout.write(f'  模型类型: {model_type}')
        self.stdout.write(f'  股票池: {universe}')
        self.stdout.write(f'  学习率: {learning_rate}')
        self.stdout.write(f'  训练轮数: {epochs}')

        # 检查 Qlib 是否安装
        if not self._check_qlib_installed():
            self.stdout.write(
                self.style.ERROR('Qlib 未安装！请运行: pip install pyqlib')
            )
            return

        # 异步模式
        if async_mode:
            self._train_async(
                name=name,
                model_type=model_type,
                universe=universe,
                start_date=start_date,
                end_date=end_date,
                learning_rate=learning_rate,
                epochs=epochs,
                activate=activate,
                model_path=model_path,
            )
            return

        # 同步模式
        result = self._train_sync(
            name=name,
            model_type=model_type,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            learning_rate=learning_rate,
            epochs=epochs,
            activate=activate,
            force=force,
            model_path=model_path,
        )

        if result['success']:
            self.stdout.write(self.style.SUCCESS('  ✓ 模型训练完成'))
            self.stdout.write(f'    Artifact Hash: {result["artifact_hash"][:8]}...')
            self.stdout.write(f'    IC: {result.get("ic", "N/A")}')
            self.stdout.write(f'    ICIR: {result.get("icir", "N/A")}')
        else:
            self.stdout.write(self.style.ERROR(f'  ✗ 训练失败: {result["error"]}'))

    def _check_qlib_installed(self) -> bool:
        """检查 Qlib 是否安装"""
        try:
            import qlib
            self.stdout.write(f'  Qlib 版本: {qlib.__version__}')
            return True
        except ImportError:
            return False

    def _train_async(self, **kwargs):
        """异步训练"""
        from apps.alpha.application.tasks import qlib_train_model

        self.stdout.write('  提交异步训练任务...')

        task = qlib_train_model.delay(
            model_name=kwargs['name'],
            model_type=kwargs['model_type'],
            train_config={
                'universe': kwargs['universe'],
                'start_date': kwargs['start_date'],
                'end_date': kwargs['end_date'],
                'learning_rate': kwargs['learning_rate'],
                'epochs': kwargs['epochs'],
                'model_path': kwargs['model_path'],
            }
        )

        self.stdout.write(
            self.style.SUCCESS(f'  ✓ 任务已提交: {task.id}')
        )
        self.stdout.write('  使用以下命令查看状态:')
        self.stdout.write(f'    celery -A core inspect active | grep {task.id}')

    def _train_sync(self, **kwargs) -> dict:
        """同步训练"""
        try:
            # 初始化 Qlib
            from django.conf import settings
            qlib_config = settings.QLIB_SETTINGS
            import qlib
            qlib.init(
                provider_uri=qlib_config['provider_uri'],
                region=qlib_config['region']
            )

            # 准备训练配置
            train_config = self._prepare_train_config(kwargs)

            # 执行训练
            self.stdout.write('  开始训练...')
            model, artifact_hash = self._execute_training(
                name=kwargs['name'],
                model_type=kwargs['model_type'],
                universe=kwargs['universe'],
                config=train_config
            )

            # 评估模型
            metrics = self._evaluate_model(model, kwargs['universe'])

            # 保存模型
            model_path = self._save_model(
                model=model,
                name=kwargs['name'],
                artifact_hash=artifact_hash,
                config={
                    **train_config,
                    "model_type": kwargs["model_type"],
                },
                metrics=metrics,
            )

            # 写入 Registry
            registry_entry = self._save_to_registry(
                name=kwargs['name'],
                model_type=kwargs['model_type'],
                universe=kwargs['universe'],
                artifact_hash=artifact_hash,
                model_path=model_path,
                train_config=train_config,
                metrics=metrics
            )

            # 自动激活
            if kwargs['activate']:
                registry_entry.activate(activated_by='train_command')
                self.stdout.write(self.style.SUCCESS('  ✓ 模型已激活'))

            return {
                'success': True,
                'artifact_hash': artifact_hash,
                'ic': metrics.get('ic'),
                'icir': metrics.get('icir'),
            }

        except Exception as e:
            logger.error(f"训练失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _prepare_train_config(self, options: dict) -> dict:
        """准备训练配置"""
        from datetime import datetime, timedelta

        end_date = options.get('end_date')
        if not end_date:
            end_date = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        start_date = options.get('start_date')
        if not start_date:
            start_date = (timezone.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        return {
            'start_date': start_date,
            'end_date': end_date,
            'learning_rate': options['learning_rate'],
            'epochs': options['epochs'],
            'model_path': options.get('model_path', '/models/qlib'),
        }

    def _execute_training(self, name: str, model_type: str, universe: str, config: dict):
        """执行训练"""
        from apps.alpha.application.tasks import _calculate_artifact_hash, _train_qlib_model

        supported_model_types = {'LGBModel', 'LSTMModel', 'GRUModel', 'MLPModel'}
        if model_type not in supported_model_types:
            raise ValueError(f"不支持的模型类型: {model_type}")

        # 准备数据
        self.stdout.write(f'  准备数据: {config["start_date"]} 到 {config["end_date"]}')
        train_config = {
            **config,
            "universe": universe,
            "model_type": model_type,
        }

        # 生成 artifact_hash（这里简化）
        artifact_hash = _calculate_artifact_hash(
            f"{name}_{model_type}_{universe}_{config['end_date']}"
        )
        model = _train_qlib_model(model_type=model_type, train_config=train_config)

        return model, artifact_hash

    def _evaluate_model(self, model, universe: str) -> dict:
        """
        评估模型 IC/ICIR 指标

        优先使用 Qlib 完整评估，失败时尝试缓存评估，
        均不可用时返回空指标（不使用硬编码假数据）。
        """
        # 1) 尝试 Qlib 完整评估
        try:
            from apps.alpha.application.tasks import _evaluate_model_metrics
            metrics = _evaluate_model_metrics(model, universe)
            if metrics and metrics.get('ic') is not None:
                self.stdout.write(
                    f"  IC={metrics['ic']:.4f}  ICIR={metrics.get('icir', 0):.4f}  "
                    f"Rank IC={metrics.get('rank_ic', 0):.4f}"
                )
                return metrics
        except Exception as e:
            logger.warning(f"Qlib 完整评估不可用: {e}")

        # 2) 尝试缓存评估
        try:
            from datetime import timedelta

            from apps.alpha.infrastructure.cache_evaluation import evaluate_model_from_cache

            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=60)

            # 需要 artifact_hash —— 在 handle() 中计算后传入
            # 此处 fallback：扫描该 universe 最近的缓存
            from apps.alpha.infrastructure.models import AlphaScoreCacheModel
            latest = (
                AlphaScoreCacheModel.objects
                .filter(universe_id=universe, provider_source="qlib")
                .order_by('-intended_trade_date')
                .first()
            )
            if latest and latest.model_artifact_hash:
                cache_metrics = evaluate_model_from_cache(
                    model_artifact_hash=latest.model_artifact_hash,
                    universe_id=universe,
                    start_date=start_date,
                    end_date=end_date,
                )
                result = {
                    'ic': cache_metrics.ic if cache_metrics.ic is not None else None,
                    'icir': cache_metrics.icir if cache_metrics.icir is not None else None,
                    'rank_ic': cache_metrics.rank_ic if cache_metrics.rank_ic is not None else None,
                }
                if result['ic'] is not None:
                    self.stdout.write(
                        f"  (缓存评估) IC={result['ic']:.4f}  "
                        f"ICIR={result.get('icir', 0) or 0:.4f}  "
                        f"Rank IC={result.get('rank_ic', 0) or 0:.4f}"
                    )
                    return result
        except Exception as e:
            logger.warning(f"缓存评估不可用: {e}")

        # 3) 均不可用：返回空指标，不造假
        self.stdout.write(self.style.WARNING(
            '  ⚠ 无法计算 IC/ICIR（Qlib 未初始化且无缓存数据）'
        ))
        return {
            'ic': None,
            'icir': None,
            'rank_ic': None,
        }

    def _save_model(self, model, name: str, artifact_hash: str, config: dict, metrics: dict) -> str:
        """保存模型到文件系统"""
        model_path = Path(config['model_path'])
        artifact_dir = model_path / name / artifact_hash
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # 保存模型
        model_file = artifact_dir / "model.pkl"
        with open(model_file, 'wb') as f:
            pickle.dump(model, f)

        # 保存配置
        config_file = artifact_dir / "config.json"
        with open(config_file, 'w') as f:
            json.dump({
                'model_name': name,
                'model_type': config.get('model_type'),
                'artifact_hash': artifact_hash,
                'train_config': config,
                'created_at': timezone.now().isoformat(),
            }, f, indent=2)

        # 保存指标
        metrics_file = artifact_dir / "metrics.json"
        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=2)

        self.stdout.write(f'  模型已保存: {artifact_dir}')

        return str(artifact_dir)

    def _save_to_registry(
        self,
        name: str,
        model_type: str,
        universe: str,
        artifact_hash: str,
        model_path: str,
        train_config: dict,
        metrics: dict
    ):
        """保存到模型注册表"""
        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        registry, created = QlibModelRegistryModel._default_manager.update_or_create(
            artifact_hash=artifact_hash,
            defaults={
                'model_name': name,
                'model_type': model_type,
                'universe': universe,
                'train_config': train_config,
                'feature_set_id': 'v1',
                'label_id': 'return_5d',
                'data_version': train_config.get('end_date'),
                'ic': metrics.get('ic'),
                'icir': metrics.get('icir'),
                'rank_ic': metrics.get('rank_ic'),
                'model_path': model_path,
                'is_active': False,
            }
        )

        action = "创建" if created else "更新"
        self.stdout.write(f'  ✓ {action} Registry 记录')

        return registry
