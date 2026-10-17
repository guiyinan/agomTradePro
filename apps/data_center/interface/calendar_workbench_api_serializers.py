"""Strict JSON inputs for the session-bound calendar workbench API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import cast

from django.http import QueryDict
from rest_framework import serializers

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CaptureExchangeCalendarSnapshotIntent,
)

_MAX_CONFIRMATION_TOKEN_CHARACTERS = 32_768


class _StrictObjectSerializer(serializers.Serializer[dict[str, object]]):
    """Reject non-object input and every field outside an explicit contract."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Reject unknown keys before DRF can silently ignore them."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("请求体必须是 JSON 对象。")
        keys = tuple(data.keys())
        if any(type(key) is not str for key in keys):
            raise serializers.ValidationError("请求字段名称无效。")
        if set(cast(tuple[str, ...], keys)) - set(self.fields):
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "请求包含不支持的字段；身份、数据库、时间与有效期由服务端管理。"
                    ]
                }
            )
        return cast(dict[str, object], super().to_internal_value(data))


class _ExactTextField(serializers.CharField):
    """Accept exact JSON strings without trimming or coercion."""

    def __init__(
        self,
        *,
        max_length: int,
        allow_blank: bool = False,
        write_only: bool = False,
    ) -> None:
        """Create a bounded, non-trimming text field."""

        super().__init__(
            max_length=max_length,
            min_length=1 if not allow_blank else None,
            allow_blank=allow_blank,
            trim_whitespace=False,
            write_only=write_only,
            help_text=(
                "工作台内部接续字段，仅供当前页面内存提交，不应显示或复制。" if write_only else None
            ),
        )

    def to_internal_value(self, data: object) -> str:
        """Reject booleans, numbers, and values with surrounding whitespace."""

        if type(data) is not str:
            raise serializers.ValidationError("必须提供字符串。")
        if data.strip() != data:
            raise serializers.ValidationError("首尾空格不被接受。")
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as error:
            raise serializers.ValidationError("字段长度或内容无效。") from error


class _ExactCalendarDateField(serializers.DateField):
    """Accept only a canonical ISO-8601 date string."""

    def to_internal_value(self, data: object) -> date:
        """Reject datetimes, date objects, and alternate date spellings."""

        if type(data) is not str:
            raise serializers.ValidationError("日期必须使用 YYYY-MM-DD 格式。")
        try:
            value = date.fromisoformat(data)
        except ValueError as error:
            raise serializers.ValidationError("日期必须使用有效的 YYYY-MM-DD 格式。") from error
        if value.isoformat() != data:
            raise serializers.ValidationError("日期必须使用规范的 YYYY-MM-DD 格式。")
        return value


class CalendarWorkbenchPrepareInputSerializer(_StrictObjectSerializer):
    """Validate the exchange and full date range used by one prepare request."""

    exchange = _ExactTextField(max_length=32)
    coverage_start = _ExactCalendarDateField()
    coverage_end = _ExactCalendarDateField()

    def validate_exchange(self, value: str) -> str:
        """Reject internal whitespace instead of normalizing exchange input."""

        if any(character.isspace() for character in value):
            raise serializers.ValidationError("交易所标识不能包含空格。")
        return value

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require an ordered explicit calendar range."""

        start = cast(date, attrs["coverage_start"])
        end = cast(date, attrs["coverage_end"])
        if start > end:
            raise serializers.ValidationError({"coverage_start": ["起始日期不能晚于结束日期。"]})
        return attrs

    def to_intent(self) -> CaptureExchangeCalendarSnapshotIntent:
        """Return the exact typed Application intent after strict validation."""

        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        try:
            intent = CaptureExchangeCalendarSnapshotIntent(
                exchange=cast(str, data["exchange"]),
                coverage_start=cast(date, data["coverage_start"]),
                coverage_end=cast(date, data["coverage_end"]),
            )
            intent.__post_init__()
            return intent
        except CalendarPublicationOperationsError as error:
            raise serializers.ValidationError(
                {"non_field_errors": ["交易所或日期范围无效，请检查后重试。"]}
            ) from error


class CalendarWorkbenchConfirmInputSerializer(_StrictObjectSerializer):
    """Validate a hidden opaque token as the sole confirmation input."""

    confirmation_token = _ExactTextField(
        max_length=_MAX_CONFIRMATION_TOKEN_CHARACTERS,
        write_only=True,
    )

    def to_token(self) -> str:
        """Return the exact token after rejecting all caller-supplied authority."""

        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        return cast(str, data["confirmation_token"])


class CalendarWorkbenchScopeQuerySerializer(_StrictObjectSerializer):
    """Reject all query parameters for the global configuration metadata read."""

    def to_scope_query(self) -> None:
        """Validate that the caller did not choose a dataset, exchange, or cutoff."""

        self.is_valid(raise_exception=True)
        return None


class CalendarWorkbenchCurrentQuerySerializer(_StrictObjectSerializer):
    """Accept one exchange and no caller-selected dataset or cutoff."""

    exchange = _ExactTextField(max_length=32)

    def to_exchange(self) -> str:
        """Return one exact exchange value and reject duplicate query keys."""

        if (
            isinstance(self.initial_data, QueryDict)
            and len(self.initial_data.getlist("exchange")) != 1
        ):
            raise serializers.ValidationError({"exchange": ["必须且只能提供一个交易所标识。"]})
        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        return cast(str, data["exchange"])


__all__ = [
    "CalendarWorkbenchConfirmInputSerializer",
    "CalendarWorkbenchCurrentQuerySerializer",
    "CalendarWorkbenchPrepareInputSerializer",
    "CalendarWorkbenchScopeQuerySerializer",
]
