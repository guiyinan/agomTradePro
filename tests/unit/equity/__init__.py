"""
Unit tests for Signal Domain Rules.

Pure Domain layer tests using only Python standard library.
"""

import pytest

from apps.signal.domain.entities import Eligibility, SignalStatus
from apps.signal.domain.rules import (
    RejectionRecord,
    ValidationResult,
    analyze_regime_transition,
    check_eligibility,
    create_rejection_record,
    get_recommended_asset_classes,
    should_reject_signal,
    validate_invalidation_logic,
)


class TestEligibilityMatrix:
    """Tests for ELIGIBILITY_MATRIX configuration"""

    def test_matrix_structure(self):
        """Test that matrix has required structure"""
        from apps.signal.domain.rules import get_eligibility_matrix

        matrix = get_eligibility_matrix()
        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]

        for _asset_class, regime_map in matrix.items():
            for regime in regimes:
                assert regime in regime_map
                assert isinstance(regime_map[regime], Eligibility)

    def test_known_asset_classes(self):
        """Test expected asset classes exist"""
        from apps.signal.domain.rules import get_eligibility_matrix

        matrix = get_eligibility_matrix()
        expected_classes = [
            "a_share_growth", "a_share_value", "china_bond",
            "gold", "commodity", "cash"
        ]
        for asset_class in expected_classes:
            assert asset_class in matrix


class TestCheckEligibility:
    """Tests for check_eligibility function"""

    def test_check_eligibility_a_share_growth_recovery(self):
        """Test A股成长在复苏期"""
        result = check_eligibility("a_share_growth", "Recovery")
        assert result == Eligibility.PREFERRED

    def test_check_eligibility_a_share_growth_stagflation(self):
        """Test A股成长在滞胀期"""
        result = check_eligibility("a_share_growth", "Stagflation")
        assert result == Eligibility.HOSTILE

    def test_check_eligibility_gold_stagflation(self):
        """Test 黄金在滞胀期"""
        result = check_eligibility("gold", "Stagflation")
        assert result == Eligibility.PREFERRED

    def test_check_eligibility_china_bond_deflation(self):
        """Test 中国债券在通缩期"""
        result = check_eligibility("china_bond", "Deflation")
        assert result == Eligibility.PREFERRED

    def test_check_eligibility_unknown_asset(self):
        """Test with unknown asset class"""
        with pytest.raises(ValueError, match="Unknown asset class"):
            check_eligibility("unknown_asset", "Recovery")

    def test_check_eligibility_unknown_regime(self):
        """Test with unknown regime returns NEUTRAL"""
        result = check_eligibility("a_share_growth", "UnknownRegime")
        assert result == Eligibility.NEUTRAL


class TestValidateInvalidationLogic:
    """Tests for validate_invalidation_logic function"""

    def test_valid_logic_with_threshold(self):
        """Test valid logic with numeric threshold"""
        result = validate_invalidation_logic("PMI 跌破 50 且连续两月低于前值")
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_valid_logic_with_symbol(self):
        """Test valid logic with comparison symbol"""
        result = validate_invalidation_logic("CPI < 2.0 时退出")
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_valid_logic突破(self):
        """Test valid logic with 突破 keyword"""
        result = validate_invalidation_logic("突破 3000 点后减仓")
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_invalid_too_short(self):
        """Test logic that is too short"""
        result = validate_invalidation_logic("跌破")
        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "过短" in result.errors[0]

    def test_invalid_no_quantifiable_keyword(self):
        """Test logic without quantifiable keyword"""
        # Make it long enough to pass length check
        result = validate_invalidation_logic("如果市场情况不太好我们就考虑退出这个交易")
        assert result.is_valid is False
        assert any("可量化" in err for err in result.errors)

    def test_warning_vague_language(self):
        """Test warning for vague language"""
        result = validate_invalidation_logic("如果可能跌破阈值大概50")
        assert result.is_valid is True  # Has keywords, so valid
        assert len(result.warnings) > 0

    def test_multiple_errors(self):
        """Test logic with multiple errors"""
        result = validate_invalidation_logic("不行")
        assert result.is_valid is False
        assert len(result.errors) >= 2


