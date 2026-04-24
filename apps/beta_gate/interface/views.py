"""
Beta Gate DRF Views

硬闸门过滤的 API 视图。

简化版本，避免复杂的依赖。
"""

import json
import logging
import re
from dataclasses import replace

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.config_query_service import get_beta_gate_config_query_service
from ..application.repository_provider import (
    get_beta_gate_config_repository,
    get_beta_gate_decision_repository,
    get_beta_gate_universe_repository,
)
from ..domain.entities import RiskProfile, create_gate_config
from .forms import GateConfigForm

logger = logging.getLogger(__name__)


def _activate_gate_config_model(target_config):
    """Atomically switch the active Beta Gate config."""
    with transaction.atomic():
        return get_beta_gate_config_query_service().activate_config(target_config.config_id)


def _save_gate_config_form(form: GateConfigForm):
    """Persist a GateConfig form with single-active semantics."""
    with transaction.atomic():
        return get_beta_gate_config_query_service().save_form_data(form.save(commit=False))


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
            version1_id = request.query_params.get("version1") or request.query_params.get(
                "version_a"
            )
            version2_id = request.query_params.get("version2") or request.query_params.get(
                "version_b"
            )

            if not version1_id or not version2_id:
                # 返回最新10个版本的列表
                results = get_beta_gate_config_query_service().list_recent_versions(limit=10)

                return Response(
                    {
                        "success": True,
                        "results": results,
                    }
                )

            # 对比两个版本
            compare_result = get_beta_gate_config_query_service().compare_versions(
                version1_id,
                version2_id,
            )
            if compare_result is None:
                missing = []
                missing.append(f"Version {version1_id}")
                missing.append(f"Version {version2_id}")
                return Response(
                    {"success": False, "error": f"Versions not found: {', '.join(missing)}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "success": True,
                    "config1": compare_result["config1"],
                    "config2": compare_result["config2"],
                    "differences": compare_result["differences"],
                }
            )

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
            "risk_profile",
            "is_active",
            "effective_date",
            "expires_at",
            "regime_constraints",
            "policy_constraints",
            "portfolio_constraints",
        ]

        for field in fields:
            val1 = config1.get(field)
            val2 = config2.get(field)

            if val1 != val2:
                differences.append(
                    {
                        "field": field,
                        "config1": val1,
                        "config2": val2,
                    }
                )

        return differences


