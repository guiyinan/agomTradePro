from __future__ import annotations

import re
from argparse import ArgumentParser
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.alpha.application.tasks import _execute_qlib_prediction
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel

_UNIVERSE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class Command(BaseCommand):
    help = "Bootstrap Alpha caches using real Qlib assets only"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--universes",
            default="csi300",
            help="Comma-separated universes to bootstrap (default: csi300).",
        )
        parser.add_argument(
            "--trade-date",
            default=date.today().isoformat(),
            help="Trade date to bootstrap in ISO format (default: today).",
        )
        parser.add_argument(
            "--top-n",
            type=int,
            default=30,
            help="Top N scores to generate per universe (default: 30).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing same-day Qlib cache.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw_trade_date = options.get("trade_date")
        raw_universes = options.get("universes")
        top_n = options.get("top_n")
        overwrite = options.get("overwrite")
        if not isinstance(raw_trade_date, str) or len(raw_trade_date) != 10:
            raise CommandError("--trade-date must use YYYY-MM-DD")
        try:
            trade_date = date.fromisoformat(raw_trade_date)
        except ValueError as exc:
            raise CommandError("--trade-date must use YYYY-MM-DD") from exc
        if not isinstance(raw_universes, str):
            raise CommandError("--universes must be a comma-separated string")
        universes = [item.strip() for item in raw_universes.split(",") if item.strip()]
        if (
            not universes
            or len(universes) > 20
            or any(not _UNIVERSE_PATTERN.fullmatch(item) for item in universes)
        ):
            raise CommandError("--universes contains an invalid identifier")
        if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 1000:
            raise CommandError("--top-n must be between 1 and 1000")
        if not isinstance(overwrite, bool):
            raise CommandError("--overwrite must be boolean")

        self.stdout.write(self.style.SUCCESS("Alpha cold-start bootstrap begin"))

        active_model = QlibModelRegistryModel._default_manager.filter(is_active=True).first()
        if not active_model:
            self.stdout.write(self.style.WARNING("Skip Alpha bootstrap: no active Qlib model"))
            return

        model_path = active_model.model_path
        if (
            not isinstance(model_path, str)
            or not model_path
            or len(model_path) > 500
            or "://" in model_path
            or any(ord(character) < 32 for character in model_path)
        ):
            self.stdout.write(
                self.style.WARNING("Skip Alpha bootstrap: active Qlib model has no model_path")
            )
            return

        applied = 0
        skipped = 0

        for universe_id in universes:
            existing = AlphaScoreCacheModel._default_manager.filter(
                universe_id=universe_id,
                intended_trade_date=trade_date,
                provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
                model_artifact_hash=active_model.artifact_hash,
            ).exists()
            if existing and not overwrite:
                skipped += 1
                self.stdout.write(f"[skip] alpha:{universe_id} existing qlib cache")
                continue

            try:
                scores_data = _execute_qlib_prediction(
                    active_model=active_model,
                    universe_id=universe_id,
                    trade_date=trade_date,
                    top_n=top_n,
                )
            except Exception as exc:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[skip] alpha:{universe_id} qlib bootstrap unavailable "
                        f"({type(exc).__name__})"
                    )
                )
                continue

            if not scores_data:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(f"[skip] alpha:{universe_id} empty qlib result")
                )
                continue

            _, created = AlphaScoreCacheModel._default_manager.update_or_create(
                universe_id=universe_id,
                intended_trade_date=trade_date,
                provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
                model_artifact_hash=active_model.artifact_hash,
                defaults={
                    "asof_date": trade_date,
                    "model_id": active_model.model_name,
                    "model_artifact_hash": active_model.artifact_hash,
                    "feature_set_id": active_model.feature_set_id,
                    "label_id": active_model.label_id,
                    "data_version": active_model.data_version,
                    "scores": scores_data,
                    "status": AlphaScoreCacheModel.STATUS_AVAILABLE,
                    "metrics_snapshot": {
                        "bootstrap_source": "bootstrap_alpha_cold_start",
                        "count": len(scores_data),
                    },
                },
            )
            applied += 1
            action = "created" if created else "updated"
            self.stdout.write(
                f"[apply] alpha:{universe_id} {action} qlib cache count={len(scores_data)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Alpha cold-start bootstrap complete: applied={applied}, skipped={skipped}"
            )
        )
