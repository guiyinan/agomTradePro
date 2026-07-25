"""Train a Qlib model through the canonical Alpha training task contract."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.alpha.application.tasks import qlib_train_model

_SUPPORTED_MODEL_TYPES = frozenset({"LGBModel", "LSTMModel", "GRUModel", "MLPModel"})


class Command(BaseCommand):
    """Submit or synchronously execute one governed Qlib training run."""

    help = "Train a Qlib model for Alpha signals"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register CLI arguments without duplicating runtime defaults."""

        parser.add_argument("--name", required=True, help="Model name")
        parser.add_argument(
            "--type",
            choices=sorted(_SUPPORTED_MODEL_TYPES),
            default="LGBModel",
            dest="model_type",
            help="Qlib model type",
        )
        parser.add_argument(
            "--universe",
            default=None,
            help="Universe override; omitted uses Config Center",
        )
        parser.add_argument("--start-date", dest="start_date")
        parser.add_argument("--end-date", dest="end_date")
        parser.add_argument("--feature-set-id", dest="feature_set_id")
        parser.add_argument("--label-id", dest="label_id")
        parser.add_argument(
            "--learning-rate",
            type=float,
            default=None,
            dest="learning_rate",
            help="Optional model learning-rate override",
        )
        parser.add_argument(
            "--epochs",
            type=int,
            default=None,
            help="Optional boosting rounds or neural training epochs",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Activate the model only after successful evaluation and persistence",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Deprecated; immutable artifacts cannot be overwritten",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="async_mode",
            help="Submit training to the qlib_train queue",
        )
        parser.add_argument(
            "--model-path",
            default=None,
            dest="model_path",
            help="Optional model-root override; omitted uses Config Center",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Build one config and route sync/async execution through the same task."""

        del args
        if options.get("force"):
            raise CommandError("--force 不再支持：模型 artifact 不可覆盖，请使用新的训练配置")

        model_name = str(options["name"]).strip()
        if not model_name:
            raise CommandError("--name 不能为空")
        model_type = str(options["model_type"])
        train_config = self._prepare_train_config(
            model_type=model_type,
            universe=options.get("universe"),
            start_date=options.get("start_date"),
            end_date=options.get("end_date"),
            feature_set_id=options.get("feature_set_id"),
            label_id=options.get("label_id"),
            learning_rate=options.get("learning_rate"),
            epochs=options.get("epochs"),
            activate=bool(options.get("activate")),
            model_path=options.get("model_path"),
        )

        self.stdout.write("Qlib 模型训练")
        self.stdout.write(f"  模型名称: {model_name}")
        self.stdout.write(f"  模型类型: {model_type}")
        self.stdout.write(f"  训练区间: {train_config['start_date']} ~ {train_config['end_date']}")

        if options.get("async_mode"):
            task = qlib_train_model.apply_async(
                kwargs={
                    "model_name": model_name,
                    "model_type": model_type,
                    "train_config": train_config,
                },
                queue="qlib_train",
            )
            self.stdout.write(self.style.SUCCESS(f"  ✓ 任务已提交: {task.id}"))
            return

        try:
            result = qlib_train_model.run(
                model_name=model_name,
                model_type=model_type,
                train_config=train_config,
            )
        except Exception as exc:
            raise CommandError(f"Qlib 模型训练失败: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("  ✓ 模型训练完成"))
        self.stdout.write(f"    Artifact Hash: {str(result['artifact_hash'])[:12]}...")
        self.stdout.write(f"    IC: {result.get('ic', 'N/A')}")
        self.stdout.write(f"    ICIR: {result.get('icir', 'N/A')}")

    @staticmethod
    def _prepare_train_config(
        *,
        model_type: str,
        universe: object,
        start_date: object,
        end_date: object,
        feature_set_id: object,
        label_id: object,
        learning_rate: object,
        epochs: object,
        activate: bool,
        model_path: object,
    ) -> dict[str, Any]:
        """Build the canonical task configuration with model-specific parameters."""

        if model_type not in _SUPPORTED_MODEL_TYPES:
            raise CommandError(f"不支持的模型类型: {model_type}")

        resolved_end = str(end_date or (timezone.now() - timedelta(days=1)).date().isoformat())
        resolved_start = str(
            start_date or (timezone.now() - timedelta(days=365)).date().isoformat()
        )
        model_params: dict[str, object] = {}
        if learning_rate is not None:
            if isinstance(learning_rate, bool) or not isinstance(
                learning_rate,
                (int, float, str),
            ):
                raise CommandError("--learning-rate 必须是数值")
            try:
                rate = float(learning_rate)
            except ValueError as exc:
                raise CommandError("--learning-rate 必须是数值") from exc
            if not isfinite(rate) or rate <= 0:
                raise CommandError("--learning-rate 必须大于 0")
            model_params["learning_rate" if model_type == "LGBModel" else "lr"] = rate
        if epochs is not None:
            if isinstance(epochs, bool) or not isinstance(epochs, (int, str)):
                raise CommandError("--epochs 必须是正整数")
            try:
                epoch_count = int(epochs)
            except ValueError as exc:
                raise CommandError("--epochs 必须是正整数") from exc
            if epoch_count <= 0:
                raise CommandError("--epochs 必须是正整数")
            model_params["num_boost_round" if model_type == "LGBModel" else "n_epochs"] = (
                epoch_count
            )

        config: dict[str, Any] = {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "activate": activate,
            "model_params": model_params,
        }
        for key, value in (
            ("universe", universe),
            ("feature_set_id", feature_set_id),
            ("label_id", label_id),
            ("model_path", model_path),
        ):
            normalized = str(value or "").strip()
            if normalized:
                config[key] = normalized
        return config
