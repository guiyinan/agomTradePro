"""Versioned, auditable industry operating-template contracts for R1 research.

Templates contain typed drivers and a finite expression graph.  They contain
no built-in industry catalog, company list, empirical default, Python source,
or string expression.  All values enter through point-in-time facts or explicit
human/model overrides, and all outputs remain research-only forecast drafts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class ForecastScenario(StrEnum):
    """Required scenario set for an operating forecast draft."""

    BASE = "base"
    BULL = "bull"
    BEAR = "bear"


class DriverInputKind(StrEnum):
    """Mutually exclusive provenance of one driver value."""

    OBSERVED_FACT = "observed_fact"
    HUMAN_ASSUMPTION = "human_assumption"
    MODEL_INFERENCE = "model_inference"


class ExpressionOperator(StrEnum):
    """Finite operators accepted by the safe expression evaluator."""

    IDENTITY = "identity"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"


class ValueReferenceKind(StrEnum):
    """Allowed sources for an expression operand."""

    DRIVER = "driver"
    NODE = "node"


class FinancialStage(StrEnum):
    """Required operating-model dependency stages."""

    REVENUE = "revenue"
    GROSS_PROFIT = "gross_profit"
    COST = "cost"
    EXPENSE = "expense"
    NET_PROFIT = "net_profit"
    CASH_FLOW = "cash_flow"


class TemplateLifecycle(StrEnum):
    """Immutable lifecycle state of one template version."""

    ACTIVE = "active"
    INVALIDATED = "invalidated"
    RETIRED = "retired"


class TemplateRunStatus(StrEnum):
    """Availability of a research-only template run."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


_STAGE_RANK: dict[FinancialStage, int] = {
    FinancialStage.REVENUE: 0,
    FinancialStage.GROSS_PROFIT: 1,
    FinancialStage.COST: 1,
    FinancialStage.EXPENSE: 2,
    FinancialStage.NET_PROFIT: 3,
    FinancialStage.CASH_FLOW: 4,
}


