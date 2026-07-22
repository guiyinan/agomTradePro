"""HTTP contracts for experiments, trials and promotion decisions."""

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.research.composition import (
    make_evaluate_promotion,
    make_register_experiment,
    make_run_trial,
)


class ExperimentSerializer(serializers.Serializer):
    question = serializers.CharField()
    hypothesis = serializers.CharField()


class TrialSerializer(serializers.Serializer):
    experiment_id = serializers.CharField(max_length=64)
    family_id = serializers.CharField(max_length=64)
    planned_trial_count = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(
        choices=["draft", "running", "completed", "failed", "aborted"], default="draft"
    )
    pit_manifest_id = serializers.CharField(max_length=64)
    backtest_id = serializers.IntegerField(required=False, allow_null=True)
    backtest_trust_status = serializers.ChoiceField(
        choices=["legacy_unverified", "exploratory", "pit_verified"]
    )
    code_commit = serializers.CharField(max_length=64)
    dependency_lock_hash = serializers.CharField(max_length=64)
    engine_version = serializers.CharField(max_length=64)
    parameters = serializers.DictField()
    random_seed = serializers.IntegerField()
    benchmark_spec = serializers.DictField()
    cost_spec = serializers.DictField()
    slippage_spec = serializers.DictField()
    universe_spec = serializers.DictField()
    split_spec = serializers.DictField()
    metrics = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class ExperimentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):  # type: ignore[no-untyped-def]
        serializer = ExperimentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        experiment = make_register_experiment().execute(
            **serializer.validated_data,
            owner_id=request.user.id,
        )
        return Response(
            {
                "experiment_id": experiment.experiment_id,
                "question": experiment.question,
                "hypothesis": experiment.hypothesis,
                "status": experiment.status,
            },
            status=status.HTTP_201_CREATED,
        )


class TrialListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):  # type: ignore[no-untyped-def]
        serializer = TrialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trial = make_run_trial().execute(dict(serializer.validated_data))
        return Response(
            {
                "trial_id": trial.trial_id,
                "experiment_id": trial.experiment_id,
                "family_id": trial.family_id,
                "status": trial.status,
                "parameter_hash": trial.parameter_hash,
                "pit_manifest_id": trial.pit_manifest_id,
            },
            status=status.HTTP_201_CREATED,
        )


class PromotionEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trial_id: str):  # type: ignore[no-untyped-def]
        decision = make_evaluate_promotion().execute(trial_id)
        return Response(
            {
                "decision_id": decision.decision_id,
                "trial_id": decision.trial_id,
                "decision": decision.decision,
                "evidence": decision.evidence,
                "decided_at": decision.decided_at.isoformat(),
            }
        )

