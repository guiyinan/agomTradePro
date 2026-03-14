"""
Serializers for Audit API.
"""

from rest_framework import serializers


class LossAnalysisSerializer(serializers.Serializer):
    """损失分析序列化器"""
    id = serializers.IntegerField()
    loss_source = serializers.CharField()
    loss_source_display = serializers.CharField()
    impact = serializers.FloatField()
    impact_percentage = serializers.FloatField()
    description = serializers.CharField()
    improvement_suggestion = serializers.CharField(allow_blank=True)


class ExperienceSummarySerializer(serializers.Serializer):
    """经验总结序列化器"""
    id = serializers.IntegerField()
    lesson = serializers.CharField()
    recommendation = serializers.CharField()
    priority = serializers.CharField()
    is_applied = serializers.BooleanField()
    applied_at = serializers.CharField(allow_null=True)


class AttributionReportSerializer(serializers.Serializer):
    """归因报告序列化器"""
    id = serializers.IntegerField()
    backtest_id = serializers.IntegerField()
    period_start = serializers.CharField()
    period_end = serializers.CharField()
    regime_timing_pnl = serializers.FloatField()
    asset_selection_pnl = serializers.FloatField()
    interaction_pnl = serializers.FloatField()
    total_pnl = serializers.FloatField()
    regime_accuracy = serializers.FloatField()
    regime_predicted = serializers.CharField()
    regime_actual = serializers.CharField(allow_null=True)
    created_at = serializers.CharField()

    # 关联数据
    loss_analyses = LossAnalysisSerializer(many=True, required=False)
    experience_summaries = ExperienceSummarySerializer(many=True, required=False)


class GenerateAttributionReportRequestSerializer(serializers.Serializer):
    """生成归因报告请求序列化器"""
    backtest_id = serializers.IntegerField(required=True)


class GenerateAttributionReportResponseSerializer(serializers.Serializer):
    """生成归因报告响应序列化器"""
    success = serializers.BooleanField()
    report_id = serializers.IntegerField(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


# ============ MCP/SDK 操作审计日志序列化器 ============

class OperationLogSerializer(serializers.Serializer):
    """操作审计日志序列化器"""
    id = serializers.CharField()
    request_id = serializers.CharField()
    user_id = serializers.IntegerField(allow_null=True)
    username = serializers.CharField()
    ip_address = serializers.CharField(allow_null=True)
    user_agent = serializers.CharField()
    source = serializers.CharField()
    client_id = serializers.CharField()
    operation_type = serializers.CharField()
    module = serializers.CharField()
    action = serializers.CharField()
    resource_type = serializers.CharField()
    resource_id = serializers.CharField(allow_null=True)
    mcp_tool_name = serializers.CharField(allow_null=True)
    mcp_client_id = serializers.CharField()
    mcp_role = serializers.CharField()
    sdk_version = serializers.CharField()
    request_method = serializers.CharField()
    request_path = serializers.CharField()
    request_params = serializers.DictField()
    response_payload = serializers.JSONField(allow_null=True)
    response_text = serializers.CharField()
    response_status = serializers.IntegerField()
    response_message = serializers.CharField()
    error_code = serializers.CharField()
    exception_traceback = serializers.CharField()
    timestamp = serializers.CharField()
    duration_ms = serializers.IntegerField(allow_null=True)
    checksum = serializers.CharField()


class OperationLogListSerializer(serializers.Serializer):
    """操作日志列表响应序列化器"""
    success = serializers.BooleanField()
    logs = OperationLogSerializer(many=True)
    total_count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class OperationLogDetailSerializer(serializers.Serializer):
    """操作日志详情响应序列化器"""
    success = serializers.BooleanField()
    log = OperationLogSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


class OperationLogQuerySerializer(serializers.Serializer):
    """操作日志查询参数序列化器"""
    user_id = serializers.IntegerField(required=False, allow_null=True)
    username = serializers.CharField(required=False, allow_blank=True)
    operation_type = serializers.CharField(required=False, allow_blank=True)
    module = serializers.CharField(required=False, allow_blank=True)
    action = serializers.CharField(required=False, allow_blank=True)
    mcp_tool_name = serializers.CharField(required=False, allow_blank=True)
    mcp_client_id = serializers.CharField(required=False, allow_blank=True)
    mcp_role = serializers.CharField(required=False, allow_blank=True)
    response_status = serializers.IntegerField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    resource_id = serializers.CharField(required=False, allow_blank=True)
    source = serializers.CharField(required=False, allow_blank=True)
    ordering = serializers.CharField(required=False, default='-timestamp')
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)


