"""Replay a failed E1's exact retained Main and Balance captures with zero provider traffic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction
from django.utils.timezone import now

from apps.data_center.application.financial_e1_capture_use_case import FinancialE1RetainedResponse
from apps.data_center.application.financial_response_artifact import (
    FinancialResponseArtifactRetention,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3OfficialSourceProfileExpectation,
)
from apps.data_center.domain.control_plane import SyncRunStatus
from apps.data_center.domain.financial_e1_capture_contract import FinancialE1EndpointRequest
from apps.data_center.infrastructure.control_plane_repositories import SyncRunRepository
from apps.data_center.infrastructure.egress_models import EgressRequestAuditModel
from apps.data_center.infrastructure.financial_e1_discovery_composition import (
    build_django_financial_e1_discovery_use_case,
)
from apps.data_center.infrastructure.financial_e1_execution_plan_file import (
    load_pinned_financial_e1_plan,
)
from apps.data_center.infrastructure.financial_e1_governed_execution import (
    preflight_django_financial_e1_actor_simulated_account,
)
from apps.data_center.infrastructure.financial_e1_recovery_binding import (
    claim_recovery,
    forecast_digest,
    validate_recovery_source,
)
from apps.data_center.infrastructure.financial_response_artifact_config import (
    resolve_financial_response_artifact_config,
)
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    reference_from_audit,
)
from apps.data_center.infrastructure.financial_response_body_store import FinancialResponseBodyStore
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataFetchError, DataValidationError


def _retained(
    request: FinancialE1EndpointRequest,
    capture: UUID,
    audit_hash: str,
    provider_id: int,
    store: FinancialResponseBodyStore,
) -> FinancialE1RetainedResponse:
    audits = RawAuditRepository().list_by_artifact_capture_id(capture)
    if len(audits) != 1 or audits[0].content_hash != audit_hash:
        raise ValueError("The independently pinned raw audit is absent or ambiguous.")
    audit = audits[0]
    reference = reference_from_audit(audit)
    if reference.capture_id != capture:
        raise ValueError("The retained capture identity differs from the pin.")
    attempts = list(
        EgressRequestAuditModel.objects.filter(request_id=capture).values(
            "provider_id", "dataset_key", "attempt", "outcome", "target_host", "rule_id"
        )
    )
    host = urlsplit(
        request.endpoint if "://" in request.endpoint else "https://" + request.endpoint
    ).hostname
    if len(attempts) != 1:
        raise ValueError("Expected exactly one original egress attempt.")
    attempt = attempts[0]
    if (
        attempt["provider_id"] != provider_id
        or attempt["dataset_key"] != request.dataset_key
        or attempt["attempt"] != 1
        or attempt["outcome"] != "success"
        or attempt["rule_id"] is None
        or attempt["target_host"] != host
    ):
        raise ValueError("Original egress audit differs from the approved endpoint.")
    raw = store.read(reference)
    return FinancialE1RetainedResponse(
        request,
        FinancialResponseArtifactRetention(reference, audit),
        raw,
        provider_id,
        json.loads(raw),
        attempt["attempt"],
    )


class Command(BaseCommand):
    """Preview or atomically ingest an independently pinned, previously retained E1 pair."""

    def add_arguments(self, parser: CommandParser) -> None:
        """Require independent scope, digest, capture and actor pins."""
        for key in (
            "plan-file",
            "plan-sha256",
            "operator",
            "main-audit-hash",
            "balance-audit-hash",
        ):
            parser.add_argument("--" + key, required=True)
        for key in ("source-run", "main-capture", "balance-capture"):
            parser.add_argument("--" + key, required=True, type=UUID)
        parser.add_argument("--forecast-sha256")
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args: object, **options: object) -> str:
        """Preview by default and claim at most one write transaction for a failed source."""
        try:
            source = UUID(str(options["source_run"]))
            pinned = load_pinned_financial_e1_plan(
                Path(str(options["plan_file"])), expected_sha256=str(options["plan_sha256"])
            )
            plan = pinned.discovery_plan
            guard = preflight_django_financial_e1_actor_simulated_account(
                expected_actor=str(options["operator"]),
                simulated_account_id=pinned.simulated_account_id,
            )
            guard.assert_current()
            pin = pinned.official_source_profile_pin
            expectation = FinancialV3OfficialSourceProfileExpectation(
                profile_id=pin.profile_id,
                profile_version=pin.profile_version,
                publisher_code=pin.publisher_code,
                publisher_class=pin.publisher_class,
                profile_content_sha256=pin.profile_content_sha256,
            )
            use_case = build_django_financial_e1_discovery_use_case(
                plan, official_source_profile_expectation=expectation, authority_guard=guard
            )
            config = resolve_financial_response_artifact_config(environment="production")
            if config is None:
                raise ValueError("Retained financial storage is unavailable.")
            store = FinancialResponseBodyStore(
                config.root,
                encryption_key=config.encryption_key,
                encryption_key_ref=config.encryption_key_ref,
                encryption_key_version=config.encryption_key_version,
                max_body_bytes=config.max_body_bytes,
            )
            main = _retained(
                plan.main_request,
                UUID(str(options["main_capture"])),
                str(options["main_audit_hash"]),
                plan.provider_id,
                store,
            )
            balance = _retained(
                plan.balance_request,
                UUID(str(options["balance_capture"])),
                str(options["balance_audit_hash"]),
                plan.provider_id,
                store,
            )
            validate_recovery_source(
                source, pinned.plan_file_sha256, main.retention.audit, balance.retention.audit
            )
            predicted = use_case.preview_retained_recovery(plan, main, balance)
            digest = forecast_digest(predicted)
            if not options.get("execute"):
                return f"outcome=preview source_run={source} forecast={len(predicted)} forecast_sha256={digest} physical_attempts=0 stored=0"
            guard.assert_current()
            if digest != options.get("forecast_sha256"):
                raise ValueError("Recovery forecast differs from independently reviewed preview.")
            run = claim_recovery(
                source,
                pinned.plan_file_sha256,
                main.retention.audit,
                balance.retention.audit,
                digest,
            )
            try:
                facts = use_case.store_retained_recovery(plan, run, main, balance)
            except (
                DatabaseError,
                DataFetchError,
                DataValidationError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                with transaction.atomic():
                    from apps.data_center.infrastructure.fact_and_operational_models import (
                        SyncRunModel,
                    )

                    actual = SyncRunModel.objects.select_for_update().get(pk=run.run_id).to_domain()
                    if actual == run:
                        SyncRunRepository().save(
                            replace(
                                run,
                                status=SyncRunStatus.FAILED,
                                outcome="failed",
                                failed=run.requested,
                                finished_at=now(),
                                error_code=getattr(exc, "code", "FINANCIAL_E1_RECOVERY_FAILED"),
                            )
                        )
                raise
            return f"outcome=stored source_run={source} run_id={run.run_id} physical_attempts=0 stored={len(facts)}"
        except (
            DataValidationError,
            DataFetchError,
            DatabaseError,
            OSError,
            LookupError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise CommandError(f"Financial retained recovery blocked: {exc}") from exc
