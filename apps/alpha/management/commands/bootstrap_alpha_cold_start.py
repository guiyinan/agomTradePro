from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from apps.alpha.application.tasks import _execute_qlib_prediction
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel


class Command(BaseCommand):
    help = "Bootstrap Alpha caches using real Qlib assets only"

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        trade_date = date.fromisoformat(options["trade_date"])
        universes = [item.strip() for item in options["universes"].split(",") if item.strip()]
        top_n = options["top_n"]
        overwrite = options["overwrite"]

        self.stdout.write(self.style.SUCCESS("Alpha cold-start bootstrap begin"))

        active_model = (
            QlibModelRegistryModel._default_manager.filter(is_active=True).first()
        )
        if not active_model:
            self.stdout.write(self.style.WARNING("Skip Alpha bootstrap: no active Qlib model"))
            return

        model_path = active_model.model_path
        if not model_path:
            self.stdout.write(self.style.WARNING("Skip Alpha bootstrap: active Qlib model has no model_path"))
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
                    self.style.WARNING(f"[skip] alpha:{universe_id} qlib bootstrap unavailable: {exc}")
                )
                continue

            if not scores_data:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"[skip] alpha:{universe_id} empty qlib result"))
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
            self.stdout.write(f"[apply] alpha:{universe_id} {action} qlib cache count={len(scores_data)}")

        self.stdout.write(self.style.SUCCESS(f"Alpha cold-start bootstrap complete: applied={applied}, skipped={skipped}"))