def _require_text(value: str, field_name: str, *, maximum: int) -> None:
    """Require a bounded non-blank string."""

    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_token(value: str, field_name: str, *, maximum: int) -> None:
    """Require a compact identifier without whitespace."""

    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require a timezone-aware timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    """Require a finite Decimal without implicit float calculation."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_sha256(value: str, field_name: str) -> None:
    """Require one SHA-256 hexadecimal digest."""

    if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _decimal_text(value: Decimal) -> str:
    """Serialize a Decimal without exponent or insignificant trailing zeros."""

    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _utc_iso(value: datetime | None) -> str | None:
    """Serialize an aware timestamp in stable UTC form."""

    return value.astimezone(UTC).isoformat() if value is not None else None


def _canonical_hash(payload: object) -> str:
    """Return the stable SHA-256 hash of a JSON-compatible payload."""

    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class DriverDefinition:
    """Typed unit, frequency, source and provenance contract for one driver."""

    driver_key: str
    name: str
    unit: str
    frequency: str
    source: str
    allowed_input_kinds: tuple[DriverInputKind, ...]
    metric_code: str = ""
    metric_definition_version: int = 0
    subject_type: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if any(not isinstance(kind, DriverInputKind) for kind in self.allowed_input_kinds):
            raise ValueError("DriverDefinition.allowed_input_kinds is invalid")
        object.__setattr__(
            self,
            "allowed_input_kinds",
            tuple(sorted(self.allowed_input_kinds, key=lambda item: item.value)),
        )
        _require_token(self.driver_key, "DriverDefinition.driver_key", maximum=80)
        _require_text(self.name, "DriverDefinition.name", maximum=160)
        _require_text(self.unit, "DriverDefinition.unit", maximum=40)
        _require_token(self.frequency, "DriverDefinition.frequency", maximum=40)
        _require_token(self.source, "DriverDefinition.source", maximum=100)
        if not self.allowed_input_kinds:
            raise ValueError("DriverDefinition.allowed_input_kinds cannot be empty")
        if len(set(self.allowed_input_kinds)) != len(self.allowed_input_kinds):
            raise ValueError("DriverDefinition.allowed_input_kinds cannot contain duplicates")
        supports_fact = DriverInputKind.OBSERVED_FACT in self.allowed_input_kinds
        if supports_fact:
            _require_token(self.metric_code, "DriverDefinition.metric_code", maximum=64)
            if (
                isinstance(self.metric_definition_version, bool)
                or self.metric_definition_version <= 0
            ):
                raise ValueError("fact-backed driver requires metric_definition_version")
            _require_token(
                self.subject_type,
                "DriverDefinition.subject_type",
                maximum=40,
            )
        elif self.metric_code or self.metric_definition_version != 0 or self.subject_type:
            raise ValueError("non-fact driver cannot carry a Data Center metric binding")

    def to_payload(self) -> dict[str, object]:
        """Return all governed driver semantics as a canonical payload."""

        return {
            "allowed_input_kinds": sorted(kind.value for kind in self.allowed_input_kinds),
            "description": self.description,
            "driver_key": self.driver_key,
            "frequency": self.frequency,
            "metric_code": self.metric_code,
            "metric_definition_version": self.metric_definition_version,
            "name": self.name,
            "source": self.source,
            "subject_type": self.subject_type,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class UnitDerivationRule:
    """Versioned unit rule for one multiply or divide expression."""

    rule_key: str
    operator: ExpressionOperator
    left_unit: str
    right_unit: str
    output_unit: str
    methodology_ref: str

    def __post_init__(self) -> None:
        _require_token(self.rule_key, "UnitDerivationRule.rule_key", maximum=80)
        if self.operator not in {
            ExpressionOperator.MULTIPLY,
            ExpressionOperator.DIVIDE,
        }:
            raise ValueError("unit derivation rules only support multiply or divide")
        for value, field_name in (
            (self.left_unit, "left_unit"),
            (self.right_unit, "right_unit"),
            (self.output_unit, "output_unit"),
        ):
            _require_text(value, f"UnitDerivationRule.{field_name}", maximum=40)
        _require_text(
            self.methodology_ref,
            "UnitDerivationRule.methodology_ref",
            maximum=300,
        )

    def to_payload(self) -> dict[str, object]:
        """Return the governed unit transformation as canonical JSON data."""

        return {
            "left_unit": self.left_unit,
            "methodology_ref": self.methodology_ref,
            "operator": self.operator.value,
            "output_unit": self.output_unit,
            "right_unit": self.right_unit,
            "rule_key": self.rule_key,
        }


@dataclass(frozen=True)
class ValueReference:
    """Typed reference to a driver or another expression node."""

    kind: ValueReferenceKind
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ValueReferenceKind):
            raise ValueError("ValueReference.kind is invalid")
        _require_token(self.key, "ValueReference.key", maximum=80)

    def to_payload(self) -> dict[str, object]:
        """Return the typed reference as canonical JSON data."""

        return {"key": self.key, "kind": self.kind.value}


@dataclass(frozen=True)
class ExpressionNode:
    """One finite AST node whose dependencies form the template DAG."""

    node_key: str
    stage: FinancialStage
    operator: ExpressionOperator
    operands: tuple[ValueReference, ...]
    output_unit: str
    unit_rule_key: str = ""

    def __post_init__(self) -> None:
        _require_token(self.node_key, "ExpressionNode.node_key", maximum=80)
        if not isinstance(self.stage, FinancialStage):
            raise ValueError("ExpressionNode.stage is invalid")
        if not isinstance(self.operator, ExpressionOperator):
            raise ValueError("ExpressionNode.operator is invalid")
        _require_text(self.output_unit, "ExpressionNode.output_unit", maximum=40)
        expected_arity = {
            ExpressionOperator.IDENTITY: (1, 1),
            ExpressionOperator.ADD: (2, 1_000),
            ExpressionOperator.SUBTRACT: (2, 2),
            ExpressionOperator.MULTIPLY: (2, 2),
            ExpressionOperator.DIVIDE: (2, 2),
        }[self.operator]
        if not expected_arity[0] <= len(self.operands) <= expected_arity[1]:
            raise ValueError("expression operand count does not match its operator")
        if self.operator in {
            ExpressionOperator.MULTIPLY,
            ExpressionOperator.DIVIDE,
        }:
            _require_token(
                self.unit_rule_key,
                "ExpressionNode.unit_rule_key",
                maximum=80,
            )
        elif self.unit_rule_key:
            raise ValueError("identity/add/subtract cannot carry a unit derivation rule")

    def to_payload(self) -> dict[str, object]:
        """Return the finite AST node as canonical JSON data."""

        return {
            "node_key": self.node_key,
            "operands": [operand.to_payload() for operand in self.operands],
            "operator": self.operator.value,
            "output_unit": self.output_unit,
            "stage": self.stage.value,
            "unit_rule_key": self.unit_rule_key,
        }


@dataclass(frozen=True)
class StageOutput:
    """Bind one required financial stage to its public output node."""

    stage: FinancialStage
    node_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, FinancialStage):
            raise ValueError("StageOutput.stage is invalid")
        _require_token(self.node_key, "StageOutput.node_key", maximum=80)

    def to_payload(self) -> dict[str, object]:
        """Return the stage binding as canonical JSON data."""

        return {"node_key": self.node_key, "stage": self.stage.value}


@dataclass(frozen=True)
class IndustryOperatingTemplate:
    """Immutable, versioned and research-only industry calculation template."""

    template_code: str
    template_version: int
    industry_code: str
    name: str
    methodology_ref: str
    effective_at: datetime
    lifecycle: TemplateLifecycle
    drivers: tuple[DriverDefinition, ...]
    unit_rules: tuple[UnitDerivationRule, ...]
    nodes: tuple[ExpressionNode, ...]
    stage_outputs: tuple[StageOutput, ...]
    effective_to: datetime | None = None
    lifecycle_reason: str = ""
    supersedes_version: int | None = None
    description: str = ""
    research_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "drivers",
            tuple(sorted(self.drivers, key=lambda item: item.driver_key)),
        )
        object.__setattr__(
            self,
            "unit_rules",
            tuple(sorted(self.unit_rules, key=lambda item: item.rule_key)),
        )
        object.__setattr__(
            self,
            "nodes",
            tuple(sorted(self.nodes, key=lambda item: item.node_key)),
        )
        object.__setattr__(
            self,
            "stage_outputs",
            tuple(sorted(self.stage_outputs, key=lambda item: item.stage.value)),
        )
        _require_token(
            self.template_code,
            "IndustryOperatingTemplate.template_code",
            maximum=80,
        )
        if isinstance(self.template_version, bool) or self.template_version <= 0:
            raise ValueError("IndustryOperatingTemplate.template_version must be positive")
        _require_token(
            self.industry_code,
            "IndustryOperatingTemplate.industry_code",
            maximum=80,
        )
        _require_text(self.name, "IndustryOperatingTemplate.name", maximum=160)
        _require_text(
            self.methodology_ref,
            "IndustryOperatingTemplate.methodology_ref",
            maximum=300,
        )
        _require_aware(self.effective_at, "IndustryOperatingTemplate.effective_at")
        if self.effective_to is not None:
            _require_aware(self.effective_to, "IndustryOperatingTemplate.effective_to")
            if self.effective_to <= self.effective_at:
                raise ValueError("template effective_to must follow effective_at")
        if not isinstance(self.lifecycle, TemplateLifecycle):
            raise ValueError("IndustryOperatingTemplate.lifecycle is invalid")
        if self.lifecycle is TemplateLifecycle.ACTIVE:
            if self.lifecycle_reason:
                raise ValueError("active template cannot carry invalidation/retirement reason")
        else:
            _require_text(
                self.lifecycle_reason,
                "IndustryOperatingTemplate.lifecycle_reason",
                maximum=500,
            )
        if self.supersedes_version is not None and (
            isinstance(self.supersedes_version, bool)
            or not 0 < self.supersedes_version < self.template_version
        ):
            raise ValueError("supersedes_version must reference an earlier positive version")
        if not self.research_only:
            raise ValueError("industry templates must remain research-only")
        self._validate_graph()

    def _validate_graph(self) -> None:
        """Validate references, cycles, stage direction and unit compatibility."""

        if not self.drivers or not self.nodes:
            raise ValueError("industry template requires drivers and expression nodes")
        drivers = {driver.driver_key: driver for driver in self.drivers}
        nodes = {node.node_key: node for node in self.nodes}
        rules = {rule.rule_key: rule for rule in self.unit_rules}
        if len(drivers) != len(self.drivers):
            raise ValueError("industry template driver keys must be unique")
        if len(nodes) != len(self.nodes):
            raise ValueError("industry template node keys must be unique")
        if len(rules) != len(self.unit_rules):
            raise ValueError("industry template unit rule keys must be unique")
        overlap = set(drivers) & set(nodes)
        if overlap:
            raise ValueError("driver and node keys cannot overlap")
        outputs = {output.stage: output.node_key for output in self.stage_outputs}
        if len(outputs) != len(self.stage_outputs) or set(outputs) != set(FinancialStage):
            raise ValueError("stage_outputs must contain every financial stage exactly once")
        for stage, node_key in outputs.items():
            node = nodes.get(node_key)
            if node is None or node.stage is not stage:
                raise ValueError("stage output must reference a node in the same stage")

        dependencies: dict[str, tuple[str, ...]] = {}
        for node in self.nodes:
            node_dependencies: list[str] = []
            for operand in node.operands:
                if operand.kind is ValueReferenceKind.DRIVER:
                    if operand.key not in drivers:
                        raise ValueError(f"missing driver reference:{operand.key}")
                else:
                    dependency = nodes.get(operand.key)
                    if dependency is None:
                        raise ValueError(f"missing node reference:{operand.key}")
                    if _STAGE_RANK[dependency.stage] > _STAGE_RANK[node.stage]:
                        raise ValueError("financial dependency points backward across stages")
                    node_dependencies.append(operand.key)
            dependencies[node.node_key] = tuple(node_dependencies)

        order = _topological_order(nodes, dependencies)
        units: dict[str, str] = {key: driver.unit for key, driver in drivers.items()}
        for node_key in order:
            node = nodes[node_key]
            operand_units = tuple(units[operand.key] for operand in node.operands)
            if node.operator is ExpressionOperator.IDENTITY:
                if node.output_unit != operand_units[0]:
                    raise ValueError("identity expression unit mismatch")
            elif node.operator in {
                ExpressionOperator.ADD,
                ExpressionOperator.SUBTRACT,
            }:
                if len(set(operand_units)) != 1 or node.output_unit != operand_units[0]:
                    raise ValueError("add/subtract expression unit mismatch")
            else:
                rule = rules.get(node.unit_rule_key)
                if rule is None:
                    raise ValueError("expression unit derivation rule is missing")
                if (
                    rule.operator is not node.operator
                    or rule.left_unit != operand_units[0]
                    or rule.right_unit != operand_units[1]
                    or rule.output_unit != node.output_unit
                ):
                    raise ValueError("multiply/divide expression unit rule mismatch")
            units[node_key] = node.output_unit

        revenue_key = outputs[FinancialStage.REVENUE]
        gross_key = outputs[FinancialStage.GROSS_PROFIT]
        cost_key = outputs[FinancialStage.COST]
        expense_key = outputs[FinancialStage.EXPENSE]
        net_profit_key = outputs[FinancialStage.NET_PROFIT]
        cash_flow_key = outputs[FinancialStage.CASH_FLOW]
        ancestors = _transitive_dependencies(dependencies)
        if revenue_key not in ancestors[gross_key] and cost_key not in ancestors[gross_key]:
            raise ValueError("gross-profit output must depend on revenue or cost")
        if not ({gross_key, cost_key} & ancestors[net_profit_key]):
            raise ValueError("net-profit output must depend on gross profit or cost")
        if expense_key not in ancestors[net_profit_key]:
            raise ValueError("net-profit output must depend on expense")
        if net_profit_key not in ancestors[cash_flow_key]:
            raise ValueError("cash-flow output must depend on net profit")
        financial_units = {
            units[revenue_key],
            units[net_profit_key],
            units[cash_flow_key],
        }
        if len(financial_units) != 1:
            raise ValueError("revenue, net profit and cash flow units must match")

    @property
    def topological_node_keys(self) -> tuple[str, ...]:
        """Return the stable, cycle-free evaluation order."""

        nodes = {node.node_key: node for node in self.nodes}
        dependencies = {
            node.node_key: tuple(
                operand.key for operand in node.operands if operand.kind is ValueReferenceKind.NODE
            )
            for node in self.nodes
        }
        return _topological_order(nodes, dependencies)

    @property
    def stage_output_keys(self) -> dict[FinancialStage, str]:
        """Return an isolated mapping of financial stages to output nodes."""

        return {output.stage: output.node_key for output in self.stage_outputs}

    def is_effective_at(self, as_of_time: datetime) -> bool:
        """Return whether this exact active version is usable at ``as_of_time``."""

        _require_aware(as_of_time, "as_of_time")
        return (
            self.lifecycle is TemplateLifecycle.ACTIVE
            and self.effective_at <= as_of_time
            and (self.effective_to is None or as_of_time < self.effective_to)
        )

    def to_payload(self) -> dict[str, object]:
        """Return every immutable template semantic as canonical JSON data."""

        return {
            "description": self.description,
            "drivers": [
                driver.to_payload()
                for driver in sorted(self.drivers, key=lambda item: item.driver_key)
            ],
            "effective_at": _utc_iso(self.effective_at),
            "effective_to": _utc_iso(self.effective_to),
            "industry_code": self.industry_code,
            "lifecycle": self.lifecycle.value,
            "lifecycle_reason": self.lifecycle_reason,
            "methodology_ref": self.methodology_ref,
            "name": self.name,
            "nodes": [
                node.to_payload() for node in sorted(self.nodes, key=lambda item: item.node_key)
            ],
            "research_only": self.research_only,
            "stage_outputs": [
                output.to_payload()
                for output in sorted(
                    self.stage_outputs,
                    key=lambda item: item.stage.value,
                )
            ],
            "supersedes_version": self.supersedes_version,
            "template_code": self.template_code,
            "template_version": self.template_version,
            "unit_rules": [
                rule.to_payload()
                for rule in sorted(self.unit_rules, key=lambda item: item.rule_key)
            ],
        }

    @property
    def content_hash(self) -> str:
        """Seal the complete template version in a stable SHA-256 digest."""

        return _canonical_hash(self.to_payload())


def _topological_order(
    nodes: dict[str, ExpressionNode],
    dependencies: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Return a deterministic topological order or reject dependency cycles."""

    pending = {key: set(dependencies[key]) for key in nodes}
    ordered: list[str] = []
    while pending:
        ready = sorted(key for key, values in pending.items() if not values)
        if not ready:
            raise ValueError("industry template expression graph contains a cycle")
        for key in ready:
            ordered.append(key)
            pending.pop(key)
        for values in pending.values():
            values.difference_update(ready)
    return tuple(ordered)


