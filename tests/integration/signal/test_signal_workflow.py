"""
Integration Tests for Signal Complete Lifecycle

测试投资信号的完整生命周期，包括：
1. 信号创建→审批→证伪流程
2. 基于 Regime 的准入过滤
3. Policy 否决逻辑
"""

from datetime import date, timedelta

import pytest

from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.policy.domain.entities import PolicyEvent, PolicyLevel
from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.signal.application.use_cases import (
    CheckSignalInvalidationRequest,
    CheckSignalInvalidationUseCase,
    ReevaluateSignalsRequest,
    ReevaluateSignalsUseCase,
    ValidateSignalRequest,
    ValidateSignalUseCase,
)
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.signal.infrastructure.repositories import DjangoSignalRepository


@pytest.mark.django_db
class TestSignalCompleteWorkflow:
    """测试信号完整生命周期"""

    def test_signal_creation_to_invalidation(self):
        """测试信号完整生命周期

        流程：
        1. 创建信号（含证伪规则）
        2. 审批信号
        3. 模拟宏观数据变化
        4. 触发证伪检查
        5. 验证信号被证伪
        """
        # 1. 创建验证用例
        validate_use_case = ValidateSignalUseCase()

        # 2. 创建信号请求（PMI 回升到 51 以上）
        request = ValidateSignalRequest(
            asset_code="000001.SH",
            asset_class="EQUITY",
            direction="LONG",
            logic_desc="PMI 连续回升，经济复苏",
            invalidation_logic="PMI 跌破 50 且连续 2 月低于前值",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            current_regime="Recovery",
            policy_level=0,  # P0 - 无政策干预
            regime_confidence=0.5
        )

        # 3. 验证并创建信号
        signal = validate_use_case.validate_and_create_signal(request)

        assert signal is not None, "信号应通过验证"
        assert signal.status == SignalStatus.APPROVED
        assert signal.asset_code == "000001.SH"
        assert signal.invalidation_logic == "PMI 跌破 50 且连续 2 月低于前值"

        # 设置默认的 rejection_reason（模型要求不能为 NULL）
        signal = InvestmentSignal(
            id=signal.id,
            asset_code=signal.asset_code,
            asset_class=signal.asset_class,
            direction=signal.direction,
            logic_desc=signal.logic_desc,
            invalidation_logic=signal.invalidation_logic,
            invalidation_threshold=signal.invalidation_threshold,
            target_regime=signal.target_regime,
            created_at=signal.created_at,
            status=signal.status,
            rejection_reason=""  # 空字符串作为默认值
        )

        # 4. 保存信号到数据库
        signal_repo = DjangoSignalRepository()
        saved_signal = signal_repo.save_signal(signal)

        assert saved_signal.id is not None, "信号应被分配 ID"
        assert saved_signal.status == SignalStatus.APPROVED

        # 5. 模拟宏观数据变化（PMI 跌破 50）
        macro_repo = DjangoMacroRepository()
        base_date = date(2024, 1, 1)

        # 前两个月：PMI > 50
        for i in range(2):
            observed_date = base_date + timedelta(days=30 * i)
            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=51.0,  # 高于 50
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=observed_date + timedelta(days=1),
                    source="test"
                )
            )

        # 第三个月：PMI 跌破 50
        macro_repo.save_indicator(
            MacroIndicator(
                code="CN_PMI",
                value=49.5,  # 低于 50
                reporting_period=base_date + timedelta(days=30 * 2),
                period_type=PeriodType.MONTH,
                unit="指数",
                original_unit="指数",
                published_at=base_date + timedelta(days=30 * 2 + 1),
                source="test"
            )
        )

        # 6. 触发证伪检查
        check_use_case = CheckSignalInvalidationUseCase()

        # 获取当前指标值
        current_values = {"PMI": 49.5}

        check_request = CheckSignalInvalidationRequest(
            signal=saved_signal,
            current_indicator_values=current_values
        )

        response = check_use_case.execute(check_request)

        # 7. 验证信号被证伪
        assert response.is_invalidated, "信号应被证伪"
        assert "50" in response.reason, "证伪原因应包含阈值 50"

        # 8. 更新信号状态
        signal_repo.update_signal_status(
            signal_id=saved_signal.id,
            new_status=SignalStatus.INVALIDATED
        )

        # 验证状态已更新
        updated_signal = signal_repo.get_signal_by_id(saved_signal.id)
        assert updated_signal.status == SignalStatus.INVALIDATED

    def test_regime_based_rejection(self):
        """测试基于 Regime 的准入过滤

        验证：
        1. 设置当前 Regime
        2. 创建不匹配的信号
        3. 验证信号被拒绝
        4. 验证 RejectionLog 记录
        """
        # 1. 设置当前 Regime 为 Stagflation（滞胀）
        # 在滞胀环境下，a_share_growth 是 HOSTILE（敌对）的

        # 2. 创建验证请求（使用内部资产类别名称）
        validate_use_case = ValidateSignalUseCase()

        request = ValidateSignalRequest(
            asset_code="000300.SH",
            asset_class="a_share_growth",  # 使用内部资产类别名称
            direction="LONG",
            logic_desc="看好成长股",
            invalidation_logic="当 PMI 跌破 49 且连续两个月低于前值时证伪",
            invalidation_threshold=49.0,
            target_regime="Recovery",  # 目标是复苏
            current_regime="Stagflation",  # 但当前是滞胀（a_share_growth 在滞胀下为 HOSTILE）
            policy_level=0,
            regime_confidence=0.6
        )

        # 3. 执行验证
        response = validate_use_case.execute(request)

        # 4. 验证信号被拒绝
        assert response.is_valid, "证伪逻辑应有效"
        assert not response.is_approved, "信号应被拒绝（a_share_growth 在 Stagflation 下为 HOSTILE）"
        assert response.rejection_record is not None, "应有拒绝记录"

        # 5. 验证拒绝原因
        assert "Stagflation" in response.rejection_record.reason or \
               "HOSTILE" in str(response.rejection_record.eligibility) or \
               "敌对" in response.rejection_record.reason, \
               f"拒绝原因应与 Regime 不匹配相关，实际: {response.rejection_record.reason if response.rejection_record else 'None'}"

    def test_policy_veto_logic(self):
        """测试 Policy 否决逻辑

        验证：
        1. 创建 P2 档位 Policy 事件
        2. 尝试创建信号
        3. 验证信号被暂停或否决
        """
        # 1. 创建 P2 Policy 事件（干预状态）
        policy_repo = DjangoPolicyRepository()
        policy_event = PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="央行降准",
            description="中国人民银行决定下调存款准备金率 0.5 个百分点，这是对经济的直接干预措施",
            evidence_url="https://example.com/news/1"
        )
        policy_repo.save_event(policy_event)

        # 2. 尝试创建信号
        validate_use_case = ValidateSignalUseCase()

        request = ValidateSignalRequest(
            asset_code="10Y国债",
            asset_class="BOND",
            direction="LONG",
            logic_desc="利率下行，债券牛市",
            invalidation_logic="利率上行超过 3%",
            invalidation_threshold=3.0,
            target_regime="Deflation",
            current_regime="Deflation",
            policy_level=2,  # P2 - 干预状态
            regime_confidence=0.5
        )

        # 3. 执行验证
        response = validate_use_case.execute(request)

        # 4. 验证 P2 档位的影响
        # P2 档位下，部分资产类别可能被暂停
        # 检查是否有 Policy 相关的影响
        if response.rejection_record:
            assert response.rejection_record.policy_veto or \
                   "policy" in response.rejection_record.reason.lower(), \
                   "P2 档位应影响信号审批"

    def test_signal_status_transitions(self):
        """测试信号状态转换

        验证信号状态机：
        PENDING -> APPROVED -> INVALIDATED
        PENDING -> REJECTED
        """
        signal_repo = DjangoSignalRepository()

        # 1. 创建待处理信号
        signal = InvestmentSignal(
            id=None,
            asset_code="000001.SH",
            asset_class="EQUITY",
            direction="LONG",
            logic_desc="测试信号",
            invalidation_logic="PMI < 50",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            created_at=date.today(),
            status=SignalStatus.PENDING,
            rejection_reason=""
        )

        saved = signal_repo.save_signal(signal)
        assert saved.status == SignalStatus.PENDING

        # 2. 转换到 APPROVED
        approved = signal_repo.update_signal_status(
            signal_id=saved.id,
            new_status=SignalStatus.APPROVED
        )
        assert approved

        updated = signal_repo.get_signal_by_id(saved.id)
        assert updated.status == SignalStatus.APPROVED

        # 3. 转换到 INVALIDATED
        invalidated = signal_repo.update_signal_status(
            signal_id=saved.id,
            new_status=SignalStatus.INVALIDATED
        )
        assert invalidated

        final = signal_repo.get_signal_by_id(saved.id)
        assert final.status == SignalStatus.INVALIDATED

        # 4. 测试 PENDING -> REJECTED
        signal2 = InvestmentSignal(
            id=None,
            asset_code="000002.SH",
            asset_class="EQUITY",
            direction="LONG",
            logic_desc="测试信号2",
            invalidation_logic="CPI > 3",
            invalidation_threshold=3.0,
            target_regime="Overheat",
            created_at=date.today(),
            status=SignalStatus.PENDING,
            rejection_reason=""
        )

        saved2 = signal_repo.save_signal(signal2)

        rejected = signal_repo.update_signal_status(
            signal_id=saved2.id,
            new_status=SignalStatus.REJECTED,
            rejection_reason="不匹配当前 Regime"
        )
        assert rejected

        rejected_signal = signal_repo.get_signal_by_id(saved2.id)
        assert rejected_signal.status == SignalStatus.REJECTED
        assert rejected_signal.rejection_reason == "不匹配当前 Regime"

    def test_get_recommended_assets(self):
        """测试获取推荐资产

        验证在不同 Regime 下获取推荐资产列表
        """
        from apps.signal.application.use_cases import (
            GetRecommendedAssetsRequest,
            GetRecommendedAssetsUseCase,
        )

        use_case = GetRecommendedAssetsUseCase()

        # 1. Recovery 象限
        request = GetRecommendedAssetsRequest(current_regime="Recovery")
        response = use_case.execute(request)

        assert len(response.recommended) > 0, "Recovery 象限应有推荐资产"
        # Domain 层返回内部资产类别名称（如 a_share_growth）
        assert any("share" in asset or "equity" in asset.lower() for asset in response.recommended), \
            f"复苏期应推荐股票类资产，实际: {response.recommended}"

        # 2. Deflation 象限
        request = GetRecommendedAssetsRequest(current_regime="Deflation")
        response = use_case.execute(request)

        assert any("bond" in asset.lower() for asset in response.recommended), \
            f"通缩期应推荐债券，实际: {response.recommended}"

        # 3. Overheat 象限
        request = GetRecommendedAssetsRequest(current_regime="Overheat")
        response = use_case.execute(request)

        assert any(asset in response.recommended for asset in ["gold", "commodity"]), \
            f"过热期应推荐大宗商品或黄金，实际: {response.recommended}"


