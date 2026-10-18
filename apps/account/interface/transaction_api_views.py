"""Account transaction and capital flow API views."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import (
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerBalanceSnapshotSummary,
    BrokerBaselineDecision,
)
from apps.account.application.interface_services import (
    get_user_capital_flow_queryset,
    get_user_portfolio,
)
from apps.account.application.manual_trade_sync import (
    BrokerTradeImportResult,
    ManualTradeImportUseCase,
)
from apps.account.application.transaction_record_use_cases import (
    CreateTransactionUseCase as CreateTransactionRecordUseCase,
)
from apps.account.application.transaction_record_use_cases import (
    GetTransactionUseCase,
    ListTransactionPageUseCase,
)
from apps.account.domain.transaction_record_contracts import CreateTransactionInput
from core.exceptions import AuthorizationError, InvalidInputError

from .permissions import TradingPermission
from .serializers import (
    CapitalFlowCreateSerializer,
    CapitalFlowSerializer,
    TransactionCreateData,
    TransactionCreatedSerializer,
    TransactionCreateSerializer,
    TransactionSerializer,
)

_ViewMethod = TypeVar("_ViewMethod", bound=Callable[..., object])
_typed_extend_schema = cast(
    Callable[..., Callable[[_ViewMethod], _ViewMethod]],
    extend_schema,
)


MAX_BROKER_IMPORT_FILE_BYTES = 10 * 1024 * 1024
MAX_TUI_BROKER_IMPORT_TEXT_BYTES = 2 * 1024 * 1024

ALLOWED_BROKER_IMPORT_SUFFIXES = {".csv", ".xlsx", ".xls"}
BASELINE_DECISIONS = ("pending", "included", "excluded")
_PUBLIC_BROKER_IMPORT_RESULT_FIELDS = (
    "total_rows",
    "valid_rows",
    "duplicate_rows",
    "error_rows",
    "rows",
    "errors",
    "imported_rows",
    "skipped_rows",
    "batch_id",
    "facts_saved_count",
    "duplicate_facts_reused_count",
    "pending_fact_count",
    "projected_fact_count",
    "already_in_baseline_count",
    "projection_blocked_count",
    "matching_failed_count",
    "new_fact_rows",
    "retryable_existing_rows",
    "terminal_duplicate_rows",
    "reconciliation_conflict_code",
    "reconciliation_error_code",
    "batch_summary_error_code",
    "balance_unavailable",
)
_TUI_BROKER_IMPORT_ROW_FIELDS = (
    "row_number",
    "transaction_id",
    "traded_at",
    "asset_code",
    "action",
    "shares",
    "price",
    "commission",
    "stamp_duty",
    "transfer_fee",
    "commission_known",
    "stamp_duty_known",
    "transfer_fee_known",
    "fee_known",
    "fees_known",
    "duplicate",
    "status",
    "status_reason",
    "reconciliation_state",
    "reconciliation_reason_code",
    "projection_outcome",
    "matching_status",
    "matching_reason_code",
)
_TUI_RECONCILIATION_STATE_LABELS = {
    "not_applicable": "不适用",
    "legacy_unverified": "历史事实待核对",
    "awaiting_baseline": "待核对余额",
    "projection_pending": "等待持仓投影",
    "projection_blocked": "持仓投影受阻",
    "projected": "持仓已更新",
    "already_in_baseline": "已包含在当前余额",
}
_TUI_FACT_STATUS_LABELS = {
    "fact_saved": "成交事实已保存",
    "existing_fact_reused": "复用已有成交事实",
    "fact_persistence_failed": "成交事实保存失败",
    "stable_key_conflict": "成交标识冲突，待核对",
    "fact_unavailable": "成交事实当前状态不可用",
}
_TUI_PROJECTION_OUTCOME_LABELS = {
    "awaiting_baseline": "待核对",
    "already_in_baseline": "已包含，不改数量",
    "projected": "已更新持仓数量",
    "blocked": "持仓投影受阻",
    "pending": "等待核对",
}
_TUI_MATCHING_STATUS_LABELS = {
    "matched": "已关联推荐",
    "manual_only": "未匹配推荐，成交已保存",
    "deferred": "等待匹配重试",
    "failed": "匹配失败",
}
_TUI_REASON_LABELS = {
    "real_account_mapping_missing": "未找到本地实盘账户映射",
    "broker_matcher_failed": "推荐匹配暂未完成",
    "BROKER_FACT_CURRENT_STATE_UNAVAILABLE": "成交事实当前状态无法确认，未重建；请重新导入并先核对文件和余额",
}


def _serialize_broker_import_result(result: BrokerTradeImportResult) -> dict[str, Any]:
    """Expose the public import contract without serializing its private preview context."""

    public_data = {
        key: getattr(result, key)
        for key in _PUBLIC_BROKER_IMPORT_RESULT_FIELDS
        if hasattr(result, key)
    }
    for field_name in (
        "reconciliation_error_code",
        "batch_summary_error_code",
        "balance_unavailable",
    ):
        public_data[field_name] = getattr(result, field_name, None)
    public_data["expected_fact_set_fingerprint"] = result.expected_fact_set_fingerprint
    public_data["expected_balance_fingerprint"] = result.expected_balance_fingerprint
    public_data["balance_snapshots"] = [
        asdict(snapshot)
        for snapshot in result.balance_snapshots
        if isinstance(snapshot, BrokerBalanceSnapshotSummary)
    ]
    return public_data


def _sanitize_tui_import_rows(result: dict[str, Any], *, preview_only: bool = False) -> None:
    """Keep only human-facing scalar fields and translate internal outcome codes."""

    rows = result.get("rows")
    if not isinstance(rows, list):
        return
    visible_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        visible_row = {
            key: value
            for key in _TUI_BROKER_IMPORT_ROW_FIELDS
            if key in row
            and isinstance(
                value := row[key],
                str | int | float | bool | type(None),
            )
        }
        action = visible_row.get("action")
        if isinstance(action, str):
            visible_row["action"] = {
                "buy": "买入",
                "sell": "卖出",
            }.get(action.lower(), "方向待识别")
        duplicate = visible_row.get("duplicate")
        if isinstance(duplicate, bool):
            visible_row["duplicate"] = "是" if duplicate else "否"

        fact_status = visible_row.pop("status", None)
        reconciliation_state = visible_row.pop("reconciliation_state", None)
        visible_row["status"] = (
            _TUI_FACT_STATUS_LABELS.get(fact_status, "成交事实状态待识别")
            if isinstance(fact_status, str)
            else ("预览有效，待确认" if preview_only else "处理结果待识别")
        )
        if isinstance(reconciliation_state, str):
            visible_row["reconciliation_status"] = _TUI_RECONCILIATION_STATE_LABELS.get(
                reconciliation_state,
                "待核对（状态尚未识别）",
            )
        elif isinstance(fact_status, str):
            visible_row["reconciliation_status"] = _TUI_FACT_STATUS_LABELS.get(
                fact_status,
                "待核对（状态尚未识别）",
            )
        else:
            visible_row["reconciliation_status"] = "待核对（状态尚未识别）"

        projection_outcome = visible_row.pop("projection_outcome", None)
        if isinstance(projection_outcome, str):
            visible_row["projection_status"] = _TUI_PROJECTION_OUTCOME_LABELS.get(
                projection_outcome,
                "待核对（持仓处理状态尚未识别）",
            )

        reconciliation_reason = visible_row.pop("reconciliation_reason_code", None)
        status_reason = visible_row.pop("status_reason", None)
        if isinstance(reconciliation_reason, str):
            visible_row["status_reason"] = _TUI_REASON_LABELS.get(
                reconciliation_reason,
                "待核对，原因尚未识别",
            )
        elif isinstance(status_reason, str):
            visible_row["status_reason"] = _TUI_REASON_LABELS.get(
                status_reason,
                "待核对，原因尚未识别",
            )

        matching_status = visible_row.pop("matching_status", None)
        if isinstance(matching_status, str):
            visible_row["matching_status"] = _TUI_MATCHING_STATUS_LABELS.get(
                matching_status,
                "待核对（匹配状态尚未识别）",
            )
        matching_reason = visible_row.pop("matching_reason_code", None)
        if isinstance(matching_reason, str):
            visible_row["matching_reason"] = _TUI_REASON_LABELS.get(
                matching_reason,
                "匹配原因尚未识别",
            )

        fee_known = visible_row.pop("fee_known", None)
        if fee_known is None:
            fee_known = visible_row.pop("fees_known", None)
        else:
            visible_row.pop("fees_known", None)
        fee_known_flags = {
            key: visible_row.pop(key, None)
            for key in (
                "commission_known",
                "stamp_duty_known",
                "transfer_fee_known",
            )
        }
        if isinstance(fee_known, bool):
            visible_row["fee_status"] = "费用信息已知" if fee_known else "费用信息未知"
        elif any(isinstance(value, bool) for value in fee_known_flags.values()):
            fee_labels = {
                "commission_known": "佣金",
                "stamp_duty_known": "印花税",
                "transfer_fee_known": "过户费",
            }
            visible_row["fee_status"] = "；".join(
                f"{fee_labels[key]}{'已知' if value else '未知'}"
                for key, value in fee_known_flags.items()
                if isinstance(value, bool)
            )
        else:
            fee_labels = {
                "commission": "佣金",
                "stamp_duty": "印花税",
                "transfer_fee": "过户费",
            }
            visible_row["fee_status"] = "；".join(
                f"{label}{'已知' if visible_row.get(key) is not None else '未知'}"
                for key, label in fee_labels.items()
            )
        visible_rows.append(visible_row)
    result["rows"] = visible_rows
    errors = result.get("errors")
    if isinstance(errors, list):
        visible_errors: list[Any] = []
        for error in errors:
            if (
                not isinstance(error, dict)
                or error.get("error_code") != "BROKER_FACT_CURRENT_STATE_UNAVAILABLE"
            ):
                visible_errors.append(error)
                continue
            visible_error: dict[str, Any] = {
                "message": _TUI_REASON_LABELS["BROKER_FACT_CURRENT_STATE_UNAVAILABLE"]
            }
            row_number = error.get("row_number")
            if isinstance(row_number, str) or (
                isinstance(row_number, int) and not isinstance(row_number, bool)
            ):
                visible_error["row_number"] = row_number
            visible_errors.append(visible_error)
        result["errors"] = visible_errors


def _add_tui_balance_columns(result: dict[str, Any]) -> None:
    """Join human-readable balance snapshots onto the existing trade preview grid."""

    snapshots = result.get("balance_snapshots")
    if not isinstance(snapshots, list):
        return
    snapshots_by_asset = {
        snapshot["asset_code"]: snapshot
        for snapshot in snapshots
        if isinstance(snapshot, dict) and isinstance(snapshot.get("asset_code"), str)
    }
    rows = result.get("rows")
    if not isinstance(rows, list):
        return
    visible_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        visible_row = dict(row)
        asset_code = row.get("asset_code")
        snapshot = snapshots_by_asset.get(asset_code) if isinstance(asset_code, str) else None
        if snapshot is not None:
            visible_row.update(
                {
                    "balance_total_shares": snapshot.get("total_shares"),
                    "balance_available_quantity": snapshot.get("available_quantity"),
                    "balance_available_status": (
                        "已知" if snapshot.get("available_quantity_known") is True else "未知"
                    ),
                    "balance_average_cost": snapshot.get("average_cost"),
                    "balance_reference_mark": snapshot.get("reference_mark"),
                    "balance_valuation_status": snapshot.get("valuation_status"),
                    "balance_source_updated_at": snapshot.get("source_updated_at"),
                    "balance_observed_at": snapshot.get("observed_at"),
                }
            )
        visible_rows.append(visible_row)
    result["rows"] = visible_rows


def _add_reconciliation_conflict_message(result: dict[str, Any], conflict_code: str | None) -> None:
    """Attach a stable readable explanation when facts were saved but projection was blocked."""

    if conflict_code is None:
        return
    messages = {
        "BROKER_FACT_PREVIEW_CHANGED": (
            "成交事实已保存，但文件事实范围与预览不一致；请重新预览后再核对余额。"
        ),
        "BROKER_BALANCE_PREVIEW_CHANGED": (
            "成交事实已保存，但本地余额已变化，持仓未投影；请重新预览并重新确认。"
        ),
    }
    message = messages.get(
        conflict_code,
        "成交事实已保存，但持仓核对条件已变化；请重新预览并确认。",
    )
    result["message"] = message
    result["reconciliation_blocked"] = {
        "code": conflict_code,
        "message": message,
    }


def _prepend_tui_import_summary_row(
    result: dict[str, Any],
    import_result: BrokerTradeImportResult,
    baseline_decision: str,
) -> None:
    """Prepend a display-only receipt without changing fact rows or business counts."""

    decision_labels = {
        "pending": "待核对",
        "included": "已包含",
        "excluded": "未包含",
    }
    summary = "；".join(
        (
            f"本次选择：{decision_labels.get(baseline_decision, '待核对')}",
            f"保存成交事实 {import_result.facts_saved_count}",
            f"复用已有事实 {import_result.duplicate_facts_reused_count}",
            f"待核对 {import_result.pending_fact_count}",
            f"数量投影 {import_result.projected_fact_count}",
            f"已包含 {import_result.already_in_baseline_count}",
            f"受阻 {import_result.projection_blocked_count}",
            f"匹配失败 {import_result.matching_failed_count}",
        )
    )
    conflict = result.get("message")
    if isinstance(conflict, str) and conflict:
        summary = f"{summary}；{conflict}"
    summary_row: dict[str, Any] = {
        "row_number": "汇总",
        "display_type": "summary",
        "status": "导入汇总",
        "summary": summary,
    }
    rows = result.get("rows")
    fact_rows = rows if isinstance(rows, list) else []
    result["rows"] = [summary_row, *fact_rows]


def _request_session_expiry(request: Request) -> str:
    """Return the existing authenticated session expiry for a private TUI continuation."""

    session = getattr(request, "session", None)
    expiry_getter = getattr(session, "get_expiry_date", None)
    if not callable(expiry_getter):
        raise ValidationError("当前登录会话无法建立预览交接，请重新登录后重试")
    expiry = expiry_getter()
    if not isinstance(expiry, datetime) or expiry.tzinfo is None:
        raise ValidationError("当前登录会话无法建立预览交接，请重新登录后重试")
    return expiry.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware_iso_datetime(value: Any) -> datetime:
    """Parse one ISO datetime only when its input carries an explicit offset."""

    if not isinstance(value, str):
        raise serializers.ValidationError("baseline_as_of 必须是带时区的 ISO 日期时间")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise serializers.ValidationError("baseline_as_of 必须是带时区的 ISO 日期时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise serializers.ValidationError("baseline_as_of 必须包含时区偏移")
    return parsed


class _AwareISODateTimeField(serializers.DateTimeField):
    """Require a timezone offset before DRF normalizes an ISO datetime."""

    def to_internal_value(self, value: Any) -> datetime:
        """Reject naive timestamps before Django applies a default timezone."""

        parsed = _aware_iso_datetime(value)
        return super().to_internal_value(parsed.isoformat())


def _validate_baseline_context(attrs: dict[str, Any]) -> dict[str, Any]:
    """Require both frozen preview fingerprints for included/excluded declarations."""

    decision = attrs.get("baseline_decision", "pending")
    fact_fingerprint = attrs.get("expected_fact_set_fingerprint")
    balance_fingerprint = attrs.get("expected_balance_fingerprint")
    if bool(fact_fingerprint) != bool(balance_fingerprint):
        raise serializers.ValidationError("确认基线时必须同时提供事实预览和余额预览依据")
    if decision in {"included", "excluded"} and not fact_fingerprint:
        raise serializers.ValidationError("included 或 excluded 需要先预览同一文件和余额快照")
    return attrs


def _authenticated_user_id(request: Request) -> int:
    """Return the persisted user ID guaranteed by the permission boundary."""
    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise NotAuthenticated("Authenticated user has no persisted ID")
    return user_id


class TransactionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Any],
):
    """
    交易记录 API ViewSet

    提供以下接口:
    - GET /api/account/transactions/ - 获取交易列表
    - POST /api/account/transactions/ - 创建交易记录
    - GET /api/account/transactions/{id}/ - 获取交易详情
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == "create":
            return cast(
                type[serializers.BaseSerializer[Any]],
                TransactionCreateSerializer,
            )
        return cast(type[serializers.BaseSerializer[Any]], TransactionSerializer)

    @_typed_extend_schema(
        request=TransactionCreateSerializer,
        responses={status.HTTP_201_CREATED: TransactionCreatedSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create through Application while keeping the existing 201 response."""
        serializer = TransactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(TransactionCreateData, serializer.validated_data)
        command = CreateTransactionInput(
            actor_user_id=_authenticated_user_id(request),
            portfolio_id=data["portfolio"],
            position_id=data.get("position"),
            action=data["action"],
            asset_code=data["asset_code"],
            shares=data["shares"],
            price=data["price"],
            notes=data.get("notes", ""),
            traded_at=data["traded_at"],
            commission=data.get("commission"),
            slippage=data.get("slippage"),
            stamp_duty=data.get("stamp_duty"),
            transfer_fee=data.get("transfer_fee"),
        )
        try:
            record = CreateTransactionRecordUseCase().execute(command)
        except AuthorizationError as exc:
            raise PermissionDenied(exc.message) from exc
        except InvalidInputError as exc:
            field = exc.details.get("field")
            if isinstance(field, str):
                raise ValidationError({field: exc.message}) from exc
            raise ValidationError({"non_field_errors": exc.message}) from exc

        response_data = TransactionCreatedSerializer(record).data
        headers = self.get_success_headers(response_data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read the existing page-number contract through a typed Application page."""
        pagination = PageNumberPagination()
        page_size = pagination.get_page_size(request)
        if page_size is None:
            page_size = 20
        page_use_case = ListTransactionPageUseCase()
        first_page = page_use_case.execute(
            user_id=_authenticated_user_id(request),
            page_number=1,
            page_size=page_size,
        )
        count_page = Paginator(range(first_page.count), page_size)
        try:
            page_number = count_page.validate_number(
                pagination.get_page_number(request, count_page)
            )
        except (EmptyPage, PageNotAnInteger) as exc:
            raise NotFound("Invalid page.") from exc

        page = (
            first_page
            if page_number == 1
            else page_use_case.execute(
                user_id=_authenticated_user_id(request),
                page_number=page_number,
                page_size=page_size,
            )
        )
        pagination.request = request
        pagination.page = count_page.page(page_number)
        serialized = TransactionSerializer(page.results, many=True).data
        return pagination.get_paginated_response(serialized)

    @_typed_extend_schema(
        parameters=[OpenApiParameter("id", int, OpenApiParameter.PATH)],
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read one transaction in the authenticated user's scope."""
        raw_id = kwargs.get(self.lookup_field)
        if not isinstance(raw_id, str) or not raw_id.isdigit():
            raise NotFound()
        try:
            transaction_id = int(raw_id)
        except ValueError as exc:
            raise NotFound() from exc
        if transaction_id <= 0:
            raise NotFound()
        record = GetTransactionUseCase().execute(
            user_id=_authenticated_user_id(request),
            transaction_id=transaction_id,
        )
        if record is None:
            raise NotFound()
        return Response(TransactionSerializer(record).data)


class BrokerTradeImportSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate manual broker trade import requests."""

    portfolio_id = serializers.IntegerField(min_value=1)
    broker_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="manual",
        max_length=64,
        trim_whitespace=True,
    )
    file = serializers.FileField()

    def validate_file(self, value: UploadedFile[bytes]) -> UploadedFile[bytes]:
        """Reject unsupported or unbounded broker files before reading them."""
        raw_filename = value.name
        if not isinstance(raw_filename, str) or not raw_filename:
            raise serializers.ValidationError("导入文件名无效")
        filename = raw_filename.lower()
        if not any(filename.endswith(suffix) for suffix in ALLOWED_BROKER_IMPORT_SUFFIXES):
            raise serializers.ValidationError("仅支持 CSV、XLSX 或 XLS 文件")
        if value.size is None or value.size > MAX_BROKER_IMPORT_FILE_BYTES:
            raise serializers.ValidationError("导入文件不能超过 10 MiB")
        return value


class BrokerTradeTuiImportSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate UTF-8 CSV text submitted by the TUI file field."""

    portfolio_id = serializers.IntegerField(min_value=1)
    broker_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="manual",
        max_length=64,
        trim_whitespace=True,
    )
    file = serializers.CharField(
        allow_blank=False,
        trim_whitespace=False,
        max_length=MAX_TUI_BROKER_IMPORT_TEXT_BYTES,
    )

    def validate_file(self, value: str) -> str:
        """Reject text whose encoded payload exceeds the runtime file budget."""

        if len(value.encode("utf-8")) > MAX_TUI_BROKER_IMPORT_TEXT_BYTES:
            raise serializers.ValidationError("CSV 文件不能超过 2 MiB")
        return value


class BrokerTradeTuiImportConfirmSerializer(BrokerTradeTuiImportSerializer):
    """Validate visible baseline choices and the private preview handoff."""

    baseline_decision = serializers.ChoiceField(
        choices=BASELINE_DECISIONS,
        required=False,
        default="pending",
    )
    baseline_as_of = _AwareISODateTimeField(required=False, allow_null=True)
    expected_fact_set_fingerprint = serializers.CharField(
        required=False, allow_blank=False, max_length=128
    )
    expected_balance_fingerprint = serializers.CharField(
        required=False, allow_blank=False, max_length=128
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate the confirmation's declaration and both CAS values together."""

        return _validate_baseline_context(attrs)


class BrokerTradeImportConfirmSerializer(BrokerTradeImportSerializer):
    """Validate explicit baseline declarations for canonical multipart confirmation."""

    baseline_decision = serializers.ChoiceField(
        choices=BASELINE_DECISIONS,
        required=False,
        default="pending",
    )
    baseline_as_of = _AwareISODateTimeField(required=False, allow_null=True)
    expected_fact_set_fingerprint = serializers.CharField(
        required=False, allow_blank=False, max_length=128
    )
    expected_balance_fingerprint = serializers.CharField(
        required=False, allow_blank=False, max_length=128
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate that included/excluded declarations carry the exact preview context."""

        return _validate_baseline_context(attrs)


class _BrokerTradeTuiImportBaseView(APIView):
    """Shared TUI boundary for previewing or confirming UTF-8 CSV imports."""

    permission_classes = [IsAuthenticated, TradingPermission]

    preview_only = True

    def post(self, request: Request) -> Response:
        """Run the owner-scoped manual trade import use case."""

        serializer_class = (
            BrokerTradeTuiImportSerializer
            if self.preview_only
            else BrokerTradeTuiImportConfirmSerializer
        )
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        use_case = ManualTradeImportUseCase()
        user_id = _authenticated_user_id(request)
        portfolio_id = cast(int, data["portfolio_id"])
        broker_name = cast(str, data.get("broker_name") or "manual")
        content = cast(str, data["file"]).encode("utf-8")
        try:
            if self.preview_only:
                result = use_case.preview(
                    user_id=user_id,
                    portfolio_id=portfolio_id,
                    broker_name=broker_name,
                    filename="tui-manual-trades.csv",
                    content=content,
                )
            else:
                result = use_case.confirm(
                    user_id=user_id,
                    portfolio_id=portfolio_id,
                    broker_name=broker_name,
                    filename="tui-manual-trades.csv",
                    content=content,
                    baseline_decision=cast(
                        BrokerBaselineDecision, data.get("baseline_decision", "pending")
                    ),
                    baseline_as_of=cast(datetime | None, data.get("baseline_as_of")),
                    expected_fact_set_fingerprint=cast(
                        str | None, data.get("expected_fact_set_fingerprint")
                    ),
                    expected_balance_fingerprint=cast(
                        str | None, data.get("expected_balance_fingerprint")
                    ),
                )
        except LookupError as exc:
            raise PermissionDenied("无权导入该投资组合的券商成交") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError("CSV 文件格式或内容无效") from exc

        response_data = _serialize_broker_import_result(result)
        if self.preview_only:
            fact_fingerprint = response_data.pop("expected_fact_set_fingerprint", None)
            balance_fingerprint = response_data.pop("expected_balance_fingerprint", None)
            _sanitize_tui_import_rows(response_data, preview_only=True)
            _add_tui_balance_columns(response_data)
            if (
                isinstance(fact_fingerprint, str)
                and fact_fingerprint
                and isinstance(balance_fingerprint, str)
                and balance_fingerprint
            ):
                response_data["continuation"] = {
                    "action_key": "audit.manual-trade-import",
                    "input": {
                        "expected_fact_set_fingerprint": fact_fingerprint,
                        "expected_balance_fingerprint": balance_fingerprint,
                    },
                    "expires_at": _request_session_expiry(request),
                }
            else:
                response_data["baseline_context_available"] = False
                response_data["message"] = (
                    "当前文件或余额尚不能完成基线核对；仍可选择“待核对”保存有效成交事实。"
                )
            return Response(response_data, status=status.HTTP_200_OK)

        response_data.pop("expected_fact_set_fingerprint", None)
        response_data.pop("expected_balance_fingerprint", None)
        _sanitize_tui_import_rows(response_data)
        conflict_code = result.reconciliation_conflict_code
        _add_reconciliation_conflict_message(response_data, conflict_code)
        _prepend_tui_import_summary_row(
            response_data,
            result,
            cast(str, data.get("baseline_decision", "pending")),
        )
        response_status = (
            status.HTTP_409_CONFLICT if conflict_code is not None else status.HTTP_201_CREATED
        )
        return Response(response_data, status=response_status)


class BrokerTradeTuiImportPreviewView(_BrokerTradeTuiImportBaseView):
    """Preview a UTF-8 CSV manual trade file submitted by the TUI."""


class BrokerTradeTuiImportConfirmView(_BrokerTradeTuiImportBaseView):
    """Confirm a UTF-8 CSV manual trade import submitted by the TUI."""

    preview_only = False


class BrokerTradeImportPreviewView(APIView):
    """Preview CSV/XLSX broker trades before importing."""

    permission_classes = [IsAuthenticated, TradingPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = BrokerTradeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = cast("UploadedFile[bytes]", serializer.validated_data["file"])
        filename = uploaded_file.name
        if not isinstance(filename, str):
            raise ValidationError("导入文件名无效")
        try:
            result = ManualTradeImportUseCase().preview(
                user_id=_authenticated_user_id(request),
                portfolio_id=serializer.validated_data["portfolio_id"],
                broker_name=serializer.validated_data.get("broker_name") or "manual",
                filename=filename,
                content=uploaded_file.read(),
            )
        except LookupError as exc:
            raise PermissionDenied("无权导入该投资组合的券商成交") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError("导入文件格式或内容无效") from exc
        return Response(_serialize_broker_import_result(result), status=status.HTTP_200_OK)


class BrokerTradeImportConfirmView(APIView):
    """Import CSV/XLSX broker trades and sync account positions."""

    permission_classes = [IsAuthenticated, TradingPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = BrokerTradeImportConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = cast("UploadedFile[bytes]", serializer.validated_data["file"])
        filename = uploaded_file.name
        if not isinstance(filename, str):
            raise ValidationError("导入文件名无效")
        try:
            result = ManualTradeImportUseCase().confirm(
                user_id=_authenticated_user_id(request),
                portfolio_id=serializer.validated_data["portfolio_id"],
                broker_name=serializer.validated_data.get("broker_name") or "manual",
                filename=filename,
                content=uploaded_file.read(),
                baseline_decision=cast(
                    BrokerBaselineDecision,
                    serializer.validated_data.get("baseline_decision", "pending"),
                ),
                baseline_as_of=cast(
                    datetime | None, serializer.validated_data.get("baseline_as_of")
                ),
                expected_fact_set_fingerprint=cast(
                    str | None,
                    serializer.validated_data.get("expected_fact_set_fingerprint"),
                ),
                expected_balance_fingerprint=cast(
                    str | None,
                    serializer.validated_data.get("expected_balance_fingerprint"),
                ),
            )
        except LookupError as exc:
            raise PermissionDenied("无权导入该投资组合的券商成交") from exc
        except (TypeError, ValueError) as exc:
            raise ValidationError("导入文件格式或内容无效") from exc
        response_data = _serialize_broker_import_result(result)
        conflict_code = result.reconciliation_conflict_code
        _add_reconciliation_conflict_message(response_data, conflict_code)
        response_status = (
            status.HTTP_409_CONFLICT if conflict_code is not None else status.HTTP_201_CREATED
        )
        return Response(response_data, status=response_status)


class CapitalFlowViewSet(
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Any],
):
    """
    资金流水 API ViewSet

    提供以下接口:
    - GET /api/account/capital-flows/ - 获取资金流水列表
    - POST /api/account/capital-flows/ - 创建资金流水
    - GET /api/account/capital-flows/{id}/ - 获取流水详情
    - DELETE /api/account/capital-flows/{id}/ - 删除流水
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self) -> Any:
        """只返回当前用户投资组合的资金流水"""
        return get_user_capital_flow_queryset(_authenticated_user_id(self.request))

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == "create":
            return cast(
                type[serializers.BaseSerializer[Any]],
                CapitalFlowCreateSerializer,
            )
        return cast(type[serializers.BaseSerializer[Any]], CapitalFlowSerializer)

    def perform_create(self, serializer: serializers.BaseSerializer[Any]) -> None:
        """创建时验证投资组合归属"""
        portfolio_id = serializer.validated_data.get("portfolio")
        if isinstance(portfolio_id, bool) or not isinstance(portfolio_id, int):
            raise ValidationError({"portfolio": "投资组合 ID 格式无效"})
        user_id = _authenticated_user_id(self.request)
        portfolio = get_user_portfolio(
            user_id=user_id,
            portfolio_id=portfolio_id,
        )
        if portfolio is None:
            raise NotFound()
        serializer.save(portfolio=portfolio, user=self.request.user)
