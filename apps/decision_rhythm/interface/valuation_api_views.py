"""Valuation API views."""

import json

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .workspace_api_support import (
    AIClientFactory,
    _build_system_invalidation_template,
    _decimal,
    _extract_json_payload,
    _pulse_context,
    _regime_context,
    generate_chat_completion,
    get_valuation_snapshot,
    recalculate_valuation_snapshot,
)


class ValuationSnapshotDetailView(APIView):
    """GET /api/valuation/snapshot/{snapshot_id}/"""

    def get(self, request, snapshot_id: str) -> Response:
        snapshot = get_valuation_snapshot(snapshot_id)
        if snapshot is None:
            return Response(
                {"success": False, "error": "Valuation snapshot not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "data": snapshot.to_dict()})


class ValuationRecalculateView(APIView):
    """POST /api/valuation/recalculate/"""

    def post(self, request) -> Response:
        security_code = (request.data or {}).get("security_code")
        if not security_code:
            return Response(
                {"success": False, "error": "security_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valuation_method = (request.data or {}).get("valuation_method", "COMPOSITE")
        fair_value = _decimal((request.data or {}).get("fair_value"))
        current_price = _decimal((request.data or {}).get("current_price"))
        if fair_value is None and current_price is None:
            return Response(
                {"success": False, "error": "fair_value or current_price is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fair_value = fair_value or current_price
        current_price = current_price or fair_value

        snapshot = recalculate_valuation_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=(request.data or {}).get("input_parameters")
            or {"source": "api_recalculate"},
        )
        return Response(
            {"success": True, "data": snapshot.to_dict()}, status=status.HTTP_201_CREATED
        )


class InvalidationTemplateView(APIView):
    """POST /api/decision/workspace/invalidation/template/"""

    def post(self, request) -> Response:
        security_code = str((request.data or {}).get("security_code") or "").strip().upper()
        side = str((request.data or {}).get("side") or "BUY").strip().upper()
        rationale = str((request.data or {}).get("rationale") or "").strip()

        if not security_code:
            return Response(
                {"success": False, "error": "security_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        template = _build_system_invalidation_template(
            security_code=security_code,
            side=side,
            rationale=rationale,
        )
        return Response(
            {
                "success": True,
                "data": {
                    "template": template,
                    "pulse_context": _pulse_context(),
                    "regime_context": _regime_context(),
                },
            }
        )


class InvalidationAIDraftView(APIView):
    """POST /api/decision/workspace/invalidation/ai-draft/"""

    def post(self, request) -> Response:
        security_code = str((request.data or {}).get("security_code") or "").strip().upper()
        side = str((request.data or {}).get("side") or "BUY").strip().upper()
        rationale = str((request.data or {}).get("rationale") or "").strip()
        user_prompt = str((request.data or {}).get("user_prompt") or "").strip()
        existing_rule = (request.data or {}).get("existing_rule") or {}

        if not security_code:
            return Response(
                {"success": False, "error": "security_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pulse = _pulse_context()
        regime = _regime_context()
        system_template = _build_system_invalidation_template(
            security_code=security_code,
            side=side,
            rationale=rationale,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是投资系统的证伪逻辑助手。只返回一个 JSON 对象。"
                    "字段必须包含 logic, conditions, requires_user_confirmation, description。"
                    "conditions 中每项必须包含 indicator_code, indicator_type, operator, threshold。"
                    "不要输出 Markdown，不要解释。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "生成适用于交易计划审批前的证伪逻辑草稿",
                        "security_code": security_code,
                        "side": side,
                        "rationale": rationale,
                        "user_prompt": user_prompt,
                        "existing_rule": existing_rule,
                        "pulse_context": pulse,
                        "regime_context": regime,
                        "system_template": system_template,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        ai_response = generate_chat_completion(
            messages=messages,
            temperature=0.2,
            max_tokens=500,
            factory_builder=AIClientFactory,
        )
        if ai_response.get("status") != "success":
            return Response(
                {
                    "success": False,
                    "error": ai_response.get("error_message") or "AI 生成失败",
                    "fallback_template": system_template,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            draft = _extract_json_payload(ai_response.get("content", ""))
        except Exception as exc:
            return Response(
                {
                    "success": False,
                    "error": f"AI 返回解析失败: {exc}",
                    "fallback_template": system_template,
                    "raw_content": ai_response.get("content", ""),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        draft.setdefault("logic", "AND")
        draft.setdefault("conditions", [])
        draft.setdefault("requires_user_confirmation", False)
        draft.setdefault("description", "AI 生成的证伪草稿")
        draft.setdefault("meta", {})
        draft["meta"]["security_code"] = security_code
        draft["meta"]["side"] = side
        draft["meta"]["pulse_context"] = pulse
        draft["meta"]["regime_context"] = regime

        return Response(
            {
                "success": True,
                "data": {
                    "draft": draft,
                    "pulse_context": pulse,
                    "regime_context": regime,
                    "provider_used": ai_response.get("provider_used", ""),
                    "model": ai_response.get("model", ""),
                },
            }
        )
