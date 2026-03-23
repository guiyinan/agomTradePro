"""
Share Application Use Cases

用例编排层，协调 Domain 层和 Infrastructure 层完成业务用例。
"""
from datetime import datetime
from typing import List, Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.share.domain.entities import (
    AccessResultStatus,
    ShareLevel,
    ShareLinkEntity,
    ShareStatus,
    ShareTheme,
)
from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareLinkModel,
    ShareSnapshotModel,
)

User = get_user_model()


class ShareLinkUseCases:
    """
    分享链接用例

    处理分享链接的创建、查询、更新、撤销等操作。
    """

    def create_share_link(
        self,
        owner_id: int,
        account_id: int,
        title: str,
        subtitle: str | None = None,
        theme: str = "bloomberg",
        share_level: str = "snapshot",
        password: str | None = None,
        expires_at: datetime | None = None,
        max_access_count: int | None = None,
        allow_indexing: bool = False,
        show_amounts: bool = False,
        show_positions: bool = True,
        show_transactions: bool = True,
        show_decision_summary: bool = True,
        show_decision_evidence: bool = False,
        show_invalidation_logic: bool = False,
        short_code: str | None = None,
    ) -> ShareLinkEntity:
        """
        创建分享链接

        Args:
            owner_id: 所有者用户 ID
            account_id: 关联的模拟账户 ID
            title: 标题
            subtitle: 副标题
            theme: 页面风格
            share_level: 分享级别
            password: 访问密码（明文，将在方法内哈希）
            expires_at: 过期时间
            max_access_count: 最大访问次数
            allow_indexing: 是否允许搜索引擎索引
            show_amounts: 是否显示金额
            show_positions: 是否显示持仓
            show_transactions: 是否显示交易
            show_decision_summary: 是否显示决策摘要
            show_decision_evidence: 是否显示决策依据
            show_invalidation_logic: 是否显示证伪逻辑
            short_code: 预设短码（仅用于测试，通常应为 None）

        Returns:
            ShareLinkEntity

        Raises:
            ValidationError: 验证失败
        """
        from apps.share.domain.services import generate_short_code

        # 验证账户存在
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
        try:
            account = SimulatedAccountModel.objects.get(id=account_id)
        except SimulatedAccountModel.DoesNotExist:
            raise ValidationError({"account_id": "模拟账户不存在"})

        # 验证用户
        try:
            user = User.objects.get(id=owner_id)
        except User.DoesNotExist:
            raise ValidationError({"owner_id": "用户不存在"})

        # 生成或验证短码
        if short_code is None:
            # 生成唯一短码
            for _ in range(10):  # 最多尝试10次
                code = generate_short_code(10)
                if not ShareLinkModel.objects.filter(short_code=code).exists():
                    short_code = code
                    break
            else:
                raise ValidationError("无法生成唯一短码，请稍后重试")
        else:
            # 验证预设短码格式和唯一性
            if ShareLinkModel.objects.filter(short_code=short_code).exists():
                raise ValidationError({"short_code": "短码已存在"})

        # 处理密码哈希
        password_hash = None
        if password:
            from django.contrib.auth.hashers import make_password
            password_hash = make_password(password)

        # 创建模型实例
        model = ShareLinkModel.objects.create(
            owner_id=owner_id,
            account_id=account_id,
            short_code=short_code,
            title=title,
            subtitle=subtitle,
            theme=theme,
            share_level=share_level,
            status="active",
            password_hash=password_hash,
            expires_at=expires_at,
            max_access_count=max_access_count,
            access_count=0,
            allow_indexing=allow_indexing,
            show_amounts=show_amounts,
            show_positions=show_positions,
            show_transactions=show_transactions,
            show_decision_summary=show_decision_summary,
            show_decision_evidence=show_decision_evidence,
            show_invalidation_logic=show_invalidation_logic,
        )

        return self._model_to_entity(model)

    def get_share_link(self, share_link_id: int) -> ShareLinkEntity | None:
        """
        获取分享链接

        Args:
            share_link_id: 分享链接 ID

        Returns:
            ShareLinkEntity 或 None
        """
        try:
            model = ShareLinkModel.objects.get(id=share_link_id)
            return self._model_to_entity(model)
        except ShareLinkModel.DoesNotExist:
            return None

    def get_share_link_by_code(self, short_code: str) -> ShareLinkEntity | None:
        """
        通过短码获取分享链接

        Args:
            short_code: 短码

        Returns:
            ShareLinkEntity 或 None
        """
        try:
            model = ShareLinkModel.objects.get(short_code=short_code)
            return self._model_to_entity(model)
        except ShareLinkModel.DoesNotExist:
            return None

    def list_share_links(
        self,
        owner_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
        share_level: str | None = None,
    ) -> list[ShareLinkEntity]:
        """
        列出分享链接

        Args:
            owner_id: 按所有者过滤
            account_id: 按账户过滤
            status: 按状态过滤
            share_level: 按分享级别过滤

        Returns:
            ShareLinkEntity 列表
        """
        queryset = ShareLinkModel.objects.all()

        if owner_id is not None:
            queryset = queryset.filter(owner_id=owner_id)
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        if status is not None:
            queryset = queryset.filter(status=status)
        if share_level is not None:
            queryset = queryset.filter(share_level=share_level)

        return [self._model_to_entity(m) for m in queryset]

    def update_share_link(
        self,
        share_link_id: int,
        owner_id: int,
        title: str | None = None,
        subtitle: str | None = None,
        theme: str | None = None,
        share_level: str | None = None,
        password: str | None = None,
        expires_at: datetime | None = None,
        max_access_count: int | None = None,
        allow_indexing: bool | None = None,
        show_amounts: bool | None = None,
        show_positions: bool | None = None,
        show_transactions: bool | None = None,
        show_decision_summary: bool | None = None,
        show_decision_evidence: bool | None = None,
        show_invalidation_logic: bool | None = None,
    ) -> ShareLinkEntity | None:
        """
        更新分享链接

        Args:
            share_link_id: 分享链接 ID
            owner_id: 所有者用户 ID（用于权限验证）
            其他参数同 create_share_link

        Returns:
            更新后的 ShareLinkEntity 或 None

        Raises:
            ValidationError: 验证失败
        """
        try:
            model = ShareLinkModel.objects.get(id=share_link_id)
        except ShareLinkModel.DoesNotExist:
            return None

        # 验证权限
        if model.owner_id != owner_id:
            raise ValidationError("无权修改此分享链接")

        # 更新字段
        update_fields = []

        if title is not None:
            model.title = title
            update_fields.append("title")
        if subtitle is not None:
            model.subtitle = subtitle
            update_fields.append("subtitle")
        if theme is not None:
            model.theme = theme
            update_fields.append("theme")
        if share_level is not None:
            model.share_level = share_level
            update_fields.append("share_level")
        if expires_at is not None:
            model.expires_at = expires_at
            update_fields.append("expires_at")
        if max_access_count is not None:
            model.max_access_count = max_access_count
            update_fields.append("max_access_count")
        if allow_indexing is not None:
            model.allow_indexing = allow_indexing
            update_fields.append("allow_indexing")
        if show_amounts is not None:
            model.show_amounts = show_amounts
            update_fields.append("show_amounts")
        if show_positions is not None:
            model.show_positions = show_positions
            update_fields.append("show_positions")
        if show_transactions is not None:
            model.show_transactions = show_transactions
            update_fields.append("show_transactions")
        if show_decision_summary is not None:
            model.show_decision_summary = show_decision_summary
            update_fields.append("show_decision_summary")
        if show_decision_evidence is not None:
            model.show_decision_evidence = show_decision_evidence
            update_fields.append("show_decision_evidence")
        if show_invalidation_logic is not None:
            model.show_invalidation_logic = show_invalidation_logic
            update_fields.append("show_invalidation_logic")

        # 处理密码
        if password is not None:
            if password == "":
                # 清除密码
                model.password_hash = None
            else:
                from django.contrib.auth.hashers import make_password
                model.password_hash = make_password(password)
            update_fields.append("password_hash")

        if update_fields:
            model.save(update_fields=update_fields)

        return self._model_to_entity(model)

    def revoke_share_link(self, share_link_id: int, owner_id: int) -> bool:
        """
        撤销分享链接

        Args:
            share_link_id: 分享链接 ID
            owner_id: 所有者用户 ID

        Returns:
            是否成功
        """
        try:
            model = ShareLinkModel.objects.get(id=share_link_id, owner_id=owner_id)
            model.status = "revoked"
            model.save(update_fields=["status"])
            return True
        except ShareLinkModel.DoesNotExist:
            return False

    def delete_share_link(self, share_link_id: int, owner_id: int) -> bool:
        """
        删除分享链接

        Args:
            share_link_id: 分享链接 ID
            owner_id: 所有者用户 ID

        Returns:
            是否成功
        """
        try:
            model = ShareLinkModel.objects.get(id=share_link_id, owner_id=owner_id)
            model.delete()
            return True
        except ShareLinkModel.DoesNotExist:
            return False

    def verify_password(self, share_link_id: int, password: str) -> bool:
        """
        验证访问密码

        Args:
            share_link_id: 分享链接 ID
            password: 密码（明文）

        Returns:
            是否正确
        """
        try:
            model = ShareLinkModel.objects.get(id=share_link_id)
            if not model.password_hash:
                return True  # 无密码即通过
            from django.contrib.auth.hashers import check_password
            return check_password(password, model.password_hash)
        except ShareLinkModel.DoesNotExist:
            return False

    def _model_to_entity(self, model: ShareLinkModel) -> ShareLinkEntity:
        """将 ORM 模型转换为 Domain 实体"""
        return ShareLinkEntity(
            id=model.id,
            owner_id=model.owner_id,
            account_id=model.account_id,
            short_code=model.short_code,
            title=model.title,
            subtitle=model.subtitle,
            theme=ShareTheme(model.theme),
            share_level=ShareLevel(model.share_level),
            status=ShareStatus(model.status),
            password_hash=model.password_hash,
            expires_at=model.expires_at,
            max_access_count=model.max_access_count,
            access_count=model.access_count,
            last_snapshot_at=model.last_snapshot_at,
            last_accessed_at=model.last_accessed_at,
            allow_indexing=model.allow_indexing,
            show_amounts=model.show_amounts,
            show_positions=model.show_positions,
            show_transactions=model.show_transactions,
            show_decision_summary=model.show_decision_summary,
            show_decision_evidence=model.show_decision_evidence,
            show_invalidation_logic=model.show_invalidation_logic,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class ShareSnapshotUseCases:
    """
    分享快照用例

    处理快照的创建、查询等操作。
    """

    def create_snapshot(
        self,
        share_link_id: int,
        summary_payload: dict,
        performance_payload: dict,
        positions_payload: dict,
        transactions_payload: dict,
        decision_payload: dict,
        source_range_start: datetime | None = None,
        source_range_end: datetime | None = None,
    ) -> int | None:
        """
        创建快照

        Args:
            share_link_id: 分享链接 ID
            summary_payload: 摘要数据
            performance_payload: 绩效数据
            positions_payload: 持仓数据
            transactions_payload: 交易数据
            decision_payload: 决策数据
            source_range_start: 数据起始日期
            source_range_end: 数据结束日期

        Returns:
            快照 ID 或 None
        """
        try:
            share_link = ShareLinkModel.objects.get(id=share_link_id)

            # 获取当前最大版本号
            last_version = (
                ShareSnapshotModel.objects.filter(share_link_id=share_link_id)
                .order_by('-snapshot_version')
                .values_list('snapshot_version', flat=True)
                .first()
            )

            next_version = (last_version + 1) if last_version is not None else 1

            snapshot = ShareSnapshotModel.objects.create(
                share_link=share_link,
                snapshot_version=next_version,
                summary_payload=summary_payload or {},
                performance_payload=performance_payload or {},
                positions_payload=positions_payload or {},
                transactions_payload=transactions_payload or {},
                decision_payload=decision_payload or {},
                source_range_start=source_range_start,
                source_range_end=source_range_end,
            )

            # 更新分享链接的最后快照时间
            share_link.last_snapshot_at = timezone.now()
            share_link.save(update_fields=['last_snapshot_at'])

            return snapshot.id

        except ShareLinkModel.DoesNotExist:
            return None

    def get_latest_snapshot(self, share_link_id: int) -> dict | None:
        """
        获取最新快照

        Args:
            share_link_id: 分享链接 ID

        Returns:
            快照数据字典或 None
        """
        try:
            snapshot = ShareSnapshotModel.objects.filter(
                share_link_id=share_link_id
            ).order_by('-snapshot_version').first()

            if not snapshot:
                return None

            return {
                "id": snapshot.id,
                "snapshot_version": snapshot.snapshot_version,
                "summary": snapshot.summary_payload,
                "performance": snapshot.performance_payload,
                "positions": snapshot.positions_payload,
                "transactions": snapshot.transactions_payload,
                "decisions": snapshot.decision_payload,
                "generated_at": snapshot.generated_at,
                "source_range_start": snapshot.source_range_start,
                "source_range_end": snapshot.source_range_end,
            }

        except ShareSnapshotModel.DoesNotExist:
            return None


class ShareAccessUseCases:
    """
    分享访问用例

    处理访问验证、日志记录等操作。
    """

    def log_access(
        self,
        share_link_id: int,
        ip_address: str,
        user_agent: str | None = None,
        referer: str | None = None,
        result_status: str = "success",
        is_verified: bool = False,
    ) -> int:
        """
        记录访问日志

        Args:
            share_link_id: 分享链接 ID
            ip_address: 访问者 IP
            user_agent: 用户代理
            referer: 来源页面
            result_status: 访问结果
            is_verified: 是否通过验证

        Returns:
            日志 ID
        """
        import hashlib

        # 对 IP 进行哈希
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()

        log = ShareAccessLogModel.objects.create(
            share_link_id=share_link_id,
            ip_hash=ip_hash,
            user_agent=user_agent,
            referer=referer,
            is_verified=is_verified,
            result_status=result_status,
        )

        return log.id

    def get_access_logs(
        self,
        share_link_id: int,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取访问日志

        Args:
            share_link_id: 分享链接 ID
            limit: 返回数量限制

        Returns:
            日志列表
        """
        logs = ShareAccessLogModel.objects.filter(
            share_link_id=share_link_id
        ).order_by('-accessed_at')[:limit]

        return [
            {
                "id": log.id,
                "accessed_at": log.accessed_at,
                "ip_hash": log.ip_hash,
                "user_agent": log.user_agent,
                "referer": log.referer,
                "is_verified": log.is_verified,
                "result_status": log.result_status,
            }
            for log in logs
        ]

    def get_access_stats(self, share_link_id: int) -> dict:
        """
        获取访问统计

        Args:
            share_link_id: 分享链接 ID

        Returns:
            统计数据
        """
        logs = ShareAccessLogModel.objects.filter(share_link_id=share_link_id)

        total = logs.count()
        successful = logs.filter(result_status="success").count()
        unique_visitors = logs.values("ip_hash").distinct().count()

        return {
            "total_accesses": total,
            "successful_accesses": successful,
            "unique_visitors": unique_visitors,
        }
