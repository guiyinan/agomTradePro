"""
Beta Gate DRF Views

硬闸门过滤的 API 视图。

简化版本，避免复杂的依赖。
"""

import logging
from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..infrastructure.repositories import get_config_repository


logger = logging.getLogger(__name__)


class BetaGateVersionCompareAPIView(APIView):
    """
    Beta Gate 版本对比 API

    处理版本对比请求。
    """

    def get(self, request) -> Response:
        """
        获取两个版本的差异

        GET /api/beta-gate/version/compare/?version1=1&version2=2
        """
        try:
            version1_id = request.query_params.get("version1")
            version2_id = request.query_params.get("version2")

            if not version1_id or not version2_id:
                # 返回最新10个版本的列表
                from ..infrastructure.models import GateConfigModel
                configs = list(GateConfigModel.objects.all().order_by('-version')[:10])

                results = []
                for config in configs:
                    results.append({
                        "config_id": config.config_id,
                        "version": config.version,
                        "risk_profile": config.risk_profile,
                        "is_active": config.is_active,
                        "effective_date": config.effective_date.isoformat() if config.effective_date else None,
                        "expires_at": config.expires_at.isoformat() if config.expires_at else None,
                        "created_at": config.created_at.isoformat() if config.created_at else None,
                    })

                return Response({
                    "success": True,
                    "results": results,
                })

            # 对比两个版本
            from ..infrastructure.models import GateConfigModel

            try:
                config1 = GateConfigModel.objects.filter(version=version1_id).first()
                config2 = GateConfigModel.objects.filter(version=version2_id).first()
            except ValueError:
                return Response(
                    {"success": False, "error": "Invalid version number"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not config1 or not config2:
                missing = []
                if not config1:
                    missing.append(f"Version {version1_id}")
                if not config2:
                    missing.append(f"Version {version2_id}")
                return Response(
                    {"success": False, "error": f"Versions not found: {', '.join(missing)}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 解析约束
            def parse_constraints(constraints_str):
                try:
                    import json
                    if isinstance(constraints_str, str):
                        return json.loads(constraints_str)
                    return constraints_str or {}
                except:
                    return {}

            # 构建对比结果
            def build_config_dict(config):
                return {
                    "config_id": config.config_id,
                    "version": config.version,
                    "risk_profile": config.risk_profile,
                    "is_active": config.is_active,
                    "effective_date": config.effective_date.isoformat() if config.effective_date else None,
                    "expires_at": config.expires_at.isoformat() if config.expires_at else None,
                    "regime_constraints": parse_constraints(config.regime_constraints),
                    "policy_constraints": parse_constraints(config.policy_constraints),
                    "portfolio_constraints": parse_constraints(config.portfolio_constraints),
                }

            config1_dict = build_config_dict(config1)
            config2_dict = build_config_dict(config2)

            # 计算差异
            differences = self._compare_configs(config1_dict, config2_dict)

            return Response({
                "success": True,
                "config1": config1_dict,
                "config2": config2_dict,
                "differences": differences,
            })

        except Exception as e:
            logger.error(f"Failed to compare versions: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _compare_configs(self, config1, config2):
        """对比两个配置，返回差异列表"""
        differences = []
        fields = [
            "risk_profile", "is_active", "effective_date", "expires_at",
            "regime_constraints", "policy_constraints", "portfolio_constraints"
        ]

        for field in fields:
            val1 = config1.get(field)
            val2 = config2.get(field)

            if val1 != val2:
                differences.append({
                    "field": field,
                    "config1": val1,
                    "config2": val2,
                })

        return differences


class RollbackConfigView(APIView):
    """
    回滚配置 API

    POST /api/beta-gate/config/rollback/
    """

    def post(self, request) -> Response:
        """
        回滚到指定版本

        POST /api/beta-gate/config/rollback/
        {
            "version": 2
        }
        """
        try:
            import json
            from ..infrastructure.models import GateConfigModel

            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            target_version = int(data.get("version"))

            # 获取目标版本配置
            try:
                target_config = GateConfigModel.objects.filter(version=target_version).first()
            except ValueError:
                return Response(
                    {"success": False, "error": "Invalid version number"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not target_config:
                return Response(
                    {"success": False, "error": f"Version {target_version} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 将当前激活的配置设置为非激活
            GateConfigModel.objects.filter(is_active=True).update(is_active=False)

            # 激活目标版本
            target_config.is_active = True
            target_config.effective_date = timezone.now().date()
            target_config.save()

            return Response({
                "success": True,
                "message": f"已回滚到版本 {target_version}",
                "config_id": target_config.config_id,
            })

        except Exception as e:
            logger.error(f"Failed to rollback config: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== Template Views ==========


def beta_gate_test_view(request):
    """
    Beta Gate 资产测试工具页面

    允许用户快速测试特定资产在当前配置下是否能通过 Beta Gate。
    """
    try:
        from ..infrastructure.models import GateConfigModel, GateDecisionModel
        from django.utils import timezone

        # 获取当前配置
        try:
            active_config = GateConfigModel.objects.filter(is_active=True).first()
        except Exception as e:
            logger.warning(f"Failed to query active config: {e}")
            active_config = None

        # 获取当前 Regime
        current_regime = None
        try:
            from apps.regime.application.use_cases import GetCurrentRegimeUseCase
            from apps.regime.infrastructure.repositories import get_regime_repository
            regime_use_case = GetCurrentRegimeUseCase(get_regime_repository())
            regime_response = regime_use_case.execute()
            if regime_response.success and regime_response.regime_state:
                current_regime = regime_response.regime_state
        except Exception as e:
            logger.warning(f"Failed to get current regime: {e}")

        # 获取当前 Policy
        current_policy = None
        try:
            from apps.policy.application.use_cases import GetCurrentPolicyUseCase
            from apps.policy.infrastructure.repositories import get_policy_repository
            policy_use_case = GetCurrentPolicyUseCase(get_policy_repository())
            policy_response = policy_use_case.execute()
            if policy_response.success and policy_response.policy_level:
                current_policy = policy_response.policy_level
        except Exception as e:
            logger.warning(f"Failed to get current policy: {e}")

        # 获取最近测试记录
        recent_tests = []
        try:
            recent_tests = list(GateDecisionModel.objects.all().order_by('-evaluated_at')[:10])
        except Exception as e:
            logger.warning(f"Failed to query recent tests: {e}")
            recent_tests = []

        # 获取所有资产类别
        all_asset_classes = [
            "a_股票", "a_债券", "a_商品", "a_现金",
            "港股", "美股", "黄金", "原油"
        ]

        context = {
            "active_config": active_config,
            "current_regime": current_regime,
            "current_policy": current_policy,
            "recent_tests": recent_tests,
            "all_asset_classes": all_asset_classes,
            "page_title": "资产测试工具",
            "page_description": "测试资产在当前 Beta Gate 配置下是否能通过",
        }

        return render(request, "beta_gate/test_asset.html", context)

    except Exception as e:
        logger.error(f"Failed to load beta gate test page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "资产测试工具",
        }
        return render(request, "beta_gate/test_asset.html", context, status=500)


def beta_gate_version_view(request):
    """
    Beta Gate 版本对比页面

    显示配置历史版本，支持版本对比和回滚。
    """
    try:
        from ..infrastructure.models import GateConfigModel

        # 获取所有版本，按版本号排序
        all_configs = list(GateConfigModel.objects.all().order_by('-version'))

        # 按风险画像分组
        configs_by_profile = {}
        for config in all_configs:
            profile = config.risk_profile
            if profile not in configs_by_profile:
                configs_by_profile[profile] = []
            configs_by_profile[profile].append(config)

        context = {
            "all_configs": all_configs,
            "configs_by_profile": configs_by_profile,
            "page_title": "配置版本对比",
            "page_description": "查看和对比 Beta Gate 配置历史版本",
        }

        return render(request, "beta_gate/version_compare.html", context)

    except Exception as e:
        logger.error(f"Failed to load beta gate version page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "配置版本对比",
        }
        return render(request, "beta_gate/version_compare.html", context, status=500)
    try:
        from ..infrastructure.models import GateConfigModel, GateDecisionModel
        from django.utils import timezone

        # 获取当前配置
        try:
            active_config = GateConfigModel.objects.filter(is_active=True).first()
        except Exception as e:
            logger.warning(f"Failed to query active config: {e}")
            active_config = None

        # 获取当前 Regime
        current_regime = None
        try:
            from apps.regime.application.use_cases import GetCurrentRegimeUseCase
            from apps.regime.infrastructure.repositories import get_regime_repository
            regime_use_case = GetCurrentRegimeUseCase(get_regime_repository())
            regime_response = regime_use_case.execute()
            if regime_response.success and regime_response.regime_state:
                current_regime = regime_response.regime_state
        except Exception as e:
            logger.warning(f"Failed to get current regime: {e}")

        # 获取当前 Policy
        current_policy = None
        try:
            from apps.policy.application.use_cases import GetCurrentPolicyUseCase
            from apps.policy.infrastructure.repositories import get_policy_repository
            policy_use_case = GetCurrentPolicyUseCase(get_policy_repository())
            policy_response = policy_use_case.execute()
            if policy_response.success and policy_response.policy_level:
                current_policy = policy_response.policy_level
        except Exception as e:
            logger.warning(f"Failed to get current policy: {e}")

        # 获取最近测试记录
        recent_tests = []
        try:
            recent_tests = list(GateDecisionModel.objects.all().order_by('-evaluated_at')[:10])
        except Exception as e:
            logger.warning(f"Failed to query recent tests: {e}")

        # 获取所有资产类别
        all_asset_classes = [
            "a_股票", "a_债券", "a_商品", "a_现金",
            "港股", "美股", "黄金", "原油"
        ]

        context = {
            "active_config": active_config,
            "current_regime": current_regime,
            "current_policy": current_policy,
            "recent_tests": recent_tests,
            "all_asset_classes": all_asset_classes,
            "page_title": "资产测试工具",
            "page_description": "测试资产在当前 Beta Gate 配置下是否能通过",
        }

        return render(request, "beta_gate/test_asset.html", context)

    except Exception as e:
        logger.error(f"Failed to load beta gate test page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "资产测试工具",
        }
        return render(request, "beta_gate/test_asset.html", context, status=500)


class BetaGateTestAPIView(APIView):
    """
    资产测试 API

    处理单个或批量资产测试请求。
    """

    def post(self, request) -> Response:
        """
        测试单个或多个资产

        POST /api/beta-gate/test/
        {
            "asset_codes": ["000001.SH", "000300.SH"],
            "asset_class": "a_股票"
        }
        """
        try:
            import json
            from ..application.use_cases import EvaluateBatchUseCase, EvaluateBatchRequest
            from ..domain.entities import RiskProfile
            from ..infrastructure.repositories import get_config_repository

            # 解析请求
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            asset_codes = data.get("asset_codes", [])
            asset_class = data.get("asset_class", "a_股票")

            if not asset_codes:
                return Response(
                    {"success": False, "error": "请提供资产代码"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 获取当前环境信息
            current_regime = data.get("current_regime", "Recovery")
            regime_confidence = float(data.get("regime_confidence", 0.5))
            policy_level = int(data.get("policy_level", 0))
            risk_profile = RiskProfile(data.get("risk_profile", "BALANCED"))

            # 构建资产列表
            assets = [(code, asset_class) for code in asset_codes]

            # 创建配置选择器
            class SimpleConfigSelector:
                def __init__(self, config_repo):
                    self.config_repo = config_repo

                def get_config(self, risk_profile):
                    configs = self.config_repo.get_all_active()
                    if configs:
                        return configs[0]
                    # 返回默认配置
                    from ..domain.entities import GateConfig, RegimeConstraint, PolicyConstraint, PortfolioConstraint
                    return GateConfig(
                        config_id="default",
                        version=1,
                        is_active=True,
                        is_valid=True,
                        risk_profile=RiskProfile.BALANCED,
                        regime_constraint=RegimeConstraint(
                            current_regime="Recovery",
                            confidence=0.5,
                            allowed_asset_classes=all_asset_classes,
                        ),
                        policy_constraint=PolicyConstraint(
                            current_level=0,
                            max_risk_exposure=100,
                            hard_exclusions=[],
                        ),
                        portfolio_constraint=PortfolioConstraint(
                            max_positions=10,
                            max_single_position_weight=20,
                            max_concentration_ratio=60,
                        ),
                    )

            config_selector = SimpleConfigSelector(get_config_repository())

            # 创建用例
            use_case = EvaluateBatchUseCase(config_selector)

            # 构建请求
            eval_request = EvaluateBatchRequest(
                assets=assets,
                current_regime=current_regime,
                regime_confidence=regime_confidence,
                policy_level=policy_level,
                risk_profile=risk_profile,
            )

            # 执行评估
            response = use_case.execute(eval_request)

            if response.success:
                results = []
                for decision in response.decisions:
                    results.append({
                        "asset_code": decision.asset_code,
                        "asset_class": decision.asset_class,
                        "passed": decision.is_passed,
                        "status": decision.status.value,
                        "blocking_reason": decision.blocking_reason if not decision.is_passed else None,
                        "evaluated_at": decision.evaluated_at.isoformat(),
                    })

                return Response({
                    "success": True,
                    "results": results,
                    "summary": response.summary,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            logger.error(f"Failed to test assets: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GateConfigViewSet(viewsets.ViewSet):
    """闸门配置视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_repository = get_config_repository()

    def list(self, request) -> Response:
        """获取所有激活配置"""
        try:
            configs = self.config_repository.get_all_active()
            results = []
            for config in configs:
                results.append({
                    "config_id": config.config_id,
                    "risk_profile": config.risk_profile.value,
                    "version": config.version,
                    "is_active": config.is_active,
                    "regime_constraints": config.regime_constraint.to_dict(),
                    "policy_constraints": config.policy_constraint.to_dict(),
                    "portfolio_constraints": config.portfolio_constraint.to_dict(),
                    "effective_date": config.effective_date.isoformat() if config.effective_date else None,
                    "expires_at": config.expires_at.isoformat() if config.expires_at else None,
                })
            return Response({
                "success": True,
                "count": len(results),
                "results": results,
            })
        except Exception as e:
            logger.error(f"Failed to list configs: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """获取指定配置"""
        try:
            config = self.config_repository.get_by_id(pk)
            if config is None:
                return Response(
                    {"success": False, "error": "Config not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({
                "success": True,
                "result": {
                    "config_id": config.config_id,
                    "risk_profile": config.risk_profile.value,
                    "version": config.version,
                    "is_active": config.is_active,
                    "regime_constraints": config.regime_constraint.to_dict(),
                    "policy_constraints": config.policy_constraint.to_dict(),
                    "portfolio_constraints": config.portfolio_constraint.to_dict(),
                },
            })
        except Exception as e:
            logger.error(f"Failed to retrieve config: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GateDecisionViewSet(viewsets.ViewSet):
    """闸门决策视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from ..infrastructure.repositories import get_decision_repository
        self.decision_repository = get_decision_repository()

    def list(self, request) -> Response:
        """获取决策历史"""
        try:
            days = int(request.query_params.get("days", 30))
            decisions = self.decision_repository.get_recent(days)
            results = []
            for decision in decisions:
                results.append({
                    "decision_id": getattr(decision, "decision_id", ""),
                    "asset_code": decision.asset_code,
                    "asset_class": decision.asset_class,
                    "status": decision.status.value,
                    "current_regime": decision.current_regime,
                    "policy_level": decision.policy_level,
                    "regime_confidence": decision.regime_confidence,
                    "evaluated_at": decision.evaluated_at.isoformat(),
                })
            return Response({
                "success": True,
                "count": len(results),
                "results": results,
            })
        except Exception as e:
            logger.error(f"Failed to list decisions: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """获取指定决策"""
        try:
            decision = self.decision_repository.get_by_id(pk)
            if decision is None:
                return Response(
                    {"success": False, "error": "Decision not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({
                "success": True,
                "result": {
                    "decision_id": getattr(decision, "decision_id", ""),
                    "asset_code": decision.asset_code,
                    "asset_class": decision.asset_class,
                    "status": decision.status.value,
                    "current_regime": decision.current_regime,
                    "policy_level": decision.policy_level,
                    "regime_confidence": decision.regime_confidence,
                    "evaluated_at": decision.evaluated_at.isoformat(),
                },
            })
        except Exception as e:
            logger.error(f"Failed to retrieve decision: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VisibilityUniverseViewSet(viewsets.ViewSet):
    """可见性宇宙视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from ..infrastructure.repositories import get_universe_repository
        self.universe_repository = get_universe_repository()

    def list(self, request) -> Response:
        """获取历史快照"""
        try:
            regime = request.query_params.get("regime", None)
            policy_level = request.query_params.get("policy_level", None)
            limit = int(request.query_params.get("limit", 100))

            snapshots = self.universe_repository.get_history(regime, policy_level, limit)
            return Response({
                "success": True,
                "count": len(snapshots),
                "results": snapshots,
            })
        except Exception as e:
            logger.error(f"Failed to list universe snapshots: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """获取指定快照"""
        try:
            snapshot = self.universe_repository.get_by_id(pk)
            if snapshot is None:
                return Response(
                    {"success": False, "error": "Snapshot not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({
                "success": True,
                "result": snapshot,
            })
        except Exception as e:
            logger.error(f"Failed to retrieve snapshot: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== Template Views ==========


def beta_gate_config_view(request):
    """
    Beta 闸门配置页面

    显示当前 Regime/Policy 下的可见资产类别和硬性排除规则。
    """
    try:
        from ..infrastructure.models import GateConfigModel, GateDecisionModel

        # 获取最新配置（直接查询 ORM，避免 repository 问题）
        try:
            configs = GateConfigModel.objects.filter(is_active=True)[:1]
            active_config = configs[0] if configs else None
        except Exception as e:
            logger.warning(f"Failed to query active configs: {e}")
            active_config = None

        # 获取最近决策
        try:
            recent_decisions = list(GateDecisionModel.objects.all().order_by('-evaluated_at')[:10])
        except Exception as e:
            logger.warning(f"Failed to query recent decisions: {e}")
            recent_decisions = []

        # 构建上下文数据
        context_data = {
            "active_config": None,
            "recent_decisions": recent_decisions,
            "page_title": "Beta 闸门配置",
            "page_description": "基于 Regime 和 Policy 的资产可见性过滤",
        }

        # 如果有配置，构建简化的数据结构供模板使用
        if active_config:
            # 从 JSON 字段提取数据
            regime_constraints = active_config.regime_constraints if isinstance(active_config.regime_constraints, dict) else {}
            policy_constraints = active_config.policy_constraints if isinstance(active_config.policy_constraints, dict) else {}
            portfolio_constraints = active_config.portfolio_constraints if isinstance(active_config.portfolio_constraints, dict) else {}

            # 构建简化的配置对象
            class SimpleConfig:
                def __init__(self, model, regime_c, policy_c, portfolio_c):
                    self.config_id = model.config_id
                    self.risk_profile = model.risk_profile
                    self.version = model.version
                    self.is_active = model.is_active
                    self.effective_date = model.effective_date
                    self.expires_at = model.expires_at
                    # Regime 约束
                    self.regime_constraint = type('obj', (), {
                        'current_regime': regime_c.get('current_regime', '未知'),
                        'confidence': regime_c.get('confidence', 0.5),
                        'allowed_asset_classes': regime_c.get('allowed_asset_classes', []),
                    })()
                    # Policy 约束
                    self.policy_constraint = type('obj', (), {
                        'current_level': policy_c.get('current_level', 0),
                        'max_risk_exposure': policy_c.get('max_risk_exposure', 100),
                        'hard_exclusions': policy_c.get('hard_exclusions', []),
                    })()
                    # 组合约束
                    self.portfolio_constraint = type('obj', (), {
                        'max_positions': portfolio_c.get('max_positions', 10),
                        'max_single_position_weight': portfolio_c.get('max_single_position_weight', 20),
                        'max_concentration_ratio': portfolio_c.get('max_concentration_ratio', 60),
                    })()

            context_data["active_config"] = SimpleConfig(
                active_config,
                regime_constraints,
                policy_constraints,
                portfolio_constraints
            )

        return render(request, "beta_gate/config.html", context_data)

    except Exception as e:
        logger.error(f"Failed to load beta gate config page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "Beta 闸门配置",
        }
        return render(request, "beta_gate/config.html", context, status=500)