def _transitive_dependencies(
    dependencies: dict[str, tuple[str, ...]],
) -> dict[str, set[str]]:
    """Expand node dependencies after cycle validation."""

    expanded: dict[str, set[str]] = {}
    for node_key in dependencies:
        seen: set[str] = set()
        stack = list(dependencies[node_key])
        while stack:
            dependency = stack.pop()
            if dependency in seen:
                continue
            seen.add(dependency)
            stack.extend(dependencies[dependency])
        expanded[node_key] = seen
    return expanded


@dataclass(frozen=True)
class PITDriverFact:
    """Verified Data Center point-in-time evidence for one template driver."""

    version_id: int
    dataset: str
    business_key: str
    metric_code: str
    metric_definition_version: int
    subject_code: str
    effective_at: datetime
    available_at: datetime
    value: Decimal
    unit: str
    frequency: str
    source: str
    source_record_id: str
    content_hash: str
    is_verified: bool

    def __post_init__(self) -> None:
        if isinstance(self.version_id, bool) or self.version_id <= 0:
            raise ValueError("PITDriverFact.version_id must be positive")
        _require_token(self.dataset, "PITDriverFact.dataset", maximum=64)
        _require_text(self.business_key, "PITDriverFact.business_key", maximum=255)
        _require_token(self.metric_code, "PITDriverFact.metric_code", maximum=64)
        if isinstance(self.metric_definition_version, bool) or self.metric_definition_version <= 0:
            raise ValueError("PITDriverFact.metric_definition_version must be positive")
        _require_token(self.subject_code, "PITDriverFact.subject_code", maximum=80)
        _require_aware(self.effective_at, "PITDriverFact.effective_at")
        _require_aware(self.available_at, "PITDriverFact.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("PIT driver fact cannot be available before effective_at")
        _require_finite(self.value, "PITDriverFact.value")
        _require_text(self.unit, "PITDriverFact.unit", maximum=40)
        _require_token(self.frequency, "PITDriverFact.frequency", maximum=40)
        _require_token(self.source, "PITDriverFact.source", maximum=100)
        _require_text(self.source_record_id, "PITDriverFact.source_record_id", maximum=255)
        _require_sha256(self.content_hash, "PITDriverFact.content_hash")
        if not isinstance(self.is_verified, bool):
            raise ValueError("PITDriverFact.is_verified must be a boolean")

    def to_payload(self) -> dict[str, object]:
        """Return exact PIT evidence for run audit and hash sealing."""

        return {
            "available_at": _utc_iso(self.available_at),
            "business_key": self.business_key,
            "content_hash": self.content_hash.lower(),
            "dataset": self.dataset,
            "effective_at": _utc_iso(self.effective_at),
            "frequency": self.frequency,
            "is_verified": self.is_verified,
            "metric_code": self.metric_code,
            "metric_definition_version": self.metric_definition_version,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "subject_code": self.subject_code,
            "unit": self.unit,
            "value": _decimal_text(self.value),
            "version_id": self.version_id,
        }


@dataclass(frozen=True)
class ScenarioDriverOverride:
    """Explicit human or model override for one scenario and driver."""

    scenario: ForecastScenario
    driver_key: str
    value: Decimal
    unit: str
    input_kind: DriverInputKind
    rationale: str
    lineage_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("ScenarioDriverOverride.scenario is invalid")
        _require_token(self.driver_key, "ScenarioDriverOverride.driver_key", maximum=80)
        _require_finite(self.value, "ScenarioDriverOverride.value")
        _require_text(self.unit, "ScenarioDriverOverride.unit", maximum=40)
        if self.input_kind not in {
            DriverInputKind.HUMAN_ASSUMPTION,
            DriverInputKind.MODEL_INFERENCE,
        }:
            raise ValueError("scenario overrides must be human assumptions or model inference")
        _require_text(self.rationale, "ScenarioDriverOverride.rationale", maximum=500)
        _require_text(self.lineage_ref, "ScenarioDriverOverride.lineage_ref", maximum=255)


@dataclass(frozen=True)
class ForecastAssumptionDraft:
    """Sector-owned DTO convertible to an Equity forecast assumption."""

    scenario: ForecastScenario
    assumption_key: str
    value: Decimal
    unit: str
    input_kind: DriverInputKind
    rationale: str
    observed_fact_version_id: int | None = None
    human_assumption_ref: str = ""
    model_version: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("ForecastAssumptionDraft.scenario is invalid")
        _require_token(
            self.assumption_key,
            "ForecastAssumptionDraft.assumption_key",
            maximum=80,
        )
        _require_finite(self.value, "ForecastAssumptionDraft.value")
        _require_text(self.unit, "ForecastAssumptionDraft.unit", maximum=40)
        if not isinstance(self.input_kind, DriverInputKind):
            raise ValueError("ForecastAssumptionDraft.input_kind is invalid")
        _require_text(self.rationale, "ForecastAssumptionDraft.rationale", maximum=500)
        fact_present = self.observed_fact_version_id is not None
        if fact_present and (
            isinstance(self.observed_fact_version_id, bool)
            or (self.observed_fact_version_id or 0) <= 0
        ):
            raise ValueError("observed_fact_version_id must be positive")
        populated = {
            DriverInputKind.OBSERVED_FACT: fact_present,
            DriverInputKind.HUMAN_ASSUMPTION: bool(self.human_assumption_ref.strip()),
            DriverInputKind.MODEL_INFERENCE: bool(self.model_version.strip()),
        }
        if not populated[self.input_kind] or sum(populated.values()) != 1:
            raise ValueError("forecast draft lineage must match exactly one input kind")

    @property
    def lineage_ref(self) -> str:
        """Return the single provenance reference for composition conversion."""

        if self.input_kind is DriverInputKind.OBSERVED_FACT:
            return f"data_center_pit_fact:{self.observed_fact_version_id}"
        if self.input_kind is DriverInputKind.HUMAN_ASSUMPTION:
            return self.human_assumption_ref
        return self.model_version

    def to_payload(self) -> dict[str, object]:
        """Return an Equity-compatible assumption payload."""

        return {
            "assumption_key": self.assumption_key,
            "input_kind": self.input_kind.value,
            "lineage_ref": self.lineage_ref,
            "rationale": self.rationale,
            "scenario": self.scenario.value,
            "unit": self.unit,
            "value": _decimal_text(self.value),
        }


@dataclass(frozen=True)
class StageValue:
    """Calculated output for one audited financial stage."""

    stage: FinancialStage
    node_key: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, FinancialStage):
            raise ValueError("StageValue.stage is invalid")
        _require_token(self.node_key, "StageValue.node_key", maximum=80)
        _require_finite(self.value, "StageValue.value")
        _require_text(self.unit, "StageValue.unit", maximum=40)

    def to_payload(self) -> dict[str, object]:
        """Return the exact stage result as canonical JSON data."""

        return {
            "node_key": self.node_key,
            "stage": self.stage.value,
            "unit": self.unit,
            "value": _decimal_text(self.value),
        }


