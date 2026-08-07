"""Strict append-only repository for complete R7 research result packets."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import Protocol

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r7_research_result_persistence import (
    ExactR7ResearchEvidenceGraphProvider,
    R7ResearchResultConflict,
    R7ResearchResultCorruption,
    R7ResearchResultUnavailable,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
    R7ResearchEvidenceGraph,
)
from apps.research.domain.r7_sample_policy import PersistedR7SamplePolicy
from apps.research.infrastructure.r7_research_result_codec import (
    decode_persisted_r7_research_result,
    encode_persisted_r7_research_result,
)
from apps.research.infrastructure.r7_research_result_models import (
    R7ResearchResultModel,
    _activate_r7_research_result_uow,
    _claim_r7_research_result_insert,
    _require_active_r7_research_result_uow,
)
from apps.research.infrastructure.r7_sample_policy_models import R7SamplePolicyModel
from apps.research.infrastructure.r7_sample_policy_repository import (
    DjangoR7SamplePolicyRepository,
)


class R7ResearchResultClock(Protocol):
    """Server clock boundary shared by registration and PIT reads."""

    def now(self) -> datetime:
        """Return an authoritative timezone-aware timestamp."""


class DjangoR7ResearchResultClock:
    """Django server clock implementation."""

    def now(self) -> datetime:
        """Return Django's timezone-aware server time."""

        return timezone.now()


