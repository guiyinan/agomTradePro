from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.prompt.composition import make_promote_prompt_version, make_run_prompt_evaluation


class PromptEvaluationSerializer(serializers.Serializer):
    version_id = serializers.CharField(max_length=64)
    dataset_id = serializers.CharField(max_length=64)
    evaluation_type = serializers.ChoiceField(choices=["offline", "online", "regression"])
    provider = serializers.CharField(max_length=64, required=False, allow_blank=True)
    model = serializers.CharField(max_length=64, required=False, allow_blank=True)
    temperature = serializers.FloatField(default=0)
    max_cost = serializers.DecimalField(max_digits=12, decimal_places=6)
    max_tokens = serializers.IntegerField(min_value=1)
    max_cases = serializers.IntegerField(min_value=1)
    assertion_results = serializers.ListField(child=serializers.DictField(), default=list)


class PromptEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):  # type: ignore[no-untyped-def]
        serializer = PromptEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = make_run_prompt_evaluation().execute(dict(serializer.validated_data))
        return Response(
            {
                "run_id": run.run_id,
                "status": run.status,
                "actual_cost": str(run.actual_cost),
                "actual_tokens": run.actual_tokens,
                "executed_cases": run.executed_cases,
                "failure_summary": run.failure_summary,
            },
            status=status.HTTP_201_CREATED,
        )


class PromptVersionActivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, version_id: str):  # type: ignore[no-untyped-def]
        decision = make_promote_prompt_version().execute(version_id)
        response_status = status.HTTP_200_OK if decision.decision == "approved" else status.HTTP_409_CONFLICT
        return Response(
            {
                "decision_id": decision.decision_id,
                "version_id": decision.prompt_version_id,
                "decision": decision.decision,
                "evidence": decision.evidence,
            },
            status=response_status,
        )