class OperationLogIngestSerializer(serializers.Serializer):
    """操作日志内部写入序列化器"""
    request_id = serializers.CharField(required=True)
    user_id = serializers.IntegerField(required=False, allow_null=True)
    username = serializers.CharField(required=False, default='anonymous')
    source = serializers.CharField(required=False, default='MCP')
    operation_type = serializers.CharField(required=False, default='MCP_CALL')
    module = serializers.CharField(required=False, default='')
    action = serializers.CharField(required=False, default='READ')
    mcp_tool_name = serializers.CharField(required=False, allow_null=True)
    request_params = serializers.DictField(required=False, default=dict)
    response_payload = serializers.JSONField(required=False, allow_null=True, default=None)
    response_text = serializers.CharField(required=False, allow_blank=True, default='')
    response_status = serializers.IntegerField(required=False, default=200)
    response_message = serializers.CharField(required=False, allow_blank=True, default='')
    error_code = serializers.CharField(required=False, allow_blank=True, default='')
    exception_traceback = serializers.CharField(required=False, allow_blank=True, default='')
    duration_ms = serializers.IntegerField(required=False, allow_null=True)
    ip_address = serializers.CharField(required=False, allow_null=True)
    user_agent = serializers.CharField(required=False, allow_blank=True, default='')
    client_id = serializers.CharField(required=False, allow_blank=True, default='')
    resource_type = serializers.CharField(required=False, allow_blank=True, default='')
    resource_id = serializers.CharField(required=False, allow_null=True)
    mcp_client_id = serializers.CharField(required=False, allow_blank=True, default='')
    mcp_role = serializers.CharField(required=False, allow_blank=True, default='')
    sdk_version = serializers.CharField(required=False, allow_blank=True, default='')
    request_method = serializers.CharField(required=False, default='MCP')
    request_path = serializers.CharField(required=False, allow_blank=True, default='')


class OperationStatsSerializer(serializers.Serializer):
    """操作统计序列化器"""
    total_count = serializers.IntegerField()
    error_count = serializers.IntegerField()
    error_rate = serializers.FloatField()
    avg_duration_ms = serializers.FloatField(allow_null=True)
    period = serializers.DictField()
    by_module = serializers.ListField(required=False)
    by_tool = serializers.ListField(required=False)
    by_user = serializers.ListField(required=False)
    by_status = serializers.ListField(required=False)


class ExportOperationLogsSerializer(serializers.Serializer):
    """导出操作日志响应序列化器"""
    success = serializers.BooleanField()
    data = serializers.CharField(allow_null=True, required=False)
    filename = serializers.CharField(allow_null=True, required=False)
    row_count = serializers.IntegerField()
    error = serializers.CharField(allow_null=True, required=False)


class DecisionTraceStepSerializer(serializers.Serializer):
    """决策链步骤序列化器"""
    step_index = serializers.IntegerField()
    log_id = serializers.CharField()
    timestamp = serializers.CharField()
    tool_name = serializers.CharField()
    module = serializers.CharField()
    action = serializers.CharField()
    request_path = serializers.CharField()
    response_status = serializers.IntegerField()
    duration_ms = serializers.IntegerField(allow_null=True)
    summary = serializers.CharField()
    response_message = serializers.CharField()


class DecisionTraceSummarySerializer(serializers.Serializer):
    """决策链摘要序列化器"""
    request_id = serializers.CharField()
    mcp_client_id = serializers.CharField()
    username = serializers.CharField()
    user_id = serializers.IntegerField(allow_null=True)
    source = serializers.CharField()
    started_at = serializers.CharField(allow_null=True)
    finished_at = serializers.CharField(allow_null=True)
    step_count = serializers.IntegerField()
    status = serializers.CharField()
    last_status = serializers.IntegerField()
    modules = serializers.ListField(child=serializers.CharField())
    tools = serializers.ListField(child=serializers.CharField())
    summary = serializers.CharField()


class DecisionTraceListSerializer(serializers.Serializer):
    """决策链列表响应序列化器"""
    success = serializers.BooleanField()
    traces = DecisionTraceSummarySerializer(many=True)
    total_count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class DecisionTraceDetailSerializer(serializers.Serializer):
    """决策链详情响应序列化器"""
    success = serializers.BooleanField()
    trace = serializers.DictField(required=False)
    error = serializers.CharField(allow_null=True, required=False)
