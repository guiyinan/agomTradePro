"""
Unit tests for InvalidationCheckService Application Layer.

Tests for checking pending and approved signals with invalidation rules.
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from apps.data_center.infrastructure.models import MacroFactModel
from apps.signal.application.invalidation_checker import (
    InvalidationCheckService,
    check_and_invalidate_signals,
)
from apps.signal.domain.entities import SignalStatus
from apps.signal.domain.invalidation import (
    ComparisonOperator,
    IndicatorType,
    IndicatorValue,
    InvalidationCheckResult,
    InvalidationCondition,
    InvalidationRule,
    LogicOperator,
)
from apps.signal.infrastructure.models import InvestmentSignalModel


def _make_check_result(is_invalidated: bool, reason: str) -> InvalidationCheckResult:
    """Helper to create InvalidationCheckResult with required checked_at field"""
    return InvalidationCheckResult(
        is_invalidated=is_invalidated,
        reason=reason,
        checked_conditions=[],
        checked_at=datetime.now().isoformat()
    )


@pytest.fixture
def invalidation_rule():
    """Create a test invalidation rule"""
    return InvalidationRule(
        conditions=[
            InvalidationCondition(
                indicator_code="CN_PMI_MANUFACTURING",
                indicator_type=IndicatorType.MACRO,
                operator=ComparisonOperator.LT,
                threshold=50.0,
            )
        ],
        logic=LogicOperator.AND,
    )


class TestInvalidationCheckServiceIntegration:
    """集成风格测试 - 测试状态转换逻辑"""

    def test_pending_signal_becomes_rejected(self):
        """测试 pending 信号证伪条件满足时变为 rejected 状态"""
        service = InvalidationCheckService()

        # Create mock signal
        signal_model = Mock(spec=InvestmentSignalModel)
        signal_model.id = 1
        signal_model.asset_code = "000001.SH"

        # Create mock result
        result = _make_check_result(is_invalidated=True, reason="PMI 跌破 50")

        # Call _invalidate_signal with pending status
        service._invalidate_signal(signal_model, result, current_status='pending')

        # Verify status became rejected
        assert signal_model.status == 'rejected'
        assert signal_model.rejection_reason == "PMI 跌破 50"
        signal_model.save.assert_called_once()

    def test_approved_signal_becomes_invalidated(self):
        """测试 approved 信号证伪条件满足时变为 invalidated 状态"""
        service = InvalidationCheckService()

        # Create mock signal
        signal_model = Mock(spec=InvestmentSignalModel)
        signal_model.id = 2
        signal_model.asset_code = "000001.SH"

        # Create mock result
        result = _make_check_result(is_invalidated=True, reason="PMI 跌破 50")

        # Mock timezone.now()
        with patch('apps.signal.application.invalidation_checker.timezone') as mock_tz:
            mock_now = datetime.now()
            mock_tz.now.return_value = mock_now

            # Call _invalidate_signal with approved status
            service._invalidate_signal(signal_model, result, current_status='approved')

        # Verify status became invalidated
        assert signal_model.status == 'invalidated'
        assert signal_model.rejection_reason == "PMI 跌破 50"
        assert signal_model.invalidated_at == mock_now
        signal_model.save.assert_called_once()

    def test_check_signal_model_returns_none_for_rejected(self, invalidation_rule):
        """测试 rejected 信号返回 None"""
        service = InvalidationCheckService()

        # Create a rejected signal
        signal_model = Mock(spec=InvestmentSignalModel)
        entity = Mock()
        entity.id = "3"
        entity.status = SignalStatus.REJECTED
        entity.invalidation_rule = invalidation_rule
        signal_model.to_domain_entity.return_value = entity

        result = service._check_signal_model(signal_model)

        # Should return None for rejected signals
        assert result is None

    def test_check_signal_model_returns_none_for_expired(self, invalidation_rule):
        """测试 expired 信号返回 None"""
        service = InvalidationCheckService()

        # Create an expired signal
        signal_model = Mock(spec=InvestmentSignalModel)
        entity = Mock()
        entity.id = "4"
        entity.status = SignalStatus.EXPIRED
        entity.invalidation_rule = invalidation_rule
        signal_model.to_domain_entity.return_value = entity

        result = service._check_signal_model(signal_model)

        # Should return None for expired signals
        assert result is None

    def test_check_signal_model_checks_pending(self, invalidation_rule):
        """测试 pending 信号会被检查"""
        service = InvalidationCheckService()

        # Create a pending signal
        signal_model = Mock(spec=InvestmentSignalModel)
        entity = Mock()
        entity.id = "5"
        entity.status = SignalStatus.PENDING
        entity.invalidation_rule = invalidation_rule
        signal_model.to_domain_entity.return_value = entity

        # Mock macro_repo methods
        with patch.object(service, 'macro_repo') as mock_repo:
            mock_repo.get_latest_by_code.return_value = Mock(
                value=51.0,
                unit="",
                observed_at=datetime.now()
            )
            mock_repo.get_history_by_code.return_value = []

            result = service._check_signal_model(signal_model)

        # Should return a result (not None)
        assert result is not None
        assert isinstance(result, InvalidationCheckResult)

    def test_check_signal_model_checks_approved(self, invalidation_rule):
        """测试 approved 信号会被检查"""
        service = InvalidationCheckService()

        # Create an approved signal
        signal_model = Mock(spec=InvestmentSignalModel)
        entity = Mock()
        entity.id = "6"
        entity.status = SignalStatus.APPROVED
        entity.invalidation_rule = invalidation_rule
        signal_model.to_domain_entity.return_value = entity

        # Mock macro_repo methods
        with patch.object(service, 'macro_repo') as mock_repo:
            mock_repo.get_latest_by_code.return_value = Mock(
                value=51.0,
                unit="",
                observed_at=datetime.now()
            )
            mock_repo.get_history_by_code.return_value = []

            result = service._check_signal_model(signal_model)

        # Should return a result (not None)
        assert result is not None
        assert isinstance(result, InvalidationCheckResult)

    def test_check_signal_model_without_rule_returns_none(self):
        """测试没有证伪规则的信号返回 None"""
        service = InvalidationCheckService()

        # Create a signal without invalidation rule
        signal_model = Mock(spec=InvestmentSignalModel)
        entity = Mock()
        entity.id = "7"
        entity.status = SignalStatus.APPROVED
        entity.invalidation_rule = None
        signal_model.to_domain_entity.return_value = entity

        result = service._check_signal_model(signal_model)

        # Should return None for signals without invalidation rule
        assert result is None

    def test_check_pending_signals_method_exists(self):
        """测试 check_pending_signals 方法存在"""
        signal_repository = Mock()
        signal_repository.find_signals_with_invalidation_rules.return_value = []
        service = InvalidationCheckService(
            signal_repository=signal_repository,
            macro_repository=Mock(),
        )

        # Should not raise
        result = service.check_pending_signals()
        assert result == []
        signal_repository.find_signals_with_invalidation_rules.assert_called_once_with(
            status=SignalStatus.PENDING
        )

    @patch('apps.signal.infrastructure.repositories.DjangoSignalRepository')
    def test_check_and_invalidate_returns_correct_structure(self, mock_repository_cls):
        """测试 check_and_invalidate_signals 返回正确的结构"""
        repository = Mock()
        repository.find_signals_with_invalidation_rules.return_value = []
        repository.count_by_status.side_effect = lambda status: 1 if status == "approved" else 0
        mock_repository_cls.return_value = repository

        result = check_and_invalidate_signals()

        # Verify result structure
        assert 'checked' in result
        assert 'invalidated' in result
        assert 'rejected' in result
        assert 'invalidated_ids' in result
        assert 'rejected_ids' in result

    def test_pending_signal_with_satisfied_invalidation_gets_rejected(self, invalidation_rule):
        """测试证伪条件满足的 pending 信号被标记为 rejected"""
        service = InvalidationCheckService()

        # Create a pending signal
        signal_model = Mock(spec=InvestmentSignalModel)
        signal_model.id = 8
        signal_model.asset_code = "000001.SH"
        signal_model.status = "pending"
        entity = Mock()
        entity.id = "8"
        entity.status = SignalStatus.PENDING
        entity.invalidation_rule = invalidation_rule
        signal_model.to_domain_entity.return_value = entity

        # Mock macro_repo to return values that satisfy the invalidation condition
        with patch.object(service, 'macro_repo') as mock_repo:
            mock_repo.get_latest_by_code.return_value = Mock(
                value=49.0,  # PMI < 50, so condition is met
                unit="",
                observed_at=datetime.now()
            )
            mock_repo.get_history_by_code.return_value = []

            result = service._check_signal_model(signal_model)

        # Verify the signal was rejected (not invalidated)
        assert signal_model.status == 'rejected'
        assert signal_model.rejection_reason is not None
        # For pending signals, invalidated_at should not be set
        # (the Mock object might have the attribute, but we check the status change)

    def test_approved_signal_with_satisfied_invalidation_gets_invalidated(self, invalidation_rule):
        """测试证伪条件满足的 approved 信号被标记为 invalidated"""
        service = InvalidationCheckService()

        # Create an approved signal
        signal_model = Mock(spec=InvestmentSignalModel)
        entity = Mock()
        entity.id = "9"
        entity.status = SignalStatus.APPROVED
        entity.invalidation_rule = invalidation_rule
        signal_model.to_domain_entity.return_value = entity

        # Mock macro_repo to return values that satisfy the invalidation condition
        with patch.object(service, 'macro_repo') as mock_repo:
            mock_repo.get_latest_by_code.return_value = Mock(
                value=49.0,  # PMI < 50, so condition is met
                unit="",
                observed_at=datetime.now()
            )
            mock_repo.get_history_by_code.return_value = []

            result = service._check_signal_model(signal_model)

        # Verify the signal was invalidated
        assert signal_model.status == 'invalidated'
        assert signal_model.invalidated_at is not None
        assert signal_model.rejection_reason is not None

    @pytest.mark.django_db
    def test_default_macro_repository_reads_data_center(self, invalidation_rule):
        MacroFactModel.objects.create(
            indicator_code="CN_PMI_MANUFACTURING",
            reporting_period=datetime(2025, 2, 1).date(),
            value=49.2,
            unit="指数",
            source="tushare",
            published_at=datetime(2025, 2, 3).date(),
        )

        service = InvalidationCheckService()

        indicator_values = service._fetch_indicator_values(invalidation_rule)

        assert indicator_values["CN_PMI_MANUFACTURING"].current_value == pytest.approx(49.2)
        assert indicator_values["CN_PMI_MANUFACTURING"].history_values == [49.2]
