"""Typed TUI read adapters for audit overview and attribution reports."""

from __future__ import annotations

from datetime import date, datetime

from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.application.interface_services import (
    build_audit_overview_context,
    build_indicator_performance_page_context,
    build_manual_trade_review_context_payload,
    build_report_list_context,
    build_threshold_validation_page_context,
    get_attribution_chart_data_payload,
)

from .serializers import (
    AttributionReportSerializer,
    AuditTuiReportListQuerySerializer,
)


def _json_scalar(value: object) -> object:
    """Convert date-like boundary values to JSON-safe strings."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _attribute(source: object, key: str, default: object = None) -> object:
    """Read one model-like attribute at the HTTP serialization boundary."""

    return _json_scalar(getattr(source, key, default))


def _serialize_backtest(
    backtest: object,
    *,
    existing_backtest_ids: set[int],
) -> dict[str, object]:
    """Serialize the bounded backtest fields required for report generation."""

    raw_id = getattr(backtest, "id", 0)
    backtest_id = int(raw_id) if raw_id is not None else 0
    return {
        "id": backtest_id,
        "name": str(getattr(backtest, "name", "")),
        "status": str(getattr(backtest, "status", "")),
        "start_date": _attribute(backtest, "start_date"),
        "end_date": _attribute(backtest, "end_date"),
        "already_generated": backtest_id in existing_backtest_ids,
    }


def _serialize_validation(summary: object | None) -> dict[str, object] | None:
    """Serialize the P0 validation summary shown by the audit overview."""

    if summary is None:
        return None
    keys = (
        "validation_run_id",
        "run_date",
        "total_indicators",
        "approved_indicators",
        "rejected_indicators",
        "pending_indicators",
        "avg_f1_score",
        "avg_stability_score",
        "overall_recommendation",
        "status",
    )
    return {key: _attribute(summary, key) for key in keys}


class AuditTuiOverviewView(APIView):
    """Return the bounded audit workbench overview for an authenticated user."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return current validation, recent reports, and pending backtests."""

        del request
        context = build_audit_overview_context()
        recent_reports = AttributionReportSerializer(
            context.get("recent_reports", []),
            many=True,
        ).data
        pending_backtests = [
            _serialize_backtest(backtest, existing_backtest_ids=set())
            for backtest in context.get("pending_backtests", [])
        ]
        return Response(
            {
                "success": True,
                "latest_validation": _serialize_validation(context.get("latest_validation")),
                "recent_reports": list(recent_reports),
                "pending_backtests": pending_backtests,
                "report_total_count": int(context.get("report_total_count", 0)),
                "completed_backtest_count": int(context.get("completed_backtest_count", 0)),
            }
        )


class AuditTuiReportListView(APIView):
    """Return filtered reports and bounded generation candidates."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """List up to 50 reports and completed backtests for generation."""

        query = AuditTuiReportListQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return Response(
                {
                    "success": False,
                    "error": "参数验证失败",
                    "details": query.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        method = str(query.validated_data.get("method", ""))
        context = build_report_list_context(method)
        existing_backtest_ids = {
            int(backtest_id) for backtest_id in context.get("existing_backtest_ids", set())
        }
        reports = AttributionReportSerializer(
            context.get("reports", []),
            many=True,
        ).data
        candidates = [
            _serialize_backtest(
                backtest,
                existing_backtest_ids=existing_backtest_ids,
            )
            for backtest in context.get("backtests", [])
        ]
        return Response(
            {
                "success": True,
                "reports": list(reports),
                "total_count": int(context.get("total_count", 0)),
                "method": method,
                "generation_candidates": candidates,
            }
        )


class AuditTuiAttributionDetailView(APIView):
    """Return one attribution report as detail and chart-ready contribution rows."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request, report_id: int) -> Response:
        """Return report evidence with percentage-valued contribution rows."""

        del request
        payload = get_attribution_chart_data_payload(report_id)
        if payload is None:
            return Response(
                {"success": False, "error": "报告不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )
        contributions = [
            {
                "component": label,
                "value_percent": float(payload.get(key, 0) or 0) * 100,
            }
            for key, label in (
                ("regime_timing_pnl", "Regime 择时"),
                ("asset_selection_pnl", "资产选择"),
                ("interaction_pnl", "交互效应"),
                ("total_pnl", "总收益"),
            )
        ]
        return Response(
            {
                "success": True,
                **payload,
                "contributions": contributions,
            }
        )


class AuditTuiIndicatorPerformanceView(APIView):
    """Return the latest indicator performance summary and chart-ready rows."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return latest indicator metrics without template-embedded JSON."""

        del request
        context = build_indicator_performance_page_context()
        rows: list[dict[str, object]] = []
        for raw_row in context.get("indicator_reports", []):
            row = dict(raw_row)
            f1_score = row.get("f1_score")
            stability_score = row.get("stability_score")
            row["f1_percent"] = float(f1_score) * 100 if f1_score is not None else None
            row["stability_percent"] = (
                float(stability_score) * 100 if stability_score is not None else None
            )
            rows.append(row)
        return Response(
            {
                "success": True,
                "summary": {
                    "total_indicators": context.get("total_indicators", 0),
                    "approved_indicators": context.get("approved_indicators", 0),
                    "pending_indicators": context.get("pending_indicators", 0),
                    "rejected_indicators": context.get("rejected_indicators", 0),
                    "avg_f1_score": context.get("avg_f1_score", 0),
                    "avg_stability_score": context.get(
                        "avg_stability_score",
                        0,
                    ),
                },
                "results": rows,
                "total_count": len(rows),
            }
        )


class AuditTuiThresholdValidationView(APIView):
    """Return threshold configs and flattened recent validation history."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return current thresholds plus chart-ready history evidence."""

        del request
        context = build_threshold_validation_page_context()
        configs: list[dict[str, object]] = []
        history: list[dict[str, object]] = []
        for raw_config in context.get("threshold_configs", []):
            config = dict(raw_config)
            validation_history = list(config.pop("validation_history", []))
            configs.append(config)
            for raw_record in validation_history:
                record = dict(raw_record)
                f1_score = record.get("f1_score")
                stability_score = record.get("stability_score")
                validation_date = _json_scalar(record.get("validation_date"))
                history.append(
                    {
                        "observation": (f"{config.get('indicator_code', '')} · {validation_date}"),
                        "indicator_code": config.get("indicator_code", ""),
                        "validation_date": validation_date,
                        "f1_percent": (float(f1_score) * 100 if f1_score is not None else None),
                        "stability_percent": (
                            float(stability_score) * 100 if stability_score is not None else None
                        ),
                    }
                )
        return Response(
            {
                "success": True,
                "validation_status": context.get("validation_status", "pending"),
                "validation_status_label": context.get(
                    "validation_status_label",
                    "待运行",
                ),
                "validation_message": context.get("validation_message", ""),
                "results": configs,
                "history": history,
                "total_count": len(configs),
            }
        )


class AuditTuiManualTradeSummaryView(APIView):
    """Return owner-scoped manual trade import and transaction history."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return bounded import batches and transactions for the current user."""

        user_id = getattr(request.user, "id", None)
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            return Response(
                {"success": False, "error": "认证用户缺少持久化身份"},
                status=status.HTTP_403_FORBIDDEN,
            )
        payload = build_manual_trade_review_context_payload(user_id)
        return Response(
            {
                "success": True,
                "batches": list(payload.get("batches", [])),
                "transactions": list(payload.get("transactions", [])),
            }
        )
