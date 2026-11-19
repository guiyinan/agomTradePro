"""Native transaction/immutability evidence; all price/spec trials here are fixtures."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, connections, transaction

from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.infrastructure.pit_models import PITFactVersionModel
from apps.data_center.infrastructure.pit_repository import PITManifestRepository
from apps.research.application.event_study_control import EventStudyControl
from apps.research.application.use_cases import RunTrial
from apps.research.domain.event_study_control import (
    EventStudyBindingRequest,
    EventStudyControlError,
    FinalOOSClaim,
)
from apps.research.infrastructure.event_study_control_models import (
    EventStudyBindingModel,
    EventStudyFinalOOSClaimModel,
    EventStudySpecModel,
)
from apps.research.infrastructure.event_study_control_repository import DjangoEventStudyRegistry
from apps.research.infrastructure.models import (
    DatasetSplitSpec,
    ExperimentTrial,
    MultipleTestFamily,
    ResearchExperiment,
)
from apps.research.infrastructure.repositories import ResearchRegistryRepository

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=(
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "apps.research",
            "apps.data_center",
        ),
    ),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="native PostgreSQL required"),
]
DOCUMENT = (
    (Path(__file__).resolve().parents[2] / "fixtures/research/cal_event_study_v1.json")
    .read_bytes()
    .decode("utf-8")
)
SPEC = json.loads(DOCUMENT)
SPEC_SHA = hashlib.sha256(DOCUMENT.encode()).hexdigest()
assert SPEC_SHA == "29a44d0cd2670dd2a72853494d21271c9765d6584dafa4998e1df3c2a6edfe71"
AS_OF = datetime(2026, 11, 18, 10, tzinfo=UTC)


@pytest.fixture
def registered() -> tuple[DjangoEventStudyRegistry, EventStudyBindingRequest, int]:
    assert connection.settings_dict["NAME"] == "cal03_event_study_control_qa"
    user = get_user_model()._default_manager.create(
        username="cal03-owner", is_active=True, is_staff=True
    )
    registry = DjangoEventStudyRegistry()
    registry.register_spec(DOCUMENT, SPEC_SHA, actor_user_id=user.pk)
    PITFactVersionModel.objects.create(
        dataset="cal03_fixture",
        business_key="synthetic-close",
        effective_at=AS_OF - timedelta(days=1),
        available_at=AS_OF - timedelta(days=1),
        ingested_at=AS_OF - timedelta(days=1),
        source_record_id="fixture-only-not-official",
        content_hash="1" * 64,
        pit_quality="verified",
        payload={"synthetic_fixture": True, "close": 100.0},
    )
    manifest = PITManifestRepository().build(
        as_of_time=AS_OF,
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version="fixture-calendar",
        query_spec={"cal03_fixture": {}},
    )
    ResearchExperiment._default_manager.create(
        experiment_id="cal03-exp",
        question="fixture question",
        hypothesis="fixture only",
        owner=user,
    )
    params = {
        "event_study_spec": SPEC,
        "event_study_spec_sha256": SPEC_SHA,
        "synthetic_fixture": True,
    }
    temporal = SPEC["temporal_split"]
    RunTrial(ResearchRegistryRepository()).execute(
        {
            "experiment_id": "cal03-exp",
            "family_id": "cal03-family",
            "planned_trial_count": 2,
            "status": "draft",
            "pit_manifest_id": manifest.manifest_id,
            "backtest_id": None,
            "backtest_trust_status": "exploratory",
            "code_commit": "a" * 40,
            "dependency_lock_hash": "b" * 64,
            "engine_version": "cal03-fixture-v1",
            "parameters": params,
            "random_seed": 7,
            "benchmark_spec": {"synthetic_fixture": True},
            "cost_spec": {},
            "slippage_spec": {},
            "universe_spec": {},
            "split_spec": {
                "training_window": {
                    "minimum_calendar_years": temporal["first_training_window_years"],
                    "calendar_version": "fixture-calendar",
                },
                "validation_window": {
                    "trading_days_per_fold": temporal["validation_trading_days_per_fold"]
                },
                "out_of_sample_window": {
                    "trading_days": temporal["total_oos_trading_days"],
                    "use": "once",
                    "calendar_version": "fixture-calendar",
                },
                "walk_forward_windows": [
                    {"validation_sessions": temporal["validation_trading_days_per_fold"]}
                    for _ in range(temporal["minimum_walk_forward_folds"])
                ],
                "embargo_days": temporal["embargo"]["trading_days"],
            },
            "metrics": [],
        },
        actor_user_id=user.pk,
    )
    trial = ExperimentTrial._default_manager.get(experiment_id="cal03-exp")
    request = EventStudyBindingRequest(
        "cal03-study",
        trial.pk,
        SPEC["spec_id"],
        SPEC_SHA,
        manifest.manifest_hash,
        trial.parameter_hash,
        "a" * 40,
        "b" * 64,
    )
    return registry, request, user.pk


def test_binding_is_idempotent_but_final_claim_is_never_replayed(registered) -> None:
    registry, request, actor = registered
    first = registry.bind(request, actor_user_id=actor)
    assert registry.bind(request, actor_user_id=actor) == first
    receipt = registry.claim(request.study_key, actor_user_id=actor)
    assert receipt.binding == first and receipt.cumulative_family_trials == 1
    with pytest.raises(EventStudyControlError, match="FINAL_OOS_ALREADY_USED"):
        registry.claim(request.study_key, actor_user_id=actor)
    assert EventStudyFinalOOSClaimModel.objects.count() == 1


def test_two_independent_connections_have_one_committed_winner(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    barrier = Barrier(2)

    def claim() -> str:
        connections.close_all()
        try:
            barrier.wait(timeout=15)
            try:
                DjangoEventStudyRegistry().claim(request.study_key, actor_user_id=actor)
                return "claimed"
            except EventStudyControlError as error:
                return str(error)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: claim(), range(2)))
    assert sorted(results) == ["FINAL_OOS_ALREADY_USED", "claimed"]
    assert EventStudyFinalOOSClaimModel.objects.count() == 1


def test_evaluation_failure_cannot_refund_use(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)

    class Fail:
        def evaluate(self, claim: FinalOOSClaim) -> None:
            assert not connection.in_atomic_block
            assert EventStudyFinalOOSClaimModel.objects.filter(pk=claim.claim_id).exists()
            raise ArithmeticError("fixture failure after durable claim")

    with pytest.raises(ArithmeticError):
        EventStudyControl(registry).run_final_once(
            request.study_key, actor_user_id=actor, evaluator=Fail()
        )
    with pytest.raises(EventStudyControlError, match="FINAL_OOS_ALREADY_USED"):
        registry.claim(request.study_key, actor_user_id=actor)


def test_outer_rollback_is_rejected_before_claim(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    with (
        transaction.atomic(),
        pytest.raises(EventStudyControlError, match="OOS_REQUIRES_DURABLE_BOUNDARY"),
    ):
        registry.claim(request.study_key, actor_user_id=actor)
    assert not EventStudyFinalOOSClaimModel.objects.exists()


@pytest.mark.parametrize(
    "field", ["manifest_sha256", "parameter_sha256", "code_commit", "dependency_sha256"]
)
def test_expected_identity_mismatch_cannot_bind(registered, field: str) -> None:
    registry, request, actor = registered
    with pytest.raises(EventStudyControlError, match="BINDING_IDENTITY_MISMATCH"):
        registry.bind(
            replace(request, **{field: "f" * (40 if field == "code_commit" else 64)}),
            actor_user_id=actor,
        )
    assert not EventStudyBindingModel.objects.exists()


def test_registered_frozen_spec_cannot_be_weakened_or_replaced(registered) -> None:
    registry, request, actor = registered
    weak = json.loads(DOCUMENT)
    weak["sample_gates"]["target_expected_session_coverage_min"] = 0.5
    text = json.dumps(weak)
    with pytest.raises(EventStudyControlError, match="FROZEN_SPEC_CONFLICT"):
        registry.register_spec(text, hashlib.sha256(text.encode()).hexdigest(), actor_user_id=actor)
    assert EventStudySpecModel.objects.get().document_sha256 == SPEC_SHA
    trial = ExperimentTrial._default_manager.get(pk=request.trial_id)
    params = dict(trial.parameters)
    params["event_study_spec"] = weak
    ExperimentTrial._default_manager.filter(pk=trial.pk).update(parameters=params)
    with pytest.raises(EventStudyControlError, match="FROZEN_SPEC_MISMATCH"):
        registry.bind(request, actor_user_id=actor)


@pytest.mark.parametrize(
    "tamper",
    ["parameters", "split", "code", "manifest_clock", "manifest_payload", "manifest_future_clock"],
)
def test_any_bound_input_drift_blocks_claim(registered, tamper: str) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    if tamper == "parameters":
        ExperimentTrial._default_manager.filter(pk=request.trial_id).update(parameter_hash="e" * 64)
    elif tamper == "code":
        ExperimentTrial._default_manager.filter(pk=request.trial_id).update(code_commit="e" * 40)
    else:
        with connection.cursor() as cursor:
            if tamper == "split":
                cursor.execute(
                    "UPDATE research_dataset_split_spec SET embargo_days=0 WHERE trial_id=%s",
                    [request.trial_id],
                )
            elif tamper == "manifest_clock":
                cursor.execute(
                    "UPDATE data_center_pit_fact_version SET available_at=%s WHERE dataset='cal03_fixture'",
                    [AS_OF - timedelta(days=2)],
                )
            elif tamper == "manifest_future_clock":
                cursor.execute(
                    "UPDATE data_center_pit_fact_version SET available_at=%s WHERE dataset='cal03_fixture'",
                    [AS_OF + timedelta(days=2)],
                )
            else:
                cursor.execute(
                    "UPDATE data_center_pit_fact_version SET payload=%s WHERE dataset='cal03_fixture'",
                    [json.dumps({"close": 999})],
                )
    with pytest.raises(EventStudyControlError):
        registry.claim(request.study_key, actor_user_id=actor)
    assert not EventStudyFinalOOSClaimModel.objects.exists()


def test_other_actor_is_denied_without_claiming(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    other = get_user_model()._default_manager.create(username="cal03-other", is_active=True)
    with pytest.raises(EventStudyControlError, match="RESEARCH_ACCESS_DENIED"):
        registry.claim(request.study_key, actor_user_id=other.pk)
    assert not EventStudyFinalOOSClaimModel.objects.exists()


@pytest.mark.parametrize(
    "table",
    [
        "research_event_study_spec",
        "research_event_study_binding",
        "research_event_study_final_oos_claim",
    ],
)
def test_native_update_delete_guards_reject_raw_sql(registered, table: str) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    registry.claim(request.study_key, actor_user_id=actor)
    for statement in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}"):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement)
    assert EventStudyFinalOOSClaimModel.objects.count() == 1


def test_orm_save_base_bulk_and_delete_paths_cannot_refund(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    registry.claim(request.study_key, actor_user_id=actor)
    row = EventStudyFinalOOSClaimModel.objects.get()
    for operation in (
        row.save,
        row.save_base,
        row.delete,
        lambda: EventStudyFinalOOSClaimModel.objects.all().delete(),
        lambda: EventStudyFinalOOSClaimModel._base_manager.all().update(actor_user_id=999),
        lambda: EventStudyFinalOOSClaimModel.objects.bulk_create([row], ignore_conflicts=True),
    ):
        with pytest.raises(ValidationError):
            operation()


def test_operator_command_replays_exact_original_without_refreshing_clock(registered) -> None:
    _, _, actor = registered
    original = EventStudySpecModel.objects.get().registered_at
    call_command(
        "register_event_study_spec",
        file=str(Path(__file__).resolve().parents[2] / "fixtures/research/cal_event_study_v1.json"),
        expected_sha256=SPEC_SHA,
        actor_user_id=actor,
    )
    assert EventStudySpecModel.objects.get().registered_at == original


def test_claim_survives_a_fresh_python_process(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    registry.claim(request.study_key, actor_user_id=actor)
    program = """import django,sys;django.setup()
