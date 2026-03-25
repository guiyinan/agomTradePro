"""Tests for Regime → Asset Guidance Mapping"""

import pytest

from apps.regime.domain.navigator_services import (
    RegimeAssetConfig,
    map_regime_to_asset_guidance,
)
from apps.regime.domain.services_v2 import RegimeType


class TestMapRegimeToAssetGuidance:
    """Test map_regime_to_asset_guidance()"""

    def test_recovery_returns_high_equity_range(self):
        """Recovery → equity should be 50-70%"""
        result = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)
        eq_range = next(wr for wr in result["weight_ranges"] if wr["category"] == "equity")
        assert eq_range["lower"] == 0.50
        assert eq_range["upper"] == 0.70
        assert eq_range["label"] == "权益类"

    def test_stagflation_returns_high_cash_range(self):
        """Stagflation → cash should be 25-40%"""
        result = map_regime_to_asset_guidance(RegimeType.STAGFLATION, 0.7)
        cash_range = next(wr for wr in result["weight_ranges"] if wr["category"] == "cash")
        assert cash_range["lower"] == 0.25
        assert cash_range["upper"] == 0.40

    def test_deflation_returns_high_bond_range(self):
        """Deflation → bond should be 40-60%"""
        result = map_regime_to_asset_guidance(RegimeType.DEFLATION, 0.6)
        bond_range = next(wr for wr in result["weight_ranges"] if wr["category"] == "bond")
        assert bond_range["lower"] == 0.40
        assert bond_range["upper"] == 0.60

    def test_overheat_returns_high_commodity_range(self):
        """Overheat → commodity should be 25-40%"""
        result = map_regime_to_asset_guidance(RegimeType.OVERHEAT, 0.7)
        comm_range = next(wr for wr in result["weight_ranges"] if wr["category"] == "commodity")
        assert comm_range["lower"] == 0.25
        assert comm_range["upper"] == 0.40

    def test_risk_budget_matches_regime(self):
        """Each regime has appropriate risk budget"""
        assert map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)["risk_budget"] == 0.85
        assert map_regime_to_asset_guidance(RegimeType.OVERHEAT, 0.8)["risk_budget"] == 0.70
        assert map_regime_to_asset_guidance(RegimeType.STAGFLATION, 0.8)["risk_budget"] == 0.50
        assert map_regime_to_asset_guidance(RegimeType.DEFLATION, 0.8)["risk_budget"] == 0.60

    def test_low_confidence_reduces_risk_budget(self):
        """Confidence < 0.3 should reduce risk budget by 20%"""
        normal = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)
        low = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.2)
        assert low["risk_budget"] < normal["risk_budget"]
        assert low["risk_budget"] == pytest.approx(0.85 * 0.8)

    def test_sectors_are_regime_specific(self):
        """Each regime has different recommended sectors"""
        recovery = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)
        stagflation = map_regime_to_asset_guidance(RegimeType.STAGFLATION, 0.8)
        assert "科技" in recovery["sectors"]
        assert "医药" in stagflation["sectors"]

    def test_styles_are_regime_specific(self):
        """Each regime has different benefiting styles"""
        recovery = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)
        deflation = map_regime_to_asset_guidance(RegimeType.DEFLATION, 0.8)
        assert "成长" in recovery["styles"]
        assert "低波" in deflation["styles"]

    def test_custom_config_overrides_defaults(self):
        """Custom RegimeAssetConfig should override defaults"""
        custom_config = RegimeAssetConfig(
            asset_ranges={"Recovery": {"equity": (0.30, 0.50), "bond": (0.50, 0.70)}},
            risk_budget={"Recovery": 0.90},
            sectors={"Recovery": ["CustomSector"]},
            styles={"Recovery": ["CustomStyle"]},
        )
        result = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8, config=custom_config)
        eq_range = next(wr for wr in result["weight_ranges"] if wr["category"] == "equity")
        assert eq_range["lower"] == 0.30
        assert eq_range["upper"] == 0.50
        assert result["risk_budget"] == 0.90
        assert "CustomSector" in result["sectors"]

    def test_reasoning_contains_regime_description(self):
        """Reasoning should explain the regime context"""
        result = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)
        assert "复苏" in result["reasoning"]
        assert "权益" in result["reasoning"]

    def test_all_four_asset_categories_present(self):
        """Output should contain all 4 categories"""
        result = map_regime_to_asset_guidance(RegimeType.RECOVERY, 0.8)
        categories = {wr["category"] for wr in result["weight_ranges"]}
        assert categories == {"equity", "bond", "commodity", "cash"}