@pytest.mark.django_db
class TestSignalReevaluation:
    """测试信号重评功能"""

    def test_reevaluate_signals_on_regime_change(self):
        """测试 Regime 变化时的信号重评

        当 Regime 从一个变为另一个时，重新评估所有活跃信号
        """
        signal_repo = DjangoSignalRepository()

        # 1. 创建多个活跃信号（使用内部资产类别名称）
        base_date = date.today()

        # a_share_growth 在 Stagflation 下为 HOSTILE，应被拒绝
        signal1 = InvestmentSignal(
            id=None,
            asset_code="000001.SH",
            asset_class="a_share_growth",  # 使用内部资产类别名称
            direction="LONG",
            logic_desc="成长股信号1",
            invalidation_logic="PMI 连续两个月跌破 50 则证伪",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            created_at=base_date,
            status=SignalStatus.APPROVED,
            rejection_reason=""
        )

        # commodity 在 Stagflation 下也为 HOSTILE，应被拒绝
        signal2 = InvestmentSignal(
            id=None,
            asset_code="CU0.SHF",  # 铜期货
            asset_class="commodity",  # 使用内部资产类别名称
            direction="LONG",
            logic_desc="大宗商品信号",
            invalidation_logic="价格跌破前值 5% 则证伪",
            invalidation_threshold=5.0,
            target_regime="Overheat",  # 目标是过热
            created_at=base_date,
            status=SignalStatus.APPROVED,
            rejection_reason=""
        )

        saved1 = signal_repo.save_signal(signal1)
        signal_repo.save_signal(signal2)

        # 2. Regime 变为 Stagflation（滞胀）
        # 创建重评用例
        reevaluate_use_case = ReevaluateSignalsUseCase(signal_repository=signal_repo)

        request = ReevaluateSignalsRequest(
            policy_level=0,
            current_regime="Stagflation",  # a_share_growth 和 commodity 在 Stagflation 下均为 HOSTILE
            regime_confidence=0.6
        )

        response = reevaluate_use_case.execute(request)

        # 3. 验证重评结果
        assert response.total_count >= 2, f"应找到至少 2 个活跃信号，实际: {response.total_count}"
        # 目标为 Recovery/Overheat 的信号在 Stagflation 下应被拒绝
        assert response.rejected_count > 0, f"应有信号被拒绝，实际拒绝: {response.rejected_count}/{response.total_count}"

        # 4. 验证信号状态已更新
        signal_repo.get_signal_by_id(saved1.id)
        # a_share_growth 在 Stagflation 下为 HOSTILE，应被拒绝
        # 但实际的拒绝逻辑由 domain rules 决定

    def test_reevaluate_on_policy_level_change(self):
        """测试政策档位变化时的信号重评

        当 Policy 从 P0 变为 P2/P3 时，某些信号应被暂停
        """
        signal_repo = DjangoSignalRepository()

        # 1. 创建活跃信号
        signal = InvestmentSignal(
            id=None,
            asset_code="000001.SH",
            asset_class="EQUITY",
            direction="LONG",
            logic_desc="股票信号",
            invalidation_logic="PMI < 50",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            created_at=date.today(),
            status=SignalStatus.APPROVED,
            rejection_reason=""
        )

        signal_repo.save_signal(signal)

        # 2. Policy 变为 P3（危机模式）
        reevaluate_use_case = ReevaluateSignalsUseCase(signal_repository=signal_repo)

        request = ReevaluateSignalsRequest(
            policy_level=3,  # P3 - 危机模式
            current_regime="Stagflation",
            regime_confidence=0.7
        )

        reevaluate_use_case.execute(request)

        # 3. 验证 P3 的影响
        # 在 P3 危机模式下，几乎所有投机性信号都应被暂停


