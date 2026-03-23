"""
资产分析日志和告警服务测试

测试评分日志记录器和告警服务。
"""

from datetime import date, datetime

import pytest

from apps.asset_analysis.application.logging_service import (
    AlertService,
    ScoringLogEntry,
    ScoringLogger,
)
from apps.asset_analysis.domain.entities import AssetScore, AssetStyle, AssetType
from apps.asset_analysis.domain.value_objects import ScoreContext, WeightConfig
from apps.asset_analysis.infrastructure.models import (
    AssetAnalysisAlert,
    AssetScoringLog,
)


class TestScoringLogEntry:
    """测试评分日志条目"""

    def test_create_log_entry(self):
        """测试创建日志条目"""
        entry = ScoringLogEntry(
            asset_type="fund",
            request_source="test",
            regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            total_assets=100,
            scored_assets=100,
            filtered_assets=20,
            execution_time_ms=1500,
            status="success",
        )

        assert entry.asset_type == "fund"
        assert entry.request_source == "test"
        assert entry.total_assets == 100
        assert entry.execution_time_ms == 1500
        assert entry.status == "success"


class TestScoringLogger:
    """测试评分日志记录器"""

    def test_log_scoring_success(self, db):
        """测试记录成功的评分日志"""
        logger = ScoringLogger()

        entry = ScoringLogEntry(
            asset_type="fund",
            request_source="test_dashboard",
            user_id=1,
            regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals_count=3,
            weight_config_name="default",
            regime_weight=0.40,
            policy_weight=0.25,
            sentiment_weight=0.20,
            signal_weight=0.15,
            filters={"fund_type": "股票型"},
            total_assets=100,
            scored_assets=100,
            filtered_assets=20,
            execution_time_ms=1500,
            cache_hit=False,
            status="success",
        )

        log_id = logger.log_scoring(entry)

        assert log_id is not None
        assert AssetScoringLog.objects.count() == 1

        log = AssetScoringLog.objects.first()
        assert log.asset_type == "fund"
        assert log.request_source == "test_dashboard"
        assert log.user_id == 1
        assert log.regime == "Recovery"
        assert log.policy_level == "P0"
        assert log.status == "success"

    def test_log_scoring_from_context(self, db):
        """测试从上下文记录日志"""
        logger = ScoringLogger()

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
            score_date=date.today(),
        )

        weights = WeightConfig()

        log_id = logger.log_scoring_from_context(
            asset_type="fund",
            request_source="api_call",
            context=context,
            weights=weights,
            filters={"min_scale": 1000000000},
            total_assets=50,
            filtered_assets=10,
            execution_time_ms=2000,
            user_id=None,
            status="success",
        )

        assert log_id is not None
        assert AssetScoringLog.objects.count() == 1

        log = AssetScoringLog.objects.first()
        assert log.asset_type == "fund"
        assert log.request_source == "api_call"
        assert log.total_assets == 50
        assert log.filtered_assets == 10

    def test_log_scoring_with_error(self, db):
        """测试记录失败的评分日志"""
        logger = ScoringLogger()

        entry = ScoringLogEntry(
            asset_type="equity",
            request_source="test",
            regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            total_assets=0,
            scored_assets=0,
            filtered_assets=0,
            status="failed",
            error_message="数据库连接失败",
        )

        log_id = logger.log_scoring(entry)

        assert log_id is not None
        log = AssetScoringLog.objects.first()
        assert log.status == "failed"
        assert log.error_message == "数据库连接失败"


