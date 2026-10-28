"""
统一推荐聚合服务单元测试

测试 GenerateUnifiedRecommendationsUseCase、GetUnifiedRecommendationsUseCase、
GetConflictsUseCase 等用例。
"""

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.alpha.application.services import AlphaProviderRegistry, AlphaService
from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.alpha.domain.interfaces import AlphaProvider, AlphaProviderStatus
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.alpha.infrastructure.models import AlphaScoreCacheModel
from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
from apps.decision_rhythm.application.dtos import UnifiedRecommendationDTO
from apps.decision_rhythm.application.use_cases import (
    GenerateRecommendationsRequest,
    GenerateUnifiedRecommendationsUseCase,
    GetConflictsRequest,
    GetConflictsUseCase,
    GetModelParamsUseCase,
    GetRecommendationsRequest,
    GetUnifiedRecommendationsUseCase,
)
from apps.decision_rhythm.domain.entities import (
    DecisionFeatureSnapshot,
    ModelParamConfig,
    RecommendationStatus,
    UnifiedRecommendation,
)
from apps.decision_rhythm.infrastructure.feature_providers import (
    BetaGateFeatureProvider,
    CompositeFeatureProvider,
)
from apps.equity.application import query_services as equity_query_services

# ============================================================================
# Mock 提供者
# ============================================================================


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("P0", 0),
        ("P2", 2),
        ("LEVEL_3", 3),
        ("PX", 0),
        ("unexpected", 0),
    ],
)
def test_beta_gate_policy_level_labels_are_normalized(
    label: str,
    expected: int,
) -> None:
    """Policy labels must enter the Beta Gate request as bounded integers."""

    assert BetaGateFeatureProvider._parse_policy_level(label) == expected


class MockFeatureDataProvider:
    """Mock 特征数据提供者"""

    def __init__(self):
        self._regime = {"regime": "GROWTH_INFLATION", "confidence": 0.85}
        self._policy_level = "LEVEL_2"
        self._beta_gate_results: dict[str, bool] = {}
        self._scores: dict[str, dict[str, float]] = {}
        self._feature_contracts: dict[str, dict[str, dict[str, object]]] = {}

    def get_regime(self) -> dict[str, Any] | None:
        return self._regime

    def get_policy_level(self) -> str | None:
        return self._policy_level

    def check_beta_gate(self, security_code: str) -> bool:
        return self._beta_gate_results.get(security_code, True)

    def get_sentiment_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("sentiment", 0.7)

    def get_flow_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("flow", 0.65)

    def get_technical_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("technical", 0.75)

    def get_fundamental_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("fundamental", 0.8)

    def get_alpha_model_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("alpha", 0.85)

    def get_feature_freshness_contracts(
        self,
        security_code: str,
    ) -> dict[str, dict[str, object]]:
        return self._feature_contracts.get(security_code, {})

    def set_beta_gate(self, security_code: str, passed: bool):
        self._beta_gate_results[security_code] = passed

    def set_scores(self, security_code: str, scores: dict[str, float]):
        if security_code not in self._scores:
            self._scores[security_code] = {}
        self._scores[security_code].update(scores)

    def set_feature_contracts(
        self,
        security_code: str,
        contracts: dict[str, dict[str, object]],
    ) -> None:
        self._feature_contracts[security_code] = contracts


class MockValuationProvider:
    """Mock 估值数据提供者"""

    def __init__(self):
        self._valuations: dict[str, dict[str, Any]] = {}

    def get_valuation(self, security_code: str) -> dict[str, Any] | None:
        return self._valuations.get(security_code)

    def set_valuation(self, security_code: str, valuation: dict[str, Any]):
        self._valuations[security_code] = valuation


class MockSignalProvider:
    """Mock 信号数据提供者"""

    def __init__(self):
        self._signals: list[dict[str, Any]] = []

    def get_active_signals(self, security_code: str | None = None) -> list[dict[str, Any]]:
        if security_code:
            return [s for s in self._signals if s.get("security_code") == security_code]
        return self._signals

    def add_signal(self, signal_id: str, security_code: str):
        self._signals.append({"signal_id": signal_id, "security_code": security_code})


class MockCandidateProvider:
    """Mock 候选数据提供者"""

    def __init__(self):
        self._candidates: list[dict[str, Any]] = []

    def get_active_candidates(self, account_id: str | None = None) -> list[dict[str, Any]]:
        if account_id:
            return [c for c in self._candidates if c.get("account_id") == account_id]
        return self._candidates

    def add_candidate(self, candidate_id: str, account_id: str, security_code: str):
        self._candidates.append(
            {
                "candidate_id": candidate_id,
                "account_id": account_id,
                "security_code": security_code,
            }
        )


class MockRecommendationRepository:
    """Mock 推荐仓储"""

    def __init__(self):
        self._recommendations: dict[str, UnifiedRecommendation] = {}
        self._snapshots: dict[str, DecisionFeatureSnapshot] = {}
        self._conflicts: list[str] = []

    def save(self, recommendation: UnifiedRecommendation) -> UnifiedRecommendation:
        self._recommendations[recommendation.recommendation_id] = recommendation
        return recommendation

    def save_feature_snapshot(self, snapshot: DecisionFeatureSnapshot) -> DecisionFeatureSnapshot:
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list[UnifiedRecommendation]:
        result = [
            r
            for r in self._recommendations.values()
            if r.account_id == account_id and r.recommendation_id not in self._conflicts
        ]
        if status:
            result = [r for r in result if r.status.value == status]
        return result

    def get_conflicts(self, account_id: str) -> list[UnifiedRecommendation]:
        return [
            r
            for r in self._recommendations.values()
            if r.account_id == account_id and r.recommendation_id in self._conflicts
        ]

    def mark_as_conflict(self, recommendation_id: str) -> None:
        self._conflicts.append(recommendation_id)


