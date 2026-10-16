"""Application ports and use cases for version-two A-share rule configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.risk_center.application.ashare_execution_rule_catalog import (
    ExecutionRuleCorruption,
    ExecutionRuleImportResult,
    ExecutionRuleInputError,
    ExecutionRuleVersionMismatch,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2


class AShareExecutionSubmissionRuleCatalog(Protocol):
    """Persistence boundary for exact v2 rule configurations."""

    def import_submission_rules(
        self, *, rules: tuple[ExecutionSubmissionRuleV2, ...]
    ) -> ExecutionRuleImportResult:
        """Atomically append a complete v2 batch or report its exact replay."""

    def get_effective_submission_rule(
        self, *, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2:
        """Read one recorded, source-available, effective v2 configuration."""


class ImportAShareExecutionSubmissionRulesUseCase:
    """Validate and persist one operator-supplied v2 rule batch."""

    def __init__(self, repository: AShareExecutionSubmissionRuleCatalog) -> None:
        """Require the Risk-owned v2 rule catalog port explicitly."""

        self._repository = repository

    def execute(self, *, rules: tuple[ExecutionSubmissionRuleV2, ...]) -> ExecutionRuleImportResult:
        """Import a nonempty immutable tuple of sealed v2 domain rules."""

        if type(rules) is not tuple or not rules:
            raise ExecutionRuleInputError("v2 rule import requires a nonempty immutable tuple")
        for rule in rules:
            if type(rule) is not ExecutionSubmissionRuleV2:
                raise ExecutionRuleInputError("v2 rule import requires exact typed domain rules")
            try:
                ExecutionSubmissionRuleV2.__post_init__(rule)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise ExecutionRuleInputError("v2 rule import contains invalid content") from error
        return self._repository.import_submission_rules(rules=rules)


class ReadEffectiveAShareExecutionSubmissionRuleUseCase:
    """Read one exact v2 rule as of the caller's local knowledge cutoff."""

    def __init__(self, repository: AShareExecutionSubmissionRuleCatalog) -> None:
        """Require the Risk-owned v2 rule catalog port explicitly."""

        self._repository = repository

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSubmissionRuleV2:
        """Return one v2 rule whose local and source clocks precede the cutoff."""

        if (
            type(security_id) is not str
            or not security_id
            or security_id.strip() != security_id
            or len(security_id) > 192
            or any(character.isspace() for character in security_id)
        ):
            raise ExecutionRuleInputError("security_id must be a bounded canonical token")
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ExecutionRuleInputError("rule lookup requires an aware knowledge cutoff")
        rule = self._repository.get_effective_submission_rule(security_id=security_id, as_of=as_of)
        if type(rule) is not ExecutionSubmissionRuleV2:
            raise ExecutionRuleVersionMismatch("v2 rule repository returned a non-v2 rule")
        try:
            ExecutionSubmissionRuleV2.__post_init__(rule)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ExecutionRuleCorruption(
                "v2 repository returned invalid sealed content"
            ) from error
        if rule.execution_rule_v1.security_id != security_id:
            raise ExecutionRuleCorruption("v2 repository returned a different security")
        base = rule.execution_rule_v1
        if not (
            base.source_available_at <= as_of and base.effective_from <= as_of < base.valid_until
        ):
            raise ExecutionRuleCorruption("v2 rule is outside its requested cutoff")
        return rule