class TestAlertService:
    """测试告警服务"""

    def test_create_alert(self, db):
        """测试创建告警"""
        service = AlertService()

        alert_id = service.create_alert(
            severity="warning",
            alert_type="scoring_error",
            title="测试告警",
            message="这是一个测试告警",
            asset_type="fund",
            context={"test_key": "test_value"},
        )

        assert alert_id is not None
        assert AssetAnalysisAlert.objects.count() == 1

        alert = AssetAnalysisAlert.objects.first()
        assert alert.severity == "warning"
        assert alert.alert_type == "scoring_error"
        assert alert.title == "测试告警"
        assert alert.message == "这是一个测试告警"
        assert alert.asset_type == "fund"
        assert alert.context == {"test_key": "test_value"}
        assert alert.is_resolved is False

    def test_create_scoring_error_alert(self, db):
        """测试创建评分错误告警"""
        service = AlertService()

        alert_id = service.create_scoring_error_alert(
            asset_type="fund",
            error_message="权重配置不存在",
            context={"config_name": "custom_config"},
        )

        assert alert_id is not None
        alert = AssetAnalysisAlert.objects.first()
        assert alert.severity == "error"
        assert alert.alert_type == "scoring_error"
        assert "fund" in alert.title

    def test_create_weight_config_error_alert(self, db):
        """测试创建权重配置错误告警"""
        service = AlertService()

        alert_id = service.create_weight_config_error_alert(
            asset_type="equity",
            error_message="权重总和不为1.0",
            context={"regime": 0.5, "policy": 0.6},
        )

        assert alert_id is not None
        alert = AssetAnalysisAlert.objects.first()
        assert alert.severity == "critical"
        assert alert.alert_type == "weight_config_error"

    def test_create_performance_alert(self, db):
        """测试创建性能告警"""
        service = AlertService()

        # 超过阈值，应该创建告警
        alert_id = service.create_performance_alert(
            asset_type="fund",
            execution_time_ms=6000,
            threshold_ms=5000,
            context={"total_assets": 1000},
        )

        assert alert_id is not None
        alert = AssetAnalysisAlert.objects.first()
        assert alert.severity == "warning"
        assert alert.alert_type == "performance_issue"

    def test_create_performance_alert_below_threshold(self, db):
        """测试性能告警 - 低于阈值不创建告警"""
        service = AlertService()

        # 低于阈值，不应该创建告警
        alert_id = service.create_performance_alert(
            asset_type="fund",
            execution_time_ms=3000,
            threshold_ms=5000,
        )

        assert alert_id is None
        assert AssetAnalysisAlert.objects.count() == 0

    def test_create_data_quality_alert(self, db):
        """测试创建数据质量问题告警"""
        service = AlertService()

        alert_id = service.create_data_quality_alert(
            asset_type="equity",
            issue_description="PE数据异常",
            asset_code="000001",
            context={"pe_value": -999},
        )

        assert alert_id is not None
        alert = AssetAnalysisAlert.objects.first()
        assert alert.severity == "warning"
        assert alert.alert_type == "data_quality_issue"
        assert alert.asset_code == "000001"

    def test_create_api_failure_alert(self, db):
        """测试创建API调用失败告警"""
        service = AlertService()

        alert_id = service.create_api_failure_alert(
            api_name="TusharePro",
            error_message="API调用超时",
            stack_trace="Traceback...",
        )

        assert alert_id is not None
        alert = AssetAnalysisAlert.objects.first()
        assert alert.severity == "error"
        assert alert.alert_type == "api_failure"
        assert "TusharePro" in alert.title

    def test_get_unresolved_alerts(self, db):
        """测试获取未解决的告警"""
        service = AlertService()

        # 创建3个告警
        service.create_alert(
            severity="warning",
            alert_type="test",
            title="告警1",
            message="测试告警1",
        )
        service.create_alert(
            severity="error",
            alert_type="test",
            title="告警2",
            message="测试告警2",
        )
        service.create_alert(
            severity="info",
            alert_type="test",
            title="告警3",
            message="测试告警3",
        )

        # 获取所有未解决告警
        alerts = service.get_unresolved_alerts()
        assert len(alerts) == 3

        # 按严重程度过滤
        error_alerts = service.get_unresolved_alerts(severity="error")
        assert len(error_alerts) == 1

    def test_resolve_alert(self, db):
        """测试解决告警"""
        service = AlertService()

        alert_id = service.create_alert(
            severity="warning",
            alert_type="test",
            title="测试告警",
            message="待解决的告警",
        )

        # 解决告警
        success = service.resolve_alert(
            alert_id=alert_id,
            resolved_by=1,
            resolution_notes="已修复",
        )

        assert success is True

        alert = AssetAnalysisAlert.objects.get(id=alert_id)
        assert alert.is_resolved is True
        assert alert.resolved_by == 1
        assert alert.resolution_notes == "已修复"
        assert alert.resolved_at is not None

    def test_resolve_nonexistent_alert(self, db):
        """测试解决不存在的告警"""
        service = AlertService()

        success = service.resolve_alert(
            alert_id=99999,  # 不存在的ID
            resolved_by=1,
        )

        assert success is False


class TestScoringLoggerIntegration:
    """集成测试：日志记录器与评分服务"""

    def test_score_batch_with_logging(self, db):
        """测试批量评分时的日志记录"""
        from apps.asset_analysis.application.services import AssetMultiDimScorer
        from apps.asset_analysis.infrastructure.repositories import DjangoWeightConfigRepository

        # 创建测试数据
        assets = [
            AssetScore(
                asset_type=AssetType.FUND,
                asset_code=f"00000{i}",
                asset_name=f"测试基金{i}",
            )
            for i in range(1, 6)
        ]

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
            score_date=date.today(),
        )

        # 创建评分器（启用日志）
        weight_repo = DjangoWeightConfigRepository()
        scorer = AssetMultiDimScorer(
            weight_repository=weight_repo,
            enable_logging=True,
            enable_alerts=False,  # 禁用告警以避免干扰
        )

        # 执行批量评分
        result = scorer.score_batch(
            assets=assets,
            context=context,
            request_source="test_integration",
            user_id=1,
            filters={"test": "value"},
        )

        # 验证评分结果
        assert len(result) == 5
        assert result[0].rank == 1

        # 验证日志已记录
        assert AssetScoringLog.objects.count() == 1

        log = AssetScoringLog.objects.first()
        assert log.asset_type == "fund"
        assert log.request_source == "test_integration"
        assert log.total_assets == 5
        assert log.status == "success"
