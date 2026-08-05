"""Comprehensive valuation action for the equity API viewset.

This action is isolated from the general analysis mixin because its OpenAPI
contract and response assembly are comparatively verbose.  It is composed by
``EquityAnalysisActionsMixin`` and deliberately does not import the legacy
``views`` facade.
"""

from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.public import get_decision_publication_gate
from apps.equity.application.use_cases import (
    ComprehensiveValuationRequest,
    ComprehensiveValuationUseCase,
)

from .serializers import (
    ComprehensiveValuationRequestSerializer,
    ComprehensiveValuationResponseSerializer,
)
from .valuation_actions import typed_action, typed_schema


class EquityComprehensiveValuationActionsMixin:
    """Expose the comprehensive valuation action."""

    stock_repo: Any

    def _get_comprehensive_publication_gate(
        self,
        dataset_key: str,
        publication_key: str,
    ) -> dict[str, object] | None:
        """Resolve the publication gate, keeping the owner hook patchable."""

        return get_decision_publication_gate(dataset_key, publication_key)

    def _build_comprehensive_valuation_use_case(self) -> ComprehensiveValuationUseCase:
        """Build the valuation use case for direct mixin consumers."""

        return ComprehensiveValuationUseCase(stock_repository=self.stock_repo)

    @typed_schema(
        summary="综合估值分析",
        description="整合多种估值方法，提供综合的低估/高估判断",
        request=ComprehensiveValuationRequestSerializer,
        responses={200: ComprehensiveValuationResponseSerializer},
    )
    @typed_action(detail=False, methods=["post"], url_path="comprehensive-valuation")
    def comprehensive_valuation(self, request: Request) -> Response:
        """POST /api/equity/comprehensive-valuation/."""
        serializer = ComprehensiveValuationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        mode = str(data["mode"])
        publication_key = str(data["publication_key"])
        publication_gates: dict[str, dict[str, object] | None] = {}
        if mode == "published":
            for dataset_key in (
                "equity.financial.fact",
                "equity.valuation.fact",
                "equity.price.bar",
            ):
                publication_gates[dataset_key] = self._get_comprehensive_publication_gate(
                    dataset_key,
                    publication_key,
                )
            blocked_publication = next(
                (
                    gate
                    for gate in publication_gates.values()
                    if gate is None or bool(gate.get("must_not_use_for_decision"))
                ),
                None,
            )
            if blocked_publication is not None:
                return Response(
                    {
                        "success": False,
                        "status": "blocked",
                        "stock_code": str(data["stock_code"]),
                        "stock_name": "",
                        "overall_score": 0.0,
                        "overall_signal": "hold",
                        "recommendation": "",
                        "confidence": 0.0,
                        "scores": [],
                        "error": (
                            blocked_publication.get("blocked_reason")
                            if blocked_publication
                            else "canonical_publication_missing"
                        ),
                        "mode": mode,
                        "publication_key": publication_key,
                        "publication_gates": publication_gates,
                        "must_not_use_for_decision": True,
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                {
                    "success": False,
                    "status": "blocked",
                    "stock_code": str(data["stock_code"]),
                    "stock_name": "",
                    "overall_score": 0.0,
                    "overall_signal": "hold",
                    "recommendation": "",
                    "confidence": 0.0,
                    "scores": [],
                    "error": "canonical_publication_member_snapshot_missing",
                    "mode": mode,
                    "publication_key": publication_key,
                    "publication_gates": publication_gates,
                    "must_not_use_for_decision": True,
                },
                status=status.HTTP_200_OK,
            )

        use_case_request = ComprehensiveValuationRequest(
            stock_code=data["stock_code"],
            lookback_days=data.get("lookback_days", 252),
            industry_avg_pe=data.get("industry_avg_pe", 20.0),
            industry_avg_pb=data.get("industry_avg_pb", 2.0),
            risk_free_rate=data.get("risk_free_rate", 0.03),
            mode=mode,
            publication_key=publication_key,
        )
        use_case = self._build_comprehensive_valuation_use_case()
        use_case_response = use_case.execute(use_case_request)

        response_serializer = ComprehensiveValuationResponseSerializer(use_case_response)
        payload = dict(response_serializer.data)
        payload["mode"] = mode
        payload["publication_key"] = publication_key
        if mode == "published":
            payload["publication_gates"] = publication_gates
            payload["must_not_use_for_decision"] = False
        return Response(payload, status=status.HTTP_200_OK)


__all__ = ["EquityComprehensiveValuationActionsMixin"]
