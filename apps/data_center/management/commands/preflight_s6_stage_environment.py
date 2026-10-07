"""Run the candidate-side, read-only portion of the S6 environment preflight."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from apps.data_center.application.full_market_publication_preflight import (
    CHECK_PROVIDER_POLICY_AND_ROUTES,
)
from apps.data_center.full_market_publication_preflight_composition import (
    build_full_market_publication_preflight_use_case,
)
from apps.data_center.infrastructure.akshare_financial_slice_rehearsal import (
    _require_akshare_financial_egress_routes,
    _select_provider,
)
from apps.data_center.infrastructure.akshare_financial_slice_sync import (
    load_akshare_financial_slice_sync_budget,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.rehearsal_identity import (
    load_rehearsal_identities,
    verify_configured_rehearsal_identities,
)
from shared.release_rehearsal_stage_environment import SCHEMA

_MODEL_MARKET_STAGES = (
    "provider_probe",
    "full_universe_capacity",
    "production_policy_parity",
)
_FINANCIAL_STAGES = ("akshare_financial_slice",)
_DATABASE_STAGES = (
    "isolated_postgresql_write",
    "akshare_financial_slice",
)
_STOPPED_SCHEDULES = (
    "full-market-current-publications",
    "financial-current-publication-refresh",
)


class Command(BaseCommand):
    """Report all candidate-side gaps while performing no writes or provider calls."""

    help = "Run the aggregate read-only S6 stage environment preflight."

    def add_arguments(self, parser: Any) -> None:
        """Register exact frozen-input paths only."""

        parser.add_argument("--provider-settings-json", type=Path, required=True)
        parser.add_argument("--provider-identities", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)

    def handle(self, *args: object, **options: Any) -> None:
        """Evaluate every dynamic category and write only stable issue metadata."""

        del args
        settings_path = options.get("provider_settings_json")
        identities_path = options.get("provider_identities")
        output_path = options.get("output")
        if (
            not isinstance(settings_path, Path)
            or not isinstance(identities_path, Path)
            or not isinstance(output_path, Path)
        ):
            raise CommandError("REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_INPUT_INVALID")
        issues: list[dict[str, object]] = []
        self._check_model_market_routes(settings_path, issues)
        self._check_financial_contract(identities_path, issues)
        self._check_clock(issues)
        self._check_external_state(issues)
        raw = (
            json.dumps({"schema": SCHEMA, "issues": issues}, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        if output_path.is_symlink() or output_path.exists() or not output_path.parent.is_dir():
            raise CommandError("REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_INPUT_INVALID")
        try:
            with output_path.open("xb") as stream:
                stream.write(raw.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise CommandError("REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_INPUT_INVALID") from exc

    @staticmethod
    def _append(
        issues: list[dict[str, object]], category: str, code: str, stages: tuple[str, ...]
    ) -> None:
        issues.append({"category": category, "code": code, "stages": list(stages)})

    def _check_model_market_routes(
        self, settings_path: Path, issues: list[dict[str, object]]
    ) -> None:
        try:
            if settings_path.is_symlink() or not settings_path.is_file():
                raise ValueError
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
            report = build_full_market_publication_preflight_use_case(
                provider_settings_override={str(key): value for key, value in raw.items()}
            ).execute(checks=(CHECK_PROVIDER_POLICY_AND_ROUTES,))
            if report.outcome != "pass":
                raise ValueError
        except Exception:
            self._append(
                issues,
                "network_egress",
                "REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID",
                _MODEL_MARKET_STAGES,
            )

    def _check_financial_contract(
        self, identities_path: Path, issues: list[dict[str, object]]
    ) -> None:
        provider_available = False
        try:
            identities = verify_configured_rehearsal_identities(
                load_rehearsal_identities(identities_path)
            )
            provider, _identity = _select_provider(identities)
            provider_available = True
        except Exception:
            self._append(
                issues,
                "identity_and_secrets",
                "REHEARSAL_STAGE_PROVIDER_IDENTITY_INVALID",
                _FINANCIAL_STAGES,
            )
        if provider_available:
            try:
                _require_akshare_financial_egress_routes(provider)
            except Exception:
                self._append(
                    issues,
                    "network_egress",
                    "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED",
                    _FINANCIAL_STAGES,
                )
        try:
            if resolve_financial_response_artifact_config() is None:
                raise ValueError
        except Exception:
            self._append(
                issues,
                "identity_and_secrets",
                "REHEARSAL_STAGE_FINANCIAL_SECRET_CONTRACT_INVALID",
                _FINANCIAL_STAGES,
            )
        try:
            budget = load_akshare_financial_slice_sync_budget()
            if (
                budget is None
                or budget.max_slices != 1
                or budget.provider_requests_per_slice != 2
                or budget.max_provider_requests != 2
            ):
                raise ValueError
        except Exception:
            self._append(
                issues,
                "external_state",
                "REHEARSAL_STAGE_FINANCIAL_BUDGET_INVALID",
                _FINANCIAL_STAGES,
            )

    def _check_clock(self, issues: list[dict[str, object]]) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT clock_timestamp()")
                row = cursor.fetchone()
            observed = row[0] if row else None
            now = timezone.now()
            if (
                observed is None
                or observed.tzinfo is None
                or abs(observed - now) > timedelta(seconds=5)
            ):
                raise ValueError
        except Exception:
            self._append(
                issues,
                "resources_and_time",
                "REHEARSAL_STAGE_DATABASE_CLOCK_INVALID",
                _DATABASE_STAGES,
            )

    def _check_external_state(self, issues: list[dict[str, object]]) -> None:
        try:
            rows = tuple(
                PeriodicTask._default_manager.filter(name__in=_STOPPED_SCHEDULES)
                .order_by("name")
                .values_list("name", "enabled")
            )
            if len(rows) != len(_STOPPED_SCHEDULES) or any(enabled for _name, enabled in rows):
                raise ValueError
        except Exception:
            self._append(
                issues,
                "external_state",
                "REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID",
                ("production_policy_parity", "akshare_financial_slice"),
            )
