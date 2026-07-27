"""Initialize the database-governed Regime confidence configuration."""

from __future__ import annotations

import math
from typing import Any, Protocol, TypedDict, cast

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction

from apps.audit.infrastructure.models import ConfidenceConfigModel


class ConfidenceConfigSeed(TypedDict):
    """Validated values used to create or explicitly refresh one active row."""

    day_0_coefficient: float
    day_7_coefficient: float
    day_14_coefficient: float
    day_30_coefficient: float
    daily_data_bonus: float
    weekly_data_bonus: float
    daily_consistency_bonus: float
    base_confidence: float
    daily_persist_threshold: int
    hybrid_weight_daily: float
    hybrid_weight_monthly: float
    decay_threshold: float
    decay_penalty: float
    improvement_threshold: float
    improvement_bonus: float
    description: str


class _DefaultField(Protocol):
    """Narrow Django's field/relation metadata union at the schema boundary."""

    def get_default(self) -> object:
        """Return the configured schema default."""


_SEED_FIELD_NAMES: tuple[str, ...] = (
    "day_0_coefficient",
    "day_7_coefficient",
    "day_14_coefficient",
    "day_30_coefficient",
    "daily_data_bonus",
    "weekly_data_bonus",
    "daily_consistency_bonus",
    "base_confidence",
    "daily_persist_threshold",
    "hybrid_weight_daily",
    "hybrid_weight_monthly",
    "decay_threshold",
    "decay_penalty",
    "improvement_threshold",
    "improvement_bonus",
    "description",
)


def _field_default(field_name: str) -> object:
    """Read one bootstrap value from the ORM schema default source."""

    field = cast(_DefaultField, ConfidenceConfigModel._meta.get_field(field_name))
    value: object = field.get_default()
    return value


