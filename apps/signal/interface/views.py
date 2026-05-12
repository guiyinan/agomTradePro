"""
Page Views for Investment Signal Management.
"""


from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.signal.application.invalidation_checker import InvalidationCheckService
from apps.signal.application.query_services import (
    build_signal_management_context,
    create_investment_signal_record,
    delete_investment_signal_record,
    get_current_regime_payload,
    get_pending_unified_signals,
    get_recommended_assets_payload,
    get_unified_signals_by_asset,
    mark_unified_signal_executed,
    update_investment_signal_status,
)
from apps.signal.application.use_cases import (
    ValidateSignalRequest,
    ValidateSignalUseCase,
)
from apps.signal.domain.rules import Eligibility, get_eligibility_matrix


def signal_manage_view(request):
    """投资信号管理页面"""
    status_filter = request.GET.get("status", "")
    asset_class = request.GET.get("asset_class", "")
    direction = request.GET.get("direction", "")
    search = request.GET.get("search", "")

    context = build_signal_management_context(
        status_filter=status_filter,
        asset_class=asset_class,
        direction=direction,
        search=search,
    )

    return render(request, "signal/manage.html", context)


def get_current_regime():
    """获取当前 Regime 信息"""
    return get_current_regime_payload()


def get_recommended_assets(regime: str):
    """获取推荐资产列表"""
    return get_recommended_assets_payload(regime)


@require_http_methods(["GET", "POST"])
def create_signal_view(request):
    """创建新投资信号"""
    if request.method == "GET":
        return redirect("signal:manage")

    import json

    asset_code = request.POST.get("asset_code", "").strip()
    asset_class = request.POST.get("asset_class", "").strip()
    direction = request.POST.get("direction", "LONG").strip()
    logic_desc = request.POST.get("logic_desc", "").strip()
    invalidation_rules_json = request.POST.get("invalidation_rules", "{}")
    target_regime = request.POST.get("target_regime", "Recovery").strip()

    # 基本验证
    if not all([asset_code, asset_class, logic_desc]):
        return JsonResponse({"success": False, "error": "请填写所有必填字段"})

    # 解析证伪规则
    try:
        invalidation_rules = json.loads(invalidation_rules_json)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "证伪规则格式错误"})

    # 生成人类可读的描述
    invalidation_logic = generate_invalidation_logic_text(invalidation_rules)

    # 提取阈值（取第一个条件的阈值）
    invalidation_threshold = None
    if invalidation_rules.get("conditions"):
        invalidation_threshold = invalidation_rules["conditions"][0].get("threshold")

    # 获取当前 Regime
    current_regime_data = get_current_regime()
    current_regime = current_regime_data["dominant_regime"]
    confidence = current_regime_data["confidence"]

    # 执行准入检查
    validate_use_case = ValidateSignalUseCase()
    validate_request = ValidateSignalRequest(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=invalidation_threshold,
        target_regime=target_regime,
        current_regime=current_regime,
        policy_level=0,
        regime_confidence=confidence,
    )

    response = validate_use_case.execute(validate_request)

    signal = create_investment_signal_record(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=invalidation_threshold,
        invalidation_rules=invalidation_rules if invalidation_rules else None,
        target_regime=target_regime,
        is_approved=response.is_approved,
        rejection_reason=response.rejection_record.reason if response.rejection_record else "",
    )

    return JsonResponse(
        {
            "success": True,
            "signal_id": signal["id"],
            "is_approved": response.is_approved,
            "warnings": response.warnings,
            "rejection_reason": signal["rejection_reason"] if not response.is_approved else None,
        }
    )


