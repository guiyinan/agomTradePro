"""Strict append-only repository and PIT adapters for R7 analogy/path owners."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.domain.r7_analogy_path_owner import (
    AnalogyCandidateRawEvidence,
    HistoricalAnalogyDefinition,
    HistoricalAnalogyReceipt,
    PathObservedSampleMember,
    PathShockObservation,
    ScenarioPathDefinition,
    ScenarioPathReceipt,
)
from apps.research.domain.scenario_probability_contracts import ScenarioResearchScope
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyStudyEvidence,
    ScenarioPathStudyEvidence,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    _activate_r5_monitoring_uow,
    _claim_r5_monitoring_insert,
)
from apps.research.infrastructure.r7_analogy_path_owner_codec import (
    decode_historical_analogy_definition,
    decode_historical_analogy_receipt,
    decode_scenario_path_definition,
    decode_scenario_path_receipt,
    encode_historical_analogy_definition,
    encode_historical_analogy_receipt,
    encode_scenario_path_definition,
    encode_scenario_path_receipt,
)
from apps.research.infrastructure.r7_analogy_path_owner_models import (
    R7HistoricalAnalogyCandidateModel,
    R7HistoricalAnalogyDefinitionModel,
    R7HistoricalAnalogyReceiptModel,
    R7ScenarioPathDefinitionModel,
    R7ScenarioPathMemberModel,
    R7ScenarioPathReceiptModel,
)


class R7AnalogyPathOwnerConflict(RuntimeError):
    """One immutable identity has another exact winner or lost an append race."""


class R7AnalogyPathOwnerCorruption(RuntimeError):
    """Persisted headers, payloads, membership, or PIT winners were substituted."""


class R7AnalogyPathOwnerClock(Protocol):
    """Trusted clock required by private registration."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

    def now(self) -> datetime:
        """Return one authoritative timezone-aware timestamp."""


class DjangoR7AnalogyPathOwnerClock:
    """Django server clock bound to one database alias."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def now(self) -> datetime:
        return timezone.now()


class DjangoR7HistoricalAnalogyProvider:
    """Public read-only exact PIT adapter for the existing R7 analogy port."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self, *, scope: ScenarioResearchScope, as_of: datetime
    ) -> HistoricalAnalogyStudyEvidence | None:
        """Return the unique exact visible receipt or explicit absence."""

        scope_copy = _scope(scope)
        _aware(as_of, "R7 analogy query as_of")
        rows = tuple(
            R7HistoricalAnalogyReceiptModel._default_manager.using(self._using)
            .select_related("definition")
            .prefetch_related("candidates")
            .filter(
                scope_hash=scope_copy.content_hash,
                query_as_of__lte=as_of,
                source_available_at__lte=as_of,
                recorded_at__lte=as_of,
                definition__activated_at__lte=as_of,
                definition_valid_until__gt=as_of,
            )
        )
        if not rows:
            return None
        restored = tuple(_analogy_receipt_from_model(row) for row in rows)
        matches = tuple(item for item in restored if item.definition.scope == scope_copy)
        if len(rows) != 1 or len(matches) != 1:
            raise R7AnalogyPathOwnerCorruption(
                "R7 analogy PIT cutoff has multiple or substituted winners"
            )
        return matches[0].to_study_evidence()


