"""Application ports and use cases for operator-managed A-share rule configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.risk_center.application.execution_settlement_v3 import (
    ExecutionSettlementV3ReadRecord as _ExecutionSettlementV3ReadRecord,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import AShareExecutionRule
from core.exceptions import BusinessLogicError, InvalidInputError


class ExecutionRuleInputError(InvalidInputError):
    """An operator supplied an invalid A-share rule batch or lookup key."""

    default_message = "A-share execution rule input is invalid"
    default_code = "A_SHARE_EXECUTION_RULE_INPUT_INVALID"


class ExecutionRuleConflict(BusinessLogicError):
    """An immutable rule identity or same-security effective window conflicts."""

    default_message = "A-share execution rule conflicts with stored configuration"
    default_code = "A_SHARE_EXECUTION_RULE_CONFLICT"
    default_status_code = 409


class ExecutionRuleUnavailable(BusinessLogicError):
    """No single valid rule is available for the requested security and cutoff."""

    default_message = "A-share execution rule is unavailable"
    default_code = "A_SHARE_EXECUTION_RULE_UNAVAILABLE"
    default_status_code = 503


class ExecutionRuleVersionMismatch(ExecutionRuleUnavailable):
    """A version-specific reader encountered a rule encoded under another schema."""

    default_message = "A-share execution rule schema does not match the requested API"
    default_code = "A_SHARE_EXECUTION_RULE_VERSION_MISMATCH"
    default_status_code = 409


class ExecutionRuleCorruption(ExecutionRuleUnavailable):
    """Persisted rule payload or duplicated lookup columns failed integrity checks."""

    default_message = "A-share execution rule storage is inconsistent"
    default_code = "A_SHARE_EXECUTION_RULE_CORRUPT"


class ExecutionRulePersistenceUnavailable(ExecutionRuleUnavailable):
    """The rule repository could not safely complete a database operation."""

    default_message = "A-share execution rule storage is temporarily unavailable"
    default_code = "A_SHARE_EXECUTION_RULE_STORAGE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ExecutionRuleImportResult:
    """Counts newly persisted and exact idempotent rules in one import batch."""

    inserted_count: int
    unchanged_count: int

    def __post_init__(self) -> None:
        """Validate consistent nonnegative import counts."""

        if (
            type(self.inserted_count) is not int
            or type(self.unchanged_count) is not int
            or self.inserted_count < 0
            or self.unchanged_count < 0
        ):
            raise ValueError("rule import counts must be nonnegative integers")


def _validate_security_lookup(security_id: str, as_of: datetime) -> None:
    """Apply the exact shared V1/V2 lookup-token and knowledge-cutoff checks."""

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


class AShareExecutionRuleCatalog(Protocol):
    """Persistence boundary for exact Risk-owned A-share rule configuration."""

    def import_rules(self, *, rules: tuple[AShareExecutionRule, ...]) -> ExecutionRuleImportResult:
        """Atomically append an operator-supplied batch or report its exact replay."""

    def get_effective_rule(self, *, security_id: str, as_of: datetime) -> AShareExecutionRule:
        """Read one source-available and effective rule, failing closed otherwise."""


class ImportAShareExecutionRulesUseCase:
    """Validate and delegate one complete operator-supplied configuration batch."""

    def __init__(self, repository: AShareExecutionRuleCatalog) -> None:
        """Require the Risk-owned rule catalog port explicitly."""

        self._repository = repository

    def execute(self, *, rules: tuple[AShareExecutionRule, ...]) -> ExecutionRuleImportResult:
        """Import a nonempty tuple of already sealed domain rules atomically."""

        if type(rules) is not tuple or not rules:
            raise ExecutionRuleInputError("rule import requires a nonempty immutable tuple")
        for rule in rules:
            if type(rule) is not AShareExecutionRule:
                raise ExecutionRuleInputError("rule import requires exact typed domain rules")
            try:
                AShareExecutionRule.__post_init__(rule)
            except (TypeError, ValueError) as error:
                raise ExecutionRuleInputError(
                    "rule import contains an invalid domain rule"
                ) from error
        return self._repository.import_rules(rules=rules)


class ReadEffectiveAShareExecutionRuleUseCase:
    """Read configuration as of a caller's knowledge time without granting execution."""

    def __init__(self, repository: AShareExecutionRuleCatalog) -> None:
        """Require the Risk-owned rule catalog port explicitly."""

        self._repository = repository

    def execute(self, *, security_id: str, as_of: datetime) -> AShareExecutionRule:
        """Return one effective rule whose source was already available at the cutoff."""

        _validate_security_lookup(security_id, as_of)
        rule = self._repository.get_effective_rule(security_id=security_id, as_of=as_of)
        if type(rule) is not AShareExecutionRule:
            raise ExecutionRuleCorruption("rule repository returned an invalid domain type")
        try:
            AShareExecutionRule.__post_init__(rule)
        except (TypeError, ValueError) as error:
            raise ExecutionRuleCorruption(
                "rule repository returned invalid sealed content"
            ) from error
        if rule.security_id != security_id:
            raise ExecutionRuleCorruption("rule repository returned a different security")
        if not (
            rule.source_available_at <= as_of and rule.effective_from <= as_of < rule.valid_until
        ):
            raise ExecutionRuleCorruption("rule repository returned a rule outside its cutoff")
        return rule


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

        _validate_security_lookup(security_id, as_of)
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


class AShareExecutionSettlementRuleV3Catalog(Protocol):
    """Persistence boundary for exact v3 settlement rule bundles."""

    def import_settlement_bundles(
        self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
    ) -> ExecutionRuleImportResult:
        """Atomically append v3 bundles or report exact idempotent replays."""

    def get_effective_settlement_bundle(
        self, *, security_id: str, as_of: datetime
    ) -> _ExecutionSettlementV3ReadRecord | None:
        """Read one v3 bundle and retain its local database knowledge timestamp."""


class ImportAShareExecutionSettlementRulesV3UseCase:
    """Validate and persist one operator-supplied v3 bundle batch."""

    def __init__(self, repository: AShareExecutionSettlementRuleV3Catalog) -> None:
        """Require the Risk-owned shared rule-table port explicitly."""

        self._repository = repository

    def execute(
        self, *, bundles: tuple[ExecutionSettlementBundleV3, ...]
    ) -> ExecutionRuleImportResult:
        """Import exact sealed bundles, preserving their V3 hash and identity."""

        if type(bundles) is not tuple or not bundles:
            raise ExecutionRuleInputError(
                "v3 settlement import requires a nonempty immutable tuple"
            )
        for bundle in bundles:
            if type(bundle) is not ExecutionSettlementBundleV3:
                raise ExecutionRuleInputError(
                    "v3 settlement import requires exact typed domain bundles"
                )
            try:
                ExecutionSettlementBundleV3.__post_init__(bundle)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise ExecutionRuleInputError(
                    "v3 settlement import contains invalid content"
                ) from error
        return self._repository.import_settlement_bundles(bundles=bundles)