def generate_invalidation_logic_text(rules: dict) -> str:
    """从结构化规则生成人类可读的文本"""
    if not rules or not rules.get("conditions"):
        return "未设置证伪条件"

    conditions = []
    for cond in rules.get("conditions", []):
        indicator = cond.get("indicator", "")
        op = cond.get("condition", "")
        threshold = cond.get("threshold", "")

        op_map = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "="}
        cond_str = f"{indicator} {op_map.get(op, op)} {threshold}"

        if cond.get("duration"):
            cond_str += f" 连续{cond['duration']}期"
        if cond.get("compare_with"):
            compare_map = {"prev_value": "前值", "prev_year": "同期"}
            cond_str += f" (较{compare_map.get(cond['compare_with'], cond['compare_with'])})"

        conditions.append(cond_str)

    rules.get("logic", "AND")
    return f"当{' 且 '.join(conditions)}时证伪"


@require_http_methods(["POST"])
def approve_signal_view(request):
    """手动批准信号"""
    signal_id = request.POST.get("signal_id")
    signal = update_investment_signal_status(
        signal_id=signal_id,
        status="approved",
        rejection_reason="",
    )
    if signal is None:
        return JsonResponse({"success": False, "error": "信号不存在"}, status=404)

    return JsonResponse({"success": True, "message": f"信号 {signal['asset_code']} 已批准"})


@require_http_methods(["POST"])
def reject_signal_view(request):
    """手动拒绝信号"""
    signal_id = request.POST.get("signal_id")
    reason = request.POST.get("reason", "手动拒绝").strip()

    signal = update_investment_signal_status(
        signal_id=signal_id,
        status="rejected",
        rejection_reason=reason,
    )
    if signal is None:
        return JsonResponse({"success": False, "error": "信号不存在"}, status=404)

    return JsonResponse({"success": True, "message": f"信号 {signal['asset_code']} 已拒绝"})


@require_http_methods(["POST"])
def invalidate_signal_view(request):
    """手动证伪信号"""
    signal_id = request.POST.get("signal_id")
    reason = request.POST.get("reason", "手动证伪").strip()

    signal = update_investment_signal_status(
        signal_id=signal_id,
        status="invalidated",
        rejection_reason=reason,
    )
    if signal is None:
        return JsonResponse({"success": False, "error": "信号不存在"}, status=404)

    return JsonResponse({"success": True, "message": f"信号 {signal['asset_code']} 已证伪"})


@require_http_methods(["DELETE"])
def delete_signal_view(request, signal_id):
    """删除信号"""
    asset_code = delete_investment_signal_record(signal_id)
    if asset_code is None:
        return JsonResponse({"success": False, "error": "信号不存在"}, status=404)

    return JsonResponse({"success": True, "message": f"信号 {asset_code} 已删除"})


@require_http_methods(["POST"])
def check_invalidation_view(request, signal_id):
    """手动触发证伪检查"""
    service = InvalidationCheckService()
    result = service.check_signal(signal_id)

    if result:
        return JsonResponse(
            {
                "success": True,
                "is_invalidated": result.is_invalidated,
                "reason": result.reason,
                "details": result.checked_conditions,
            }
        )
    else:
        return JsonResponse({"success": False, "error": "信号不存在"})


@require_http_methods(["GET", "POST"])
def run_batch_check_view(request):
    """批量检查所有信号"""
    if request.method == "GET":
        return redirect("signal:manage")

    from apps.signal.application.invalidation_checker import check_and_invalidate_signals

    result = check_and_invalidate_signals()

    return JsonResponse({"success": True, **result})