class TestShouldRejectSignal:
    """Tests for should_reject_signal function"""

    def test_reject_hostile_regime(self):
        """Test rejection in hostile regime"""
        should_reject, reason, eligibility = should_reject_signal(
            asset_class="a_share_growth",
            current_regime="Stagflation",  # HOSTILE for growth
            policy_level=0,
            confidence=0.5
        )
        assert should_reject is True
        assert reason is not None
        assert "HOSTILE" in reason
        assert eligibility == Eligibility.HOSTILE

    def test_reject_p3_policy(self):
        """Test rejection at P3 policy level"""
        should_reject, reason, eligibility = should_reject_signal(
            asset_class="china_bond",
            current_regime="Deflation",  # PREFERRED for bond
            policy_level=3,  # P3 - complete exit
            confidence=0.5
        )
        assert should_reject is True
        assert "P3" in reason
        assert "完全退出" in reason

    def test_reject_low_confidence_neutral(self):
        """Test rejection with low confidence and NEUTRAL eligibility"""
        should_reject, reason, eligibility = should_reject_signal(
            asset_class="commodity",
            current_regime="Recovery",  # NEUTRAL
            policy_level=0,
            confidence=0.25  # Low confidence < 0.3
        )
        assert should_reject is True
        assert "置信度较低" in reason

    def test_pass_preferred_high_confidence(self):
        """Test signal passes with PREFERRED and high confidence"""
        should_reject, reason, eligibility = should_reject_signal(
            asset_class="a_share_growth",
            current_regime="Recovery",  # PREFERRED
            policy_level=0,
            confidence=0.5
        )
        assert should_reject is False
        assert reason is None
        assert eligibility == Eligibility.PREFERRED

    def test_pass_neutral_high_confidence(self):
        """Test signal passes with NEUTRAL but high confidence"""
        should_reject, reason, eligibility = should_reject_signal(
            asset_class="commodity",
            current_regime="Recovery",  # NEUTRAL
            policy_level=0,
            confidence=0.5  # High confidence
        )
        assert should_reject is False
        assert eligibility == Eligibility.NEUTRAL

    def test_unknown_asset_class(self):
        """Test with unknown asset class"""
        should_reject, reason, eligibility = should_reject_signal(
            asset_class="unknown_asset",
            current_regime="Recovery",
            policy_level=0,
            confidence=0.5
        )
        # Unknown asset treated as NEUTRAL
        assert should_reject is False
        assert eligibility == Eligibility.NEUTRAL


class TestCreateRejectionRecord:
    """Tests for create_rejection_record function"""

    def test_create_rejection_for_hostile_regime(self):
        """Test creating rejection record for hostile regime"""
        record = create_rejection_record(
            asset_code="000001.SH",
            asset_class="a_share_growth",
            current_regime="Stagflation",
            policy_level=0,
            confidence=0.5
        )

        assert isinstance(record, RejectionRecord)
        assert record.asset_code == "000001.SH"
        assert record.asset_class == "a_share_growth"
        assert record.eligibility == Eligibility.HOSTILE
        assert record.policy_veto is False

    def test_create_rejection_for_p3_policy(self):
        """Test creating rejection record for P3 policy"""
        record = create_rejection_record(
            asset_code="000001.SH",
            asset_class="a_share_growth",
            current_regime="Recovery",  # PREFERRED
            policy_level=3,  # P3
            confidence=0.5
        )

        assert isinstance(record, RejectionRecord)
        assert record.policy_veto is True

    def test_no_rejection_for_preferred_regime(self):
        """Test no rejection for preferred regime"""
        record = create_rejection_record(
            asset_code="000001.SH",
            asset_class="a_share_growth",
            current_regime="Recovery",
            policy_level=0,
            confidence=0.5
        )

        assert record is None


class TestGetRecommendedAssetClasses:
    """Tests for get_recommended_asset_classes function"""

    def test_recovery_recommendations(self):
        """Test recommendations for Recovery regime"""
        recommended = get_recommended_asset_classes("Recovery")
        assert "a_share_growth" in recommended
        assert "a_share_value" in recommended
        # PREFERRED assets should come before NEUTRAL
        growth_idx = recommended.index("a_share_growth")
        commodity_idx = recommended.index("commodity")
        assert growth_idx < commodity_idx

    def test_stagflation_recommendations(self):
        """Test recommendations for Stagflation regime"""
        recommended = get_recommended_asset_classes("Stagflation")
        assert "gold" in recommended  # PREFERRED
        assert "a_share_growth" not in recommended  # HOSTILE, should not be in list

    def test_deflation_recommendations(self):
        """Test recommendations for Deflation regime"""
        recommended = get_recommended_asset_classes("Deflation")
        assert "china_bond" in recommended  # PREFERRED
        assert "cash" in recommended  # PREFERRED

    def test_overheat_recommendations(self):
        """Test recommendations for Overheat regime"""
        recommended = get_recommended_asset_classes("Overheat")
        assert "gold" in recommended  # PREFERRED
        assert "a_share_value" in recommended  # PREFERRED


