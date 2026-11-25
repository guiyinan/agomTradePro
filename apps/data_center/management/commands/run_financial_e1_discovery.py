"""Run one explicitly selected Main+Balance E1 capture on the governed path."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.akshare_financial_capture_composition import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3OfficialSourceProfileExpectation,
)
from apps.data_center.domain.egress_routing import EgressRoutingError
from apps.data_center.infrastructure.egress_target import resolve_public_target
from apps.data_center.infrastructure.financial_e1_discovery_composition import (
    build_django_financial_e1_discovery_use_case,
)
from apps.data_center.infrastructure.financial_e1_execution_plan_file import (
    load_pinned_financial_e1_plan,
)
from apps.data_center.infrastructure.financial_e1_governed_execution import (
    finish_django_financial_e1_non_success_run,
    preflight_django_financial_e1_actor_simulated_account,
    start_django_financial_e1_sync_run,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_API_URL,
)
from core.exceptions import DataValidationError


class Command(BaseCommand):
    """Execute a finite explicit qualification selection and report reconciliation."""

    help = "Capture one explicitly qualified AKShare Main+Balance E1 financial slice."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require an external plan pin, current actor, and explicit execute flag."""

        parser.add_argument("--plan-file", required=True)
        parser.add_argument("--plan-sha256", required=True)
        parser.add_argument("--operator", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args: object, **options: object) -> str:
        """Verify the external pin and existing authorities before E1 capture."""

        del args
        if options.get("execute") is not True:
            raise CommandError("--execute is required for the bounded E1 capture.")
        plan_path = options.get("plan_file")
        expected_sha256 = options.get("plan_sha256")
        operator = options.get("operator")
        if (
            type(plan_path) is not str
            or not plan_path
            or type(expected_sha256) is not str
            or type(operator) is not str
        ):
            raise CommandError("An external plan file/hash and exact operator are required.")
        try:
            pinned = load_pinned_financial_e1_plan(
                Path(plan_path),
                expected_sha256=expected_sha256,
            )
        except (OSError, TypeError, ValueError) as error:
            raise CommandError(f"The independently pinned E1 plan is invalid: {error}") from error
        try:
            authority_guard = preflight_django_financial_e1_actor_simulated_account(
                expected_actor=operator,
                simulated_account_id=pinned.simulated_account_id,
            )
        except (DataValidationError, RuntimeError, TypeError, ValueError) as error:
            raise CommandError(
                f"E1 SystemAudit/simulated-account preflight blocked: {error}"
            ) from error
        profile_pin = pinned.official_source_profile_pin
        expectation = FinancialV3OfficialSourceProfileExpectation(
            profile_id=profile_pin.profile_id,
            profile_version=profile_pin.profile_version,
            publisher_code=profile_pin.publisher_code,
            publisher_class=profile_pin.publisher_class,
            profile_content_sha256=profile_pin.profile_content_sha256,
        )
        try:
            use_case = build_django_financial_e1_discovery_use_case(
                pinned.discovery_plan,
                official_source_profile_expectation=expectation,
                authority_guard=authority_guard,
            )
            for role, url in (
                ("Main", AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT_URL),
                ("Balance", AKSHARE_BALANCE_API_URL),
            ):
                try:
                    resolve_public_target(url)
                except EgressRoutingError as error:
                    raise CommandError(
                        f"E1 {role} target preflight failed: {error.code}"
                    ) from error
            run = start_django_financial_e1_sync_run(
                pinned,
                authority_guard=authority_guard,
            )
            result = use_case.execute(pinned.discovery_plan, run=run)
            if result.outcome != "stored":
                run = finish_django_financial_e1_non_success_run(
                    run,
                    result,
                    authority_guard=authority_guard,
                )
        except (DataValidationError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise CommandError(
                f"E1 execution was blocked before a complete commit: {error}"
            ) from error
        self.stdout.write(
            " ".join(
                (
                    f"outcome={result.outcome}",
                    f"requested={result.requested}",
                    f"succeeded={result.succeeded}",
                    f"failed={result.failed}",
                    f"stored={result.stored}",
                    f"physical_attempts={result.physical_attempts}",
                    f"run_id={run.run_id}",
                    f"plan_sha256={pinned.plan_file_sha256}",
                    f"selection_sha256={result.selection_sha256}",
                    f"failure_code={result.failure_code or 'none'}",
                    f"capture_ids={','.join(result.retained_capture_ids) or 'none'}",
                )
            )
        )
        if result.outcome != "stored":
            raise CommandError("E1 discovery did not store the complete explicit selection.")
        return "E1 discovery stored and verified the complete explicit selection."