class RollbackConfigView(APIView):
    """
    回滚配置 API

    POST /api/beta-gate/config/rollback/
    """

    def post(self, request, config_id=None) -> Response:
        """
        回滚到指定版本

        POST /api/beta-gate/config/rollback/
        {
            "version": 2
        }
        """
        try:
            import json

            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            config_service = get_beta_gate_config_query_service()
            target_version = data.get("version")
            if target_version is None and config_id:
                target_version = config_service.resolve_version_for_config_id(config_id)
            try:
                target_version = int(target_version)
            except (TypeError, ValueError):
                return Response(
                    {"success": False, "error": "Invalid version number"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 获取目标版本配置
            target_config = config_service.rollback_to_version(target_version)
            if not target_config:
                return Response(
                    {"success": False, "error": f"Version {target_version} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "success": True,
                    "message": f"已回滚到版本 {target_version}",
                    "config_id": target_config.config_id,
                }
            )

        except Exception as e:
            logger.error(f"Failed to rollback config: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BetaGateJsonSuggestAPIView(APIView):
    """根据自然语言建议生成 Beta Gate JSON。"""

    TARGET_CONFIG = {
        "regime": {
            "template": {
                "current_regime": "Recovery",
                "confidence": 0.72,
                "allowed_asset_classes": ["a_股票", "港股", "黄金"],
            },
            "hint": "字段：current_regime(str), confidence(float 0~1), allowed_asset_classes(list[str])",
        },
        "policy": {
            "template": {
                "current_level": 2,
                "max_risk_exposure": 70,
                "hard_exclusions": ["期货", "高杠杆ETF"],
            },
            "hint": "字段：current_level(int), max_risk_exposure(number 百分比), hard_exclusions(list[str])",
        },
        "portfolio": {
            "template": {
                "max_positions": 8,
                "max_single_position_weight": 20,
                "max_concentration_ratio": 55,
            },
            "hint": "字段：max_positions(int), max_single_position_weight(number 百分比), max_concentration_ratio(number 百分比)",
        },
    }

    def post(self, request) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        target = (data.get("target") or "").strip().lower()
        requirement = (data.get("requirement") or "").strip()

        if target not in self.TARGET_CONFIG:
            return Response(
                {"success": False, "error": "target 必须是 regime、policy、portfolio 之一"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not requirement:
            return Response(
                {"success": False, "error": "requirement 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fallback = self.TARGET_CONFIG[target]["template"]
        try:
            from apps.ai_provider.application.chat_completion import generate_chat_completion

            messages_payload = self._build_messages(target=target, requirement=requirement)
            ai_result = generate_chat_completion(
                messages=messages_payload,
                temperature=0.2,
                max_tokens=900,
                user=getattr(request, "user", None),
            )

            if ai_result.get("status") != "success":
                return Response(
                    {
                        "success": True,
                        "fallback": True,
                        "provider_used": ai_result.get("provider_used"),
                        "message": f"AI 生成失败，已返回默认模板: {ai_result.get('error_message')}",
                        "json_object": fallback,
                    }
                )

            parsed = self._parse_json_from_text(ai_result.get("content", ""))
            if not isinstance(parsed, dict):
                return Response(
                    {
                        "success": True,
                        "fallback": True,
                        "provider_used": ai_result.get("provider_used"),
                        "message": "AI 返回内容不是 JSON 对象，已返回默认模板",
                        "json_object": fallback,
                    }
                )

            return Response(
                {
                    "success": True,
                    "fallback": False,
                    "provider_used": ai_result.get("provider_used"),
                    "json_object": parsed,
                }
            )
        except Exception as e:
            logger.warning("AI suggest failed for beta gate: %s", e, exc_info=True)
            return Response(
                {
                    "success": True,
                    "fallback": True,
                    "provider_used": None,
                    "message": "AI 服务不可用，已返回默认模板",
                    "json_object": fallback,
                }
            )

    def _build_messages(self, target: str, requirement: str) -> list[dict]:
        config = self.TARGET_CONFIG[target]
        system_prompt = (
            "你是配置助手。只输出一个 JSON 对象，不要输出解释、markdown、代码块。"
            "不要凭空添加无关字段。"
        )
        user_prompt = (
            f"目标配置类型: {target}\n"
            f"字段说明: {config['hint']}\n"
            f"需求描述: {requirement}\n"
            f"参考模板: {json.dumps(config['template'], ensure_ascii=False)}\n"
            "请返回可直接保存的 JSON 对象。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _parse_json_from_text(self, text: str):
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fenced_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced_match:
            try:
                return json.loads(fenced_match.group(1))
            except json.JSONDecodeError:
                pass

        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                return None
        return None


# ========== Template Views ==========


def beta_gate_test_view(request):
    """
    Beta Gate 资产测试工具页面

    允许用户快速测试特定资产在当前配置下是否能通过 Beta Gate。
    """
    try:
        config_service = get_beta_gate_config_query_service()

        # 获取当前配置
        try:
            active_config = config_service.get_active_config()
        except Exception as e:
            logger.warning(f"Failed to query active config: {e}")
            active_config = None

        # 获取当前 Regime
        current_regime = None
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            current_regime = resolve_current_regime()
        except Exception as e:
            logger.warning(f"Failed to get current regime: {e}")

        # 获取当前 Policy
        current_policy = None
        try:
            from apps.policy.application.use_cases import GetCurrentPolicyUseCase
            from apps.policy.application.repository_provider import get_current_policy_repository

            policy_use_case = GetCurrentPolicyUseCase(get_current_policy_repository())
            policy_response = policy_use_case.execute()
            if policy_response.success and policy_response.policy_level:
                current_policy = policy_response.policy_level
        except Exception as e:
            logger.warning(f"Failed to get current policy: {e}")

        # 获取最近测试记录
        recent_tests = []
        try:
            recent_tests = config_service.get_recent_decisions(limit=10)
        except Exception as e:
            logger.warning(f"Failed to query recent tests: {e}")
            recent_tests = []

        # 批量解析资产名称
        from apps.asset_analysis.application.asset_name_service import resolve_asset_names

        asset_codes = [t.asset_code for t in recent_tests if t.asset_code]
        asset_name_map = resolve_asset_names(asset_codes)
        for test in recent_tests:
            test.asset_name = asset_name_map.get(test.asset_code, test.asset_code)

        # 获取所有资产类别
        all_asset_classes = ["a_股票", "a_债券", "a_商品", "a_现金", "港股", "美股", "黄金", "原油"]

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
        context = get_beta_gate_config_query_service().get_version_page_context()

        return render(request, "beta_gate/version_compare.html", context)

    except Exception as e:
        logger.error(f"Failed to load beta gate version page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "配置版本对比",
        }
        return render(request, "beta_gate/version_compare.html", context, status=500)


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

            from ..application.use_cases import EvaluateBatchRequest, EvaluateBatchUseCase
            from ..domain.entities import RiskProfile

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
            risk_profile_raw = str(data.get("risk_profile", "BALANCED"))
            try:
                risk_profile = RiskProfile(risk_profile_raw)
            except ValueError:
                risk_profile = RiskProfile(risk_profile_raw.lower())

            # 构建资产列表
            assets = [(code, asset_class) for code in asset_codes]

            # 创建配置选择器
            class SimpleConfigSelector:
                def __init__(self, config_repo):
                    self.config_repo = config_repo

                def get_config(self, risk_profile):
                    configs = self.config_repo.get_all_active()
                    if configs:
                        config = configs[0]
                        return config.to_domain() if hasattr(config, "to_domain") else config
                    # 返回默认配置
                    from ..domain.entities import (
                        GateConfig,
                        PolicyConstraint,
                        PortfolioConstraint,
                        RegimeConstraint,
                    )

                    allowed_asset_classes = [asset_class] if asset_class else []
                    return GateConfig(
                        config_id="default",
                        version=1,
                        is_active=True,
                        is_valid=True,
                        risk_profile=RiskProfile.BALANCED,
                        regime_constraint=RegimeConstraint(
                            current_regime="Recovery",
                            confidence=0.5,
                            allowed_asset_classes=allowed_asset_classes,
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

            config_selector = SimpleConfigSelector(get_beta_gate_config_repository())

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
                    results.append(
                        {
                            "asset_code": decision.asset_code,
                            "asset_class": decision.asset_class,
                            "passed": decision.is_passed,
                            "status": decision.status.value,
                            "blocking_reason": decision.blocking_reason
                            if not decision.is_passed
                            else None,
                            "evaluated_at": decision.evaluated_at.isoformat(),
                        }
                    )

                return Response(
                    {
                        "success": True,
                        "results": results,
                        "summary": response.summary,
                    }
                )
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
        self.config_repository = get_beta_gate_config_repository()

    def list(self, request) -> Response:
        """获取所有激活配置"""
        try:
            configs = self.config_repository.get_all_active()
            results = []
            for config in configs:
                config_entity = config.to_domain() if hasattr(config, "to_domain") else config
                results.append(
                    {
                        "config_id": config_entity.config_id,
                        "risk_profile": config_entity.risk_profile.value,
                        "version": config_entity.version,
                        "is_active": config_entity.is_active,
                        "regime_constraints": config_entity.regime_constraint.to_dict(),
                        "policy_constraints": config_entity.policy_constraint.to_dict(),
                        "portfolio_constraints": config_entity.portfolio_constraint.to_dict(),
                        "effective_date": config_entity.effective_date.isoformat()
                        if config_entity.effective_date
                        else None,
                        "expires_at": config_entity.expires_at.isoformat()
                        if config_entity.expires_at
                        else None,
                    }
                )
            return Response(
                {
                    "success": True,
                    "count": len(results),
                    "results": results,
                }
            )
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
            config_entity = config.to_domain() if hasattr(config, "to_domain") else config
            return Response(
                {
                    "success": True,
                    "result": {
                        "config_id": config_entity.config_id,
                        "risk_profile": config_entity.risk_profile.value,
                        "version": config_entity.version,
                        "is_active": config_entity.is_active,
                        "regime_constraints": config_entity.regime_constraint.to_dict(),
                        "policy_constraints": config_entity.policy_constraint.to_dict(),
                        "portfolio_constraints": config_entity.portfolio_constraint.to_dict(),
                    },
                }
            )
        except Exception as e:
            logger.error(f"Failed to retrieve config: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def create(self, request) -> Response:
        """创建新的 Beta Gate 配置。"""
        try:
            payload = request.data if isinstance(request.data, dict) else {}
            regime_constraints = payload.get("regime_constraints", {}) or {}
            policy_constraints = payload.get("policy_constraints", {}) or {}
            portfolio_constraints = payload.get("portfolio_constraints", {}) or {}

            risk_profile_raw = str(payload.get("risk_profile", "balanced")).strip().lower()
            try:
                risk_profile = RiskProfile(risk_profile_raw)
            except ValueError:
                return Response(
                    {"success": False, "error": f"Invalid risk_profile: {risk_profile_raw}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            level_raw = payload.get(
                "max_policy_level", policy_constraints.get("max_allowed_level", 2)
            )
            if isinstance(level_raw, str) and level_raw.upper().startswith("P"):
                level_raw = level_raw[1:]

            config = create_gate_config(
                risk_profile=risk_profile,
                allowed_regimes=payload.get(
                    "allowed_regimes", regime_constraints.get("allowed_regimes")
                ),
                min_confidence=float(
                    payload.get("min_confidence", regime_constraints.get("min_confidence", 0.3))
                ),
                max_policy_level=int(level_raw),
                veto_on_p3=bool(
                    payload.get("veto_on_p3", policy_constraints.get("veto_on_p3", True))
                ),
                max_total_position=float(
                    payload.get(
                        "max_total_position",
                        portfolio_constraints.get("max_total_position_pct", 95.0),
                    )
                ),
                max_single_position=float(
                    payload.get(
                        "max_single_position",
                        portfolio_constraints.get("max_single_position_pct", 20.0),
                    )
                ),
            )
            if payload.get("config_id"):
                config = replace(config, config_id=str(payload["config_id"]))

            saved = self.config_repository.save(config)
            return Response(
                {
                    "success": True,
                    "result": {
                        "config_id": saved.config_id,
                        "risk_profile": saved.risk_profile.lower(),
                        "version": saved.version,
                        "is_active": saved.is_active,
                        "regime_constraints": saved.regime_constraints,
                        "policy_constraints": saved.policy_constraints,
                        "portfolio_constraints": saved.portfolio_constraints,
                        "effective_date": saved.effective_date.isoformat()
                        if saved.effective_date
                        else None,
                        "expires_at": saved.expires_at.isoformat() if saved.expires_at else None,
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        except (TypeError, ValueError) as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Failed to create config: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GateDecisionViewSet(viewsets.ViewSet):
    """闸门决策视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.decision_repository = get_beta_gate_decision_repository()

    def list(self, request) -> Response:
        """获取决策历史"""
        try:
            try:
                days = int(request.query_params.get("days", 30))
            except (TypeError, ValueError):
                return Response(
                    {"success": False, "error": "days must be an integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            decisions = self.decision_repository.get_recent(days)
            results = []
            for decision in decisions:
                results.append(
                    {
                        "decision_id": getattr(decision, "decision_id", ""),
                        "asset_code": decision.asset_code,
                        "asset_class": decision.asset_class,
                        "status": decision.status.value,
                        "current_regime": decision.current_regime,
                        "policy_level": decision.policy_level,
                        "regime_confidence": decision.regime_confidence,
                        "evaluated_at": decision.evaluated_at.isoformat(),
                    }
                )
            return Response(
                {
                    "success": True,
                    "count": len(results),
                    "results": results,
                }
            )
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
            return Response(
                {
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
                }
            )
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
        self.universe_repository = get_beta_gate_universe_repository()

    def list(self, request) -> Response:
        """获取历史快照"""
        try:
            regime = request.query_params.get("regime", None)
            policy_level = request.query_params.get("policy_level", None)
            try:
                limit = int(request.query_params.get("limit", 100))
            except (TypeError, ValueError):
                return Response(
                    {"success": False, "error": "limit must be an integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            snapshots = self.universe_repository.get_history(regime, policy_level, limit)
            return Response(
                {
                    "success": True,
                    "count": len(snapshots),
                    "results": snapshots,
                }
            )
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
            return Response(
                {
                    "success": True,
                    "result": snapshot,
                }
            )
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
        context_data = get_beta_gate_config_query_service().get_config_page_context()
        recent_decisions = context_data["recent_decisions"]

        # 批量解析资产名称
        from apps.asset_analysis.application.asset_name_service import resolve_asset_names

        asset_codes = [d.asset_code for d in recent_decisions if d.asset_code]
        asset_name_map = resolve_asset_names(asset_codes)
        for decision in recent_decisions:
            decision.asset_name = asset_name_map.get(decision.asset_code, decision.asset_code)

        return render(request, "beta_gate/config.html", context_data)

    except Exception as e:
        logger.error(f"Failed to load beta gate config page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "Beta 闸门配置",
        }
        return render(request, "beta_gate/config.html", context, status=500)


def beta_gate_config_create_view(request):
    """创建 Beta Gate 配置（非 Admin）。"""
    if request.method == "POST":
        form = GateConfigForm(request.POST)
        if form.is_valid():
            instance = _save_gate_config_form(form)
            messages.success(request, f"配置 {instance.config_id} 已创建")
            return redirect("beta_gate:config")
    else:
        form = GateConfigForm()

    return render(
        request,
        "beta_gate/config_form.html",
        {
            "form": form,
            "form_mode": "create",
            "page_title": "创建 Beta Gate 配置",
        },
    )


def beta_gate_config_edit_view(request, config_id):
    """编辑 Beta Gate 配置（非 Admin）。"""
    config = get_beta_gate_config_query_service().get_config_for_edit(config_id)
    if config is None:
        messages.error(request, f"配置不存在: {config_id}")
        return redirect("beta_gate:config")

    if request.method == "POST":
        form = GateConfigForm(request.POST, instance=config)
        if form.is_valid():
            instance = _save_gate_config_form(form)
            messages.success(request, f"配置 {instance.config_id} 已更新")
            return redirect("beta_gate:config")
    else:
        form = GateConfigForm(instance=config)

    return render(
        request,
        "beta_gate/config_form.html",
        {
            "form": form,
            "config": config,
            "form_mode": "edit",
            "page_title": f"编辑配置 {config.config_id}",
        },
    )


def beta_gate_config_activate_view(request, config_id):
    """将指定配置设为激活。"""
    if request.method != "POST":
        return redirect("beta_gate:version")

    with transaction.atomic():
        config = get_beta_gate_config_query_service().activate_config(config_id)
    if config is None:
        messages.error(request, f"配置不存在: {config_id}")
        return redirect("beta_gate:version")
    messages.success(request, f"已激活配置 {config.config_id}")
    return redirect("beta_gate:version")