@dataclass(frozen=True)
class ForecastProjectionDraft:
    """Sector DTO convertible after Equity composition adds sensitivities."""

    scenario: ForecastScenario
    revenue: Decimal
    net_profit: Decimal
    cash_flow: Decimal
    currency_unit: str
    stage_values: tuple[StageValue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("ForecastProjectionDraft.scenario is invalid")
        for value, field_name in (
            (self.revenue, "revenue"),
            (self.net_profit, "net_profit"),
            (self.cash_flow, "cash_flow"),
        ):
            _require_finite(value, f"ForecastProjectionDraft.{field_name}")
        if self.revenue <= 0:
            raise ValueError("ForecastProjectionDraft.revenue must be positive")
        _require_text(
            self.currency_unit,
            "ForecastProjectionDraft.currency_unit",
            maximum=40,
        )
        if {value.stage for value in self.stage_values} != set(FinancialStage) or len(
            self.stage_values
        ) != len(FinancialStage):
            raise ValueError("projection draft must contain every financial stage")

    def to_payload(self) -> dict[str, object]:
        """Return the operating projection before valuation sensitivities."""

        return {
            "cash_flow": _decimal_text(self.cash_flow),
            "currency_unit": self.currency_unit,
            "net_profit": _decimal_text(self.net_profit),
            "revenue": _decimal_text(self.revenue),
            "scenario": self.scenario.value,
            "stage_values": [
                value.to_payload()
                for value in sorted(self.stage_values, key=lambda item: item.stage.value)
            ],
        }


@dataclass(frozen=True)
class OperatingForecastDraft:
    """Cycle-free DTO for an Equity composition root to convert and persist."""

    forecast_id: str
    forecast_key: str
    forecast_version: int
    subject_code: str
    industry_code: str
    as_of_time: datetime
    target_period_end: date
    horizon_quarters: int
    methodology_ref: str
    created_by_ref: str
    template_code: str
    template_version: int
    template_content_hash: str
    fact_version_ids: tuple[int, ...]
    assumptions: tuple[ForecastAssumptionDraft, ...]
    projections: tuple[ForecastProjectionDraft, ...]
    research_only: bool = True

    def __post_init__(self) -> None:
        for value, field_name, maximum in (
            (self.forecast_id, "forecast_id", 64),
            (self.forecast_key, "forecast_key", 128),
            (self.subject_code, "subject_code", 80),
            (self.industry_code, "industry_code", 80),
            (self.created_by_ref, "created_by_ref", 128),
            (self.template_code, "template_code", 80),
        ):
            _require_token(value, f"OperatingForecastDraft.{field_name}", maximum=maximum)
        for version_value, field_name in (
            (self.forecast_version, "forecast_version"),
            (self.horizon_quarters, "horizon_quarters"),
            (self.template_version, "template_version"),
        ):
            if isinstance(version_value, bool) or version_value <= 0:
                raise ValueError(f"OperatingForecastDraft.{field_name} must be positive")
        _require_aware(self.as_of_time, "OperatingForecastDraft.as_of_time")
        if self.target_period_end < self.as_of_time.date():
            raise ValueError("forecast draft target_period_end precedes as_of_time")
        _require_text(
            self.methodology_ref,
            "OperatingForecastDraft.methodology_ref",
            maximum=300,
        )
        _require_sha256(
            self.template_content_hash,
            "OperatingForecastDraft.template_content_hash",
        )
        if not self.research_only:
            raise ValueError("operating forecast drafts must remain research-only")
        if not self.fact_version_ids or len(set(self.fact_version_ids)) != len(
            self.fact_version_ids
        ):
            raise ValueError("forecast draft requires unique PIT fact versions")
        if any(
            isinstance(version_id, bool) or version_id <= 0 for version_id in self.fact_version_ids
        ):
            raise ValueError("forecast draft PIT fact versions must be positive")
        scenarios = [projection.scenario for projection in self.projections]
        if set(scenarios) != set(ForecastScenario) or len(scenarios) != len(ForecastScenario):
            raise ValueError("forecast draft requires exactly base, bull and bear")
        fact_ids = set(self.fact_version_ids)
        for scenario in ForecastScenario:
            scenario_assumptions = [item for item in self.assumptions if item.scenario is scenario]
            if not scenario_assumptions:
                raise ValueError(f"{scenario.value} forecast draft requires assumptions")
            observed_ids = {
                item.observed_fact_version_id
                for item in scenario_assumptions
                if item.input_kind is DriverInputKind.OBSERVED_FACT
            }
            if not observed_ids or not observed_ids.issubset(fact_ids):
                raise ValueError("forecast draft observed assumptions need captured PIT facts")

    def to_payload(self) -> dict[str, object]:
        """Return the complete cross-App forecast draft without Equity imports."""

        return {
            "as_of_time": _utc_iso(self.as_of_time),
            "assumptions": [
                assumption.to_payload()
                for assumption in sorted(
                    self.assumptions,
                    key=lambda item: (item.scenario.value, item.assumption_key),
                )
            ],
            "created_by_ref": self.created_by_ref,
            "fact_version_ids": list(self.fact_version_ids),
            "forecast_id": self.forecast_id,
            "forecast_key": self.forecast_key,
            "forecast_version": self.forecast_version,
            "horizon_quarters": self.horizon_quarters,
            "industry_code": self.industry_code,
            "methodology_ref": self.methodology_ref,
            "projections": [
                projection.to_payload()
                for projection in sorted(
                    self.projections,
                    key=lambda item: item.scenario.value,
                )
            ],
            "research_only": self.research_only,
            "subject_code": self.subject_code,
            "target_period_end": self.target_period_end.isoformat(),
            "template_code": self.template_code,
            "template_content_hash": self.template_content_hash,
            "template_version": self.template_version,
        }


@dataclass(frozen=True)
class IndustryTemplateRunResult:
    """Fail-closed and research-only result of one template execution."""

    run_key: str
    run_version: int
    template_code: str
    template_version: int
    template_content_hash: str
    subject_code: str
    industry_code: str
    as_of_time: datetime
    status: TemplateRunStatus
    facts: tuple[PITDriverFact, ...]
    forecast_draft: OperatingForecastDraft | None
    blocked_reasons: tuple[str, ...]
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_token(self.run_key, "IndustryTemplateRunResult.run_key", maximum=128)
        if isinstance(self.run_version, bool) or self.run_version <= 0:
            raise ValueError("IndustryTemplateRunResult.run_version must be positive")
        _require_token(
            self.template_code,
            "IndustryTemplateRunResult.template_code",
            maximum=80,
        )
        if isinstance(self.template_version, bool) or self.template_version <= 0:
            raise ValueError("IndustryTemplateRunResult.template_version must be positive")
        if self.template_content_hash:
            _require_sha256(
                self.template_content_hash,
                "IndustryTemplateRunResult.template_content_hash",
            )
        _require_token(self.subject_code, "IndustryTemplateRunResult.subject_code", maximum=80)
        _require_token(self.industry_code, "IndustryTemplateRunResult.industry_code", maximum=80)
        _require_aware(self.as_of_time, "IndustryTemplateRunResult.as_of_time")
        if not isinstance(self.status, TemplateRunStatus):
            raise ValueError("IndustryTemplateRunResult.status is invalid")
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("industry template runs must remain research-only")
        if self.status is TemplateRunStatus.BLOCKED:
            if not self.blocked_reasons or self.forecast_draft is not None:
                raise ValueError("blocked template run requires reasons and no forecast draft")
        elif self.blocked_reasons or self.forecast_draft is None:
            raise ValueError("available template run requires a draft and no blockers")

    def to_payload(self) -> dict[str, object]:
        """Return exact facts, output or blockers for immutable run evidence."""

        return {
            "as_of_time": _utc_iso(self.as_of_time),
            "blocked_reasons": list(self.blocked_reasons),
            "facts": [
                fact.to_payload() for fact in sorted(self.facts, key=lambda item: item.version_id)
            ],
            "forecast_draft": (
                self.forecast_draft.to_payload() if self.forecast_draft is not None else None
            ),
            "industry_code": self.industry_code,
            "must_not_execute": self.must_not_execute,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "research_only": self.research_only,
            "run_key": self.run_key,
            "run_version": self.run_version,
            "status": self.status.value,
            "subject_code": self.subject_code,
            "template_code": self.template_code,
            "template_content_hash": self.template_content_hash,
            "template_version": self.template_version,
        }

    @property
    def content_hash(self) -> str:
        """Seal all input evidence, output values and fail-closed state."""

        return _canonical_hash(self.to_payload())


from apps.sector.domain import industry_operating_template_evidence as _evidence  # noqa: E402

ImmutableTemplateRunEvidence = _evidence.ImmutableTemplateRunEvidence
TemplateEvaluationError = _evidence.TemplateEvaluationError
build_template_run_evidence = _evidence.build_template_run_evidence
evaluate_template = _evidence.evaluate_template
restore_template_run_result = _evidence.restore_template_run_result
_evidence_bool = _evidence._evidence_bool
_evidence_date = _evidence._evidence_date
_evidence_datetime = _evidence._evidence_datetime
_evidence_decimal = _evidence._evidence_decimal
_evidence_int = _evidence._evidence_int
_evidence_list = _evidence._evidence_list
_evidence_object = _evidence._evidence_object
_evidence_text = _evidence._evidence_text
_restore_assumption = _evidence._restore_assumption

__all__ = [
    "DriverDefinition",
    "DriverInputKind",
    "ExpressionNode",
    "ExpressionOperator",
    "FinancialStage",
    "ForecastAssumptionDraft",
    "ForecastProjectionDraft",
    "ForecastScenario",
    "ImmutableTemplateRunEvidence",
    "IndustryOperatingTemplate",
    "IndustryTemplateRunResult",
    "OperatingForecastDraft",
    "PITDriverFact",
    "ScenarioDriverOverride",
    "StageOutput",
    "StageValue",
    "TemplateEvaluationError",
    "TemplateLifecycle",
    "TemplateRunStatus",
    "UnitDerivationRule",
    "ValueReference",
    "ValueReferenceKind",
    "build_template_run_evidence",
    "evaluate_template",
    "restore_template_run_result",
]