def _bounded_float(
    value: object,
    *,
    field_name: str,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    """Narrow one finite numeric model default into its governed range."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError(f"Invalid model default for {field_name}")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise CommandError(f"Invalid model default for {field_name}")
    return result


def _build_default_config() -> ConfidenceConfigSeed:
    """Build and cross-validate the seed from model field defaults."""

    day_0 = _bounded_float(_field_default("day_0_coefficient"), field_name="day_0_coefficient")
    day_7 = _bounded_float(_field_default("day_7_coefficient"), field_name="day_7_coefficient")
    day_14 = _bounded_float(_field_default("day_14_coefficient"), field_name="day_14_coefficient")
    day_30 = _bounded_float(_field_default("day_30_coefficient"), field_name="day_30_coefficient")
    if not day_0 >= day_7 >= day_14 >= day_30:
        raise CommandError("Confidence freshness defaults must be non-increasing")

    daily_weight = _bounded_float(
        _field_default("hybrid_weight_daily"), field_name="hybrid_weight_daily"
    )
    monthly_weight = _bounded_float(
        _field_default("hybrid_weight_monthly"), field_name="hybrid_weight_monthly"
    )
    if not math.isclose(daily_weight + monthly_weight, 1.0, abs_tol=1e-9):
        raise CommandError("Confidence hybrid weight defaults must sum to one")

    persist_default = _field_default("daily_persist_threshold")
    if (
        isinstance(persist_default, bool)
        or not isinstance(persist_default, int)
        or persist_default <= 0
    ):
        raise CommandError("Invalid model default for daily_persist_threshold")
    description_default = _field_default("description")
    if not isinstance(description_default, str):
        raise CommandError("Invalid model default for description")

    improvement_bonus = _bounded_float(
        _field_default("improvement_bonus"),
        field_name="improvement_bonus",
        minimum=1.0,
        maximum=10.0,
    )
    return ConfidenceConfigSeed(
        day_0_coefficient=day_0,
        day_7_coefficient=day_7,
        day_14_coefficient=day_14,
        day_30_coefficient=day_30,
        daily_data_bonus=_bounded_float(
            _field_default("daily_data_bonus"), field_name="daily_data_bonus"
        ),
        weekly_data_bonus=_bounded_float(
            _field_default("weekly_data_bonus"), field_name="weekly_data_bonus"
        ),
        daily_consistency_bonus=_bounded_float(
            _field_default("daily_consistency_bonus"),
            field_name="daily_consistency_bonus",
        ),
        base_confidence=_bounded_float(
            _field_default("base_confidence"), field_name="base_confidence"
        ),
        daily_persist_threshold=persist_default,
        hybrid_weight_daily=daily_weight,
        hybrid_weight_monthly=monthly_weight,
        decay_threshold=_bounded_float(
            _field_default("decay_threshold"), field_name="decay_threshold"
        ),
        decay_penalty=_bounded_float(_field_default("decay_penalty"), field_name="decay_penalty"),
        improvement_threshold=_bounded_float(
            _field_default("improvement_threshold"),
            field_name="improvement_threshold",
        ),
        improvement_bonus=improvement_bonus,
        description=description_default,
    )


class Command(BaseCommand):
    """Create missing configuration or explicitly refresh the sole active row."""

    help = "Initialize default confidence configuration"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the explicit overwrite option."""

        parser.add_argument(
            "--refresh",
            action="store_true",
            dest="refresh",
            help="Refresh existing configuration (update instead of skip)",
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Apply one validated seed atomically without hiding failures."""

        del args
        refresh_value = options.get("refresh", False)
        if not isinstance(refresh_value, bool):
            raise CommandError("refresh must be a boolean")
        defaults = _build_default_config()
        seed_values: dict[str, object] = dict(defaults)

        try:
            with transaction.atomic():
                active_rows = list(
                    ConfidenceConfigModel._default_manager.select_for_update()
                    .filter(is_active=True)
                    .order_by("pk")[:2]
                )
                if len(active_rows) > 1:
                    raise CommandError("Multiple active confidence configurations found")
                if active_rows:
                    config = active_rows[0]
                    action = "preserved"
                    if refresh_value:
                        for field_name in _SEED_FIELD_NAMES:
                            setattr(config, field_name, seed_values[field_name])
                        config.full_clean()
                        config.save(update_fields=[*_SEED_FIELD_NAMES, "updated_at"])
                        action = "updated"
                else:
                    config = ConfidenceConfigModel(**defaults)
                    config.full_clean()
                    config.save()
                    action = "created"
        except CommandError:
            raise
        except (DatabaseError, TypeError, ValueError, ValidationError) as exc:
            raise CommandError(
                f"Confidence configuration initialization failed ({type(exc).__name__})"
            ) from exc

        self.stdout.write("\n" + "=" * 50)
        if action == "created":
            self.stdout.write(self.style.SUCCESS("Created confidence configuration"))
        elif action == "updated":
            self.stdout.write(self.style.WARNING("Updated existing confidence configuration"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Confidence configuration already exists (use --refresh to update)"
                )
            )
        self._display_config(config)
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("Confidence configuration initialized successfully."))
        self.stdout.write(
            'Run "python manage.py init_confidence_config --refresh" to update existing config.'
        )
        self.stdout.write("=" * 50)

    def _display_config(self, config: ConfidenceConfigModel) -> None:
        """Write the persisted configuration summary after transaction success."""

        self.stdout.write("\n配置详情:")
        self.stdout.write("  新鲜度系数:")
        self.stdout.write(f"    发布当天: {config.day_0_coefficient}")
        self.stdout.write(f"    发布1周: {config.day_7_coefficient}")
        self.stdout.write(f"    发布2周: {config.day_14_coefficient}")
        self.stdout.write(f"    发布1月: {config.day_30_coefficient}")
        self.stdout.write("  数据加成:")
        self.stdout.write(f"    日度加成: {config.daily_data_bonus}")
        self.stdout.write(f"    周度加成: {config.weekly_data_bonus}")
        self.stdout.write(f"    一致性加成: {config.daily_consistency_bonus}")
        self.stdout.write(f"  基础置信度: {config.base_confidence}")
        self.stdout.write("  冲突解决:")
        self.stdout.write(f"    日度持续阈值: {config.daily_persist_threshold}天")
        self.stdout.write(
            f"    混合权重(日度/月度): "
            f"{config.hybrid_weight_daily}/{config.hybrid_weight_monthly}"
        )