class DjangoR7SamplePolicyRecordIdentityProvider:
    """Resolve one strict persisted sample policy by ID/version inside the UoW."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7ResearchResultClock | None = None,
    ) -> None:
        self._using = using
        self._repository = DjangoR7SamplePolicyRepository(
            using=using,
            clock=clock or DjangoR7ResearchResultClock(),
        )

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact_by_identity(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> PersistedR7SamplePolicy | None:
        """Restore exact policy bytes without accepting a caller-provided hash."""

        _require_active_r7_research_result_uow()
        candidates = list(
            R7SamplePolicyModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                Q(policy_id=policy_id, policy_version=policy_version)
                | Q(
                    approval__policy_id=policy_id,
                    approval__policy_version=policy_version,
                )
            )
        )
        if not candidates:
            return None
        if len(candidates) != 1:
            raise R7ResearchResultCorruption(
                "multiple R7 sample policy rows match one result policy identity"
            )
        candidate = candidates[0]
        record = self._repository.get_exact(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_content_hash=candidate.content_hash,
            as_of=as_of,
        )
        if record is None:
            raise R7ResearchResultCorruption(
                "R7 sample policy identity exists but strict restoration failed"
            )
        return record


class DjangoR7ResearchEvidenceGraphProvider:
    """Require composition-owned UoW before dynamically rereading owner ports."""

    def __init__(self, source: ExactR7ResearchEvidenceGraphProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return self._source.unit_of_work_key

    def get_exact_graph(
        self,
        *,
        policy_record: PersistedR7SamplePolicy,
        evaluated_at: datetime,
    ) -> R7ResearchEvidenceGraph:
        """Return one complete owner graph only inside the result transaction."""

        _require_active_r7_research_result_uow()
        graph = self._source.get_exact_graph(
            policy_record=policy_record,
            evaluated_at=evaluated_at,
        )
        if (
            graph.scope_content_hash != policy_record.scope.content_hash
            or graph.evaluated_at != evaluated_at
        ):
            raise R7ResearchResultCorruption("R7 owner evidence graph substitution")
        return graph


class DjangoR7ResearchResultRepository:
    """Public read-only exact/PIT result repository."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7ResearchResultClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR7ResearchResultClock()
        self._policy_repository = DjangoR7SamplePolicyRepository(
            using=using,
            clock=self._clock,
        )

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        """Restore by redundant anchors, then apply the server-knowledge cutoff."""

        self._require_pit_cutoff(as_of)
        models = list(
            R7ResearchResultModel._default_manager.using(self._using)
            .select_related("sample_policy", "sample_policy__approval")
            .filter(
                Q(result_id=result_id, result_version=result_version)
                | Q(content_hash=expected_content_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore(model) for model in models)
        matches = tuple(
            record
            for record in records
            if record.result_id == result_id
            and record.result_version == result_version
            and record.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise R7ResearchResultCorruption(
                "multiple R7 research results match one exact identity and hash"
            )
        if not matches or matches[0].recorded_at > as_of:
            return None
        return matches[0]

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise R7ResearchResultUnavailable("R7 result as_of must be timezone-aware")
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise R7ResearchResultCorruption("R7 result server clock is naive")
        if as_of > now:
            raise R7ResearchResultUnavailable("future R7 result as_of is not permitted")

    def _restore(self, model: R7ResearchResultModel) -> PersistedR7ResearchResult:
        record = decode_persisted_r7_research_result(model.canonical_payload)
        if _record_headers(record) != _model_headers(model):
            raise R7ResearchResultCorruption("R7 research result header mismatch")
        receipt = record.input_receipt
        policy_record = self._policy_repository.get_exact(
            policy_id=receipt.policy_id,
            policy_version=receipt.policy_version,
            expected_content_hash=receipt.policy_record_hash,
            as_of=record.evidence_graph.evaluated_at,
        )
        if policy_record is None:
            raise R7ResearchResultCorruption("R7 result policy record is unavailable")
        related_policy = model.sample_policy
        if (
            model.sample_policy_id != related_policy.pk
            or related_policy.policy_id != receipt.policy_id
            or related_policy.policy_version != receipt.policy_version
            or related_policy.content_hash != receipt.policy_record_hash
            or policy_record.content_hash != receipt.policy_record_hash
            or policy_record.scope.content_hash != receipt.scope_content_hash
        ):
            raise R7ResearchResultCorruption("R7 result policy relation substitution")
        return record


class _DjangoR7ResearchResultStore:
    """Private append capability retained by the composition root."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r7_research_result_uow(self._token):
            yield

    def append(self, result: PersistedR7ResearchResult) -> PersistedR7ResearchResult:
        """Append exactly one complete result packet inside the active UoW."""

        _require_active_r7_research_result_uow()
        if (
            R7ResearchResultModel._default_manager.using(self._using)
            .filter(
                Q(result_id=result.result_id, result_version=result.result_version)
                | Q(content_hash=result.content_hash)
            )
            .exists()
        ):
            raise R7ResearchResultConflict("R7 research result identity already sealed")
        receipt = result.input_receipt
        policy_models = list(
            R7SamplePolicyModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                policy_id=receipt.policy_id,
                policy_version=receipt.policy_version,
                content_hash=receipt.policy_record_hash,
            )
        )
        if len(policy_models) != 1:
            raise R7ResearchResultCorruption("R7 result exact policy row is unavailable")
        values = _result_values(result)
        claim_values = {**values, "sample_policy_id": policy_models[0].pk}
        with _claim_r7_research_result_insert(
            token=self._token,
            expected_values=claim_values,
        ):
            R7ResearchResultModel._default_manager.using(self._using).create(
                sample_policy=policy_models[0],
                **values,
            )
        return result


def _result_values(record: PersistedR7ResearchResult) -> dict[str, object]:
    receipt = record.input_receipt
    return {
        "result_id": record.result_id,
        "result_version": record.result_version,
        "policy_id": receipt.policy_id,
        "policy_version": receipt.policy_version,
        "policy_record_hash": receipt.policy_record_hash,
        "scope_content_hash": receipt.scope_content_hash,
        "evaluated_at": receipt.evaluated_at,
        "evidence_graph_hash": record.evidence_graph.content_hash,
        "input_receipt_hash": receipt.content_hash,
        "calibration_hash": record.calibration.content_hash,
        "historical_analogy_hash": record.historical_analogy.content_hash,
        "path_research_hash": record.path_research.content_hash,
        "analogy_evidence_hash": receipt.analogy_evidence_hash,
        "path_evidence_hash": receipt.path_evidence_hash,
        "forecast_observation_count": len(receipt.forecast_observations),
        "recorded_at": record.recorded_at,
        "canonical_payload": encode_persisted_r7_research_result(record),
        "trains_probability_model": record.trains_probability_model,
        "publishes_model_probability": record.publishes_model_probability,
        "produces_decision": record.produces_decision,
        "executes_orders": record.executes_orders,
        "research_only": record.research_only,
        "must_not_use_for_decision": record.must_not_use_for_decision,
        "must_not_execute": record.must_not_execute,
        "content_hash": record.content_hash,
    }


def _record_headers(record: PersistedR7ResearchResult) -> tuple[object, ...]:
    receipt = record.input_receipt
    return (
        record.result_id,
        record.result_version,
        receipt.policy_id,
        receipt.policy_version,
        receipt.policy_record_hash,
        receipt.scope_content_hash,
        receipt.evaluated_at,
        record.evidence_graph.content_hash,
        receipt.content_hash,
        record.calibration.content_hash,
        record.historical_analogy.content_hash,
        record.path_research.content_hash,
        receipt.analogy_evidence_hash,
        receipt.path_evidence_hash,
        len(receipt.forecast_observations),
        record.recorded_at,
        record.trains_probability_model,
        record.publishes_model_probability,
        record.produces_decision,
        record.executes_orders,
        record.research_only,
        record.must_not_use_for_decision,
        record.must_not_execute,
        record.content_hash,
    )


def _model_headers(model: R7ResearchResultModel) -> tuple[object, ...]:
    return (
        model.result_id,
        model.result_version,
        model.policy_id,
        model.policy_version,
        model.policy_record_hash,
        model.scope_content_hash,
        model.evaluated_at,
        model.evidence_graph_hash,
        model.input_receipt_hash,
        model.calibration_hash,
        model.historical_analogy_hash,
        model.path_research_hash,
        model.analogy_evidence_hash,
        model.path_evidence_hash,
        model.forecast_observation_count,
        model.recorded_at,
        model.trains_probability_model,
        model.publishes_model_probability,
        model.produces_decision,
        model.executes_orders,
        model.research_only,
        model.must_not_use_for_decision,
        model.must_not_execute,
        model.content_hash,
    )


__all__ = [
    "DjangoR7ResearchEvidenceGraphProvider",
    "DjangoR7ResearchResultClock",
    "DjangoR7ResearchResultRepository",
    "DjangoR7SamplePolicyRecordIdentityProvider",
    "R7ResearchResultClock",
]
