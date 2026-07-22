"""Authenticated APIs for forecast publication, checks and outcomes."""

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.signal.forecast_composition import (
    make_finalize_forecast_outcome,
    make_record_forecast_entry,
    make_record_forecast_evaluation,
)


class ForecastEntrySerializer(serializers.Serializer):
    entry_id = serializers.CharField(max_length=64, required=False)
    signal_id = serializers.IntegerField(required=False, allow_null=True)
    published_at = serializers.DateTimeField()
    direction = serializers.ChoiceField(choices=["LONG", "SHORT", "NEUTRAL"])
    asset_code = serializers.CharField(max_length=32)
    horizon_end = serializers.DateTimeField()
    benchmark_asset = serializers.CharField(max_length=32)
    probability = serializers.FloatField(min_value=0, max_value=1)
    invalidation_rule_version = serializers.CharField(max_length=64)
    decision_snapshot_id = serializers.CharField(max_length=64)
    pit_manifest_id = serializers.CharField(max_length=64)
    strategy_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    model_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    prompt_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    source = serializers.CharField(max_length=64)
    regime = serializers.CharField(max_length=32, required=False, allow_blank=True)


class ForecastEvaluationSerializer(serializers.Serializer):
    checked_at = serializers.DateTimeField()
    data_version_ids = serializers.ListField(child=serializers.IntegerField(), default=list)
    conditions = serializers.ListField(child=serializers.DictField(), default=list)
    missing_reason = serializers.CharField(required=False, allow_blank=True)


class ForecastOutcomeSerializer(serializers.Serializer):
    finalized_at = serializers.DateTimeField()
    outcome_type = serializers.ChoiceField(
        choices=["expired", "invalidated", "exited", "data_insufficient"]
    )
    asset_return = serializers.FloatField(required=False, allow_null=True)
    benchmark_return = serializers.FloatField(required=False, allow_null=True)
    neutral_band = serializers.FloatField(min_value=0)
    evidence = serializers.DictField(required=False, default=dict)


class ForecastEntryCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):  # type: ignore[no-untyped-def]
        serializer = ForecastEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            entry = make_record_forecast_entry().execute(**serializer.validated_data)
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(
            {"entry_id": entry.entry_id, "status": entry.status},
            status=status.HTTP_201_CREATED,
        )


class ForecastEvaluationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, entry_id: str):  # type: ignore[no-untyped-def]
        serializer = ForecastEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            evaluation = make_record_forecast_evaluation().execute(
                entry_id=entry_id, **serializer.validated_data
            )
        except ObjectDoesNotExist:
            return Response(
                {"detail": "Forecast entry not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "evaluation_id": evaluation.evaluation_id,
                "triggered": evaluation.triggered,
                "status_transition": evaluation.status_transition,
            },
            status=status.HTTP_201_CREATED,
        )


class ForecastOutcomeCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, entry_id: str):  # type: ignore[no-untyped-def]
        serializer = ForecastOutcomeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outcome = make_finalize_forecast_outcome().execute(
                entry_id=entry_id, **serializer.validated_data
            )
        except ObjectDoesNotExist:
            return Response(
                {"detail": "Forecast entry not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "entry_id": outcome.entry_id,
                "outcome_type": outcome.outcome_type,
                "hit": outcome.hit,
                "brier_score": outcome.brier_score,
            },
            status=status.HTTP_201_CREATED,
        )