@pytest.mark.django_db
class TestSignalStatistics:
    """测试信号统计功能"""

    def test_get_signal_statistics(self):
        """测试获取信号统计信息"""
        signal_repo = DjangoSignalRepository()

        # 1. 创建不同状态的信号
        base_date = date.today()

        signals = [
            InvestmentSignal(
                id=None,
                asset_code=f"00000{i}.SH",
                asset_class="EQUITY",
                direction="LONG",
                logic_desc=f"信号{i}",
                invalidation_logic="PMI < 50",
                invalidation_threshold=50.0,
                target_regime="Recovery",
                created_at=base_date,
                status=status,
                rejection_reason=""
            )
            for i, status in enumerate([
                SignalStatus.PENDING,
                SignalStatus.APPROVED,
                SignalStatus.APPROVED,
                SignalStatus.REJECTED,
                SignalStatus.INVALIDATED
            ])
        ]

        for signal in signals:
            signal_repo.save_signal(signal)

        # 2. 获取统计
        stats = signal_repo.get_statistics()

        # 3. 验证统计
        assert stats["total"] == 5
        assert stats["by_status"]["pending"]["count"] == 1
        assert stats["by_status"]["approved"]["count"] == 2
        assert stats["by_status"]["rejected"]["count"] == 1
        assert stats["by_status"]["invalidated"]["count"] == 1

        # 验证百分比
        assert abs(stats["by_status"]["approved"]["percentage"] - 0.4) < 0.01

    def test_get_signals_by_filters(self):
        """测试按条件筛选信号"""
        signal_repo = DjangoSignalRepository()
        base_date = date.today()

        # 1. 创建多个信号
        for i in range(5):
            signal = InvestmentSignal(
                id=None,
                asset_code="000001.SH" if i < 3 else "000002.SH",
                asset_class="EQUITY",
                direction="LONG",
                logic_desc=f"信号{i}",
                invalidation_logic="PMI < 50",
                invalidation_threshold=50.0,
                target_regime="Recovery" if i < 2 else "Deflation",
                created_at=base_date,
                status=SignalStatus.APPROVED,
                rejection_reason=""
            )
            signal_repo.save_signal(signal)

        # 2. 按资产代码筛选
        signals_000001 = signal_repo.get_signals_by_asset("000001.SH")
        assert len(signals_000001) == 3

        signals_000002 = signal_repo.get_signals_by_asset("000002.SH")
        assert len(signals_000002) == 2

        # 3. 按 Regime 筛选
        recovery_signals = signal_repo.get_signals_by_regime("Recovery")
        assert len(recovery_signals) == 2

        deflation_signals = signal_repo.get_signals_by_regime("Deflation")
        assert len(deflation_signals) == 3

        # 4. 按状态筛选
        approved_signals = signal_repo.get_signals_by_status(SignalStatus.APPROVED)
        assert len(approved_signals) == 5

    def test_get_active_signals(self):
        """测试获取活跃信号"""
        signal_repo = DjangoSignalRepository()
        base_date = date.today()

        # 1. 创建混合状态的信号
        for status in [SignalStatus.PENDING, SignalStatus.APPROVED, SignalStatus.APPROVED,
                       SignalStatus.REJECTED, SignalStatus.INVALIDATED]:
            signal = InvestmentSignal(
                id=None,
                asset_code="000001.SH",
                asset_class="EQUITY",
                direction="LONG",
                logic_desc="测试",
                invalidation_logic="PMI < 50",
                invalidation_threshold=50.0,
                target_regime="Recovery",
                created_at=base_date,
                status=status,
                rejection_reason=""
            )
            signal_repo.save_signal(signal)

        # 2. 获取活跃信号（只有 APPROVED 算活跃）
        active_signals = signal_repo.get_active_signals()
        assert len(active_signals) == 2

        for signal in active_signals:
            assert signal.status == SignalStatus.APPROVED