def signal_eligibility_info_view(request):
    """获取资产准入信息（AJAX）"""
    asset_class = request.GET.get("asset_class", "")
    regime = request.GET.get("regime", "")

    if not asset_class or not regime:
        return JsonResponse({"error": "缺少参数"}, status=400)

    try:
        eligibility = get_eligibility_matrix().get(asset_class, {}).get(regime, Eligibility.NEUTRAL)

        return JsonResponse(
            {
                "asset_class": asset_class,
                "regime": regime,
                "eligibility": eligibility.value,
                "eligible": eligibility in [Eligibility.PREFERRED, Eligibility.NEUTRAL],
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
def ai_parse_logic_view(request):
    """AI 解析证伪逻辑"""
    import json

    from apps.signal.application.ai_invalidation_helper import ai_parse_invalidation_logic

    try:
        data = json.loads(request.body)
        user_input = data.get("text", "").strip()

        if not user_input:
            return JsonResponse({"success": False, "error": "请输入证伪逻辑描述"})

        result = ai_parse_invalidation_logic(user_input)

        if "error" in result:
            return JsonResponse(
                {
                    "success": False,
                    "error": result["error"],
                    "suggestions": result.get("suggestions", []),
                }
            )

        return JsonResponse(
            {
                "success": True,
                "conditions": result["conditions"],
                "logic": result["logic"],
                "explanation": result["explanation"],
                "confidence": result.get("confidence", 0.8),
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


def get_indicators_view(request):
    """获取可用指标列表"""
    from apps.macro.application.indicator_service import get_available_indicators_for_frontend

    try:
        indicators = get_available_indicators_for_frontend()

        # 按类别分组
        grouped = {}
        for ind in indicators:
            category = ind.get("category", "其他")
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(ind)

        return JsonResponse(
            {
                "success": True,
                "indicators": indicators,
                "grouped": grouped,
                "total": len(indicators),
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


class UnifiedSignalViewSet(viewsets.ViewSet):
    """ViewSet for unified signals from all modules"""

    def list(self, request):
        """List unified signals"""
        from datetime import date

        from apps.signal.application.unified_service import UnifiedSignalService

        signal_date_str = request.query_params.get("date", date.today().isoformat())
        signal_source = request.query_params.get("source", None)
        min_priority = int(request.query_params.get("min_priority", 1))

        try:
            signal_date = date.fromisoformat(signal_date_str)
        except ValueError:
            signal_date = date.today()

        service = UnifiedSignalService()
        signals = service.get_unified_signals(
            signal_date=signal_date, signal_source=signal_source, min_priority=min_priority
        )

        return Response(
            {
                "date": signal_date.isoformat(),
                "source": signal_source,
                "count": len(signals),
                "signals": signals,
            }
        )

    @action(detail=False, methods=["post"])
    def collect(self, request):
        """Collect signals from all modules"""
        from datetime import date

        from apps.signal.application.unified_service import UnifiedSignalService

        signal_date_str = request.data.get("date")
        if signal_date_str:
            try:
                calc_date = date.fromisoformat(signal_date_str)
            except ValueError:
                return Response(
                    {"error": f"Invalid date format: {signal_date_str}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            calc_date = date.today()

        service = UnifiedSignalService()
        results = service.collect_all_signals(calc_date)

        return Response({"date": calc_date.isoformat(), "results": results})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Get signal summary for a date range"""
        from datetime import date, timedelta

        from apps.signal.application.unified_service import UnifiedSignalService

        days = int(request.query_params.get("days", 30))
        start_date = date.today() - timedelta(days=days)

        service = UnifiedSignalService()
        summary = service.get_signal_summary(start_date=start_date)

        return Response(summary)

    @action(detail=False, methods=["get"])
    def pending(self, request):
        """Get pending (unexecuted) signals"""
        min_priority = int(request.query_params.get("min_priority", 5))
        signal_type = request.query_params.get("type", None)

        signals = get_pending_unified_signals(
            min_priority=min_priority,
            signal_type=signal_type,
        )

        return Response({"count": len(signals), "signals": signals})

    @action(detail=False, methods=["get"])
    def by_asset(self, request):
        """Get signals for a specific asset"""
        asset_code = request.query_params.get("asset_code")
        if not asset_code:
            return Response({"error": "asset_code is required"}, status=status.HTTP_400_BAD_REQUEST)

        days = int(request.query_params.get("days", 30))
        signal_source = request.query_params.get("source", None)

        signals = get_unified_signals_by_asset(
            asset_code=asset_code,
            days=days,
            signal_source=signal_source,
        )

        return Response(
            {"asset_code": asset_code, "days": days, "count": len(signals), "signals": signals}
        )

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        """Mark a signal as executed"""
        success = mark_unified_signal_executed(pk)

        if success:
            return Response({"status": "executed", "signal_id": pk})
        else:
            return Response({"error": "Signal not found"}, status=status.HTTP_404_NOT_FOUND)
