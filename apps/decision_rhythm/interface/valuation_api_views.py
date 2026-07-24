"""Valuation API views."""

import json
from collections.abc import Mapping
from typing import Any, cast

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_provider.application.chat_completion import (
    AIClientFactory,
    generate_chat_completion,
)
from apps.valuation.domain.entities import ValuationMethod

from ..application.workspace_services import (
    get_valuation_snapshot,
    recalculate_valuation_snapshot,
)
from .workspace_api_support import (
    _build_system_invalidation_template,
    _decimal,
    _extract_json_payload,
    _pulse_context,
    _regime_context,
)


def _request_payload(request: Request) -> Mapping[str, Any] | None:
    """Return an object-shaped request body without leaking DRF's dynamic type."""

    payload = request.data
    if not isinstance(payload, Mapping):
        return None
    return cast(Mapping[str, Any], payload)


def _object_body_error() -> Response:
    """Return the stable error used when JSON body is not an object."""

    return Response(
        {"success": False, "error": "request body must be a JSON object"},
        status=status.HTTP_400_BAD_REQUEST,
    )


class ValuationSnapshotDetailView(APIView):
    """GET /api/valuation/snapshot/{snapshot_id}/"""

    def get(self, request: Request, snapshot_id: str) -> Response:
        snapshot = get_valuation_snapshot(snapshot_id)
        if snapshot is None:
            return Response(
                {"success": False, "error": "Valuation snapshot not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "data": snapshot.to_dict()})


class ValuationRecalculateView(APIView):
    """POST /api/valuation/recalculate/"""

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        if payload is None:
            return _object_body_error()

        security_code = str(payload.get("security_code") or "").strip().upper()
        if not security_code:
            return Response(
                {"success": False, "error": "security_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valuation_method = (
            str(payload.get("valuation_method") or ValuationMethod.COMPOSITE.value).strip().upper()
        )
        supported_methods = {method.value for method in ValuationMethod}
        if valuation_method not in supported_methods:
            return Response(
                {"success": False, "error": "unsupported valuation_method"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fair_value = _decimal(payload.get("fair_value"))
        current_price = _decimal(payload.get("current_price"))
        if fair_value is None and current_price is None:
            return Response(
                {"success": False, "error": "fair_value or current_price is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if fair_value is None:
            fair_value = current_price
        if current_price is None:
            current_price = fair_value
        if fair_value is None or current_price is None:
            return Response(
                {"success": False, "error": "valid valuation prices are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if fair_value <= 0 or current_price <= 0:
            return Response(
                {"success": False, "error": "valuation prices must be positive"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_input_parameters = payload.get("input_parameters")
        if raw_input_parameters is None:
            input_parameters: dict[str, Any] = {"source": "api_recalculate"}
        elif isinstance(raw_input_parameters, Mapping):
            input_parameters = {str(key): value for key, value in raw_input_parameters.items()}
        else:
            return Response(
                {"success": False, "error": "input_parameters must be a JSON object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        snapshot = recalculate_valuation_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=input_parameters,
        )
        return Response(
            {"success": True, "data": snapshot.to_dict()}, status=status.HTTP_201_CREATED
        )


class InvalidationTemplateView(APIView):
    """POST /api/decision/workspace/invalidation/template/"""

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        if payload is None:
            return _object_body_error()

        security_code = str(payload.get("security_code") or "").strip().upper()
        side = str(payload.get("side") or "BUY").strip().upper()
        rationale = str(payload.get("rationale") or "").strip()

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

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        if payload is None:
            return _object_body_error()

        security_code = str(payload.get("security_code") or "").strip().upper()
        side = str(payload.get("side") or "BUY").strip().upper()
        rationale = str(payload.get("rationale") or "").strip()
        user_prompt = str(payload.get("user_prompt") or "").strip()
        raw_existing_rule = payload.get("existing_rule")
        if raw_existing_rule is None:
            existing_rule: dict[str, Any] = {}
        elif isinstance(raw_existing_rule, Mapping):
            existing_rule = {str(key): value for key, value in raw_existing_rule.items()}
        else:
            return Response(
                {"success": False, "error": "existing_rule must be a JSON object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
            raw_content = str(ai_response.get("content") or "")
            draft = _extract_json_payload(raw_content)
        except (TypeError, ValueError) as exc:
            return Response(
                {
                    "success": False,
                    "error": f"AI 返回解析失败: {exc}",
                    "fallback_template": system_template,
                    "raw_content": str(ai_response.get("content") or ""),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        draft.setdefault("logic", "AND")
        draft.setdefault("conditions", [])
        draft.setdefault("requires_user_confirmation", False)
        draft.setdefault("description", "AI 生成的证伪草稿")
        raw_meta = draft.get("meta")
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        meta["security_code"] = security_code
        meta["side"] = side
        meta["pulse_context"] = pulse
        meta["regime_context"] = regime
        draft["meta"] = meta

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
