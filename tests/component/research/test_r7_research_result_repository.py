"""Component coverage for the complete append-only R7 result ledger."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import Collector

from apps.research.application.r7_research_result_persistence import (
    GetExactR7ResearchResultCommand,
    R7ResearchResultConflict,
    R7ResearchResultCorruption,
    R7ResearchResultUnavailable,
    RegisterR7ResearchResultCommand,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyStudyEvidence,
    ScenarioPathStudyEvidence,
)
from apps.research.infrastructure.models import ResearchExperiment
from apps.research.infrastructure.r7_research_result_codec import (
    R7ResearchResultCodecError,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from apps.research.infrastructure.r7_research_result_repository import _result_values
from apps.research.infrastructure.r7_sample_policy_models import R7SamplePolicyModel
from apps.research.infrastructure.r7_sample_policy_repository import (
    _DjangoR7SamplePolicyStore,
)
from apps.research.r7_research_result_composition import (
    _build_django_r7_research_result_owner_runtime,
    _build_django_r7_research_result_test_runtime,
    _DjangoR7ResearchResultTestRuntime,
    build_django_r7_research_result_runtime,
)
from tests.unit.research.r7_research_result_factories import (
    EVALUATED_AT,
    RESULT_RECORDED_AT,
    make_forecast_observations,
    make_historical_analogy,
    make_path_study,
    make_policy_record,
)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class ForecastProvider:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.calls: list[tuple[ScenarioResearchScope, datetime, datetime, datetime]] = []
        self.fail = False
        self.write_sentinel = False

    def list_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        window_start: datetime,
        window_end: datetime,
        as_of: datetime,
    ) -> tuple[ForecastLedgerOutcomeObservation, ...]:
        self.calls.append((scope, window_start, window_end, as_of))
        if self.write_sentinel:
            ResearchExperiment._default_manager.create(
                experiment_id="r7-result-rollback-sentinel",
                question="Does the R7 result transaction roll back?",
                hypothesis="A failed append removes this owner-side write.",
            )
        if self.fail:
            raise R7ResearchResultUnavailable("authoritative Signal ledger unavailable")
        return make_forecast_observations()


class AnalogyProvider:
    unit_of_work_key = "django:default"

    def get_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> HistoricalAnalogyStudyEvidence | None:
        assert scope == make_policy_record().scope
        assert as_of == EVALUATED_AT
        return make_historical_analogy()


class PathProvider:
    unit_of_work_key = "django:default"

    def get_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> ScenarioPathStudyEvidence | None:
        assert scope == make_policy_record().scope
        assert as_of == EVALUATED_AT
        return make_path_study()


@dataclass
class RuntimeFixture:
    runtime: _DjangoR7ResearchResultTestRuntime
    clock: FixedClock
    forecast: ForecastProvider


def _persist_policy() -> None:
    store = _DjangoR7SamplePolicyStore()
    with store.atomic():
        store.append(make_policy_record())


def _runtime() -> RuntimeFixture:
    _persist_policy()
    clock = FixedClock(RESULT_RECORDED_AT)
    forecast = ForecastProvider()
    runtime = _build_django_r7_research_result_test_runtime(
        forecast_provider=forecast,
        historical_analogy_provider=AnalogyProvider(),
        path_study_provider=PathProvider(),
        clock=clock,
    )
    return RuntimeFixture(runtime, clock, forecast)


def _command() -> RegisterR7ResearchResultCommand:
    policy = make_policy_record()
    return RegisterR7ResearchResultCommand(
        result_id="r7-result:scenario-probability:1",
        result_version="r7-result.v1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        as_of=EVALUATED_AT,
    )


@pytest.mark.django_db
def test_id_only_registration_rereads_all_owners_and_supports_exact_pit_query() -> None:
    fixture = _runtime()
    result = fixture.runtime.register.execute(_command())

    assert result.recorded_at == RESULT_RECORDED_AT
    assert result.evidence_graph.historical_analogy is not None
    assert result.evidence_graph.path_study is not None
    assert result.evidence_graph.path_study.transition_probabilities
    assert result.publishes_model_probability is False
    assert result.produces_decision is False
    assert result.executes_orders is False
    assert result.must_not_execute is True
    assert R7ResearchResultModel._default_manager.count() == 1
    policy = make_policy_record()
    assert fixture.forecast.calls == [
        (
            policy.scope,
            policy.policy.sample_window_start,
            policy.policy.sample_window_end,
            EVALUATED_AT,
        )
    ]
    assert (
        fixture.runtime.get_exact.execute(
            GetExactR7ResearchResultCommand(
                result_id=result.result_id,
                result_version=result.result_version,
                expected_content_hash=result.content_hash,
                as_of=RESULT_RECORDED_AT,
            )
        )
        == result
    )


@pytest.mark.django_db
def test_missing_owner_data_and_mismatched_uow_fail_closed_without_rows() -> None:
    fixture = _runtime()
    fixture.forecast.fail = True
    with pytest.raises(R7ResearchResultUnavailable, match="Signal ledger unavailable"):
        fixture.runtime.register.execute(_command())
    assert R7ResearchResultModel._default_manager.count() == 0

    wrong_path = PathProvider()
    wrong_path.unit_of_work_key = "django:other"
    with pytest.raises(ValueError, match="different units of work"):
        _build_django_r7_research_result_test_runtime(
            forecast_provider=ForecastProvider(),
            historical_analogy_provider=AnalogyProvider(),
            path_study_provider=wrong_path,
            clock=fixture.clock,
        )


@pytest.mark.django_db
def test_canonical_owner_runtime_blocks_when_any_owner_graph_is_absent() -> None:
    _persist_policy()
    runtime = _build_django_r7_research_result_owner_runtime()

    with pytest.raises(R7ResearchResultUnavailable, match="owner evidence"):
        runtime.register.execute(_command())

    assert R7ResearchResultModel._default_manager.count() == 0


@pytest.mark.django_db
def test_production_runtime_without_owner_graph_is_inert_and_writes_nothing() -> None:
    runtime = build_django_r7_research_result_runtime()

    with pytest.raises(R7ResearchResultUnavailable, match="owner providers"):
        runtime.register.execute(_command())

    assert R7ResearchResultModel._default_manager.count() == 0


@pytest.mark.django_db
def test_duplicate_identity_stale_and_future_queries_fail_closed() -> None:
    fixture = _runtime()
    result = fixture.runtime.register.execute(_command())

    with pytest.raises(R7ResearchResultConflict, match="already sealed"):
        fixture.runtime.register.execute(_command())
    assert (
        fixture.runtime.repository.get_exact(
            result_id=result.result_id,
            result_version=result.result_version,
            expected_content_hash=result.content_hash,
            as_of=RESULT_RECORDED_AT - timedelta(microseconds=1),
        )
        is None
    )
    with pytest.raises(R7ResearchResultUnavailable, match="future"):
        fixture.runtime.repository.get_exact(
            result_id=result.result_id,
            result_version=result.result_version,
            expected_content_hash=result.content_hash,
            as_of=RESULT_RECORDED_AT + timedelta(microseconds=1),
        )


@pytest.mark.django_db
def test_direct_bulk_base_related_update_and_delete_paths_are_rejected() -> None:
    fixture = _runtime()
    result = fixture.runtime.register.execute(_command())
    row = R7ResearchResultModel._default_manager.get()
    values = _result_values(result)

    row.forecast_observation_count = 999
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(raw=True)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        R7ResearchResultModel._default_manager.update(forecast_observation_count=999)
    with pytest.raises(ValidationError, match="exact repository appends"):
        R7ResearchResultModel._default_manager.bulk_create(
            [R7ResearchResultModel(sample_policy=row.sample_policy, **values)]
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        R7ResearchResultModel._default_manager.create(
            sample_policy=row.sample_policy,
            **values,
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        row.sample_policy.research_results.create(**values)
    with pytest.raises(ValidationError, match="exact insert claim"):
        R7ResearchResultModel._default_manager.get_or_create(
            result_id="r7-result:unclaimed",
            result_version="r7-result.v1",
            defaults={"sample_policy": row.sample_policy, **values},
        )
    private_queryset = R7ResearchResultModel._base_manager.filter(pk=row.pk)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        private_queryset._raw_delete("default")
    with pytest.raises(ValidationError, match="cannot be updated"):
        private_queryset._update([])
    with pytest.raises(ValidationError, match="private insert"):
        private_queryset._insert([], [])
    with pytest.raises(ValidationError, match="private bulk insert"):
        private_queryset._batched_insert([], [], 1)
    collector = Collector(using="default")
    collector.collect([row])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        with transaction.atomic():
            collector.delete()
    assert R7ResearchResultModel._default_manager.count() == 1


@pytest.mark.django_db
def test_raw_header_identity_and_nested_payload_tamper_are_detected() -> None:
    fixture = _runtime()
    result = fixture.runtime.register.execute(_command())
    row = R7ResearchResultModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_research_result SET result_id = %s WHERE id = %s",
            ["r7-result:tampered", row.pk],
        )
    with pytest.raises(R7ResearchResultCorruption, match="header mismatch"):
        fixture.runtime.repository.get_exact(
            result_id=result.result_id,
            result_version=result.result_version,
            expected_content_hash=result.content_hash,
            as_of=RESULT_RECORDED_AT,
        )


@pytest.mark.django_db
def test_raw_typed_transition_payload_tamper_is_detected() -> None:
    fixture = _runtime()
    result = fixture.runtime.register.execute(_command())
    row = R7ResearchResultModel._default_manager.get()
    payload = deepcopy(row.canonical_payload)
    body = payload["body"]
    graph = body["evidence_graph"]
    path = graph["path_study"]
    path["transition_probabilities"][0]["probability"] = "0.99"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r7_research_result SET canonical_payload = %s WHERE id = %s",
            [json.dumps(payload), row.pk],
        )
    with pytest.raises(R7ResearchResultCodecError):
        fixture.runtime.repository.get_exact(
            result_id=result.result_id,
            result_version=result.result_version,
            expected_content_hash=result.content_hash,
            as_of=RESULT_RECORDED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_race_failure_rolls_back_the_shared_owner_transaction() -> None:
    fixture = _runtime()
    fixture.forecast.write_sentinel = True
    with (
        patch.object(R7ResearchResultModel, "save", side_effect=IntegrityError("race")),
        pytest.raises(R7ResearchResultConflict, match="race lost"),
    ):
        fixture.runtime.register.execute(_command())

    assert R7ResearchResultModel._default_manager.count() == 0
    assert not ResearchExperiment._default_manager.filter(
        experiment_id="r7-result-rollback-sentinel"
    ).exists()
    assert R7SamplePolicyModel._default_manager.count() == 1