class DjangoR7PathStudyProvider:
    """Public read-only exact PIT adapter for the existing R7 path-study port."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self, *, scope: ScenarioResearchScope, as_of: datetime
    ) -> ScenarioPathStudyEvidence | None:
        """Return the unique exact visible receipt or explicit absence."""

        scope_copy = _scope(scope)
        _aware(as_of, "R7 path query as_of")
        rows = tuple(
            R7ScenarioPathReceiptModel._default_manager.using(self._using)
            .select_related("definition")
            .prefetch_related("members")
            .filter(
                scope_hash=scope_copy.content_hash,
                pit_as_of__lte=as_of,
                source_available_at__lte=as_of,
                recorded_at__lte=as_of,
                definition__activated_at__lte=as_of,
                definition_valid_until__gt=as_of,
            )
        )
        if not rows:
            return None
        restored = tuple(_path_receipt_from_model(row) for row in rows)
        matches = tuple(item for item in restored if item.definition.scope == scope_copy)
        if len(rows) != 1 or len(matches) != 1:
            raise R7AnalogyPathOwnerCorruption(
                "R7 path PIT cutoff has multiple or substituted winners"
            )
        return matches[0].to_study_evidence()


class DjangoR7AnalogyDefinitionRepository:
    """Private/public exact identity provider used by receipt registration."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self, *, definition_id: str, definition_version: str, as_of: datetime
    ) -> HistoricalAnalogyDefinition | None:
        _identity_query(definition_id, definition_version, as_of)
        rows = tuple(
            R7HistoricalAnalogyDefinitionModel._default_manager.using(self._using).filter(
                Q(definition_id=definition_id, definition_version=definition_version)
                & Q(ledger_recorded_at__lte=as_of)
                & Q(activated_at__lte=as_of)
                & Q(valid_until__gt=as_of)
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R7AnalogyPathOwnerCorruption("R7 analogy definition has multiple PIT winners")
        return _analogy_definition_from_model(rows[0])


class DjangoR7PathDefinitionRepository:
    """Private/public exact identity provider used by receipt registration."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self, *, definition_id: str, definition_version: str, as_of: datetime
    ) -> ScenarioPathDefinition | None:
        _identity_query(definition_id, definition_version, as_of)
        rows = tuple(
            R7ScenarioPathDefinitionModel._default_manager.using(self._using).filter(
                Q(definition_id=definition_id, definition_version=definition_version)
                & Q(ledger_recorded_at__lte=as_of)
                & Q(activated_at__lte=as_of)
                & Q(valid_until__gt=as_of)
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R7AnalogyPathOwnerCorruption("R7 path definition has multiple PIT winners")
        return _path_definition_from_model(rows[0])


class _PrivateStore:
    __slots__ = ("_clock", "_token", "_using")

    def __init__(
        self,
        *,
        token: object,
        using: str,
        clock: R7AnalogyPathOwnerClock,
    ) -> None:
        self._token = token
        self._using = using
        self._clock = clock

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r5_monitoring_uow(self._token):
            yield

    def _insert(self, model_type: type[models.Model], values: dict[str, object]) -> models.Model:
        model = model_type(**values)
        model.full_clean()
        with transaction.atomic(using=self._using):
            with _claim_r5_monitoring_insert(
                token=self._token,
                model_type=model_type,
                expected_values=values,
            ):
                model.save(force_insert=True, using=self._using)
        return model


class _AnalogyDefinitionStore(_PrivateStore):
    def append(self, definition: HistoricalAnalogyDefinition) -> HistoricalAnalogyDefinition:
        exact = _analogy_definition(definition)
        rows = _analogy_definition_collisions(self._using, exact)
        if rows:
            return _match_analogy_definition(rows, exact)
        ledger_recorded_at = self._clock.now()
        _aware(ledger_recorded_at, "R7 analogy definition ledger_recorded_at")
        values = _analogy_definition_values(exact, ledger_recorded_at)
        try:
            model = cast(
                R7HistoricalAnalogyDefinitionModel,
                self._insert(R7HistoricalAnalogyDefinitionModel, values),
            )
        except (IntegrityError, ValidationError) as error:
            rows = _analogy_definition_collisions(self._using, exact)
            if not rows:
                raise R7AnalogyPathOwnerConflict(
                    "R7 analogy definition append has no winner"
                ) from error
            return _match_analogy_definition(rows, exact)
        return _analogy_definition_from_model(model)


class _PathDefinitionStore(_PrivateStore):
    def append(self, definition: ScenarioPathDefinition) -> ScenarioPathDefinition:
        exact = _path_definition(definition)
        rows = _path_definition_collisions(self._using, exact)
        if rows:
            return _match_path_definition(rows, exact)
        ledger_recorded_at = self._clock.now()
        _aware(ledger_recorded_at, "R7 path definition ledger_recorded_at")
        values = _path_definition_values(exact, ledger_recorded_at)
        try:
            model = cast(
                R7ScenarioPathDefinitionModel,
                self._insert(R7ScenarioPathDefinitionModel, values),
            )
        except (IntegrityError, ValidationError) as error:
            rows = _path_definition_collisions(self._using, exact)
            if not rows:
                raise R7AnalogyPathOwnerConflict(
                    "R7 path definition append has no winner"
                ) from error
            return _match_path_definition(rows, exact)
        return _path_definition_from_model(model)


class _AnalogyReceiptStore(_PrivateStore):
    def append(self, receipt: HistoricalAnalogyReceipt) -> HistoricalAnalogyReceipt:
        exact = _analogy_receipt(receipt)
        rows = _analogy_receipt_collisions(self._using, exact)
        if rows:
            return _match_analogy_receipt(rows, exact)
        definitions = tuple(
            R7HistoricalAnalogyDefinitionModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                definition_id=exact.definition.definition_id,
                definition_version=exact.definition.definition_version,
                definition_hash=exact.definition.content_hash,
            )
        )
        if len(definitions) != 1:
            raise R7AnalogyPathOwnerCorruption("R7 analogy receipt definition row is unavailable")
        values = _analogy_receipt_values(exact, definitions[0].pk)
        try:
            model = cast(
                R7HistoricalAnalogyReceiptModel,
                self._insert(R7HistoricalAnalogyReceiptModel, values),
            )
            for candidate in exact.source.candidates:
                self._insert(
                    R7HistoricalAnalogyCandidateModel,
                    _analogy_candidate_values(candidate, model.pk, exact.recorded_at),
                )
        except (IntegrityError, ValidationError) as error:
            rows = _analogy_receipt_collisions(self._using, exact)
            if not rows:
                raise R7AnalogyPathOwnerConflict(
                    "R7 analogy receipt append has no winner"
                ) from error
            return _match_analogy_receipt(rows, exact)
        return _analogy_receipt_from_model(model)


class _PathReceiptStore(_PrivateStore):
    def append(self, receipt: ScenarioPathReceipt) -> ScenarioPathReceipt:
        exact = _path_receipt(receipt)
        rows = _path_receipt_collisions(self._using, exact)
        if rows:
            return _match_path_receipt(rows, exact)
        definitions = tuple(
            R7ScenarioPathDefinitionModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                definition_id=exact.definition.definition_id,
                definition_version=exact.definition.definition_version,
                definition_hash=exact.definition.content_hash,
            )
        )
        if len(definitions) != 1:
            raise R7AnalogyPathOwnerCorruption("R7 path receipt definition row is unavailable")
        values = _path_receipt_values(exact, definitions[0].pk)
        try:
            model = cast(
                R7ScenarioPathReceiptModel,
                self._insert(R7ScenarioPathReceiptModel, values),
            )
            for member in exact.source.sample_members:
                self._insert(
                    R7ScenarioPathMemberModel,
                    _path_sample_values(member, model.pk, exact.recorded_at),
                )
            for shock in exact.source.shocks:
                self._insert(
                    R7ScenarioPathMemberModel,
                    _path_shock_values(shock, model.pk, exact.recorded_at),
                )
        except (IntegrityError, ValidationError) as error:
            rows = _path_receipt_collisions(self._using, exact)
            if not rows:
                raise R7AnalogyPathOwnerConflict("R7 path receipt append has no winner") from error
            return _match_path_receipt(rows, exact)
        return _path_receipt_from_model(model)


@dataclass(frozen=True)
class _R7AnalogyPathStores:
    analogy_definition: _AnalogyDefinitionStore
    analogy_receipt: _AnalogyReceiptStore
    path_definition: _PathDefinitionStore
    path_receipt: _PathReceiptStore


def _build_r7_analogy_path_stores(
    *,
    using: str = "default",
    clock: R7AnalogyPathOwnerClock | None = None,
) -> _R7AnalogyPathStores:
    token = object()
    trusted_clock = clock or DjangoR7AnalogyPathOwnerClock(using=using)
    return _R7AnalogyPathStores(
        analogy_definition=_AnalogyDefinitionStore(token=token, using=using, clock=trusted_clock),
        analogy_receipt=_AnalogyReceiptStore(token=token, using=using, clock=trusted_clock),
        path_definition=_PathDefinitionStore(token=token, using=using, clock=trusted_clock),
        path_receipt=_PathReceiptStore(token=token, using=using, clock=trusted_clock),
    )


def _analogy_definition(value: object) -> HistoricalAnalogyDefinition:
    if type(value) is not HistoricalAnalogyDefinition:
        raise TypeError("R7 analogy definition type differs")
    return HistoricalAnalogyDefinition.validated_copy(value)


def _analogy_receipt(value: object) -> HistoricalAnalogyReceipt:
    if type(value) is not HistoricalAnalogyReceipt:
        raise TypeError("R7 analogy receipt type differs")
    return HistoricalAnalogyReceipt.validated_copy(value)


def _path_definition(value: object) -> ScenarioPathDefinition:
    if type(value) is not ScenarioPathDefinition:
        raise TypeError("R7 path definition type differs")
    return ScenarioPathDefinition.validated_copy(value)


def _path_receipt(value: object) -> ScenarioPathReceipt:
    if type(value) is not ScenarioPathReceipt:
        raise TypeError("R7 path receipt type differs")
    return ScenarioPathReceipt.validated_copy(value)


def _scope(value: object) -> ScenarioResearchScope:
    if type(value) is not ScenarioResearchScope:
        raise TypeError("R7 owner query scope type differs")
    ScenarioResearchScope.__post_init__(value)
    copied = ScenarioResearchScope.create(
        scope_version=value.scope_version,
        scenario_set_revision_id=value.scenario_set_revision_id,
        scenario_revision_ids=value.scenario_revision_ids,
        forecast_horizon=value.forecast_horizon,
        censoring_rule_version=value.censoring_rule_version,
        path_horizon_periods=value.path_horizon_periods,
        path_initial_state_revision_ids=value.path_initial_state_revision_ids,
    )
    if copied != value:
        raise ValueError("R7 owner query scope differs after replay")
    return copied


def _analogy_definition_values(
    definition: HistoricalAnalogyDefinition,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "definition_hash": definition.content_hash,
        "scope_hash": definition.scope.content_hash,
        "study_version": definition.study_version,
        "feature_definition_version": definition.feature_definition_version,
        "similarity_method_version": definition.similarity_method_version,
        "activated_at": definition.activated_at,
        "valid_until": definition.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "definition_payload": encode_historical_analogy_definition(definition),
        **_safe_values(),
    }
    _validate_definition_clock(
        definition.activated_at,
        definition.valid_until,
        ledger_recorded_at,
        "R7 analogy definition",
    )
    values["ledger_header_hash"] = _header_hash(
        "research-r7-analogy-definition-header.v1", values, {"definition_payload"}
    )
    return values


def _path_definition_values(
    definition: ScenarioPathDefinition,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    values: dict[str, object] = {
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "definition_hash": definition.content_hash,
        "scope_hash": definition.scope.content_hash,
        "study_version": definition.study_version,
        "source_version": definition.source_version,
        "sample_definition_version": definition.sample_definition_version,
        "activated_at": definition.activated_at,
        "valid_until": definition.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "definition_payload": encode_scenario_path_definition(definition),
        **_safe_values(),
    }
    _validate_definition_clock(
        definition.activated_at,
        definition.valid_until,
        ledger_recorded_at,
        "R7 path definition",
    )
    values["ledger_header_hash"] = _header_hash(
        "research-r7-path-definition-header.v1", values, {"definition_payload"}
    )
    return values


def _analogy_receipt_values(
    receipt: HistoricalAnalogyReceipt,
    definition_id: object,
) -> dict[str, object]:
    source = receipt.source
    _validate_receipt_clock(
        source.query_manifest.as_of,
        source.available_at,
        receipt.recorded_at,
        receipt.definition.valid_until,
        "R7 analogy receipt",
    )
    definition_pk = _primary_key(definition_id, "R7 analogy definition primary key")
    values: dict[str, object] = {
        "definition_id": definition_pk,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "receipt_hash": receipt.content_hash,
        "scope_hash": receipt.definition.scope.content_hash,
        "query_manifest_id": source.query_manifest.manifest_id,
        "query_manifest_version": source.query_manifest.manifest_version,
        "query_manifest_hash": source.query_manifest.manifest_hash,
        "query_manifest_reference_hash": source.query_manifest.reference_hash,
        "query_as_of": source.query_manifest.as_of,
        "source_available_at": source.available_at,
        "recorded_at": receipt.recorded_at,
        "definition_valid_until": receipt.definition.valid_until,
        "receipt_payload": encode_historical_analogy_receipt(receipt),
        **_safe_values(),
    }
    values["ledger_header_hash"] = _header_hash(
        "research-r7-analogy-receipt-header.v1", values, {"receipt_payload"}
    )
    return values


def _path_receipt_values(
    receipt: ScenarioPathReceipt,
    definition_id: object,
) -> dict[str, object]:
    source = receipt.source
    _validate_receipt_clock(
        source.pit_manifest.as_of,
        source.available_at,
        receipt.recorded_at,
        receipt.definition.valid_until,
        "R7 path receipt",
    )
    definition_pk = _primary_key(definition_id, "R7 path definition primary key")
    values: dict[str, object] = {
        "definition_id": definition_pk,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "receipt_hash": receipt.content_hash,
        "scope_hash": receipt.definition.scope.content_hash,
        "pit_manifest_id": source.pit_manifest.manifest_id,
        "pit_manifest_version": source.pit_manifest.manifest_version,
        "pit_manifest_hash": source.pit_manifest.manifest_hash,
        "pit_manifest_reference_hash": source.pit_manifest.reference_hash,
        "pit_as_of": source.pit_manifest.as_of,
        "source_available_at": source.available_at,
        "recorded_at": receipt.recorded_at,
        "definition_valid_until": receipt.definition.valid_until,
        "receipt_payload": encode_scenario_path_receipt(receipt),
        **_safe_values(),
    }
    values["ledger_header_hash"] = _header_hash(
        "research-r7-path-receipt-header.v1", values, {"receipt_payload"}
    )
    return values


def _analogy_candidate_values(
    candidate: AnalogyCandidateRawEvidence,
    receipt_id: object,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    receipt_pk = _primary_key(receipt_id, "R7 analogy receipt primary key")
    _validate_candidate_clock(candidate, ledger_recorded_at)
    payload = _analogy_candidate_payload(candidate)
    values: dict[str, object] = {
        "receipt_id": receipt_pk,
        "candidate_id": candidate.candidate_id,
        "candidate_version": candidate.candidate_version,
        "candidate_hash": candidate.content_hash,
        "window_start": candidate.window_start,
        "window_end": candidate.window_end,
        "decision_cutoff": candidate.decision_cutoff,
        "manifest_id": candidate.pit_manifest.manifest_id,
        "manifest_version": candidate.pit_manifest.manifest_version,
        "manifest_hash": candidate.pit_manifest.manifest_hash,
        "manifest_reference_hash": candidate.pit_manifest.reference_hash,
        "ledger_recorded_at": ledger_recorded_at,
        "candidate_payload": payload,
        **_safe_values(),
    }
    values["ledger_header_hash"] = _header_hash(
        "research-r7-analogy-candidate-header.v1", values, {"candidate_payload"}
    )
    return values


def _path_sample_values(
    member: PathObservedSampleMember,
    receipt_id: object,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    receipt_pk = _primary_key(receipt_id, "R7 path receipt primary key")
    _validate_path_sample_clock(member, ledger_recorded_at)
    values: dict[str, object] = {
        "receipt_id": receipt_pk,
        "member_kind": "sample",
        "member_key": member.expected.member_id,
        "member_version": member.expected.member_version,
        "member_hash": member.content_hash,
        "period_index": member.expected.period_index,
        "resolution": member.resolution.value,
        "from_scenario_revision_id": member.expected.from_scenario_revision_id,
        "to_scenario_revision_id": member.to_scenario_revision_id,
        "observed_at": member.observed_at,
        "source_available_at": member.available_at,
        "ledger_recorded_at": ledger_recorded_at,
        "member_payload": _path_sample_payload(member),
        **_safe_values(),
    }
    values["ledger_header_hash"] = _header_hash(
        "research-r7-path-member-header.v1", values, {"member_payload"}
    )
    return values


def _path_shock_values(
    shock: PathShockObservation,
    receipt_id: object,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    receipt_pk = _primary_key(receipt_id, "R7 path receipt primary key")
    _validate_path_shock_clock(shock, ledger_recorded_at)
    key = _path_shock_member_key(shock)
    values: dict[str, object] = {
        "receipt_id": receipt_pk,
        "member_kind": "shock",
        "member_key": key,
        "member_version": shock.source_version,
        "member_hash": shock.content_hash,
        "period_index": shock.rule.period_index,
        "resolution": "",
        "from_scenario_revision_id": None,
        "to_scenario_revision_id": None,
        "observed_at": None,
        "source_available_at": shock.available_at,
        "ledger_recorded_at": ledger_recorded_at,
        "member_payload": _path_shock_payload(shock),
        **_safe_values(),
    }
    values["ledger_header_hash"] = _header_hash(
        "research-r7-path-member-header.v1", values, {"member_payload"}
    )
    return values


def _analogy_definition_from_model(
    row: R7HistoricalAnalogyDefinitionModel,
) -> HistoricalAnalogyDefinition:
    try:
        definition = decode_historical_analogy_definition(row.definition_payload)
        _require_row_values(
            row,
            _analogy_definition_values(definition, row.ledger_recorded_at),
            "analogy definition",
        )
        return definition
    except R7AnalogyPathOwnerCorruption:
        raise
    except Exception as error:
        raise R7AnalogyPathOwnerCorruption(
            "R7 analogy definition row cannot be restored"
        ) from error


def _path_definition_from_model(
    row: R7ScenarioPathDefinitionModel,
) -> ScenarioPathDefinition:
    try:
        definition = decode_scenario_path_definition(row.definition_payload)
        _require_row_values(
            row,
            _path_definition_values(definition, row.ledger_recorded_at),
            "path definition",
        )
        return definition
    except R7AnalogyPathOwnerCorruption:
        raise
    except Exception as error:
        raise R7AnalogyPathOwnerCorruption("R7 path definition row cannot be restored") from error


def _analogy_receipt_from_model(
    row: R7HistoricalAnalogyReceiptModel,
) -> HistoricalAnalogyReceipt:
    try:
        receipt = decode_historical_analogy_receipt(row.receipt_payload)
        definition = _analogy_definition_from_model(row.definition)
        if receipt.definition != definition:
            raise R7AnalogyPathOwnerCorruption(
                "R7 analogy receipt definition graph was substituted"
            )
        receipt_pk = _primary_key(row.pk, "R7 analogy receipt primary key")
        _require_row_values(
            row,
            _analogy_receipt_values(receipt, row.definition_id),
            "analogy receipt",
        )
        child_rows = tuple(row.candidates.all())
        children: dict[tuple[str, str], R7HistoricalAnalogyCandidateModel] = {}
        for child in child_rows:
            key = (child.candidate_id, child.candidate_version)
            if key in children:
                raise R7AnalogyPathOwnerCorruption(
                    "R7 analogy receipt contains duplicate candidate rows"
                )
            children[key] = child
        expected_keys = {
            (item.candidate_id, item.candidate_version) for item in receipt.source.candidates
        }
        if set(children) != expected_keys:
            raise R7AnalogyPathOwnerCorruption("R7 analogy receipt candidate membership differs")
        for candidate in receipt.source.candidates:
            key = (candidate.candidate_id, candidate.candidate_version)
            _require_row_values(
                children[key],
                _analogy_candidate_values(candidate, receipt_pk, receipt.recorded_at),
                "analogy candidate",
            )
        return receipt
    except R7AnalogyPathOwnerCorruption:
        raise
    except Exception as error:
        raise R7AnalogyPathOwnerCorruption("R7 analogy receipt graph cannot be restored") from error


def _path_receipt_from_model(row: R7ScenarioPathReceiptModel) -> ScenarioPathReceipt:
    try:
        receipt = decode_scenario_path_receipt(row.receipt_payload)
        definition = _path_definition_from_model(row.definition)
        if receipt.definition != definition:
            raise R7AnalogyPathOwnerCorruption("R7 path receipt definition graph was substituted")
        receipt_pk = _primary_key(row.pk, "R7 path receipt primary key")
        _require_row_values(
            row,
            _path_receipt_values(receipt, row.definition_id),
            "path receipt",
        )
        child_rows = tuple(row.members.all())
        children: dict[tuple[str, str], R7ScenarioPathMemberModel] = {}
        for child in child_rows:
            key = (child.member_kind, child.member_key)
            if key in children:
                raise R7AnalogyPathOwnerCorruption("R7 path receipt contains duplicate member rows")
            children[key] = child
        expected_keys = {
            *(("sample", item.expected.member_id) for item in receipt.source.sample_members),
            *(("shock", _path_shock_member_key(item)) for item in receipt.source.shocks),
        }
        if set(children) != expected_keys:
            raise R7AnalogyPathOwnerCorruption("R7 path receipt member graph differs")
        for member in receipt.source.sample_members:
            key = ("sample", member.expected.member_id)
            _require_row_values(
                children[key],
                _path_sample_values(member, receipt_pk, receipt.recorded_at),
                "path sample member",
            )
        for shock in receipt.source.shocks:
            key = ("shock", _path_shock_member_key(shock))
            _require_row_values(
                children[key],
                _path_shock_values(shock, receipt_pk, receipt.recorded_at),
                "path shock member",
            )
        return receipt
    except R7AnalogyPathOwnerCorruption:
        raise
    except Exception as error:
        raise R7AnalogyPathOwnerCorruption("R7 path receipt graph cannot be restored") from error


def _analogy_definition_collisions(
    using: str,
    definition: HistoricalAnalogyDefinition,
) -> tuple[R7HistoricalAnalogyDefinitionModel, ...]:
    overlap = Q(scope_hash=definition.scope.content_hash) & Q(
        activated_at__lt=definition.valid_until,
        valid_until__gt=definition.activated_at,
    )
    return tuple(
        R7HistoricalAnalogyDefinitionModel._default_manager.using(using).filter(
            Q(
                definition_id=definition.definition_id,
                definition_version=definition.definition_version,
            )
            | Q(definition_hash=definition.content_hash)
            | overlap
        )
    )


def _path_definition_collisions(
    using: str,
    definition: ScenarioPathDefinition,
) -> tuple[R7ScenarioPathDefinitionModel, ...]:
    overlap = Q(scope_hash=definition.scope.content_hash) & Q(
        activated_at__lt=definition.valid_until,
        valid_until__gt=definition.activated_at,
    )
    return tuple(
        R7ScenarioPathDefinitionModel._default_manager.using(using).filter(
            Q(
                definition_id=definition.definition_id,
                definition_version=definition.definition_version,
            )
            | Q(definition_hash=definition.content_hash)
            | overlap
        )
    )


def _analogy_receipt_collisions(
    using: str,
    receipt: HistoricalAnalogyReceipt,
) -> tuple[R7HistoricalAnalogyReceiptModel, ...]:
    overlap = Q(scope_hash=receipt.definition.scope.content_hash) & Q(
        recorded_at__lt=receipt.definition.valid_until,
        definition_valid_until__gt=receipt.recorded_at,
    )
    return tuple(
        R7HistoricalAnalogyReceiptModel._default_manager.using(using)
        .select_related("definition")
        .prefetch_related("candidates")
        .filter(
            Q(receipt_id=receipt.receipt_id, receipt_version=receipt.receipt_version)
            | Q(receipt_hash=receipt.content_hash)
            | overlap
        )
    )


def _path_receipt_collisions(
    using: str,
    receipt: ScenarioPathReceipt,
) -> tuple[R7ScenarioPathReceiptModel, ...]:
    overlap = Q(scope_hash=receipt.definition.scope.content_hash) & Q(
        recorded_at__lt=receipt.definition.valid_until,
        definition_valid_until__gt=receipt.recorded_at,
    )
    return tuple(
        R7ScenarioPathReceiptModel._default_manager.using(using)
        .select_related("definition")
        .prefetch_related("members")
        .filter(
            Q(receipt_id=receipt.receipt_id, receipt_version=receipt.receipt_version)
            | Q(receipt_hash=receipt.content_hash)
            | overlap
        )
    )


def _match_analogy_definition(
    rows: tuple[R7HistoricalAnalogyDefinitionModel, ...],
    expected: HistoricalAnalogyDefinition,
) -> HistoricalAnalogyDefinition:
    if len(rows) != 1:
        raise R7AnalogyPathOwnerConflict("R7 analogy definition has multiple collision candidates")
    restored = _analogy_definition_from_model(rows[0])
    if restored != expected:
        raise R7AnalogyPathOwnerConflict(
            "R7 analogy definition identity forks to different evidence"
        )
    return restored


def _match_path_definition(
    rows: tuple[R7ScenarioPathDefinitionModel, ...],
    expected: ScenarioPathDefinition,
) -> ScenarioPathDefinition:
    if len(rows) != 1:
        raise R7AnalogyPathOwnerConflict("R7 path definition has multiple collision candidates")
    restored = _path_definition_from_model(rows[0])
    if restored != expected:
        raise R7AnalogyPathOwnerConflict("R7 path definition identity forks to different evidence")
    return restored


def _match_analogy_receipt(
    rows: tuple[R7HistoricalAnalogyReceiptModel, ...],
    expected: HistoricalAnalogyReceipt,
) -> HistoricalAnalogyReceipt:
    if len(rows) != 1:
        raise R7AnalogyPathOwnerConflict("R7 analogy receipt has multiple collision candidates")
    restored = _analogy_receipt_from_model(rows[0])
    if restored != expected:
        raise R7AnalogyPathOwnerConflict("R7 analogy receipt identity forks to different evidence")
    return restored


def _match_path_receipt(
    rows: tuple[R7ScenarioPathReceiptModel, ...],
    expected: ScenarioPathReceipt,
) -> ScenarioPathReceipt:
    if len(rows) != 1:
        raise R7AnalogyPathOwnerConflict("R7 path receipt has multiple collision candidates")
    restored = _path_receipt_from_model(rows[0])
    if restored != expected:
        raise R7AnalogyPathOwnerConflict("R7 path receipt identity forks to different evidence")
    return restored


def _analogy_candidate_payload(
    candidate: AnalogyCandidateRawEvidence,
) -> dict[str, object]:
    return _payload_dict(
        AnalogyCandidateRawEvidence.validated_copy(candidate),
        "R7 analogy candidate",
    )


def _path_sample_payload(member: PathObservedSampleMember) -> dict[str, object]:
    return _payload_dict(
        PathObservedSampleMember.validated_copy(member),
        "R7 path sample member",
    )


def _path_shock_payload(shock: PathShockObservation) -> dict[str, object]:
    return _payload_dict(
        PathShockObservation.validated_copy(shock),
        "R7 path shock member",
    )


def _payload_dict(value: object, label: str) -> dict[str, object]:
    payload = _ledger_value(value)
    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise TypeError(f"{label} payload is not an exact string-keyed object")
    return cast(dict[str, object], payload)


def _ledger_value(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is datetime:
        return (
            _aware(value, "R7 owner ledger datetime")
            .astimezone(UTC)
            .isoformat(timespec="microseconds")
        )
    if type(value) is timedelta:
        duration = value
        return duration.days * 86_400_000_000 + duration.seconds * 1_000_000 + duration.microseconds
    if type(value) is Decimal:
        number = value
        if not number.is_finite():
            raise ValueError("R7 owner ledger Decimal must be finite")
        normalized = number.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if type(value) is UUID:
        return str(value)
    if isinstance(value, Enum):
        return _ledger_value(value.value)
    if type(value) in (tuple, list):
        return [_ledger_value(item) for item in cast(tuple[object, ...] | list[object], value)]
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise TypeError("R7 owner ledger mappings require exact string keys")
        return {
            cast(str, key): _ledger_value(item)
            for key, item in sorted(mapping.items(), key=lambda pair: cast(str, pair[0]))
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _ledger_value(getattr(value, item.name)) for item in fields(value)}
    raise TypeError(f"unsupported R7 owner ledger value: {type(value).__name__}")


def _header_hash(
    schema: str,
    values: dict[str, object],
    payload_keys: set[str],
) -> str:
    _token(schema, "R7 owner header schema")
    projected = {
        key: _ledger_value(value)
        for key, value in values.items()
        if key != "ledger_header_hash" and key not in payload_keys
    }
    return canonical_hash({"schema": schema, "values": projected})


def _safe_values() -> dict[str, object]:
    return {
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def _require_row_values(row: object, expected: dict[str, object], label: str) -> None:
    for field_name, value in expected.items():
        if getattr(row, field_name) != value:
            raise R7AnalogyPathOwnerCorruption(
                f"R7 {label} field {field_name} differs from its sealed payload"
            )


def _validate_definition_clock(
    activated_at: datetime,
    valid_until: datetime,
    ledger_recorded_at: datetime,
    label: str,
) -> None:
    activated = _aware(activated_at, f"{label} activated_at")
    expiry = _aware(valid_until, f"{label} valid_until")
    recorded = _aware(ledger_recorded_at, f"{label} ledger_recorded_at")
    if not activated <= recorded < expiry:
        raise ValueError(f"{label} ledger clock is outside definition validity")


def _validate_receipt_clock(
    pit_as_of: datetime,
    available_at: datetime,
    recorded_at: datetime,
    definition_valid_until: datetime,
    label: str,
) -> None:
    pit = _aware(pit_as_of, f"{label} PIT as_of")
    available = _aware(available_at, f"{label} source_available_at")
    recorded = _aware(recorded_at, f"{label} recorded_at")
    expiry = _aware(definition_valid_until, f"{label} definition_valid_until")
    if not pit <= available <= recorded < expiry:
        raise ValueError(f"{label} PIT/source/ledger clocks differ")


def _validate_candidate_clock(
    candidate: AnalogyCandidateRawEvidence,
    ledger_recorded_at: datetime,
) -> None:
    start = _aware(candidate.window_start, "R7 analogy candidate window_start")
    end = _aware(candidate.window_end, "R7 analogy candidate window_end")
    cutoff = _aware(candidate.decision_cutoff, "R7 analogy candidate decision_cutoff")
    recorded = _aware(ledger_recorded_at, "R7 analogy candidate ledger_recorded_at")
    if not start < end <= cutoff <= recorded:
        raise ValueError("R7 analogy candidate clocks differ")


def _validate_path_sample_clock(
    member: PathObservedSampleMember,
    ledger_recorded_at: datetime,
) -> None:
    available = _aware(member.available_at, "R7 path sample source_available_at")
    recorded = _aware(ledger_recorded_at, "R7 path sample ledger_recorded_at")
    if available > recorded:
        raise ValueError("R7 path sample is future-dated")
    if member.observed_at is not None:
        observed = _aware(member.observed_at, "R7 path sample observed_at")
        if observed > available:
            raise ValueError("R7 path sample observation is not yet available")


def _validate_path_shock_clock(
    shock: PathShockObservation,
    ledger_recorded_at: datetime,
) -> None:
    available = _aware(shock.available_at, "R7 path shock source_available_at")
    recorded = _aware(ledger_recorded_at, "R7 path shock ledger_recorded_at")
    if available > recorded:
        raise ValueError("R7 path shock is future-dated")


def _path_shock_member_key(shock: PathShockObservation) -> str:
    rule = shock.rule
    return f"{rule.period_index}:{rule.scenario_revision_id}:{rule.shock_key}"


def _identity_query(
    definition_id: object,
    definition_version: object,
    as_of: object,
) -> None:
    _token(definition_id, "R7 owner definition_id")
    _token(definition_version, "R7 owner definition_version")
    _aware(as_of, "R7 owner query as_of")


def _token(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 420
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded nonblank exact token")
    return value


def _aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


def _primary_key(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise R7AnalogyPathOwnerCorruption(f"{label} is invalid")
    return value


__all__ = [
    "DjangoR7AnalogyDefinitionRepository",
    "DjangoR7AnalogyPathOwnerClock",
    "DjangoR7HistoricalAnalogyProvider",
    "DjangoR7PathDefinitionRepository",
    "DjangoR7PathStudyProvider",
    "R7AnalogyPathOwnerConflict",
    "R7AnalogyPathOwnerCorruption",
]