from apps.research.infrastructure.event_study_control_repository import DjangoEventStudyRegistry
from apps.research.domain.event_study_control import EventStudyControlError
try:
 DjangoEventStudyRegistry().claim('cal03-study',actor_user_id=int(sys.argv[1]))
except EventStudyControlError as error:
 print(str(error));sys.exit(0 if str(error)=='FINAL_OOS_ALREADY_USED' else 2)
sys.exit(3)
"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", program, str(actor)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("FINAL_OOS_ALREADY_USED")


def add_family_trial(
    request: EventStudyBindingRequest, identity: str, *, new_family: bool = False
) -> None:
    original = ExperimentTrial._default_manager.get(pk=request.trial_id)
    family_id = original.family_id
    if new_family:
        family_id = identity + "-family"
        MultipleTestFamily._default_manager.create(
            family_id=family_id, experiment_id=original.experiment_id, planned_trial_count=2
        )
    values = {name: getattr(original, name) for name in ExperimentTrial.IMMUTABLE_FIELDS}
    values["family_id"] = family_id
    ExperimentTrial._default_manager.create(
        trial_id=identity, status="draft", parameter_hash=original.parameter_hash, **values
    )
    old_split = DatasetSplitSpec._default_manager.get(pk=original.pk)
    DatasetSplitSpec._default_manager.create(
        trial_id=identity,
        **{
            name: getattr(old_split, name)
            for name in (
                "training_window",
                "validation_window",
                "out_of_sample_window",
                "walk_forward_windows",
                "embargo_days",
            )
        },
    )


