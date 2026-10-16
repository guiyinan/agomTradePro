"""Import one strict, operator-supplied A-share rule manifest into Risk storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleConflict,
    ExecutionRuleInputError,
    ExecutionRuleUnavailable,
    ImportAShareExecutionRulesUseCase,
)
from apps.risk_center.application.ashare_execution_rule_v2_catalog import (
    ImportAShareExecutionSubmissionRulesUseCase,
)
from apps.risk_center.application.ashare_execution_rule_v3_catalog import (
    ImportAShareExecutionSettlementRulesV3UseCase,
)
from apps.risk_center.infrastructure.ashare_execution_rule_codec import (
    ASHARE_EXECUTION_RULES_SCHEMA,
    AShareExecutionRuleCodecError,
    parse_a_share_execution_rule_manifest,
)
from apps.risk_center.infrastructure.ashare_execution_rule_repository import (
    DjangoAShareExecutionRuleRepository,
)
from apps.risk_center.infrastructure.ashare_execution_rule_v2_codec import (
    ASHARE_EXECUTION_RULES_V2_SCHEMA,
    AShareExecutionRuleV2CodecError,
    parse_a_share_execution_rule_v2_manifest,
)
from apps.risk_center.infrastructure.ashare_execution_rule_v3_codec import (
    ASHARE_EXECUTION_RULES_V3_SCHEMA,
    AShareExecutionRuleV3CodecError,
    parse_a_share_execution_rule_v3_manifest,
)


class Command(BaseCommand):
    """Import operator configuration without granting execution authority."""

    help = "Import an operator-supplied A-share execution-rule JSON manifest."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the required path to the operator-supplied JSON manifest."""

        parser.add_argument(
            "--manifest",
            required=True,
            help=("Path to a canonical a-share-execution-rules.v1, .v2, or .v3 JSON manifest."),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate and atomically import the provided manifest, reporting exact counts."""

        path = Path(str(options["manifest"]))
        try:
            manifest_text = path.read_text(encoding="utf-8")
            schema = _manifest_schema(manifest_text)
            repository = DjangoAShareExecutionRuleRepository()
            if schema == ASHARE_EXECUTION_RULES_SCHEMA:
                rules = parse_a_share_execution_rule_manifest(manifest_text)
                result = ImportAShareExecutionRulesUseCase(repository).execute(rules=rules)
            elif schema == ASHARE_EXECUTION_RULES_V2_SCHEMA:
                rules_v2 = parse_a_share_execution_rule_v2_manifest(manifest_text)
                result = ImportAShareExecutionSubmissionRulesUseCase(repository).execute(
                    rules=rules_v2
                )
            elif schema == ASHARE_EXECUTION_RULES_V3_SCHEMA:
                bundles_v3 = parse_a_share_execution_rule_v3_manifest(manifest_text)
                result = ImportAShareExecutionSettlementRulesV3UseCase(repository).execute(
                    bundles=bundles_v3
                )
            else:
                raise AShareExecutionRuleCodecError("manifest schema is unsupported")
        except (
            OSError,
            AShareExecutionRuleCodecError,
            AShareExecutionRuleV2CodecError,
            AShareExecutionRuleV3CodecError,
            ExecutionRuleConflict,
            ExecutionRuleInputError,
            ExecutionRuleUnavailable,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                "A-share rule configuration imported: "
                f"inserted={result.inserted_count}, unchanged={result.unchanged_count}. "
                "Configuration import does not authorize trading."
            )
        )


def _manifest_schema(text: str) -> str:
    """Read a duplicate-safe top-level schema before selecting the strict codec."""

    try:
        raw: object = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, AShareExecutionRuleCodecError, ValueError) as error:
        raise AShareExecutionRuleCodecError("manifest JSON header is invalid") from error
    if not isinstance(raw, dict) or frozenset(raw) != frozenset({"schema", "rules"}):
        raise AShareExecutionRuleCodecError("manifest header has missing or unknown fields")
    schema = raw["schema"]
    if type(schema) is not str:
        raise AShareExecutionRuleCodecError("manifest schema must be a string")
    return schema


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AShareExecutionRuleCodecError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> NoReturn:
    raise AShareExecutionRuleCodecError(f"non-finite JSON number is forbidden: {value}")
