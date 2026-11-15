"""Strict session-authenticated JSON interface for the calendar reference task."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import TypedDict, cast

from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.domain.institutional_calendar import EventLifecycle, KnowledgeMode
from apps.data_center.institutional_calendar_task_composition import (
    make_institutional_calendar_task,
)
from apps.data_center.interface.institutional_calendar_presenter import (
    present_institutional_calendar,
)
from core.exceptions import AgomTradeProException


class _Query(TypedDict):
    date_from: date
    date_to: date
    known_at: datetime
    mode: str
    event_type: str | None
    lifecycle: str | None


class InstitutionalCalendarQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Use explicit read fields; no caller database, source URL or credential input."""

    date_from = serializers.DateField()
    date_to = serializers.DateField()
    known_at = serializers.DateTimeField(default_timezone=UTC)
    mode = serializers.ChoiceField(choices=tuple(item.value for item in KnowledgeMode))
    event_type = serializers.CharField(
        max_length=240, required=False, default=None, allow_null=True, allow_blank=True
    )
    lifecycle = serializers.ChoiceField(
        choices=tuple(item.value for item in EventLifecycle),
        required=False,
        default=None,
        allow_null=True,
        allow_blank=True,
    )

    def validate_known_at(self, value: datetime) -> datetime:
        """Require a supplied offset rather than guess an unzoned knowledge cutoff."""
        raw = self.initial_data.get("known_at")
        if not isinstance(raw, str) or re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", raw) is None:
            raise serializers.ValidationError("知识截止点必须包含明确时区。")
        return value


class InstitutionalCalendarView(APIView):
    """Let ordinary signed-in users read exact reference facts without write rights."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)
    http_method_names = ("get", "head", "options")

    def get(self, request: Request) -> Response:
        """Validate all query keys and delegate source/time semantics to Application."""
        serializer = InstitutionalCalendarQuerySerializer(data=request.query_params)
        allowed = set(serializer.fields)
        if set(request.query_params) - allowed or any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            return Response(
                {
                    "success": False,
                    "error": "查询字段重复或不受支持。",
                    "code": "INSTITUTIONAL_CALENDAR_QUERY_INVALID",
                },
                status=400,
            )
        serializer.is_valid(raise_exception=True)
        values = cast(_Query, serializer.validated_data)
        try:
            result = make_institutional_calendar_task().execute(
                values["date_from"],
                values["date_to"],
                known_at=values["known_at"],
                checked_at=timezone.now(),
                mode=KnowledgeMode(values["mode"]),
                event_type=values["event_type"] or None,
                lifecycle=None if not values["lifecycle"] else EventLifecycle(values["lifecycle"]),
            )
        except AgomTradeProException as error:
            return Response(
                {
                    "success": False,
                    "error": "日历查询无法完成，请核对日期、知识截止点或来源配置。",
                    "code": error.code,
                },
                status=422,
            )
        return Response({"success": True, "data": present_institutional_calendar(result)})


__all__ = ["InstitutionalCalendarQuerySerializer", "InstitutionalCalendarView"]