@pytest.mark.parametrize("new_family", [False, True])
def test_new_trial_or_family_does_not_reopen_same_experiment(registered, new_family: bool) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    registry.claim(request.study_key, actor_user_id=actor)
    add_family_trial(request, "later", new_family=new_family)
    with pytest.raises(EventStudyControlError, match="PREREGISTRATION_CONFLICT"):
        registry.bind(
            replace(request, study_key="another-key", trial_id="later"), actor_user_id=actor
        )
    assert EventStudyFinalOOSClaimModel.objects.count() == 1


def test_appended_family_attempt_is_counted_and_over_plan_is_blocked(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    add_family_trial(request, "second")
    assert registry.claim(request.study_key, actor_user_id=actor).cumulative_family_trials == 2


def test_over_plan_attempts_are_not_silently_ignored(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    add_family_trial(request, "second")
    add_family_trial(request, "third")
    with pytest.raises(EventStudyControlError, match="FAMILY_ATTEMPT_LIMIT_EXCEEDED"):
        registry.claim(request.study_key, actor_user_id=actor)
    assert not EventStudyFinalOOSClaimModel.objects.exists()


@pytest.mark.parametrize("field,value", [("embargo_days", 0), ("walk_forward_windows", [])])
def test_lower_split_thresholds_are_rejected_before_binding(
    registered, field: str, value: object
) -> None:
    registry, request, actor = registered
    DatasetSplitSpec._default_manager.filter(pk=request.trial_id).update(**{field: value})
    with pytest.raises(EventStudyControlError):
        registry.bind(request, actor_user_id=actor)


def test_inactive_account_cannot_consume(registered) -> None:
    registry, request, actor = registered
    registry.bind(request, actor_user_id=actor)
    get_user_model()._default_manager.filter(pk=actor).update(is_active=False)
    with pytest.raises(EventStudyControlError, match="RESEARCH_ACCESS_DENIED"):
        registry.claim(request.study_key, actor_user_id=actor)
    assert not EventStudyFinalOOSClaimModel.objects.exists()
