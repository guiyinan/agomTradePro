"""Rollback an active Qlib model with atomic, fail-closed state transitions."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction
from django.db.models import CharField

from apps.alpha.infrastructure.models import QlibModelRegistryModel

ROLLBACK_ACTOR = "rollback_command"


def _model_field_max_length(field_name: str) -> int:
    """Read a bounded text limit from the registry schema truth source."""

    field = QlibModelRegistryModel._meta.get_field(field_name)
    if not isinstance(field, CharField) or field.max_length is None:
        raise RuntimeError(f"{field_name} must be a bounded text field")
    return field.max_length


MODEL_NAME_MAX_LENGTH = _model_field_max_length("model_name")
ARTIFACT_HASH_MAX_LENGTH = _model_field_max_length("artifact_hash")


class Command(BaseCommand):
    """Atomically activate an explicit or chronologically previous model version."""

    help = "Rollback to a previous Qlib model version"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register an explicit exclusive rollback target."""

        target = parser.add_mutually_exclusive_group()
        target.add_argument(
            "--to",
            type=str,
            dest="to_hash",
            help="Rollback to a specific artifact hash",
        )
        target.add_argument(
            "--prev",
            action="store_true",
            dest="prev",
            help="Rollback to the previous chronological version",
        )
        parser.add_argument(
            "--model-name",
            type=str,
            required=True,
            dest="model_name",
            help="Model name (required)",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Validate the requested transition and execute it atomically."""

        del args
        model_name = self._required_text(
            options.get("model_name"),
            option="--model-name",
            max_length=MODEL_NAME_MAX_LENGTH,
        )
        to_hash = self._optional_text(
            options.get("to_hash"),
            option="--to",
            max_length=ARTIFACT_HASH_MAX_LENGTH,
        )
        prev = options.get("prev", False)
        if not isinstance(prev, bool):
            raise CommandError("--prev must be a boolean")
        if to_hash is not None and prev:
            raise CommandError("--to and --prev are mutually exclusive")
        if to_hash is None and not prev:
            raise CommandError("exactly one of --to or --prev is required")

        self.stdout.write(f"回滚模型: {model_name}")
        if to_hash is not None:
            self._rollback_to_hash(model_name, to_hash)
            return
        self._rollback_to_prev(model_name)

    @staticmethod
    def _required_text(raw_value: object, *, option: str, max_length: int) -> str:
        """Return a trimmed bounded non-empty option value."""

        if not isinstance(raw_value, str) or not raw_value.strip():
            raise CommandError(f"{option} must be a non-empty string")
        value = raw_value.strip()
        if len(value) > max_length:
            raise CommandError(f"{option} must be at most {max_length} characters")
        return value

    @classmethod
    def _optional_text(
        cls,
        raw_value: object,
        *,
        option: str,
        max_length: int,
    ) -> str | None:
        """Return a validated optional string without truthy coercion."""

        if raw_value is None:
            return None
        return cls._required_text(raw_value, option=option, max_length=max_length)

    def _rollback_to_hash(self, model_name: str, artifact_hash: str) -> None:
        """Lock and atomically activate one explicit model version."""

        self.stdout.write(f"  回滚到: {artifact_hash[:8]}...")
        try:
            with transaction.atomic():
                target_model = QlibModelRegistryModel._default_manager.select_for_update().get(
                    model_name=model_name,
                    artifact_hash=artifact_hash,
                )
                self._activate_locked_target(target_model)
        except QlibModelRegistryModel.DoesNotExist:
            raise CommandError(f"模型不存在: {artifact_hash}") from None
        except DatabaseError as exc:
            raise CommandError(f"模型回滚失败: {type(exc).__name__}") from exc

    def _rollback_to_prev(self, model_name: str) -> None:
        """Lock the active model and atomically activate its previous version."""

        try:
            with transaction.atomic():
                current_active = (
                    QlibModelRegistryModel._default_manager.select_for_update()
                    .filter(model_name=model_name, is_active=True)
                    .first()
                )
                if current_active is None:
                    raise CommandError("没有激活的模型")

                previous_model = (
                    QlibModelRegistryModel._default_manager.select_for_update()
                    .filter(
                        model_name=model_name,
                        created_at__lt=current_active.created_at,
                    )
                    .order_by("-created_at", "-artifact_hash")
                    .first()
                )
                if previous_model is None:
                    raise CommandError("没有找到上一个版本")

                self.stdout.write(
                    self.style.SUCCESS(f"  上一个版本: {previous_model.artifact_hash[:8]}...")
                )
                self.stdout.write(f"    创建时间: {previous_model.created_at}")
                self._activate_locked_target(previous_model)
        except DatabaseError as exc:
            raise CommandError(f"模型回滚失败: {type(exc).__name__}") from exc

    def _activate_locked_target(self, target_model: QlibModelRegistryModel) -> None:
        """Activate a locked target and report the displaced global model."""

        if target_model.is_active:
            self.stdout.write(self.style.WARNING("  目标模型已经处于激活状态"))
            return

        current_active = (
            QlibModelRegistryModel._default_manager.select_for_update()
            .filter(is_active=True)
            .exclude(pk=target_model.pk)
            .first()
        )
        target_model.activate(activated_by=ROLLBACK_ACTOR)

        if current_active is not None:
            self.stdout.write(
                self.style.WARNING(
                    "  已取消激活: "
                    f"{current_active.model_name}@{current_active.artifact_hash[:8]}..."
                )
            )
        self.stdout.write(self.style.SUCCESS(f"  已回滚到: {target_model.artifact_hash[:8]}..."))

    def _list_versions(self, model_name: str) -> None:
        """List registered versions for operational diagnostics."""

        models = QlibModelRegistryModel._default_manager.filter(model_name=model_name).order_by(
            "-created_at", "-artifact_hash"
        )
        self.stdout.write("  版本列表:")
        for model in models:
            active_flag = " [ACTIVE]" if model.is_active else ""
            self.stdout.write(f"    {model.artifact_hash[:8]}... - {model.created_at}{active_flag}")