class MockPositionSnapshotProvider:
    """Mock 持仓快照提供者"""

    def __init__(self):
        self._positions: dict[str, list[dict[str, Any]]] = {}

    def get_position_snapshots(self, account_id: str) -> list[dict[str, Any]]:
        return list(self._positions.get(account_id, []))

    def set_positions(self, account_id: str, positions: list[dict[str, Any]]):
        self._positions[account_id] = list(positions)


# ============================================================================
# 测试类
# ============================================================================


class TestGenerateUnifiedRecommendationsUseCase:
    """测试生成统一推荐用例"""

    @pytest.fixture
    def setup(self):
        """设置测试环境"""
        feature_provider = MockFeatureDataProvider()
        valuation_provider = MockValuationProvider()
        signal_provider = MockSignalProvider()
        candidate_provider = MockCandidateProvider()
        recommendation_repo = MockRecommendationRepository()
        position_snapshot_provider = MockPositionSnapshotProvider()

        # Mock 参数用例
        param_use_case = MagicMock(spec=GetModelParamsUseCase)
        param_use_case.get_model_weights.return_value = MagicMock(
            alpha_model_weight=0.40,
            sentiment_weight=0.15,
            flow_weight=0.15,
            technical_weight=0.15,
            fundamental_weight=0.15,
        )
        param_use_case.get_gate_penalties.return_value = MagicMock(
            cooldown_penalty=0.10,
            quota_penalty=0.10,
            volatility_penalty=0.10,
        )

        use_case = GenerateUnifiedRecommendationsUseCase(
            feature_provider=feature_provider,
            valuation_provider=valuation_provider,
            signal_provider=signal_provider,
            candidate_provider=candidate_provider,
            recommendation_repo=recommendation_repo,
            param_use_case=param_use_case,
            position_snapshot_provider=position_snapshot_provider,
        )

        return {
            "use_case": use_case,
            "feature_provider": feature_provider,
            "valuation_provider": valuation_provider,
            "signal_provider": signal_provider,
            "candidate_provider": candidate_provider,
            "recommendation_repo": recommendation_repo,
            "position_snapshot_provider": position_snapshot_provider,
        }

    def test_generate_single_recommendation(self, setup):
        """测试生成单个推荐"""
        # 设置数据
        setup["feature_provider"].set_scores(
            "000001.SZ",
            {
                "sentiment": 0.75,
                "flow": 0.70,
                "technical": 0.80,
                "fundamental": 0.82,
                "alpha": 0.88,
            },
        )
        setup["valuation_provider"].set_valuation(
            "000001.SZ",
            {
                "fair_value": 15.50,
                "entry_price_low": 14.80,
                "entry_price_high": 15.20,
                "target_price_low": 18.00,
                "target_price_high": 20.00,
                "stop_loss_price": 13.50,
            },
        )

        # 执行
        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        # 验证
        assert response.success is True
        assert len(response.recommendations) == 1
        assert len(response.conflicts) == 0

        rec = response.recommendations[0]
        assert rec.security_code == "000001.SZ"
        assert rec.account_id == "account_001"
        assert rec.side in ["BUY", "SELL", "HOLD"]
        assert rec.composite_score > 0
        assert rec.beta_gate_passed is True

    def test_generate_marks_blocked_recommendation_as_hold(self, setup):
        """测试 Beta Gate 不通过时仍展示资产，但保持 HOLD。"""
        # 设置数据
        setup["feature_provider"].set_beta_gate("000001.SZ", False)
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.9})

        # 执行
        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        # 验证：仍然展示，但标记为 blocked / HOLD
        assert response.success is True
        assert len(response.recommendations) == 1
        recommendation = response.recommendations[0]
        assert recommendation.side == "HOLD"
        assert recommendation.beta_gate_passed is False
        assert "BETA_GATE_BLOCKED" in recommendation.reason_codes
        assert "Beta Gate 未通过" in recommendation.human_rationale

    @pytest.mark.parametrize("missing_dataset", ["price", "financial", "valuation"])
    def test_generate_preserves_context_block_for_only_affected_asset(
        self,
        setup: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        missing_dataset: str,
    ) -> None:
        """Real context and score owners retain missing-member limits in recommendations."""

        affected, complete = "000001.SZ", "000002.SZ"
        observation = "2026-08-03T01:00:00+00:00"
        reads: list[tuple[bool, bool, bool]] = []

        def _master_rows(codes: list[str]) -> dict[str, dict[str, str]]:
            return {code: {"asset_code": code, "name": code, "market": "SZ"} for code in codes}

        def _published_payloads(
            codes: list[str], **options: object
        ) -> dict[str, dict[str, dict[str, object]]]:
            enabled = tuple(
                bool(options.get(f"include_{name}", True))
                for name in ("price", "financial", "valuation")
            )
            reads.append((enabled[0], enabled[1], enabled[2]))
            rows: dict[str, list[dict[str, object]]] = {
                "price": [{"timestamp": "2026-08-03", "close": 10.0, "volume": 1000.0}],
                "financial": [{"period_end": "2026-06-30", "metric_code": "roe", "value": 10.0}],
                "valuation": [
                    {"val_date": "2026-08-03", "pe_ttm": 10.0, "observed_at": observation}
                ],
            }
            return {
                code: {
                    name: {
                        "publication_id": f"pub-{name}",
                        "freshness_status": "fresh",
                        "observed_at": observation,
                        "must_not_use_for_decision": False,
                        "blocked_reason": "",
                        "rows": [] if code == affected and name == missing_dataset else values,
                    }
                    for name, values in rows.items()
                    if options.get(f"include_{name}", True)
                }
                for code in codes
            }

        monkeypatch.setattr(
            equity_query_services,
            "get_equity_stock_repository",
            lambda: SimpleNamespace(get_stock_master_rows=_master_rows),
        )
        monkeypatch.setattr(
            equity_query_services, "get_published_equity_context_payloads", _published_payloads
        )
        context = equity_query_services.get_published_stock_context_map(
            [affected],
            include_price=missing_dataset == "price",
            include_financial=missing_dataset != "price",
            include_valuation=missing_dataset != "price",
        )[affected]
        assert context["must_not_use_for_decision"] is True
        assert context["blocked_reason"] == "canonical_publication_members_missing"

        provider = CompositeFeatureProvider()
        for method in (
            "get_regime",
            "get_policy_level",
            "check_beta_gate",
            "get_sentiment_score",
            "get_flow_score",
            "get_alpha_model_score",
        ):
            monkeypatch.setattr(provider, method, getattr(setup["feature_provider"], method))
        setup["use_case"].feature_provider = provider

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001", security_codes=[affected, complete]
            )
        )

        assert response.success is True
        recommendations = {row.security_code: row for row in response.recommendations}
        assert recommendations[affected].side == "HOLD"
        assert recommendations[affected].confidence == 0.0
        assert "FEATURE_BLOCKED_CANONICAL_PUBLICATION_MEMBERS_MISSING" in (
            recommendations[affected].reason_codes
        )
        assert recommendations[complete].side == "BUY"
        assert recommendations[complete].confidence > 0.0
        snapshots = {
            row.security_code: row for row in setup["recommendation_repo"]._snapshots.values()
        }
        feature = "technical" if missing_dataset == "price" else "fundamental"
        assert snapshots[affected].extra_features["feature_freshness"][feature] == {
            "observed_at": observation,
            "freshness_status": "fresh",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_members_missing",
        }
        assert all(
            contract["must_not_use_for_decision"] is False
            for contract in snapshots[complete].extra_features["feature_freshness"].values()
        )
        assert set(reads) == {(True, False, False), (False, True, True)}

    @pytest.mark.parametrize(
        "mode", ["last_stale", "later_failed", "fresh_backup", "nonstale_degraded"]
    )
    def test_generate_preserves_alpha_registry_staleness_without_blocking_fresh_fallback(
        self, setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch, mode: str
    ) -> None:
        """Real Alpha selection and enrichment must reach this request's stored decision."""

        target, other = "000001.SZ", "000002.SZ"
        today = date.today()
        stale_day = today - timedelta(days=10)
        registry = AlphaProviderRegistry()
        monkeypatch.setattr(
            "apps.alpha.application.services.load_runtime_alpha_fixed_provider", lambda: ""
        )

        def _result(source: str, age: int, *, status: str = "available") -> AlphaResult:
            return AlphaResult(
                success=True,
                scores=[
                    StockScore(
                        code=code,
                        score=0.8,
                        rank=rank,
                        factors={},
                        source=source,
                        confidence=0.9,
                        asof_date=today - timedelta(days=age + (code == other)),
                        intended_trade_date=today,
                    )
                    for rank, code in enumerate((other, target), start=1)
                ],
                source=source,
                timestamp=today.isoformat(),
                staleness_days=age,
                status=status,
                metadata={"scope_hash": "original-scope"},
            )

        def _register(result: AlphaResult, priority: int) -> MagicMock:
            external = MagicMock(spec=AlphaProvider)
            external.name = result.source
            external.priority = priority
            external.health_check.return_value = AlphaProviderStatus.AVAILABLE
            external.supports.return_value = True
            external.max_staleness_days = 2
            external.get_stock_scores.return_value = result
            registry.register(external)
            return external

        original = _result(
            "cache",
            1 if mode == "nonstale_degraded" else 10,
            status="degraded" if mode == "nonstale_degraded" else "available",
        )
        primary = _register(original, 1)
        if mode in {"later_failed", "fresh_backup"}:
            backup_result = _result("simple", 0)
            if mode == "later_failed":
                backup_result.success = False
                backup_result.scores = []
                backup_result.status = "unavailable"
            backup = _register(backup_result, 2)

        # Inject only external providers; use the actual service/enrichment and score owner.
        service = object.__new__(AlphaService)
        service._registry = registry
        provider = CompositeFeatureProvider()
        provider._alpha_service = service.get_stock_scores
        for method in (
            "get_regime",
            "get_policy_level",
            "check_beta_gate",
            "get_sentiment_score",
            "get_flow_score",
            "get_technical_score",
            "get_fundamental_score",
        ):
            monkeypatch.setattr(provider, method, getattr(setup["feature_provider"], method))
        setup["use_case"].feature_provider = provider

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(account_id="account_001", security_codes=[target])
        )
        assert response.success is True
        recommendation = response.recommendations[0]
        snapshot = setup["recommendation_repo"]._snapshots[recommendation.feature_snapshot_id]
        assert snapshot.alpha_model_score == pytest.approx(0.9)
        assert original.metadata["scope_hash"] == "original-scope"
        primary.get_stock_scores.assert_called_once()
        if mode in {"later_failed", "fresh_backup"}:
            backup.get_stock_scores.assert_called_once()
        if mode in {"last_stale", "later_failed"}:
            assert original.status == "degraded"
            assert recommendation.side == "HOLD"
            assert recommendation.confidence == 0.0
            assert "FEATURE_BLOCKED_ALPHA_SOURCE_DATA_STALE" in recommendation.reason_codes
            assert snapshot.extra_features["feature_freshness"]["alpha"] == {
                "observed_at": stale_day.isoformat(),
                "freshness_status": "stale",
                "must_not_use_for_decision": True,
                "blocked_reason": "alpha_source_data_stale",
            }
        else:
            assert recommendation.side == "BUY"
            assert recommendation.confidence > 0.0
            assert not any(
                contract["must_not_use_for_decision"]
                for contract in snapshot.extra_features["feature_freshness"].values()
            )

    @pytest.mark.parametrize("fresh_backup", [False, True])
    def test_generate_preserves_cache_date_integrity_across_real_alpha_chain(
        self, setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fresh_backup: bool
    ) -> None:
        """A corrupt cache cannot become a fresh score or bypass through candidates."""
        today = date.today()
        target = "000001.SZ"
        cache_row = AlphaScoreCacheModel(
            universe_id="csi300",
            asof_date=today,
            intended_trade_date=today,
            provider_source="qlib",
            model_artifact_hash="test-model",
            created_at=datetime.now(UTC),
            metrics_snapshot={},
            scores=[
                {
                    "code": code,
                    "score": 0.8,
                    "rank": rank,
                    "factors": {},
                    "confidence": 0.9,
                    "asof_date": source_day.isoformat(),
                }
                for rank, (code, source_day) in enumerate(
                    [(target, today), ("600000.SH", today - timedelta(days=20))], start=1
                )
            ],
        )
        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        query.first.return_value = cache_row
        monkeypatch.setattr(AlphaScoreCacheModel._default_manager, "filter", lambda **kwargs: query)
        monkeypatch.setattr(
            "apps.alpha.application.services.load_runtime_alpha_fixed_provider", lambda: ""
        )
        candidate_read = MagicMock(return_value=[SimpleNamespace(alpha_score=0.99)])
        monkeypatch.setattr(
            "apps.alpha_trigger.infrastructure.repositories.AlphaCandidateRepository.get_by_asset",
            candidate_read,
        )
        registry = AlphaProviderRegistry()
        qlib = QlibAlphaProvider(provider_uri=".", model_path=".")
        monkeypatch.setattr(qlib, "_get_active_model", lambda: {"artifact_hash": "test-model"})
        for cache_provider in (qlib, CacheAlphaProvider()):
            monkeypatch.setattr(
                cache_provider, "health_check", lambda: AlphaProviderStatus.AVAILABLE
            )
            registry.register(cache_provider)
        backup = MagicMock(spec=AlphaProvider)
        backup.name = "simple"
        backup.priority = 100
        backup.max_staleness_days = 2
        backup.health_check.return_value = AlphaProviderStatus.AVAILABLE
        backup.supports.return_value = True
        backup.get_stock_scores.return_value = AlphaResult(
            success=fresh_backup,
            source="simple",
            timestamp=today.isoformat(),
            status="available" if fresh_backup else "unavailable",
            staleness_days=0,
            scores=(
                [StockScore(target, 0.8, 1, {}, "simple", 0.9, asof_date=today)]
                if fresh_backup
                else []
            ),
        )
        registry.register(backup)
        service = object.__new__(AlphaService)
        service._registry = registry
        provider = CompositeFeatureProvider()
        provider._alpha_service = service.get_stock_scores
        for method in (
            "get_regime",
            "get_policy_level",
            "check_beta_gate",
            "get_sentiment_score",
            "get_flow_score",
            "get_technical_score",
            "get_fundamental_score",
        ):
            monkeypatch.setattr(provider, method, getattr(setup["feature_provider"], method))
        setup["use_case"].feature_provider = provider

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(account_id="account_001", security_codes=[target])
        )

        assert response.success is True
        recommendation = response.recommendations[0]
        snapshot = setup["recommendation_repo"]._snapshots[recommendation.feature_snapshot_id]
        backup.get_stock_scores.assert_called_once()
        candidate_read.assert_not_called()
        if fresh_backup:
            assert recommendation.side == "BUY"
            assert recommendation.confidence > 0.0
            assert snapshot.alpha_model_score == pytest.approx(0.9)
            assert "alpha" not in snapshot.extra_features["feature_freshness"]
        else:
            assert recommendation.side == "HOLD"
            assert recommendation.confidence == 0.0
            assert snapshot.alpha_model_score == 0.5
            assert "FEATURE_BLOCKED_ALPHA_CACHE_SOURCE_DATE_CONFLICT" in recommendation.reason_codes
            assert snapshot.extra_features["feature_freshness"]["alpha"] == {
                "observed_at": None,
                "freshness_status": "unknown",
                "must_not_use_for_decision": True,
                "blocked_reason": "alpha_cache_source_date_conflict",
            }

    @pytest.mark.parametrize(
        ("status", "age_days", "older_open", "expected_score"),
        [
            ("ACTIONABLE", 31, False, 0.5),
            ("WATCH", 31, False, 0.5),
            ("CANDIDATE", 31, False, 0.5),
            ("EXECUTED", 1, False, 0.5),
            ("CANCELLED", 1, False, 0.5),
            ("ACTIONABLE", 30, False, 0.95),
            ("WATCH", 1, False, 0.95),
            ("CANDIDATE", 1, False, 0.95),
            ("ACTIONABLE", 1, False, 0.95),
            ("ACTIONABLE", 1, True, 0.95),
            ("CANCELLED", 1, True, 0.82),
            ("ACTIONABLE", 31, True, 0.82),
        ],
    )
    def test_generate_excludes_closed_candidate_fallback_scores(
        self,
        setup: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        status: str,
        age_days: int,
        older_open: bool,
        expected_score: float,
    ) -> None:
        """Current scoring cannot reuse closed candidates or manufacture source freshness."""
        target, complete = "000001.SZ", "000002.SZ"
        today = date.today()

        def _model(
            code: str, state: str, age: int, confidence: float, horizon: int = 30
        ) -> AlphaCandidateModel:
            created_day = today - timedelta(days=age)
            return AlphaCandidateModel(
                candidate_id=f"candidate-{code}-{age}",
                trigger_id=f"trigger-{code}-{age}",
                asset_code=code,
                asset_class="EQUITY",
                direction="LONG",
                strength="STRONG",
                confidence=confidence,
                status=state,
                created_at=datetime(
                    created_day.year, created_day.month, created_day.day, 4, tzinfo=UTC
                ),
                time_horizon=horizon,
            )

        rows = [_model(target, status, age_days, 0.95), _model(complete, "ACTIONABLE", 1, 0.82)]
        if older_open:
            rows.append(_model(target, "CANDIDATE", 32, 0.82, 60))
        queried: list[str] = []

        def _filter(*, asset_code: str) -> SimpleNamespace:
            queried.append(asset_code)

            def _order_by(field: str) -> list[AlphaCandidateModel]:
                assert field == "-created_at"
                return sorted(
                    [row for row in rows if row.asset_code == asset_code],
                    key=lambda row: row.created_at,
                    reverse=True,
                )

            return SimpleNamespace(order_by=_order_by)

        monkeypatch.setattr(AlphaCandidateModel.objects, "filter", _filter)
        monkeypatch.setattr(
            "apps.alpha.application.services.load_runtime_alpha_fixed_provider", lambda: ""
        )
        registry = AlphaProviderRegistry()
        external = MagicMock(spec=AlphaProvider)
        external.name = "simple"
        external.priority = 1
        external.max_staleness_days = 2
        external.health_check.return_value = AlphaProviderStatus.AVAILABLE
        external.supports.return_value = True
        external.get_stock_scores.return_value = AlphaResult(
            success=True,
            source="simple",
            timestamp=today.isoformat(),
            status="available",
            staleness_days=0,
            scores=[StockScore("600000.SH", 0.8, 1, {}, "simple", 0.9, asof_date=today)],
        )
        registry.register(external)
        service = object.__new__(AlphaService)
        service._registry = registry
        provider = CompositeFeatureProvider()
        provider._alpha_service = service.get_stock_scores
        for method in (
            "get_regime",
            "get_policy_level",
            "check_beta_gate",
            "get_sentiment_score",
            "get_flow_score",
            "get_technical_score",
            "get_fundamental_score",
        ):
            monkeypatch.setattr(provider, method, getattr(setup["feature_provider"], method))
        setup["use_case"].feature_provider = provider

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001", security_codes=[target, complete]
            )
        )

        assert response.success is True
        recommendations = {row.security_code: row for row in response.recommendations}
        for code, score in ((target, expected_score), (complete, 0.82)):
            recommendation = recommendations[code]
            snapshot = setup["recommendation_repo"]._snapshots[recommendation.feature_snapshot_id]
            assert snapshot.alpha_model_score == pytest.approx(score)
            # HOLD follows this test's existing thresholds, not a new global hard gate.
            assert recommendation.side == ("HOLD" if score == 0.5 else "BUY")
            assert "alpha" not in snapshot.extra_features["feature_freshness"]
        assert queried == [target, complete]

    @pytest.mark.parametrize(
        ("roe_case", "config_value", "config_type", "confidence", "status", "reason"),
        [
            ("missing", "0.10", "float", 0.4, "applied", "roe_missing"),
            ("null", "0.10", "float", 0.4, "applied", "roe_missing"),
            ("invalid", "0.10", "float", 0.4, "applied", "roe_invalid"),
            ("boolean", "0.10", "float", 0.4, "applied", "roe_invalid"),
            ("nonfinite", "0.10", "float", 0.4, "applied", "roe_nonfinite"),
            ("zero", "0.10", "float", 0.5, "not_required", None),
            ("negative", "0.10", "float", 0.5, "not_required", None),
            ("missing", "0.20", "float", 0.3, "applied", "roe_missing"),
            ("missing", "0.80", "float", 0.0, "applied", "roe_missing"),
            ("missing", None, "float", 0.5, "not_applied_missing_config", "roe_missing"),
            ("missing", "bad", "float", 0.5, "not_applied_invalid_config", "roe_missing"),
            ("missing", "NaN", "float", 0.5, "not_applied_invalid_config", "roe_missing"),
            ("missing", "0.10", "str", 0.5, "not_applied_invalid_config", "roe_missing"),
            ("missing", "true", "bool", 0.5, "not_applied_invalid_config", "roe_missing"),
            ("missing", "-0.10", "float", 0.5, "not_applied_invalid_config", "roe_missing"),
            ("missing", "1.10", "float", 0.5, "not_applied_invalid_config", "roe_missing"),
        ],
    )
    def test_generate_applies_roe_missing_penalty_through_real_owner_chain(
        self,
        setup: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        record_property: Callable[[str, object], None],
        roe_case: str,
        config_value: str | None,
        config_type: str,
        confidence: float,
        status: str,
        reason: str | None,
    ) -> None:
        """Latest-period quality and actual parameters reach snapshots and user explanations."""
        affected, complete = "000001.SZ", "000002.SZ"
        observed = "2026-08-03T01:00:00+00:00"
        valuation_observed = "2026-08-04T02:00:00+00:00"
        raw_values: dict[str, object] = {
            "null": None,
            "invalid": "not-a-number",
            "boolean": True,
            "nonfinite": float("nan"),
            "zero": 0.0,
            "negative": -5.0,
        }

        def _payloads(codes: list[str], **options: object) -> dict[str, object]:
            result: dict[str, object] = {}
            for code in codes:
                rows: list[dict[str, object]] = [
                    {"period_end": "2026-03-31", "metric_code": "roe", "value": 30.0},
                    {"period_end": "2026-06-30", "metric_code": "debt_ratio", "value": 45.0},
                ]
                if code == complete or roe_case != "missing":
                    rows.append(
                        {
                            "period_end": "2026-06-30",
                            "metric_code": "roe",
                            "value": 10.0 if code == complete else raw_values[roe_case],
                        }
                    )
                result[code] = {
                    name: {
                        "publication_id": f"pub-{name}",
                        "freshness_status": "fresh",
                        "observed_at": observed if name == "financial" else valuation_observed,
                        "must_not_use_for_decision": False,
                        "blocked_reason": "",
                        "rows": values,
                    }
                    for name, values in {
                        "financial": rows,
                        "valuation": [
                            {
                                "val_date": "2026-08-04",
                                "pe_ttm": 10.0,
                                "observed_at": valuation_observed,
                            }
                        ],
                    }.items()
                    if options.get(f"include_{name}", True)
                }
            return result

        monkeypatch.setattr(
            equity_query_services,
            "get_equity_stock_repository",
            lambda: SimpleNamespace(
                get_stock_master_rows=lambda codes: {
                    code: {"asset_code": code, "name": code, "market": "SZ"} for code in codes
                }
            ),
        )
        monkeypatch.setattr(
            equity_query_services, "get_published_equity_context_payloads", _payloads
        )
        configs = (
            [
                ModelParamConfig(
                    config_id="missing-penalty-config",
                    param_key="missing_feature_confidence_penalty",
                    param_value=config_value,
                    param_type=config_type,
                )
            ]
            if config_value is not None
            else []
        )
        setup["use_case"].param_use_case = GetModelParamsUseCase(
            SimpleNamespace(
                get_all_params=lambda env: configs,
                get_param=lambda key, env: next(
                    (config for config in configs if config.param_key == key), None
                ),
            )
        )

        def _save_snapshot(snapshot: DecisionFeatureSnapshot) -> DecisionFeatureSnapshot:
            stored = deepcopy(snapshot)
            setup["recommendation_repo"]._snapshots[stored.snapshot_id] = stored
            return stored

        monkeypatch.setattr(setup["recommendation_repo"], "save_feature_snapshot", _save_snapshot)
        provider = CompositeFeatureProvider()
        for method in (
            "get_regime",
            "get_policy_level",
            "check_beta_gate",
            "get_sentiment_score",
            "get_flow_score",
            "get_technical_score",
            "get_alpha_model_score",
        ):
            monkeypatch.setattr(provider, method, getattr(setup["feature_provider"], method))
        setup["use_case"].feature_provider = provider

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001", security_codes=[affected, complete]
            )
        )
        assert response.success is True
        recommendations = {row.security_code: row for row in response.recommendations}
        assert recommendations[affected].side == "BUY"
        assert recommendations[complete].side == "BUY"
        assert recommendations[complete].confidence == pytest.approx(0.5)
        recommendation = recommendations[affected]
        public_result = UnifiedRecommendationDTO.from_domain(recommendation).to_dict()
        assert public_result["confidence"] == pytest.approx(confidence)
        assert public_result["human_rationale"] == recommendation.human_rationale
        record_property("recommendation_payload", json.dumps(public_result, ensure_ascii=False))
        snapshot = setup["recommendation_repo"]._snapshots[recommendation.feature_snapshot_id]
        assert recommendation.confidence == pytest.approx(confidence)
        contract = snapshot.extra_features["feature_freshness"]["fundamental"]
        assert contract["must_not_use_for_decision"] is False
        if reason is None:
            assert not contract.get("missing_inputs")
            assert snapshot.fundamental_score == 0.0
        else:
            assert snapshot.fundamental_score == 0.5
            assert contract["missing_inputs"] == [
                {
                    "input_key": "roe",
                    "reason": reason,
                    "period_end": "2026-06-30",
                    "observed_at": observed,
                }
            ]
            adjustment = snapshot.extra_features["confidence_adjustment"]
            assert adjustment["status"] == status
            assert adjustment["base_confidence"] == pytest.approx(0.5)
            assert adjustment["adjusted_confidence"] == pytest.approx(confidence)
            assert adjustment["missing_categories"] == ["fundamental"]
            assert adjustment["deduction"] == pytest.approx(0.5 - confidence)
            assert "ROE" in recommendation.human_rationale
            expected_explanation = {
                "roe_missing": "ROE 缺失",
                "roe_invalid": "ROE 值无效",
                "roe_nonfinite": "ROE 为非有限数",
            }[reason]
            assert expected_explanation in recommendation.human_rationale
            assert "中性" in recommendation.human_rationale
            assert ("未应用" in recommendation.human_rationale) is status.startswith("not_applied")
            assert recommendation.reason_codes

    @pytest.mark.parametrize(
        ("second_category", "hard_block", "penalty", "expected"),
        [
            (False, False, "0.10", 0.4),
            (True, False, "0.10", 0.3),
            (True, False, "0.80", 0.0),
            (True, True, "0.10", 0.0),
        ],
    )
    def test_missing_confidence_counts_categories_once_and_preserves_hard_blocks(
        self,
        setup: dict[str, Any],
        second_category: bool,
        hard_block: bool,
        penalty: str,
        expected: float,
        record_property: Callable[[str, object], None],
    ) -> None:
        """Several missing inputs in one category are one penalty, and hard blocks stay prior."""
        missing_input = {
            "input_key": "roe",
            "reason": "roe_missing",
            "period_end": None,
            "observed_at": None,
        }
        contract = {
            "observed_at": None,
            "freshness_status": "fresh",
            "must_not_use_for_decision": hard_block,
            "blocked_reason": "source_unavailable" if hard_block else "",
            "missing_inputs": [missing_input, dict(missing_input)],
        }
        contracts = {"fundamental": contract}
        if second_category:
            contracts["technical"] = {
                **contract,
                "must_not_use_for_decision": False,
                "blocked_reason": "",
                "missing_inputs": [missing_input],
            }
        setup["feature_provider"].set_feature_contracts("000001.SZ", contracts)
        config = ModelParamConfig(
            "category-penalty", "missing_feature_confidence_penalty", penalty, param_type="float"
        )
        setup["use_case"].param_use_case = GetModelParamsUseCase(
            SimpleNamespace(get_all_params=lambda env: [config], get_param=lambda key, env: config)
        )
        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(account_id="account_001", security_codes=["000001.SZ"])
        )
        assert response.success is True
        recommendation = response.recommendations[0]
        assert recommendation.confidence == pytest.approx(expected)
        assert recommendation.side == ("HOLD" if hard_block else "BUY")
        record_property(
            "recommendation_payload",
            json.dumps(
                UnifiedRecommendationDTO.from_domain(recommendation).to_dict(), ensure_ascii=False
            ),
        )
        snapshot = setup["recommendation_repo"]._snapshots[recommendation.feature_snapshot_id]
        adjustment = snapshot.extra_features.get("confidence_adjustment", {})
        if hard_block:
            assert adjustment.get("status") != "applied"
            assert "FEATURE_BLOCKED_SOURCE_UNAVAILABLE" in recommendation.reason_codes
        else:
            assert adjustment["status"] == "applied"
            assert adjustment["missing_categories"] == sorted(contracts)
            assert adjustment["deduction"] == pytest.approx(0.5 - expected)

    def test_generate_holds_when_sentiment_feature_is_unavailable(self, setup):
        """过期舆情即使其他分数足够高，也不得形成方向性推荐。"""
        setup["feature_provider"].set_scores(
            "000001.SZ",
            {
                "sentiment": 0.5,
                "flow": 0.8,
                "technical": 0.8,
                "fundamental": 0.8,
                "alpha": 0.9,
            },
        )
        setup["feature_provider"].set_feature_contracts(
            "000001.SZ",
            {
                "sentiment": {
                    "observed_at": "2026-07-27",
                    "freshness_status": "stale",
                    "must_not_use_for_decision": True,
                    "blocked_reason": "sentiment_index_stale",
                }
            },
        )

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        recommendation = response.recommendations[0]
        assert recommendation.side == "HOLD"
        assert "FEATURE_BLOCKED_SENTIMENT_INDEX_STALE" in recommendation.reason_codes
        assert "sentiment_index_stale" in recommendation.human_rationale
        snapshot = next(iter(setup["recommendation_repo"]._snapshots.values()))
        assert snapshot.extra_features["feature_freshness"]["sentiment"] == {
            "observed_at": "2026-07-27",
            "freshness_status": "stale",
            "must_not_use_for_decision": True,
            "blocked_reason": "sentiment_index_stale",
        }

    def test_generate_collects_technical_freshness_after_feature_read(self, setup, monkeypatch):
        """技术/基本面取值后才读取 freshness，阻断不能被顺序丢失。"""

        feature_provider = setup["feature_provider"]
        feature_provider.set_scores(
            "000001.SZ",
            {"technical": 0.8, "fundamental": 0.8, "alpha": 0.9},
        )

        def blocked_technical_score(security_code: str) -> float:
            feature_provider.set_feature_contracts(
                security_code,
                {
                    "technical": {
                        "observed_at": None,
                        "freshness_status": "missing",
                        "must_not_use_for_decision": True,
                        "blocked_reason": "canonical_publication_missing",
                    }
                },
            )
            return 0.8

        monkeypatch.setattr(feature_provider, "get_technical_score", blocked_technical_score)

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        recommendation = response.recommendations[0]
        assert recommendation.side == "HOLD"
        assert "FEATURE_BLOCKED_CANONICAL_PUBLICATION_MISSING" in recommendation.reason_codes
        snapshot = next(iter(setup["recommendation_repo"]._snapshots.values()))
        assert (
            snapshot.extra_features["feature_freshness"]["technical"]["must_not_use_for_decision"]
            is True
        )

    def test_generate_holds_when_regime_is_blocked(self, setup):
        """Regime resolver 的阻断状态必须贯穿快照与推荐。"""
        setup["feature_provider"]._regime = {
            "regime": "",
            "confidence": 0.0,
            "observed_at": None,
            "freshness_status": "stale",
            "must_not_use_for_decision": True,
            "blocked_reason": "regime_inputs_stale",
        }
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.9})

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        recommendation = response.recommendations[0]
        assert recommendation.side == "HOLD"
        assert "FEATURE_BLOCKED_REGIME_INPUTS_STALE" in recommendation.reason_codes
        snapshot = next(iter(setup["recommendation_repo"]._snapshots.values()))
        assert (
            snapshot.extra_features["feature_freshness"]["regime"]["must_not_use_for_decision"]
            is True
        )

    def test_generate_with_valuation_data(self, setup):
        """测试包含估值数据"""
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.85})
        setup["valuation_provider"].set_valuation(
            "000001.SZ",
            {
                "fair_value": 20.00,
                "entry_price_low": 19.00,
                "entry_price_high": 19.50,
                "target_price_low": 25.00,
                "target_price_high": 28.00,
                "stop_loss_price": 17.00,
            },
        )

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        rec = response.recommendations[0]
        assert rec.fair_value == Decimal("20.00")
        assert rec.entry_price_low == Decimal("19.00")
        assert rec.stop_loss_price == Decimal("17.00")

    def test_generate_with_sources(self, setup):
        """测试包含来源信号和候选"""
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.85})
        setup["signal_provider"].add_signal("sig_001", "000001.SZ")
        setup["signal_provider"].add_signal("sig_002", "000001.SZ")
        setup["candidate_provider"].add_candidate("cand_001", "account_001", "000001.SZ")

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        rec = response.recommendations[0]
        assert "sig_001" in rec.source_signal_ids
        assert "sig_002" in rec.source_signal_ids
        assert "cand_001" in rec.source_candidate_ids

    def test_generate_determines_buy_side(self, setup):
        """测试确定 BUY 方向"""
        # 高分数应该生成 BUY
        setup["feature_provider"].set_scores(
            "000001.SZ",
            {
                "sentiment": 0.80,
                "flow": 0.75,
                "technical": 0.82,
                "fundamental": 0.85,
                "alpha": 0.90,  # 高 Alpha
            },
        )

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        rec = response.recommendations[0]
        # 高分数应该是 BUY
        assert rec.side == "BUY"

    def test_generate_saves_feature_snapshot(self, setup):
        """测试保存特征快照"""
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.85})

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(
                account_id="account_001",
                security_codes=["000001.SZ"],
            )
        )

        assert response.success is True
        # 验证快照已保存
        assert len(setup["recommendation_repo"]._snapshots) == 1

    def test_generate_includes_held_positions_when_candidates_absent(self, setup):
        """测试未传 security_codes 时，会覆盖当前持仓。"""
        setup["position_snapshot_provider"].set_positions(
            "account_001",
            [{"asset_code": "600001.SH", "quantity": 1000}],
        )
        setup["feature_provider"].set_scores("600001.SH", {"alpha": 0.55})

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(account_id="account_001")
        )

        assert response.success is True
        assert len(response.recommendations) == 1
        assert response.recommendations[0].security_code == "600001.SH"
        assert response.recommendations[0].side == "HOLD"

    def test_generate_marks_held_position_sell_when_alpha_decays(self, setup):
        """测试已持仓证券 alpha 衰减后会输出 SELL。"""
        setup["position_snapshot_provider"].set_positions(
            "account_001",
            [{"asset_code": "600002.SH", "quantity": 800}],
        )
        setup["feature_provider"].set_scores(
            "600002.SH",
            {
                "sentiment": 0.45,
                "flow": 0.40,
                "technical": 0.42,
                "fundamental": 0.50,
                "alpha": 0.20,
            },
        )

        response = setup["use_case"].execute(
            GenerateRecommendationsRequest(account_id="account_001")
        )

        assert response.success is True
        assert len(response.recommendations) == 1
        assert response.recommendations[0].security_code == "600002.SH"
        assert response.recommendations[0].side == "SELL"


