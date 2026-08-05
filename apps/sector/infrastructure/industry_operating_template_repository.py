"""Django persistence and Data Center adapter for R1 industry templates."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.data_center.application.research_data_foundation import (
    get_research_data_foundation_facade,
)
from apps.data_center.domain.pit import KnowledgeScope, PITFactVersion, PITQuality
from apps.data_center.domain.research_data_foundation import ObservationValueKind
from apps.sector.domain.industry_operating_template import (
    DriverDefinition,
    DriverInputKind,
    ExpressionNode,
    ExpressionOperator,
    FinancialStage,
    ImmutableTemplateRunEvidence,
    IndustryOperatingTemplate,
    PITDriverFact,
    StageOutput,
    TemplateLifecycle,
    TemplateRunStatus,
    UnitDerivationRule,
    ValueReference,
    ValueReferenceKind,
)

from .industry_operating_template_models import (
    IndustryOperatingTemplateVersionModel,
    IndustryTemplateRunEvidenceModel,
)


def _as_mapping(value: object, field_name: str) -> dict[str, Any]:
    """Narrow one JSON object at the ORM boundary."""

    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return cast(dict[str, Any], value)


def _as_list(value: object, field_name: str) -> list[Any]:
    """Narrow one JSON array at the ORM boundary."""

    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return value


def _as_str(value: object, field_name: str, *, allow_blank: bool = False) -> str:
    """Narrow one JSON string at the ORM boundary."""

    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError(f"{field_name} must be a string")
    return value


def _as_int(value: object, field_name: str, *, allow_zero: bool = False) -> int:
    """Narrow one JSON integer at the ORM boundary."""

    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{field_name} must be an integer")
    return value


def _as_bool(value: object, field_name: str) -> bool:
    """Narrow one strict JSON boolean at the ORM boundary."""

    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _as_datetime(value: object, field_name: str) -> datetime:
    """Parse one ISO timestamp and require timezone awareness."""

    text = _as_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _template_from_payload(payload: dict[str, Any]) -> IndustryOperatingTemplate:
    """Reconstruct and revalidate one stored immutable template version."""

    drivers: list[DriverDefinition] = []
    for raw_driver in _as_list(payload.get("drivers"), "drivers"):
        item = _as_mapping(raw_driver, "driver")
        drivers.append(
            DriverDefinition(
                driver_key=_as_str(item.get("driver_key"), "driver_key"),
                name=_as_str(item.get("name"), "name"),
                unit=_as_str(item.get("unit"), "unit"),
                frequency=_as_str(item.get("frequency"), "frequency"),
                source=_as_str(item.get("source"), "source"),
                allowed_input_kinds=tuple(
                    DriverInputKind(_as_str(value, "allowed_input_kind"))
                    for value in _as_list(
                        item.get("allowed_input_kinds"),
                        "allowed_input_kinds",
                    )
                ),
                metric_code=_as_str(
                    item.get("metric_code", ""),
                    "metric_code",
                    allow_blank=True,
                ),
                metric_definition_version=_as_int(
                    item.get("metric_definition_version", 0),
                    "metric_definition_version",
                    allow_zero=True,
                ),
                subject_type=_as_str(
                    item.get("subject_type", ""),
                    "subject_type",
                    allow_blank=True,
                ),
                description=_as_str(
                    item.get("description", ""),
                    "description",
                    allow_blank=True,
                ),
            )
        )
    rules: list[UnitDerivationRule] = []
    for raw_rule in _as_list(payload.get("unit_rules"), "unit_rules"):
        item = _as_mapping(raw_rule, "unit_rule")
        rules.append(
            UnitDerivationRule(
                rule_key=_as_str(item.get("rule_key"), "rule_key"),
                operator=ExpressionOperator(_as_str(item.get("operator"), "operator")),
                left_unit=_as_str(item.get("left_unit"), "left_unit"),
                right_unit=_as_str(item.get("right_unit"), "right_unit"),
                output_unit=_as_str(item.get("output_unit"), "output_unit"),
                methodology_ref=_as_str(
                    item.get("methodology_ref"),
                    "methodology_ref",
                ),
            )
        )
    nodes: list[ExpressionNode] = []
    for raw_node in _as_list(payload.get("nodes"), "nodes"):
        item = _as_mapping(raw_node, "node")
        operands = tuple(
            ValueReference(
                kind=ValueReferenceKind(
                    _as_str(
                        _as_mapping(raw_operand, "operand").get("kind"),
                        "operand.kind",
                    )
                ),
                key=_as_str(
                    _as_mapping(raw_operand, "operand").get("key"),
                    "operand.key",
                ),
            )
            for raw_operand in _as_list(item.get("operands"), "operands")
        )
        nodes.append(
            ExpressionNode(
                node_key=_as_str(item.get("node_key"), "node_key"),
                stage=FinancialStage(_as_str(item.get("stage"), "stage")),
                operator=ExpressionOperator(_as_str(item.get("operator"), "operator")),
                operands=operands,
                output_unit=_as_str(item.get("output_unit"), "output_unit"),
                unit_rule_key=_as_str(
                    item.get("unit_rule_key", ""),
                    "unit_rule_key",
                    allow_blank=True,
                ),
            )
        )
    outputs = tuple(
        StageOutput(
            stage=FinancialStage(
                _as_str(_as_mapping(raw_output, "stage_output").get("stage"), "stage")
            ),
            node_key=_as_str(
                _as_mapping(raw_output, "stage_output").get("node_key"),
                "node_key",
            ),
        )
        for raw_output in _as_list(payload.get("stage_outputs"), "stage_outputs")
    )
    effective_to_raw = payload.get("effective_to")
    supersedes_raw = payload.get("supersedes_version")
    template = IndustryOperatingTemplate(
        template_code=_as_str(payload.get("template_code"), "template_code"),
        template_version=_as_int(payload.get("template_version"), "template_version"),
        industry_code=_as_str(payload.get("industry_code"), "industry_code"),
        name=_as_str(payload.get("name"), "name"),
        methodology_ref=_as_str(payload.get("methodology_ref"), "methodology_ref"),
        effective_at=_as_datetime(payload.get("effective_at"), "effective_at"),
        effective_to=(
            _as_datetime(effective_to_raw, "effective_to") if effective_to_raw is not None else None
        ),
        lifecycle=TemplateLifecycle(_as_str(payload.get("lifecycle"), "lifecycle")),
        lifecycle_reason=_as_str(
            payload.get("lifecycle_reason", ""),
            "lifecycle_reason",
            allow_blank=True,
        ),
        supersedes_version=(
            _as_int(supersedes_raw, "supersedes_version") if supersedes_raw is not None else None
        ),
        description=_as_str(
            payload.get("description", ""),
            "description",
            allow_blank=True,
        ),
        drivers=tuple(drivers),
        unit_rules=tuple(rules),
        nodes=tuple(nodes),
        stage_outputs=outputs,
        research_only=_as_bool(payload.get("research_only"), "research_only"),
    )
    return template


class DjangoIndustryTemplateRepository:
    """Append and retrieve hash-verified templates and run evidence."""

    @transaction.atomic
    def append_template(
        self,
        template: IndustryOperatingTemplate,
    ) -> IndustryOperatingTemplate:
        """Insert idempotently and reject conflicting template identities."""

        existing = (
            IndustryOperatingTemplateVersionModel._default_manager.select_for_update()
            .filter(
                template_code=template.template_code,
                template_version=template.template_version,
            )
            .first()
        )
        if existing is not None:
            stored = _template_from_payload(cast(dict[str, Any], existing.payload))
            if stored != template or existing.content_hash != template.content_hash:
                raise ValueError("industry template version has conflicting content")
            return stored
        if template.supersedes_version is not None and not (
            IndustryOperatingTemplateVersionModel._default_manager.filter(
                template_code=template.template_code,
                template_version=template.supersedes_version,
            ).exists()
        ):
            raise ValueError("superseded industry template version was not found")
        model = IndustryOperatingTemplateVersionModel(
            template_code=template.template_code,
            template_version=template.template_version,
            industry_code=template.industry_code,
            name=template.name,
            methodology_ref=template.methodology_ref,
            effective_at=template.effective_at,
            effective_to=template.effective_to,
            lifecycle=template.lifecycle.value,
            lifecycle_reason=template.lifecycle_reason,
            supersedes_version=template.supersedes_version,
            content_hash=template.content_hash,
            payload=template.to_payload(),
            research_only=template.research_only,
        )
        try:
            model.full_clean()
            model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid industry operating template") from exc
        return _template_from_payload(cast(dict[str, Any], model.payload))

    def get_template(
        self,
        *,
        template_code: str,
        template_version: int,
    ) -> IndustryOperatingTemplate | None:
        """Return one exact template after payload and content-hash verification."""

        model = IndustryOperatingTemplateVersionModel._default_manager.filter(
            template_code=template_code,
            template_version=template_version,
        ).first()
        if model is None:
            return None
        template = _template_from_payload(cast(dict[str, Any], model.payload))
        if template.content_hash != model.content_hash:
            raise ValueError("stored industry template content hash mismatch")
        return template

    @transaction.atomic
    def append_run_evidence(
        self,
        evidence: ImmutableTemplateRunEvidence,
    ) -> ImmutableTemplateRunEvidence:
        """Insert idempotently and reject conflicting run evidence versions."""

        existing = (
            IndustryTemplateRunEvidenceModel._default_manager.select_for_update()
            .filter(run_key=evidence.run_key, run_version=evidence.run_version)
            .first()
        )
        if existing is not None:
            stored = self._run_evidence_to_domain(existing)
            if stored != evidence:
                raise ValueError("industry template run version has conflicting content")
            return stored
        parsed = json.loads(evidence.payload_json)
        if not isinstance(parsed, dict):
            raise ValueError("industry template run payload must be an object")
        model = IndustryTemplateRunEvidenceModel(
            run_key=evidence.run_key,
            run_version=evidence.run_version,
            template_code=evidence.template_code,
            template_version=evidence.template_version,
            template_content_hash=evidence.template_content_hash,
            as_of_time=evidence.as_of_time,
            status=evidence.status.value,
            content_hash=evidence.content_hash,
            payload=cast(dict[str, object], parsed),
            research_only=evidence.research_only,
            must_not_use_for_decision=evidence.must_not_use_for_decision,
            must_not_execute=evidence.must_not_execute,
        )
        try:
            model.full_clean()
            model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid industry template run evidence") from exc
        return self._run_evidence_to_domain(model)

    def get_run_evidence(
        self,
        *,
        run_key: str,
        run_version: int,
    ) -> ImmutableTemplateRunEvidence | None:
        """Return one exact hash-verified run evidence version."""

        model = IndustryTemplateRunEvidenceModel._default_manager.filter(
            run_key=run_key,
            run_version=run_version,
        ).first()
        return self._run_evidence_to_domain(model) if model is not None else None

    @staticmethod
    def _run_evidence_to_domain(
        model: IndustryTemplateRunEvidenceModel,
    ) -> ImmutableTemplateRunEvidence:
        """Reconstruct one stored run evidence record."""

        return ImmutableTemplateRunEvidence(
            run_key=model.run_key,
            run_version=model.run_version,
            template_code=model.template_code,
            template_version=model.template_version,
            template_content_hash=model.template_content_hash,
            as_of_time=model.as_of_time,
            status=TemplateRunStatus(model.status),
            content_hash=model.content_hash,
            payload_json=json.dumps(
                model.payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            research_only=model.research_only,
            must_not_use_for_decision=model.must_not_use_for_decision,
            must_not_execute=model.must_not_execute,
        )


class DataCenterOperatingDriverFactProvider:
    """Resolve verified Data Center PIT operating facts for Sector Application."""

    def get_fact(
        self,
        driver: DriverDefinition,
        *,
        subject_code: str,
        as_of_time: datetime,
    ) -> PITDriverFact | None:
        """Return one latest effective fact known by the explicit public clock."""

        if DriverInputKind.OBSERVED_FACT not in driver.allowed_input_kinds:
            raise ValueError("driver is not fact-backed")
        facts = get_research_data_foundation_facade().list_operating_observations(
            metric_code=driver.metric_code,
            definition_version=driver.metric_definition_version,
            value_kind=ObservationValueKind.OBSERVED_FACT,
            as_of_time=as_of_time,
            knowledge_scope=KnowledgeScope.PUBLIC,
            subject_code=subject_code,
        )
        candidates = [self._to_domain(item, driver=driver) for item in facts]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.effective_at, item.available_at, item.version_id),
        )

    @staticmethod
    def _to_domain(
        fact: PITFactVersion,
        *,
        driver: DriverDefinition,
    ) -> PITDriverFact:
        """Narrow and verify one dynamic canonical PIT payload."""

        if fact.pit_quality is not PITQuality.VERIFIED or fact.available_at is None:
            raise ValueError("operating driver fact is not verified public evidence")
        payload = fact.payload
        value_raw = payload.get("value")
        if isinstance(value_raw, bool) or not isinstance(value_raw, (str, int, float)):
            raise ValueError("operating driver fact value is invalid")
        try:
            value = Decimal(str(value_raw))
        except InvalidOperation as exc:
            raise ValueError("operating driver fact value is invalid") from exc
        if not value.is_finite():
            raise ValueError("operating driver fact value is invalid")
        metric_code = _as_str(payload.get("metric_code"), "metric_code")
        definition_version = _as_int(
            payload.get("definition_version"),
            "definition_version",
        )
        subject_type = _as_str(payload.get("subject_type"), "subject_type")
        subject_code = _as_str(payload.get("subject_code"), "subject_code")
        unit = _as_str(payload.get("unit"), "unit")
        frequency = _as_str(payload.get("frequency"), "frequency")
        source = _as_str(payload.get("source"), "source")
        if (
            metric_code != driver.metric_code
            or definition_version != driver.metric_definition_version
            or subject_type != driver.subject_type
            or unit != driver.unit
            or frequency != driver.frequency
            or source != driver.source
        ):
            raise ValueError("operating driver fact semantics mismatch")
        return PITDriverFact(
            version_id=fact.version_id,
            dataset=fact.dataset,
            business_key=fact.business_key,
            metric_code=metric_code,
            metric_definition_version=definition_version,
            subject_code=subject_code,
            effective_at=fact.effective_at,
            available_at=fact.available_at,
            value=value,
            unit=unit,
            frequency=frequency,
            source=source,
            source_record_id=fact.source_record_id,
            content_hash=fact.content_hash,
            is_verified=True,
        )


__all__ = [
    "DataCenterOperatingDriverFactProvider",
    "DjangoIndustryTemplateRepository",
]