class TestAnalyzeRegimeTransition:
    """Tests for analyze_regime_transition function"""

    def test_recovery_to_overheat(self):
        """Test transition from Recovery to Overheat"""
        impacts = analyze_regime_transition("Recovery", "Overheat")
        assert len(impacts) > 0
        # Should mention assets that change status
        " ".join(impacts)
        # Commodity goes from NEUTRAL to PREFERRED
        assert any("commodity" in impact.lower() for impact in impacts)

    def test_overheat_to_stagflation(self):
        """Test transition from Overheat to Stagflation"""
        impacts = analyze_regime_transition("Overheat", "Stagflation")
        assert len(impacts) > 0

    def test_stagflation_to_deflation(self):
        """Test transition from Stagflation to Deflation"""
        impacts = analyze_regime_transition("Stagflation", "Deflation")
        assert len(impacts) > 0
        # a_share_value goes from PREFERRED (Stagflation) to HOSTILE (Deflation)
        # china_bond goes from NEUTRAL to PREFERRED
        " ".join(impacts)
        assert any(("china_bond" in impact.lower() or "a_share_value" in impact.lower())
                   for impact in impacts)

    def test_no_transition_same_regime(self):
        """Test no change when regime stays the same"""
        impacts = analyze_regime_transition("Recovery", "Recovery")
        # Should be empty since no changes
        assert len(impacts) == 0

    def test_deflation_to_recovery_major_shift(self):
        """Test major shift from Deflation to Recovery"""
        impacts = analyze_regime_transition("Deflation", "Recovery")
        assert len(impacts) > 0
        # Many assets should change status
        # Check that we have significant number of impacts
        assert len(impacts) >= 3


class TestEligibilityEnum:
    """Tests for Eligibility enum"""

    def test_eligibility_values(self):
        """Test Eligibility enum has correct values"""
        assert hasattr(Eligibility, "PREFERRED")
        assert hasattr(Eligibility, "NEUTRAL")
        assert hasattr(Eligibility, "HOSTILE")

    def test_eligibility_comparison(self):
        """Test Eligibility enum comparison"""
        assert Eligibility.PREFERRED != Eligibility.NEUTRAL
        assert Eligibility.NEUTRAL != Eligibility.HOSTILE
        assert Eligibility.HOSTILE != Eligibility.PREFERRED


class TestSignalStatusEnum:
    """Tests for SignalStatus enum"""

    def test_signal_status_values(self):
        """Test SignalStatus enum has correct values"""
        assert hasattr(SignalStatus, "PENDING")
        assert hasattr(SignalStatus, "APPROVED")
        assert hasattr(SignalStatus, "REJECTED")
        assert hasattr(SignalStatus, "INVALIDATED")
        assert hasattr(SignalStatus, "EXPIRED")


class TestValidationResult:
    """Tests for ValidationResult dataclass"""

    def test_validation_result_valid(self):
        """Test valid ValidationResult"""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[]
        )
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validation_result_invalid(self):
        """Test invalid ValidationResult"""
        result = ValidationResult(
            is_valid=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"]
        )
        assert result.is_valid is False
        assert len(result.errors) == 2


class TestRejectionRecord:
    """Tests for RejectionRecord dataclass"""

    def test_rejection_record_creation(self):
        """Test RejectionRecord creation"""
        record = RejectionRecord(
            asset_code="000001.SH",
            asset_class="a_share_growth",
            current_regime="Stagflation",
            eligibility=Eligibility.HOSTILE,
            reason="Environment is hostile for growth stocks",
            policy_veto=False
        )
        assert record.asset_code == "000001.SH"
        assert record.eligibility == Eligibility.HOSTILE
        assert record.policy_veto is False

    def test_rejection_record_with_policy_veto(self):
        """Test RejectionRecord with policy veto"""
        record = RejectionRecord(
            asset_code="000001.SH",
            asset_class="a_share_growth",
            current_regime="Recovery",
            eligibility=Eligibility.PREFERRED,
            reason="P3 policy: Complete exit mode",
            policy_veto=True
        )
        assert record.policy_veto is True
        assert "P3" in record.reason
