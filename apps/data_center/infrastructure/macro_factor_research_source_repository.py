"""Django persistence and strict PIT projection for the R3 source ledger."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.data_center.application.macro_factor_research_source import (
    ExactMacroFactorResearchSourceDefinitionOwner,
    MacroFactorResearchSourceConflict,
    MacroFactorResearchSourceUnavailable,
)
from apps.data_center.domain.macro_factor_research_source import (
    CanonicalMacroFactorPITFact,
    CanonicalMacroFactorPITProjection,
    MacroFactorResearchMemberRole,
    MacroFactorResearchSourceDefinition,
    MacroFactorValueEncoding,
    PersistedMacroFactorResearchSourceDefinition,
)
from apps.data_center.domain.pit import (
    KnowledgeScope,
    PITDatasetManifest,
    calculate_pit_manifest_hash,
)
from apps.data_center.infrastructure.macro_factor_research_source_codec import (
    decode_persisted_macro_factor_research_source,
    encode_persisted_macro_factor_research_source,
)
from apps.data_center.infrastructure.macro_factor_research_source_models import (
    MacroFactorResearchCalendarPeriodModel,
    MacroFactorResearchMemberRuleModel,
    MacroFactorResearchSourceDefinitionModel,
    _activate_macro_factor_source_uow,
    _claim_macro_factor_source_insert,
    _require_active_macro_factor_source_uow,
)
from apps.data_center.infrastructure.pit_models import (
    PITDatasetManifestModel,
    PITFactVersionModel,
)


class _SelectedVersion(TypedDict):
    id: int
    dataset: str
    business_key: str
    content_hash: str
    payload_hash: str
    pit_quality: str


class DjangoMacroFactorResearchSourceClock:
    """Django timezone-backed trusted registration clock."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = _using_alias(using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the timezone-aware application server time."""

        return timezone.now()


