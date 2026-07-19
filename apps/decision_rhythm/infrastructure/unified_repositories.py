"""
Decision Rhythm Repositories

决策频率约束和配额管理的数据仓储实现。
实现 Domain 层定义的 Repository Protocol。

这些仓储桥接 Domain 层实体和 Django ORM 模型。
"""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class UnifiedRecommendationRepository:
    """
    统一推荐仓储

    管理统一推荐对象的持久化。
    """

    def save(self, recommendation) -> Any:
        """
        保存推荐

        Args:
            recommendation: UnifiedRecommendation 实体

        Returns:
            保存后的实体
        """
        from .models import DecisionFeatureSnapshotModel, UnifiedRecommendationModel

        # 转换 reason_codes 和其他列表字段
        reason_codes = (
            recommendation.reason_codes if hasattr(recommendation, "reason_codes") else []
        )
        source_signal_ids = (
            recommendation.source_signal_ids if hasattr(recommendation, "source_signal_ids") else []
        )
        source_candidate_ids = (
            recommendation.source_candidate_ids
            if hasattr(recommendation, "source_candidate_ids")
            else []
        )

        snapshot_model = None
        if getattr(recommendation, "feature_snapshot_id", ""):
            snapshot_model = DecisionFeatureSnapshotModel.objects.filter(
                snapshot_id=recommendation.feature_snapshot_id
            ).first()

        model, created = UnifiedRecommendationModel.objects.update_or_create(
            recommendation_id=recommendation.recommendation_id,
            defaults={
                "account_id": recommendation.account_id,
                "security_code": recommendation.security_code,
                "side": recommendation.side,
                "regime": recommendation.regime,
                "regime_confidence": recommendation.regime_confidence,
                "policy_level": recommendation.policy_level,
                "beta_gate_passed": recommendation.beta_gate_passed,
                "sentiment_score": recommendation.sentiment_score,
                "flow_score": recommendation.flow_score,
                "technical_score": recommendation.technical_score,
                "fundamental_score": recommendation.fundamental_score,
                "alpha_model_score": recommendation.alpha_model_score,
                "composite_score": recommendation.composite_score,
                "confidence": recommendation.confidence,
                "reason_codes": reason_codes,
                "human_rationale": recommendation.human_rationale,
                "fair_value": recommendation.fair_value,
                "entry_price_low": recommendation.entry_price_low,
                "entry_price_high": recommendation.entry_price_high,
                "target_price_low": recommendation.target_price_low,
                "target_price_high": recommendation.target_price_high,
                "stop_loss_price": recommendation.stop_loss_price,
                "position_pct": recommendation.position_pct,
                "suggested_quantity": recommendation.suggested_quantity,
                "max_capital": recommendation.max_capital,
                "source_signal_ids": source_signal_ids,
                "source_candidate_ids": source_candidate_ids,
                "feature_snapshot": snapshot_model,
                "status": recommendation.status.value
                if hasattr(recommendation.status, "value")
                else str(recommendation.status),
                "user_action": recommendation.user_action.value
                if hasattr(recommendation.user_action, "value")
                else str(recommendation.user_action),
                "user_action_note": getattr(recommendation, "user_action_note", ""),
                "user_action_at": getattr(recommendation, "user_action_at", None),
            },
        )

        return self._model_to_entity(model)

    def save_feature_snapshot(self, snapshot) -> Any:
        """
        保存特征快照

        Args:
            snapshot: DecisionFeatureSnapshot 实体

        Returns:
            保存后的实体
        """
        from .models import DecisionFeatureSnapshotModel

        extra_features = snapshot.extra_features if hasattr(snapshot, "extra_features") else {}

        model, created = DecisionFeatureSnapshotModel.objects.update_or_create(
            snapshot_id=snapshot.snapshot_id,
            defaults={
                "security_code": snapshot.security_code,
                "snapshot_time": snapshot.snapshot_time,
                "regime": snapshot.regime,
                "regime_confidence": snapshot.regime_confidence,
                "policy_level": snapshot.policy_level,
                "beta_gate_passed": snapshot.beta_gate_passed,
                "sentiment_score": snapshot.sentiment_score,
                "flow_score": snapshot.flow_score,
                "technical_score": snapshot.technical_score,
                "fundamental_score": snapshot.fundamental_score,
                "alpha_model_score": snapshot.alpha_model_score,
                "extra_features": extra_features,
            },
        )

        return snapshot

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list[Any]:
        """
        按账户获取推荐

        Args:
            account_id: 账户 ID
            status: 状态过滤（可选）

        Returns:
            推荐列表
        """
        from .models import UnifiedRecommendationModel

        query = UnifiedRecommendationModel.objects.filter(account_id=account_id)

        if status:
            query = query.filter(status=status)

        query = query.order_by("-created_at")
        return [self._model_to_entity(model) for model in query]

    def get_by_recommendation_id(
        self,
        recommendation_id: str,
        *,
        account_id: str | None = None,
    ) -> Any | None:
        """按 recommendation_id 获取推荐。"""
        from .models import UnifiedRecommendationModel

        query = UnifiedRecommendationModel.objects.filter(recommendation_id=recommendation_id)
        if account_id:
            query = query.filter(account_id=account_id)
        model = query.select_related("feature_snapshot").first()
        return self._model_to_entity(model) if model else None

    def get_active_by_key(
        self,
        *,
        account_id: str,
        security_code: str,
        side: str,
        exclude_conflicts: bool = True,
    ) -> Any | None:
        """Return the latest non-conflict recommendation for an aggregation key."""
        from .models import UnifiedRecommendationModel

        queryset = UnifiedRecommendationModel.objects.filter(
            account_id=account_id,
            security_code=security_code,
            side=side,
        )
        if exclude_conflicts:
            queryset = queryset.exclude(status="CONFLICT")
        model = queryset.select_related("feature_snapshot").order_by("-created_at").first()
        return self._model_to_entity(model) if model else None

    def append_source_candidate_ids(
        self,
        recommendation_id: str,
        candidate_ids: list[str],
    ) -> Any | None:
        """Append candidate ids to an existing recommendation without duplicates."""
        from .models import UnifiedRecommendationModel

        model = UnifiedRecommendationModel.objects.filter(
            recommendation_id=recommendation_id
        ).first()
        if model is None:
            return None

        existing_ids = list(model.source_candidate_ids or [])
        merged_ids = existing_ids[:]
        for candidate_id in candidate_ids:
            if candidate_id and candidate_id not in merged_ids:
                merged_ids.append(candidate_id)

        if merged_ids != existing_ids:
            model.source_candidate_ids = merged_ids
            model.save(update_fields=["source_candidate_ids", "updated_at"])

        model.refresh_from_db()
        return self._model_to_entity(model)

    def get_by_recommendation_ids(
        self,
        recommendation_ids: list[str],
        *,
        account_id: str | None = None,
    ) -> list[Any]:
        """按 recommendation_id 列表获取推荐。"""
        from .models import UnifiedRecommendationModel

        if not recommendation_ids:
            return []
        query = UnifiedRecommendationModel.objects.filter(recommendation_id__in=recommendation_ids)
        if account_id:
            query = query.filter(account_id=account_id)
        models = query.select_related("feature_snapshot").order_by("-created_at")
        return [self._model_to_entity(model) for model in models]

    def list_for_workspace(
        self,
        *,
        account_id: str,
        status: str | None = None,
        user_action: str | None = None,
        security_code: str | None = None,
        include_ignored: bool = False,
        recommendation_id: str | None = None,
        exclude_conflicts: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Any], int]:
        """按工作台筛选条件返回推荐及总数。"""
        from ..domain.entities import UserDecisionAction
        from .models import UnifiedRecommendationModel

        queryset = UnifiedRecommendationModel.objects.filter(account_id=account_id).select_related(
            "feature_snapshot"
        )
        if exclude_conflicts:
            queryset = queryset.exclude(status="CONFLICT")
        if not include_ignored:
            queryset = queryset.exclude(user_action=UserDecisionAction.IGNORED.value)
        if status:
            queryset = queryset.filter(status=status)
        if user_action:
            queryset = queryset.filter(user_action=user_action)
        if security_code:
            queryset = queryset.filter(security_code=security_code)
        if recommendation_id:
            queryset = queryset.filter(recommendation_id=recommendation_id)

        queryset = queryset.order_by("-composite_score", "-created_at")
        total_count = queryset.count()
        start = max(page - 1, 0) * page_size
        end = start + page_size
        models = queryset[start:end]
        return [self._model_to_entity(model) for model in models], total_count

    def get_plan_candidates(
        self,
        account_id: str,
        recommendation_ids: list[str] | None = None,
    ) -> list[Any]:
        """返回可生成交易计划的推荐。"""
        from ..domain.entities import RecommendationStatus, UserDecisionAction
        from .models import UnifiedRecommendationModel

        queryset = UnifiedRecommendationModel.objects.filter(account_id=account_id).exclude(
            status=RecommendationStatus.CONFLICT.value
        )
        queryset = queryset.filter(user_action=UserDecisionAction.ADOPTED.value)
        if recommendation_ids:
            queryset = queryset.filter(recommendation_id__in=recommendation_ids)
        models = queryset.select_related("feature_snapshot").order_by("-created_at")
        return [self._model_to_entity(model) for model in models]

    def update_user_action(
        self,
        *,
        recommendation_id: str,
        user_action,
        note: str = "",
        account_id: str | None = None,
    ) -> Any | None:
        """更新用户动作并返回最新推荐。"""
        from .models import UnifiedRecommendationModel

        queryset = UnifiedRecommendationModel.objects.filter(recommendation_id=recommendation_id)
        if account_id:
            queryset = queryset.filter(account_id=account_id)

        model = queryset.select_related("feature_snapshot").first()
        if model is None:
            return None

        model.user_action = user_action.value if hasattr(user_action, "value") else str(user_action)
        model.user_action_note = note
        model.user_action_at = timezone.now()
        model.save(
            update_fields=["user_action", "user_action_note", "user_action_at", "updated_at"]
        )
        return self._model_to_entity(model)

    def find_execution_match(
        self,
        *,
        account_id: str,
        security_code: str,
        side: str,
        traded_at,
        window_days: int = 5,
    ) -> dict[str, Any] | None:
        """Return the best recommendation match for one manual transaction."""

        from .models import UnifiedRecommendationModel

        start = traded_at - timedelta(days=window_days)
        end = traded_at + timedelta(days=window_days)
        model = (
            UnifiedRecommendationModel.objects.filter(
                account_id=account_id,
                security_code=security_code,
                side=side,
                created_at__gte=start,
                created_at__lte=end,
            )
            .exclude(user_action="IGNORED")
            .order_by("-composite_score", "-created_at")
            .first()
        )
        if model is None:
            return None
        return {
            "recommendation_id": model.recommendation_id,
            "match_confidence": 0.85,
        }

    def record_execution_link(
        self,
        *,
        recommendation_id: str,
        transaction_id: int,
        transaction_source: str = "account_transaction",
        account_id: str,
        security_code: str,
        actual_action: str,
        match_method: str,
        match_confidence: float,
        notes: str = "",
    ) -> dict[str, Any]:
        """Persist one recommendation/manual transaction execution link."""
        from .models import DecisionExecutionLinkModel

        model, _ = DecisionExecutionLinkModel.objects.update_or_create(
            transaction_id=transaction_id,
            transaction_source=transaction_source,
            recommendation_id=recommendation_id,
            defaults={
                "account_id": account_id,
                "security_code": security_code,
                "actual_action": actual_action,
                "match_method": match_method,
                "match_confidence": match_confidence,
                "notes": notes,
            },
        )
        return {
            "id": model.id,
            "recommendation_id": model.recommendation_id,
            "transaction_id": model.transaction_id,
            "transaction_source": model.transaction_source,
            "match_method": model.match_method,
            "match_confidence": model.match_confidence,
        }

    def list_execution_links(
        self,
        *,
        account_ids: list[str] | None = None,
        account_id: str | None = None,
        recommendation_id: str | None = None,
        transaction_source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent recommendation-to-execution links."""
        from .models import DecisionExecutionLinkModel

        queryset = DecisionExecutionLinkModel.objects.all().order_by("-created_at")
        if account_ids is not None:
            queryset = queryset.filter(account_id__in=account_ids)
        if account_id:
            queryset = queryset.filter(account_id=str(account_id))
        if recommendation_id:
            queryset = queryset.filter(recommendation_id=recommendation_id)
        if transaction_source:
            queryset = queryset.filter(transaction_source=transaction_source)

        rows = queryset[: max(1, min(int(limit or 50), 200))]
        return [
            {
                "id": model.id,
                "recommendation_id": model.recommendation_id,
                "transaction_id": model.transaction_id,
                "transaction_source": model.transaction_source,
                "account_id": model.account_id,
                "security_code": model.security_code,
                "actual_action": model.actual_action,
                "match_method": model.match_method,
                "match_confidence": model.match_confidence,
                "notes": model.notes,
                "created_at": model.created_at.isoformat() if model.created_at else None,
            }
            for model in rows
        ]

    def get_execution_plan_for_transaction(self, transaction_id: int) -> dict[str, Any] | None:
        """Return recommendation trade parameters linked to an account transaction."""
        from .models import DecisionExecutionLinkModel, UnifiedRecommendationModel

        link = (
            DecisionExecutionLinkModel.objects.filter(
                transaction_id=transaction_id,
                transaction_source="account_transaction",
            )
            .exclude(recommendation_id="")
            .order_by("-match_confidence", "-created_at")
            .first()
        )
        if link is None:
            return None
        recommendation = UnifiedRecommendationModel.objects.filter(
            recommendation_id=link.recommendation_id
        ).first()
        if recommendation is None:
            return None
        return {
            "recommendation_id": recommendation.recommendation_id,
            "side": recommendation.side,
            "suggested_quantity": recommendation.suggested_quantity,
            "entry_price_low": recommendation.entry_price_low,
            "entry_price_high": recommendation.entry_price_high,
            "target_price_low": recommendation.target_price_low,
            "target_price_high": recommendation.target_price_high,
            "stop_loss_price": recommendation.stop_loss_price,
        }

    def get_candidate_ids_for_recommendations(self, recommendation_ids: list[str]) -> list[str]:
        """返回推荐集合关联的候选 ID。"""
        from .models import UnifiedRecommendationModel

        if not recommendation_ids:
            return []
        raw_lists = UnifiedRecommendationModel.objects.filter(
            recommendation_id__in=recommendation_ids
        ).values_list("source_candidate_ids", flat=True)
        candidate_ids = [
            str(candidate_id) for row in raw_lists for candidate_id in (row or []) if candidate_id
        ]
        return list(dict.fromkeys(candidate_ids))

    def get_conflicts(self, account_id: str) -> list[Any]:
        """
        获取冲突推荐

        Args:
            account_id: 账户 ID

        Returns:
            冲突推荐列表
        """
        from ..domain.entities import RecommendationStatus
        from .models import UnifiedRecommendationModel

        models = UnifiedRecommendationModel.objects.filter(
            account_id=account_id,
            status=RecommendationStatus.CONFLICT.value,
        ).order_by("-created_at")

        return [self._model_to_entity(model) for model in models]

    def mark_as_conflict(self, recommendation_id: str) -> None:
        """
        标记为冲突

        Args:
            recommendation_id: 推荐 ID
        """
        from ..domain.entities import RecommendationStatus
        from .models import UnifiedRecommendationModel

        UnifiedRecommendationModel.objects.filter(recommendation_id=recommendation_id).update(
            status=RecommendationStatus.CONFLICT.value
        )

    def _model_to_entity(self, model) -> Any:
        """
        将 ORM 模型转换为实体

        Args:
            model: ORM 模型实例

        Returns:
            实体实例
        """

        from ..domain.entities import (
            RecommendationStatus,
            UnifiedRecommendation,
            UserDecisionAction,
        )

        # 解析状态
        try:
            status = RecommendationStatus(model.status)
        except ValueError:
            status = RecommendationStatus.NEW
        try:
            user_action = UserDecisionAction(
                getattr(model, "user_action", UserDecisionAction.PENDING.value)
            )
        except ValueError:
            user_action = UserDecisionAction.PENDING

        return UnifiedRecommendation(
            recommendation_id=model.recommendation_id,
            account_id=model.account_id,
            security_code=model.security_code,
            side=model.side,
            regime=model.regime,
            regime_confidence=model.regime_confidence,
            policy_level=model.policy_level,
            beta_gate_passed=model.beta_gate_passed,
            sentiment_score=model.sentiment_score,
            flow_score=model.flow_score,
            technical_score=model.technical_score,
            fundamental_score=model.fundamental_score,
            alpha_model_score=model.alpha_model_score,
            composite_score=model.composite_score,
            confidence=model.confidence,
            reason_codes=model.reason_codes or [],
            human_rationale=model.human_rationale,
            fair_value=Decimal(str(model.fair_value)),
            entry_price_low=Decimal(str(model.entry_price_low)),
            entry_price_high=Decimal(str(model.entry_price_high)),
            target_price_low=Decimal(str(model.target_price_low)),
            target_price_high=Decimal(str(model.target_price_high)),
            stop_loss_price=Decimal(str(model.stop_loss_price)),
            position_pct=float(model.position_pct),
            suggested_quantity=model.suggested_quantity,
            max_capital=Decimal(str(model.max_capital)),
            source_signal_ids=model.source_signal_ids or [],
            source_candidate_ids=model.source_candidate_ids or [],
            feature_snapshot_id=getattr(model, "feature_snapshot_id", ""),
            status=status,
            user_action=user_action,
            user_action_note=getattr(model, "user_action_note", ""),
            user_action_at=getattr(model, "user_action_at", None),
            created_at=getattr(model, "created_at", None),
            updated_at=getattr(model, "updated_at", None),
        )


class DecisionModelParamConfigRepository:
    """
    决策模型参数仓储

    为参数 use case 提供统一的参数读写与审计能力。
    """

    def get_param(self, param_key: str, env: str):
        from .models import DecisionModelParamConfigModel

        model = (
            DecisionModelParamConfigModel.objects.filter(param_key=param_key, env=env)
            .order_by("-version", "-updated_at")
            .first()
        )
        return model.to_domain() if model else None

    def get_all_params(self, env: str):
        from .models import DecisionModelParamConfigModel

        models = DecisionModelParamConfigModel.objects.filter(env=env, is_active=True).order_by(
            "param_key"
        )
        return [model.to_domain() for model in models]

    def get_active_param_details(self, env: str) -> list[dict[str, Any]]:
        """返回当前环境激活参数的展示明细。"""
        from .models import DecisionModelParamConfigModel

        models = DecisionModelParamConfigModel.objects.filter(env=env, is_active=True).order_by(
            "param_key"
        )
        return [
            {
                "param_key": model.param_key,
                "value": model.param_value,
                "type": model.param_type,
                "description": model.description,
                "updated_by": model.updated_by,
                "updated_at": model.updated_at.isoformat() if model.updated_at else None,
            }
            for model in models
        ]

    def save_param(self, config):
        from .models import DecisionModelParamConfigModel

        with transaction.atomic():
            # 同一参数键在同一环境下只允许一个激活版本
            DecisionModelParamConfigModel.objects.filter(
                param_key=config.param_key,
                env=config.env,
                is_active=True,
            ).exclude(config_id=config.config_id).update(is_active=False)

            model, _ = DecisionModelParamConfigModel.objects.update_or_create(
                config_id=config.config_id,
                defaults={
                    "param_key": config.param_key,
                    "param_value": config.param_value,
                    "param_type": config.param_type,
                    "env": config.env,
                    "version": config.version,
                    "is_active": config.is_active,
                    "description": config.description,
                    "updated_by": config.updated_by,
                    "updated_reason": config.updated_reason,
                },
            )

        return model.to_domain()

    def create_audit_log(self, log):
        from .models import DecisionModelParamAuditLogModel

        model = DecisionModelParamAuditLogModel.from_domain(log)
        model.save()
        return model.to_domain()


# 便捷函数