class TestGetUnifiedRecommendationsUseCase:
    """测试获取统一推荐用例"""

    def test_get_recommendations(self):
        """测试获取推荐列表"""
        repo = MockRecommendationRepository()
        repo.save(
            UnifiedRecommendation(
                recommendation_id="urec_001",
                account_id="account_001",
                security_code="000001.SZ",
                side="BUY",
                status=RecommendationStatus.NEW,
            )
        )
        repo.save(
            UnifiedRecommendation(
                recommendation_id="urec_002",
                account_id="account_001",
                security_code="000002.SZ",
                side="BUY",
                status=RecommendationStatus.APPROVED,
            )
        )

        use_case = GetUnifiedRecommendationsUseCase(repo)
        response = use_case.execute(
            GetRecommendationsRequest(
                account_id="account_001",
            )
        )

        assert response.success is True
        assert len(response.recommendations) == 2
        assert response.total_count == 2

    def test_get_recommendations_by_status(self):
        """测试按状态获取推荐"""
        repo = MockRecommendationRepository()
        repo.save(
            UnifiedRecommendation(
                recommendation_id="urec_001",
                account_id="account_001",
                security_code="000001.SZ",
                side="BUY",
                status=RecommendationStatus.NEW,
            )
        )
        repo.save(
            UnifiedRecommendation(
                recommendation_id="urec_002",
                account_id="account_001",
                security_code="000002.SZ",
                side="BUY",
                status=RecommendationStatus.APPROVED,
            )
        )

        use_case = GetUnifiedRecommendationsUseCase(repo)
        response = use_case.execute(
            GetRecommendationsRequest(
                account_id="account_001",
                status="APPROVED",
            )
        )

        assert response.success is True
        assert len(response.recommendations) == 1
        assert response.recommendations[0].status == RecommendationStatus.APPROVED


class TestGetConflictsUseCase:
    """测试获取冲突用例"""

    def test_get_conflicts(self):
        """测试获取冲突列表"""
        repo = MockRecommendationRepository()

        # 保存冲突推荐
        conflict_rec = UnifiedRecommendation(
            recommendation_id="urec_conflict",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            status=RecommendationStatus.CONFLICT,
        )
        repo.save(conflict_rec)
        repo.mark_as_conflict("urec_conflict")

        # 保存非冲突推荐
        repo.save(
            UnifiedRecommendation(
                recommendation_id="urec_normal",
                account_id="account_001",
                security_code="000002.SZ",
                side="BUY",
                status=RecommendationStatus.NEW,
            )
        )

        use_case = GetConflictsUseCase(repo)
        response = use_case.execute(
            GetConflictsRequest(
                account_id="account_001",
            )
        )

        assert response.success is True
        assert len(response.conflicts) == 1
        assert response.conflicts[0].recommendation_id == "urec_conflict"