class DjangoMacroFactorResearchSourceDefinitionOwner:
    """Require a private owner read to occur inside the repository UoW."""

    __slots__ = ("_source", "_token")

    def __init__(
        self,
        source: ExactMacroFactorResearchSourceDefinitionOwner,
        *,
        token: object,
    ) -> None:
        self._source = source
        self._token = token

    @property
    def unit_of_work_key(self) -> str:
        """Return the wrapped owner transaction identity."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> MacroFactorResearchSourceDefinition | None:
        """Read the canonical owner only inside one active transaction."""

        _require_active_macro_factor_source_uow(self._token)
        return self._source.get_exact(
            source_id=source_id,
            source_version=source_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )


class DjangoMacroFactorResearchSourceReadRepository:
    """Public using-only exact reads over definitions and legacy PIT rows."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = _using_alias(using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the database/snapshot identity."""

        return f"django:{self._using}"

    def get_exact_source_definition(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedMacroFactorResearchSourceDefinition | None:
        """Return one exact registered definition visible at ``as_of``."""

        try:
            source_id = _token(source_id, "source_id")
            source_version = _token(source_version, "source_version")
            expected_content_hash = _hash(expected_content_hash, "expected_content_hash")
            as_of = _aware(as_of, "as_of")
            rows = list(
                MacroFactorResearchSourceDefinitionModel._default_manager.using(self._using).filter(
                    source_id=source_id, source_version=source_version
                )
            )
            if len(rows) != 1:
                return None
            record = _restore_source_model(rows[0], using=self._using)
            if (
                record.definition.content_hash.lower() != expected_content_hash
                or not record.is_active_at(as_of)
            ):
                return None
            return record
        except Exception:
            return None

    def get_exact_projection(
        self,
        *,
        manifest_id: str,
        expected_manifest_hash: str | None = None,
    ) -> CanonicalMacroFactorPITProjection | None:
        """Rebuild a complete exact graph or fail closed with ``None``."""

        try:
            return self._get_exact_projection(
                manifest_id=_token(manifest_id, "manifest_id"),
                expected_manifest_hash=(
                    None
                    if expected_manifest_hash is None
                    else _hash(expected_manifest_hash, "expected_manifest_hash")
                ),
            )
        except Exception:
            return None

    def _get_exact_projection(
        self,
        *,
        manifest_id: str,
        expected_manifest_hash: str | None,
    ) -> CanonicalMacroFactorPITProjection | None:
        manifest_rows = list(
            PITDatasetManifestModel._default_manager.using(self._using).filter(
                manifest_id=manifest_id
            )
        )
        if len(manifest_rows) != 1:
            return None
        manifest_model = manifest_rows[0]
        manifest = _restore_manifest(manifest_model)
        if expected_manifest_hash is not None and (
            manifest.manifest_hash.lower() != expected_manifest_hash
        ):
            return None
        source_rows = list(
            MacroFactorResearchSourceDefinitionModel._default_manager.using(self._using).filter(
                manifest_calendar_version=manifest.calendar_version
            )
        )
        if len(source_rows) != 1:
            return None
        source = _restore_source_model(source_rows[0], using=self._using)
        definition = source.definition
        created_at = _aware(manifest_model.created_at, "manifest created_at")
        if (
            manifest.knowledge_scope is not KnowledgeScope.PUBLIC
            or not source.is_active_at(manifest.as_of_time)
            or source.ledger_recorded_at > created_at
            or manifest.as_of_time > created_at
            or manifest.query_spec != _expected_query_spec(definition)
        ):
            return None
        coverage_ratio = _verified_coverage(manifest, definition)
        selected = _selected_by_identity(manifest, definition)
        version_ids = tuple(item["id"] for item in selected.values())
        fact_rows = list(
            PITFactVersionModel._default_manager.using(self._using).filter(pk__in=version_ids)
        )
        if len(fact_rows) != len(version_ids):
            return None
        facts_by_id = {row.pk: row for row in fact_rows}
        facts = tuple(
            _restore_fact(
                rule=rule,
                period=next(item for item in definition.periods if item.row_id == rule.row_id),
                selected=selected[(rule.dataset_key, rule.business_key)],
                model=facts_by_id[selected[(rule.dataset_key, rule.business_key)]["id"]],
                manifest_as_of=manifest.as_of_time,
                manifest_created_at=created_at,
            )
            for rule in definition.members
        )
        return CanonicalMacroFactorPITProjection(
            source=source,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
            manifest_as_of=manifest.as_of_time,
            manifest_created_at=created_at,
            knowledge_scope=manifest.knowledge_scope.value,
            coverage_ratio=coverage_ratio,
            missing_count=0,
            estimated_count=0,
            unknown_count=0,
            is_verified=True,
            facts=facts,
        ).validated_copy()


class _DjangoMacroFactorResearchSourceStore:
    """Private append capability absent from production runtime graphs."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = _using_alias(using)
        self._token = object()

    @property
    def token(self) -> object:
        """Return the opaque capability needed by the private owner wrapper."""

        return self._token

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one database transaction and private insert capability."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with (
            transaction.atomic(using=self._using),
            _activate_macro_factor_source_uow(self._token),
        ):
            yield

    def append_source_definition(
        self,
        record: PersistedMacroFactorResearchSourceDefinition,
    ) -> PersistedMacroFactorResearchSourceDefinition:
        """Append the complete graph or return its exact idempotent winner."""

        _require_active_macro_factor_source_uow(self._token)
        if type(record) is not PersistedMacroFactorResearchSourceDefinition:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source append record type differs"
            )
        validated = record.validated_copy()
        rows = self._colliding_rows(validated)
        if len(rows) > 1:
            raise MacroFactorResearchSourceUnavailable("multiple macro-factor source rows collide")
        if rows:
            winner = _restore_source_model(rows[0], using=self._using)
            if winner == validated:
                return winner
            raise MacroFactorResearchSourceConflict(
                "macro-factor source identity already has another winner"
            )
        try:
            with transaction.atomic(using=self._using):
                model = self._insert_graph(validated)
        except IntegrityError as error:
            rows = self._colliding_rows(validated)
            if len(rows) == 1:
                winner = _restore_source_model(rows[0], using=self._using)
                if winner == validated:
                    return winner
            raise MacroFactorResearchSourceConflict(
                "macro-factor source append race or fork lost"
            ) from error
        winner = _restore_source_model(model, using=self._using)
        if winner != validated:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source repository changed the appended graph"
            )
        return winner

    def _colliding_rows(
        self,
        record: PersistedMacroFactorResearchSourceDefinition,
    ) -> list[MacroFactorResearchSourceDefinitionModel]:
        definition = record.definition
        return list(
            MacroFactorResearchSourceDefinitionModel._default_manager.using(self._using).filter(
                Q(source_id=definition.source_id, source_version=definition.source_version)
                | Q(source_content_hash=definition.content_hash)
                | Q(manifest_calendar_version=definition.manifest_calendar_version)
                | Q(record_hash=record.record_hash)
            )
        )

    def _insert_graph(
        self,
        record: PersistedMacroFactorResearchSourceDefinition,
    ) -> MacroFactorResearchSourceDefinitionModel:
        source_values = _source_values(record)
        with _claim_macro_factor_source_insert(
            token=self._token,
            model_name=MacroFactorResearchSourceDefinitionModel._meta.label_lower,
            expected_values=source_values,
        ):
            source = MacroFactorResearchSourceDefinitionModel._default_manager.using(
                self._using
            ).create(**source_values)
        period_models: dict[str, MacroFactorResearchCalendarPeriodModel] = {}
        for period in record.definition.periods:
            values = _period_values(source.pk, period.canonical_payload())
            with _claim_macro_factor_source_insert(
                token=self._token,
                model_name=MacroFactorResearchCalendarPeriodModel._meta.label_lower,
                expected_values=values,
            ):
                period_models[period.row_id] = (
                    MacroFactorResearchCalendarPeriodModel._default_manager.using(
                        self._using
                    ).create(**values)
                )
        for member in record.definition.members:
            values = _member_values(
                source.pk,
                period_models[member.row_id].pk,
                member.canonical_payload(),
            )
            with _claim_macro_factor_source_insert(
                token=self._token,
                model_name=MacroFactorResearchMemberRuleModel._meta.label_lower,
                expected_values=values,
            ):
                MacroFactorResearchMemberRuleModel._default_manager.using(self._using).create(
                    **values
                )
        return source


def _source_values(
    record: PersistedMacroFactorResearchSourceDefinition,
) -> dict[str, object]:
    definition = record.definition
    policy = definition.coverage_policy
    return {
        "source_id": definition.source_id,
        "source_version": definition.source_version,
        "source_content_hash": definition.content_hash,
        "manifest_calendar_version": definition.manifest_calendar_version,
        "owner": definition.owner,
        "target_code": definition.target_code,
        "candidate_asset_codes": list(definition.candidate_asset_codes),
        "calendar_id": definition.calendar.calendar_id,
        "calendar_version": definition.calendar.calendar_version,
        "calendar_content_hash": definition.calendar.content_hash,
        "source_contract_id": definition.source_contract.stable_id,
        "source_contract_version": definition.source_contract.version,
        "source_contract_hash": definition.source_contract.content_hash,
        "knowledge_scope": definition.knowledge_scope,
        "require_verified": policy.require_verified,
        "minimum_coverage_ratio": policy.minimum_coverage_ratio,
        "maximum_missing_count": policy.maximum_missing_count,
        "maximum_estimated_count": policy.maximum_estimated_count,
        "maximum_unknown_count": policy.maximum_unknown_count,
        "registered_at": definition.registered_at,
        "valid_until": definition.valid_until,
        "ledger_recorded_at": record.ledger_recorded_at,
        "canonical_payload": encode_persisted_macro_factor_research_source(record),
        "record_hash": record.record_hash,
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def _period_values(source_pk: object, payload: dict[str, str]) -> dict[str, object]:
    return {
        "source_definition_id": source_pk,
        "row_id": payload["row_id"],
        "period_id": payload["period_id"],
        "kind": payload["kind"],
        "observation_date": _date_from_text(payload["observation_date"]),
        "target_period_start": _date_from_text(payload["target_period_start"]),
        "target_period_end": _date_from_text(payload["target_period_end"]),
        "canonical_payload": payload,
        "content_hash": _stable_hash(payload),
    }


def _member_values(
    source_pk: object,
    period_pk: object,
    payload: dict[str, str],
) -> dict[str, object]:
    return {
        "source_definition_id": source_pk,
        "period_id": period_pk,
        "row_id": payload["row_id"],
        "role": payload["role"],
        "member_code": payload["member_code"],
        "dataset_key": payload["dataset_key"],
        "business_key": payload["business_key"],
        "value_field": payload["value_field"],
        "unit_field": payload["unit_field"],
        "expected_unit": payload["expected_unit"],
        "value_encoding": payload["value_encoding"],
        "canonical_payload": payload,
        "content_hash": _stable_hash(payload),
    }


def _restore_source_model(
    model: MacroFactorResearchSourceDefinitionModel,
    *,
    using: str,
) -> PersistedMacroFactorResearchSourceDefinition:
    record = decode_persisted_macro_factor_research_source(model.canonical_payload)
    if _source_values(record) != {field: getattr(model, field) for field in _source_values(record)}:
        raise MacroFactorResearchSourceUnavailable(
            "macro-factor source header differs from its sealed payload"
        )
    periods = list(
        MacroFactorResearchCalendarPeriodModel._default_manager.using(using)
        .filter(source_definition_id=model.pk)
        .order_by("row_id")
    )
    expected_periods = {item.row_id: item for item in record.definition.periods}
    if len(periods) != len(expected_periods):
        raise MacroFactorResearchSourceUnavailable(
            "macro-factor source calendar rows are incomplete"
        )
    period_pks: dict[str, object] = {}
    for period_row in periods:
        period = expected_periods.get(period_row.row_id)
        if period is None:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source calendar row is unexpected"
            )
        expected = _period_values(model.pk, period.canonical_payload())
        if expected != {field: getattr(period_row, field) for field in expected}:
            raise MacroFactorResearchSourceUnavailable("macro-factor source calendar row differs")
        period_pks[period_row.row_id] = period_row.pk
    members = list(
        MacroFactorResearchMemberRuleModel._default_manager.using(using)
        .filter(source_definition_id=model.pk)
        .order_by("row_id", "role", "member_code")
    )
    expected_members = {
        (item.row_id, item.role.value, item.member_code): item for item in record.definition.members
    }
    if len(members) != len(expected_members):
        raise MacroFactorResearchSourceUnavailable("macro-factor source member rows are incomplete")
    for member_row in members:
        member = expected_members.get((member_row.row_id, member_row.role, member_row.member_code))
        if member is None:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source member row is unexpected"
            )
        expected = _member_values(
            model.pk,
            period_pks[member.row_id],
            member.canonical_payload(),
        )
        if expected != {field: getattr(member_row, field) for field in expected}:
            raise MacroFactorResearchSourceUnavailable("macro-factor source member row differs")
    return record


def _restore_manifest(model: PITDatasetManifestModel) -> PITDatasetManifest:
    manifest_id = _token(model.manifest_id, "manifest_id")
    as_of = _aware(model.as_of_time, "manifest as_of")
    if model.knowledge_scope != KnowledgeScope.PUBLIC.value:
        raise ValueError("manifest knowledge scope differs")
    calendar_version = _token(model.calendar_version, "manifest calendar_version")
    query_spec_raw = _mapping(model.query_spec, "manifest query_spec")
    query_spec = cast(dict[str, dict[str, Any]], query_spec_raw)
    selected_raw = _list(model.selected_versions, "manifest selected_versions")
    selected = tuple(
        cast(dict[str, Any], _mapping(item, "manifest selected version")) for item in selected_raw
    )
    coverage_raw = _mapping(model.coverage, "manifest coverage")
    coverage: dict[str, float] = {}
    for key, value in coverage_raw.items():
        _token(key, "coverage dataset", maximum=64)
        if type(value) is not float or not math.isfinite(value):
            raise ValueError("manifest coverage value must be a finite JSON float")
        coverage[key] = value
    missing = tuple(
        cast(dict[str, Any], _mapping(item, "manifest missing item"))
        for item in _list(model.missing, "manifest missing")
    )
    estimated = tuple(
        cast(dict[str, Any], _mapping(item, "manifest estimated item"))
        for item in _list(model.estimated, "manifest estimated")
    )
    unknown = tuple(
        cast(dict[str, Any], _mapping(item, "manifest unknown item"))
        for item in _list(model.unknown, "manifest unknown")
    )
    manifest = PITDatasetManifest(
        manifest_id=manifest_id,
        as_of_time=as_of,
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version=calendar_version,
        query_spec=query_spec,
        selected_versions=selected,
        coverage=coverage,
        missing=missing,
        estimated=estimated,
        unknown=unknown,
        manifest_hash=_hash(model.manifest_hash, "manifest_hash"),
    )
    if calculate_pit_manifest_hash(manifest) != manifest.manifest_hash.lower():
        raise ValueError("manifest hash differs from its live graph")
    return manifest


def _expected_query_spec(
    definition: MacroFactorResearchSourceDefinition,
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[str]] = {}
    for item in definition.members:
        grouped.setdefault(item.dataset_key, []).append(item.business_key)
    return {
        dataset: {"business_key__in": sorted(keys)} for dataset, keys in sorted(grouped.items())
    }


def _verified_coverage(
    manifest: PITDatasetManifest,
    definition: MacroFactorResearchSourceDefinition,
) -> Decimal:
    expected_datasets = set(_expected_query_spec(definition))
    if (
        set(manifest.coverage) != expected_datasets
        or manifest.missing
        or manifest.estimated
        or manifest.unknown
    ):
        raise ValueError("manifest coverage evidence is incomplete")
    ratios = tuple(Decimal(str(manifest.coverage[key])) for key in sorted(expected_datasets))
    if not ratios or any(value != Decimal("1.0") for value in ratios):
        raise ValueError("R3 projection requires full exact coverage")
    return min(ratios)


def _selected_by_identity(
    manifest: PITDatasetManifest,
    definition: MacroFactorResearchSourceDefinition,
) -> dict[tuple[str, str], _SelectedVersion]:
    expected = {(item.dataset_key, item.business_key) for item in definition.members}
    result: dict[tuple[str, str], _SelectedVersion] = {}
    ordered: list[tuple[str, str]] = []
    for raw in manifest.selected_versions:
        if set(raw) != {
            "id",
            "dataset",
            "business_key",
            "content_hash",
            "payload_hash",
            "pit_quality",
        }:
            raise ValueError("manifest selected-version fields differ")
        version_id = raw["id"]
        if type(version_id) is not int or version_id <= 0:
            raise ValueError("manifest version id must be a positive exact int")
        identity = (
            _token(raw["dataset"], "selected dataset", maximum=64),
            _token(raw["business_key"], "selected business_key", maximum=255),
        )
        if identity in result:
            raise ValueError("manifest selected more than one version per member")
        result[identity] = {
            "id": version_id,
            "dataset": identity[0],
            "business_key": identity[1],
            "content_hash": _hash(raw["content_hash"], "selected content_hash"),
            "payload_hash": _hash(raw["payload_hash"], "selected payload_hash"),
            "pit_quality": _token(raw["pit_quality"], "selected pit_quality"),
        }
        ordered.append(identity)
    if set(result) != expected or len(result) != len(expected):
        raise ValueError("manifest selected-version graph is incomplete")
    if tuple(ordered) != tuple(sorted(ordered)):
        raise ValueError("manifest selected-version order is not canonical")
    if any(item["pit_quality"] != "verified" for item in result.values()):
        raise ValueError("R3 projection requires verified selected versions")
    return result


def _restore_fact(
    *,
    rule: object,
    period: object,
    selected: _SelectedVersion,
    model: PITFactVersionModel,
    manifest_as_of: datetime,
    manifest_created_at: datetime,
) -> CanonicalMacroFactorPITFact:
    from apps.data_center.domain.macro_factor_research_source import (
        MacroFactorResearchMemberRule,
        MacroFactorResearchPeriodRule,
    )

    if type(rule) is not MacroFactorResearchMemberRule or type(period) is not (
        MacroFactorResearchPeriodRule
    ):
        raise TypeError("macro-factor projection rule type differs")
    if (
        model.pk != selected["id"]
        or model.dataset != rule.dataset_key
        or model.business_key != rule.business_key
        or _hash(model.content_hash, "fact content_hash") != selected["content_hash"]
        or _stable_hash(model.payload) != selected["payload_hash"]
        or model.pit_quality != selected["pit_quality"]
    ):
        raise ValueError("selected PIT fact differs from manifest evidence")
    effective_at = _aware(model.effective_at, "fact effective_at")
    available_at = _aware(model.available_at, "fact available_at")
    ingested_at = _aware(model.ingested_at, "fact ingested_at")
    if (
        effective_at > manifest_as_of
        or available_at > manifest_as_of
        or ingested_at > manifest_created_at
        or available_at > ingested_at
    ):
        raise ValueError("selected PIT fact clock exceeds its manifest")
    if model.effective_to is not None:
        effective_to = _aware(model.effective_to, "fact effective_to")
        if effective_to <= manifest_as_of:
            raise ValueError("selected PIT fact was no longer effective")
    if model.superseded_at is not None:
        _aware(model.superseded_at, "fact superseded_at")
    if rule.role is MacroFactorResearchMemberRole.TARGET:
        if not period.target_period_start <= effective_at.date() <= period.target_period_end:
            raise ValueError("target fact falls outside its calendar period")
    elif effective_at.date() != period.observation_date:
        raise ValueError("proxy fact does not match its observation date")
    payload = _mapping(model.payload, "fact payload")
    if rule.value_field not in payload or rule.unit_field not in payload:
        raise ValueError("fact payload omits its declared value or unit")
    value = _decode_value(payload[rule.value_field], rule.value_encoding)
    unit = _token(payload[rule.unit_field], "fact unit")
    if unit != rule.expected_unit:
        raise ValueError("fact unit differs from its source definition")
    return CanonicalMacroFactorPITFact(
        row_id=rule.row_id,
        role=rule.role,
        member_code=rule.member_code,
        dataset_key=rule.dataset_key,
        business_key=rule.business_key,
        version_id=model.pk,
        content_hash=selected["content_hash"],
        payload_hash=selected["payload_hash"],
        source_record_id=_token(model.source_record_id, "fact source_record_id", maximum=255),
        revision_number=_non_negative_int(model.revision_number, "fact revision_number"),
        effective_at=effective_at,
        available_at=available_at,
        ingested_at=ingested_at,
        pit_quality=_token(model.pit_quality, "fact pit_quality"),
        value=value,
        unit=unit,
    )


def _decode_value(value: object, encoding: MacroFactorValueEncoding) -> Decimal:
    if encoding is MacroFactorValueEncoding.DECIMAL_TEXT:
        if type(value) is not str:
            raise ValueError("decimal-text fact value type differs")
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("decimal-text fact value is invalid") from error
        if not parsed.is_finite() or format(parsed, "f") != value:
            raise ValueError("decimal-text fact value is not canonical")
        return parsed
    if encoding is MacroFactorValueEncoding.JSON_NUMBER:
        if type(value) not in (int, float):
            raise ValueError("JSON-number fact value type differs")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("JSON-number fact value is not finite")
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise ValueError("JSON-number fact value is not finite")
        return parsed
    raise ValueError("fact value encoding differs")


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError(f"{field_name} must be an exact object")
    return cast(dict[str, object], value)


def _list(value: object, field_name: str) -> list[object]:
    if type(value) is not list:
        raise ValueError(f"{field_name} must be an exact list")
    return cast(list[object], value)


def _using_alias(value: object) -> str:
    return _token(value, "using", maximum=192)


def _token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact bounded token")
    return value


def _hash(value: object, field_name: str) -> str:
    text = _token(value, field_name, maximum=64)
    if len(text) != 64 or any(character not in "0123456789abcdefABCDEF" for character in text):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return text.lower()


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative exact int")
    return value


def _date_from_text(value: str) -> date:
    return date.fromisoformat(value)


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DjangoMacroFactorResearchSourceClock",
    "DjangoMacroFactorResearchSourceReadRepository",
]
