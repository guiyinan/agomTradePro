"""
Repositories for Investment Signals.

Infrastructure layer implementation using Django ORM.
"""

import json
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from ..domain.entities import InvestmentSignal, SignalStatus
from .models import InvestmentSignalModel


class SignalRepositoryError(Exception):
    """信号仓储异常"""
    pass


class DjangoSignalRepository:
    """
    Django ORM 实现的投资信号仓储

    提供投资信号的增删改查操作。
    """

    def __init__(self):
        self._model = InvestmentSignalModel

    # Protocol compatibility methods
    def get_by_id(self, id: str) -> InvestmentSignal | None:
        return self.get_signal_by_id(id)

    def get_all(self) -> list[InvestmentSignal]:
        query = self._model.objects.all().order_by("-created_at")
        return [self._orm_to_entity(obj) for obj in query]

    def _get_signal_record_by_id(self, signal_id: str) -> InvestmentSignalModel | None:
        """Return one ORM signal record or None for invalid/nonexistent ids."""

        try:
            return self._model._default_manager.filter(id=signal_id).first()
        except (TypeError, ValueError, ValidationError):
            return None

    def save(self, entity: InvestmentSignal) -> InvestmentSignal:
        return self.save_signal(entity)

    def delete(self, id: str) -> bool:
        return self.delete_signal(id)

    def find_by_criteria(self, **criteria: Any) -> list[InvestmentSignal]:
        query = self._model.objects.filter(**criteria).order_by("-created_at")
        return [self._orm_to_entity(obj) for obj in query]

    def count(self, **criteria: Any) -> int:
        return self._model.objects.filter(**criteria).count()

    def save_signal(
        self,
        signal: InvestmentSignal
    ) -> InvestmentSignal:
        """
        保存投资信号

        Args:
            signal: 信号实体

        Returns:
            InvestmentSignal: 保存后的信号
        """
        # 转换 status 枚举
        status_value = (
            signal.status.value if isinstance(signal.status, SignalStatus)
            else signal.status
        )

        # 检查是否已存在（有 ID）
        if signal.id:
            try:
                existing = self._model.objects.get(id=signal.id)
                # 更新
                existing.asset_code = signal.asset_code
                existing.asset_class = signal.asset_class
                existing.direction = signal.direction
                existing.logic_desc = signal.logic_desc
                existing.invalidation_logic = signal.invalidation_logic
                existing.invalidation_threshold = signal.invalidation_threshold
                existing.target_regime = signal.target_regime
                existing.status = status_value
                existing.rejection_reason = signal.rejection_reason
                existing.save()
                orm_obj = existing
            except self._model.DoesNotExist:
                # ID 不存在，创建新记录
                orm_obj = self._model.objects.create(
                    asset_code=signal.asset_code,
                    asset_class=signal.asset_class,
                    direction=signal.direction,
                    logic_desc=signal.logic_desc,
                    invalidation_logic=signal.invalidation_logic,
                    invalidation_threshold=signal.invalidation_threshold,
                    target_regime=signal.target_regime,
                    status=status_value,
                    rejection_reason=signal.rejection_reason
                )
        else:
            # 新建
            orm_obj = self._model.objects.create(
                asset_code=signal.asset_code,
                asset_class=signal.asset_class,
                direction=signal.direction,
                logic_desc=signal.logic_desc,
                invalidation_logic=signal.invalidation_logic,
                invalidation_threshold=signal.invalidation_threshold,
                target_regime=signal.target_regime,
                status=status_value,
                rejection_reason=signal.rejection_reason
            )

        return self._orm_to_entity(orm_obj)

    def get_signal_by_id(self, signal_id: str) -> InvestmentSignal | None:
        """
        按 ID 获取信号

        Args:
            signal_id: 信号 ID

        Returns:
            Optional[InvestmentSignal]: 信号实体，不存在则返回 None
        """
        orm_obj = self._get_signal_record_by_id(signal_id)
        if orm_obj is None:
            return None
        return self._orm_to_entity(orm_obj)

    def get_signals_by_asset(
        self,
        asset_code: str,
        status: SignalStatus | None = None
    ) -> list[InvestmentSignal]:
        """
        按资产代码获取信号列表

        Args:
            asset_code: 资产代码
            status: 状态过滤（None 表示所有状态）

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        query = self._model.objects.filter(asset_code=asset_code)

        if status:
            status_value = status.value if isinstance(status, SignalStatus) else status
            query = query.filter(status=status_value)

        query = query.order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def get_signals_by_status(
        self,
        status: SignalStatus
    ) -> list[InvestmentSignal]:
        """
        按状态获取信号列表

        Args:
            status: 信号状态

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        status_value = status.value if isinstance(status, SignalStatus) else status
        query = self._model.objects.filter(status=status_value).order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def get_pending_signals(self) -> list[InvestmentSignal]:
        """
        获取待处理信号

        Returns:
            List[InvestmentSignal]: 待处理信号列表
        """
        return self.get_signals_by_status(SignalStatus.PENDING)

    def get_active_signals(self) -> list[InvestmentSignal]:
        """
        获取活跃信号（已批准但未失效）

        Returns:
            List[InvestmentSignal]: 活跃信号列表
        """
        query = self._model.objects.filter(status='approved').order_by('-created_at')
        return [self._orm_to_entity(obj) for obj in query]

    def list_signal_records(
        self,
        *,
        status_filter: str = "",
        asset_class: str = "",
        direction: str = "",
        search: str = "",
        limit: int = 50,
    ) -> list[InvestmentSignalModel]:
        """Return signal ORM records for the management page."""

        queryset = self._model._default_manager.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if asset_class:
            queryset = queryset.filter(asset_class=asset_class)
        if direction:
            queryset = queryset.filter(direction=direction)
        if search:
            queryset = queryset.filter(
                Q(asset_code__icontains=search) | Q(logic_desc__icontains=search)
            )
        return list(queryset.order_by("-created_at")[:limit])

    def get_signal_management_metadata(self) -> dict[str, Any]:
        """Return status counts and filter options for the management page."""

        manager = self._model._default_manager
        return {
            "stats": {
                "total": manager.count(),
                "pending": manager.filter(status="pending").count(),
                "approved": manager.filter(status="approved").count(),
                "rejected": manager.filter(status="rejected").count(),
                "invalidated": manager.filter(status="invalidated").count(),
            },
            "asset_classes": [
                item["asset_class"]
                for item in manager.values("asset_class").distinct()
                if item.get("asset_class")
            ],
            "directions": [
                item["direction"]
                for item in manager.values("direction").distinct()
                if item.get("direction")
            ],
        }

    def list_signal_payloads(
        self,
        *,
        status_filter: str = "",
        asset_class: str = "",
        direction: str = "",
        search: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return serialized signal payloads for API responses."""

        return [
            self._serialize_signal_record(signal)
            for signal in self.list_signal_records(
                status_filter=status_filter,
                asset_class=asset_class,
                direction=direction,
                search=search,
                limit=limit,
            )
        ]

    def get_signal_payload(self, signal_id: str) -> dict[str, Any] | None:
        """Return one serialized signal payload by id."""

        signal = self._get_signal_record_by_id(signal_id)
        if signal is None:
            return None
        return self._serialize_signal_record(signal)

    def create_signal_record(
        self,
        *,
        asset_code: str,
        asset_class: str,
        direction: str,
        logic_desc: str,
        invalidation_logic: str,
        invalidation_threshold: float | None,
        invalidation_rules: dict | None,
        invalidation_description: str | None = None,
        invalidation_rule_json: dict[str, Any] | None = None,
        target_regime: str,
        status: str,
        rejection_reason: str,
    ) -> dict[str, Any]:
        """Create one investment signal record and return its serialized payload."""

        signal = self._model._default_manager.create(
            asset_code=asset_code,
            asset_class=asset_class,
            direction=direction,
            logic_desc=logic_desc,
            invalidation_description=invalidation_description or invalidation_logic,
            invalidation_logic=invalidation_logic,
            invalidation_threshold=invalidation_threshold,
            invalidation_rules=invalidation_rules if invalidation_rules else None,
            invalidation_rule_json=invalidation_rule_json,
            target_regime=target_regime,
            status=status,
            rejection_reason=rejection_reason,
        )
        return self._serialize_signal_record(signal)

    def update_signal_record_fields(
        self,
        signal_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """Update arbitrary signal fields and return the serialized payload."""

        signal = self._get_signal_record_by_id(signal_id)
        if signal is None:
            return None

        update_fields: list[str] = []
        for field_name, value in fields.items():
            setattr(signal, field_name, value)
            update_fields.append(field_name)

        if update_fields:
            update_fields.append("updated_at")
            signal.save(update_fields=update_fields)
        return self._serialize_signal_record(signal)

    def update_signal_record_status(
        self,
        *,
        signal_id: str,
        status: str,
        rejection_reason: str = "",
    ) -> dict[str, Any] | None:
        """Update one signal status and return public fields."""

        signal = self._get_signal_record_by_id(signal_id)
        if signal is None:
            return None

        signal.status = status
        signal.rejection_reason = rejection_reason
        update_fields = ["status", "rejection_reason", "updated_at"]
        if status == "invalidated":
            signal.invalidated_at = timezone.now()
            update_fields.insert(2, "invalidated_at")
        signal.save(update_fields=update_fields)
        return self._serialize_signal_record(signal)

    def delete_signal_record(self, signal_id: str) -> str | None:
        """Delete one signal record and return its asset code if found."""

        signal = self._get_signal_record_by_id(signal_id)
        if signal is None:
            return None
        asset_code = signal.asset_code
        signal.delete()
        return asset_code

    def count_signal_records(self) -> int:
        """Return the total number of investment signal records."""

        return self._model._default_manager.count()

    def find_signals_with_invalidation_rules(
        self,
        status: SignalStatus
    ) -> list[InvestmentSignal]:
        """
        查找具有证伪规则的信号

        Args:
            status: 信号状态

        Returns:
            List[InvestmentSignal]: 具有证伪规则的信号列表
        """
        status_value = status.value if isinstance(status, SignalStatus) else status
        query = self._model.objects.filter(
            status=status_value,
            invalidation_rule_json__isnull=False
        ).exclude(invalidation_rule_json={}).order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def find_signals_to_invalidate(self, as_of_date: date) -> list[InvestmentSignal]:
        """
        查找需要证伪检查的信号

        Args:
            as_of_date: 检查日期

        Returns:
            List[InvestmentSignal]: 需要检查的信号列表
        """
        # 获取所有有证伪规则的已批准和待处理信号
        query = self._model.objects.filter(
            status__in=['approved', 'pending'],
            invalidation_rule_json__isnull=False
        ).exclude(invalidation_rule_json={}).order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def mark_invalidated(
        self,
        signal_id: str,
        reason: str,
        details: dict
    ) -> bool:
        """
        标记信号为已证伪

        Args:
            signal_id: 信号 ID
            reason: 证伪原因
            details: 证伪详情

        Returns:
            bool: 是否成功更新
        """
        try:
            orm_obj = self._model.objects.get(id=signal_id)
            orm_obj.status = 'invalidated'
            orm_obj.invalidated_at = timezone.now()
            orm_obj.invalidation_details = details
            orm_obj.rejection_reason = reason
            orm_obj.save()
            return True
        except self._model.DoesNotExist:
            return False

    def mark_rejected(
        self,
        signal_id: str,
        reason: str
    ) -> bool:
        """
        标记信号为已拒绝

        Args:
            signal_id: 信号 ID
            reason: 拒绝原因

        Returns:
            bool: 是否成功更新
        """
        try:
            orm_obj = self._model.objects.get(id=signal_id)
            orm_obj.status = 'rejected'
            orm_obj.rejection_reason = reason
            orm_obj.save()
            return True
        except self._model.DoesNotExist:
            return False

    def persist_invalidation_outcome(
        self,
        *,
        signal_id: str,
        current_status: str,
        reason: str,
        details: dict[str, Any],
    ) -> bool:
        """Persist a legacy invalidation outcome without exposing ORM to application code."""

        try:
            orm_obj = self._model.objects.get(id=signal_id)
        except self._model.DoesNotExist:
            return False

        orm_obj.invalidation_details = details
        orm_obj.rejection_reason = reason

        if current_status == "pending":
            orm_obj.status = "rejected"
            orm_obj.save(
                update_fields=[
                    "status",
                    "invalidation_details",
                    "rejection_reason",
                    "updated_at",
                ]
            )
            return True

        orm_obj.status = "invalidated"
        orm_obj.invalidated_at = timezone.now()
        orm_obj.save(
            update_fields=[
                "status",
                "invalidated_at",
                "invalidation_details",
                "rejection_reason",
                "updated_at",
            ]
        )
        return True

    def count_by_status(self, status: str) -> int:
        """
        按状态统计信号数量

        Args:
            status: 信号状态

        Returns:
            int: 信号数量
        """
        return self._model.objects.filter(status=status).count()

    def get_signals_created_between(
        self,
        start_datetime,
        end_datetime
    ) -> list[dict]:
        """
        获取指定时间范围内创建的信号（返回字典格式，用于摘要报告）

        Args:
            start_datetime: 开始时间
            end_datetime: 结束时间

        Returns:
            List[dict]: 信号字典列表
        """
        return list(
            self._model.objects.filter(
                created_at__range=[start_datetime, end_datetime]
            ).values('asset_code', 'logic_desc', 'user_id')[:10]
        )

    def get_signals_invalidated_between(
        self,
        start_datetime,
        end_datetime
    ) -> list[dict]:
        """
        获取指定时间范围内证伪的信号（返回字典格式，用于摘要报告）

        Args:
            start_datetime: 开始时间
            end_datetime: 结束时间

        Returns:
            List[dict]: 信号字典列表
        """
        return list(
            self._model.objects.filter(
                invalidated_at__range=[start_datetime, end_datetime]
            ).values('asset_code', 'logic_desc', 'invalidation_details', 'id')[:10]
        )

    def get_old_invalidated_signals(self, days: int) -> list[dict]:
        """
        获取旧的已证伪信号

        Args:
            days: 天数阈值

        Returns:
            List[dict]: 信号字典列表
        """
        from datetime import timedelta
        cutoff_date = timezone.now() - timedelta(days=days)

        return list(
            self._model.objects.filter(
                status='invalidated',
                invalidated_at__lt=cutoff_date
            ).values_list('id', flat=True)
        )

    def get_signals_by_regime(
        self,
        target_regime: str,
        status: SignalStatus | None = None
    ) -> list[InvestmentSignal]:
        """
        按目标 Regime 获取信号

        Args:
            target_regime: 目标 Regime
            status: 状态过滤

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        query = self._model.objects.filter(target_regime=target_regime)

        if status:
            status_value = status.value if isinstance(status, SignalStatus) else status
            query = query.filter(status=status_value)

        query = query.order_by('-created_at')

        return [self._orm_to_entity(obj) for obj in query]

    def update_signal_status(
        self,
        signal_id: str,
        new_status: SignalStatus,
        rejection_reason: str | None = None
    ) -> bool:
        """
        更新信号状态

        Args:
            signal_id: 信号 ID
            new_status: 新状态
            rejection_reason: 拒绝原因（仅 REJECTED 状态）

        Returns:
            bool: 是否成功更新
        """
        try:
            orm_obj = self._model.objects.get(id=signal_id)
            orm_obj.status = new_status.value if isinstance(new_status, SignalStatus) else new_status

            if new_status == SignalStatus.REJECTED and rejection_reason:
                orm_obj.rejection_reason = rejection_reason

            orm_obj.save()
            return True
        except self._model.DoesNotExist:
            return False

    def delete_signal(self, signal_id: str) -> bool:
        """
        删除信号

        Args:
            signal_id: 信号 ID

        Returns:
            bool: 是否成功删除
        """
        count, _ = self._model.objects.filter(id=signal_id).delete()
        return count > 0

    def get_signal_count(
        self,
        status: SignalStatus | None = None
    ) -> int:
        """
        获取信号数量

        Args:
            status: 状态过滤

        Returns:
            int: 信号数量
        """
        query = self._model.objects.all()

        if status:
            status_value = status.value if isinstance(status, SignalStatus) else status
            query = query.filter(status=status_value)

        return query.count()

    def get_user_signals(
        self,
        user_id: int,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[InvestmentSignal]:
        """
        获取用户的投资信号列表

        Args:
            user_id: 用户ID
            status: 状态过滤 (pending, approved, rejected)
            limit: 返回数量限制

        Returns:
            List[InvestmentSignal]: 信号列表
        """
        query = self._model.objects.filter(user_id=user_id).order_by('-created_at')

        if status:
            query = query.filter(status=status)

        if limit:
            query = query[:limit]

        return [self._orm_to_entity(obj) for obj in query]

    def get_statistics(self) -> dict:
        """
        获取信号统计信息

        Returns:
            dict: 统计信息字典
        """
        from django.db.models import Count

        total = self._model.objects.count()

        # 按状态统计
        status_stats = {}
        for status_choice in self._model.STATUS_CHOICES:
            status_value = status_choice[0]
            count = self._model.objects.filter(status=status_value).count()
            status_stats[status_value] = {
                'count': count,
                'percentage': count / total if total > 0 else 0
            }

        # 按资产类别统计
        asset_stats = []
        for item in self._model.objects.values('asset_class').annotate(
            count=Count('id')
        ).order_by('-count'):
            asset_stats.append({
                'asset_class': item['asset_class'],
                'count': item['count']
            })

        return {
            'total': total,
            'by_status': status_stats,
            'by_asset_class': asset_stats
        }

    def get_valid_signal_summaries(self, asset_codes: list[str] | None = None) -> list[dict]:
        query = self._model.objects.filter(status='approved')
        if asset_codes:
            query = query.filter(asset_code__in=asset_codes)
        query = query.order_by('-created_at')
        return list(query.values('id', 'asset_code', 'logic_desc'))

    def get_signal_snapshot(self, signal_id: int) -> dict | None:
        signal = self._model.objects.filter(id=signal_id).values(
            'id', 'asset_code', 'status', 'logic_desc', 'user_id'
        ).first()
        if signal is None:
            return None
        signal['is_valid'] = signal['status'] == 'approved'
        signal['signal_id'] = signal.pop('id')
        return signal

    def get_signal_invalidation_payload(self, signal_id: int) -> tuple[str | None, str]:
        signal = self._model.objects.filter(id=signal_id).values(
            'invalidation_rule_json', 'invalidation_description'
        ).first()
        if signal is None:
            return None, ""
        invalidation_rule_json = None
        if signal.get('invalidation_rule_json'):
            invalidation_rule_json = json.dumps(signal['invalidation_rule_json'], ensure_ascii=False)
        return invalidation_rule_json, (signal.get('invalidation_description') or "")

    def get_invalidation_payloads(self, signal_ids: list[int]) -> dict[str, dict[str, Any]]:
        """批量获取信号证伪载荷。"""
        normalized_ids = [signal_id for signal_id in signal_ids if signal_id]
        if not normalized_ids:
            return {}

        rows = self._model.objects.filter(id__in=normalized_ids).values(
            "id",
            "invalidation_rule_json",
            "invalidation_description",
            "invalidation_logic",
        )
        return {
            str(row["id"]): {
                "invalidation_rule_json": row.get("invalidation_rule_json") or {},
                "invalidation_description": row.get("invalidation_description") or "",
                "invalidation_logic": row.get("invalidation_logic") or "",
            }
            for row in rows
        }

    @staticmethod
    def _serialize_signal_record(signal: InvestmentSignalModel) -> dict[str, Any]:
        """Serialize one investment signal ORM record for interface consumers."""

        return {
            "id": signal.id,
            "asset_code": signal.asset_code,
            "asset_class": signal.asset_class,
            "direction": signal.direction,
            "status": signal.status,
            "logic_desc": signal.logic_desc,
            "invalidation_description": signal.invalidation_description or signal.invalidation_logic,
            "invalidation_rule": signal.invalidation_rule_json or signal.invalidation_rules,
            "human_readable_invalidation": signal.get_human_readable_rules(),
            "target_regime": signal.target_regime,
            "rejection_reason": signal.rejection_reason,
            "created_at": signal.created_at,
            "updated_at": signal.updated_at,
            "invalidated_at": signal.invalidated_at,
            "backtest_performance_score": signal.backtest_performance_score,
            "avg_backtest_return": signal.avg_backtest_return,
        }

    @staticmethod
    def _orm_to_entity(orm_obj: InvestmentSignalModel) -> InvestmentSignal:
        """将 ORM 对象转换为 Domain 实体"""
        from apps.signal.domain.invalidation import InvalidationRule

        # 尝试解析证伪规则
        invalidation_rule = None
        if orm_obj.invalidation_rule_json:
            try:
                invalidation_rule = InvalidationRule.from_dict(orm_obj.invalidation_rule_json)
            except (KeyError, ValueError, TypeError):
                # 解析失败时保持为 None
                pass

        return InvestmentSignal(
            id=str(orm_obj.id),
            asset_code=orm_obj.asset_code,
            asset_class=orm_obj.asset_class,
            direction=orm_obj.direction,
            logic_desc=orm_obj.logic_desc,
            invalidation_rule=invalidation_rule,
            invalidation_description=orm_obj.invalidation_description or orm_obj.invalidation_logic,
            invalidation_logic=orm_obj.invalidation_logic,
            invalidation_threshold=orm_obj.invalidation_threshold,
            target_regime=orm_obj.target_regime,
            created_at=orm_obj.created_at.date() if orm_obj.created_at else None,
            status=SignalStatus(orm_obj.status),
            rejection_reason=orm_obj.rejection_reason,
            backtest_performance_score=orm_obj.backtest_performance_score,
            avg_backtest_return=orm_obj.avg_backtest_return,
        )


class UnifiedSignalRepository:
    """
    统一信号仓储

    管理来自所有模块（Regime、Factor、Rotation、Hedge）的统一信号。
    """

    def __init__(self):
        from .models import UnifiedSignalModel
        self._model = UnifiedSignalModel

    def create_signal(
        self,
        signal_date: date,
        signal_source: str,
        signal_type: str,
        asset_code: str,
        reason: str,
        asset_name: str = "",
        target_weight: float = None,
        current_weight: float = None,
        priority: int = 5,
        action_required: str = "",
        extra_data: dict = None,
        related_signal_id: str = ""
    ) -> dict:
        """
        创建新的统一信号

        Args:
            signal_date: 信号日期
            signal_source: 信号来源 (regime/factor/rotation/hedge/manual)
            signal_type: 信号类型 (buy/sell/rebalance/alert/info)
            asset_code: 资产代码
            reason: 信号原因
            asset_name: 资产名称
            target_weight: 目标权重
            current_weight: 当前权重
            priority: 优先级 (1-10)
            action_required: 所需操作
            extra_data: 额外数据
            related_signal_id: 关联的原始信号ID

        Returns:
            创建的信号字典
        """
        signal = self._model.objects.create(
            signal_date=signal_date,
            signal_source=signal_source,
            signal_type=signal_type,
            asset_code=asset_code,
            asset_name=asset_name,
            target_weight=target_weight,
            current_weight=current_weight,
            priority=priority,
            reason=reason,
            action_required=action_required,
            extra_data=extra_data or {},
            related_signal_id=related_signal_id,
        )

        return self._orm_to_dict(signal)

    def get_signals_by_date(
        self,
        signal_date: date,
        signal_source: str = None,
        signal_type: str = None,
        is_executed: bool = None
    ) -> list:
        """
        按日期获取信号

        Args:
            signal_date: 信号日期
            signal_source: 信号来源过滤
            signal_type: 信号类型过滤
            is_executed: 执行状态过滤

        Returns:
            信号列表
        """
        query = self._model.objects.filter(signal_date=signal_date)

        if signal_source:
            query = query.filter(signal_source=signal_source)
        if signal_type:
            query = query.filter(signal_type=signal_type)
        if is_executed is not None:
            query = query.filter(is_executed=is_executed)

        return [self._orm_to_dict(s) for s in query.order_by('-priority')]

    def get_signals_by_asset(
        self,
        asset_code: str,
        days: int = 30,
        signal_source: str = None
    ) -> list:
        """
        按资产获取最近的信号

        Args:
            asset_code: 资产代码
            days: 查询天数
            signal_source: 信号来源过滤

        Returns:
            信号列表
        """
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days)

        query = self._model.objects.filter(
            asset_code=asset_code,
            signal_date__gte=cutoff_date
        )

        if signal_source:
            query = query.filter(signal_source=signal_source)

        return [self._orm_to_dict(s) for s in query.order_by('-signal_date', '-priority')]

    def get_pending_signals(
        self,
        min_priority: int = 1,
        signal_type: str = None
    ) -> list:
        """
        获取待处理的信号

        Args:
            min_priority: 最低优先级
            signal_type: 信号类型过滤

        Returns:
            待处理信号列表
        """
        query = self._model.objects.filter(
            is_executed=False,
            priority__gte=min_priority
        )

        if signal_type:
            query = query.filter(signal_type=signal_type)

        return [self._orm_to_dict(s) for s in query.order_by('-signal_date', '-priority')]

    def mark_executed(self, signal_id: int) -> bool:
        """
        标记信号为已执行

        Args:
            signal_id: 信号ID

        Returns:
            是否成功
        """
        try:
            signal = self._model.objects.get(id=signal_id)
            signal.mark_executed()
            return True
        except self._model.DoesNotExist:
            return False

    def get_signal_summary(
        self,
        start_date: date,
        end_date: date = None
    ) -> dict:
        """
        获取信号汇总

        Args:
            start_date: 开始日期
            end_date: 结束日期（默认今天）

        Returns:
            汇总信息
        """
        if end_date is None:
            end_date = date.today()

        query = self._model.objects.filter(
            signal_date__gte=start_date,
            signal_date__lte=end_date
        )

        total = query.count()
        executed = query.filter(is_executed=True).count()
        pending = total - executed

        # 按来源统计
        by_source = {}
        for source, _ in self._model.SIGNAL_SOURCE_CHOICES:
            count = query.filter(signal_source=source).count()
            by_source[source] = count

        # 按类型统计
        by_type = {}
        for signal_type, _ in self._model.SIGNAL_TYPE_CHOICES:
            count = query.filter(signal_type=signal_type).count()
            by_type[signal_type] = count

        # 高优先级信号
        high_priority = query.filter(priority__gte=7, is_executed=False).count()

        return {
            'total': total,
            'executed': executed,
            'pending': pending,
            'by_source': by_source,
            'by_type': by_type,
            'high_priority_count': high_priority,
        }

    def delete_old_signals(self, days_to_keep: int = 90) -> int:
        """
        删除旧信号

        Args:
            days_to_keep: 保留天数

        Returns:
            删除的信号数量
        """
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days_to_keep)

        count, _ = self._model.objects.filter(
            signal_date__lt=cutoff_date,
            is_executed=True
        ).delete()

        return count

    @staticmethod
    def _orm_to_dict(orm_obj) -> dict:
        """将 ORM 对象转换为字典"""
        return {
            'id': orm_obj.id,
            'signal_date': orm_obj.signal_date.isoformat(),
            'signal_source': orm_obj.signal_source,
            'signal_type': orm_obj.signal_type,
            'asset_code': orm_obj.asset_code,
            'asset_name': orm_obj.asset_name,
            'target_weight': float(orm_obj.target_weight) if orm_obj.target_weight else None,
            'current_weight': float(orm_obj.current_weight) if orm_obj.current_weight else None,
            'priority': orm_obj.priority,
            'is_executed': orm_obj.is_executed,
            'executed_at': orm_obj.executed_at.isoformat() if orm_obj.executed_at else None,
            'reason': orm_obj.reason,
            'action_required': orm_obj.action_required,
            'extra_data': orm_obj.extra_data,
            'related_signal_id': orm_obj.related_signal_id,
            'created_at': orm_obj.created_at.isoformat(),
        }


class DjangoUserRepository:
    """
    Django ORM 实现的用户仓储

    提供用户相关的数据访问操作。
    """

    def __init__(self):
        from django.contrib.auth import get_user_model
        self._model = get_user_model()

    def get_staff_emails(self) -> list[str]:
        """
        获取所有活跃 staff 用户的邮箱

        Returns:
            List[str]: 邮箱列表
        """
        return list(
            self._model.objects.filter(
                is_staff=True,
                is_active=True
            ).exclude(
                email=''
            ).values_list('email', flat=True)
        )

    def get_user_by_id(self, user_id: int) -> Any | None:
        """
        通过 ID 获取用户

        Args:
            user_id: 用户 ID

        Returns:
            用户对象或 None
        """
        try:
            return self._model.objects.get(id=user_id)
        except self._model.DoesNotExist:
            return None

    def get_user_email(self, user_id: int) -> str | None:
        """
        获取用户邮箱

        Args:
            user_id: 用户 ID

        Returns:
            邮箱地址或 None
        """
        try:
            user = self._model.objects.get(id=user_id)
            return user.email if user.email else None
        except self._model.DoesNotExist:
            return None
