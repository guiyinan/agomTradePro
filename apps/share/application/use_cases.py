"""
Share Application Use Cases

用例编排层，协调 Domain 层和 Infrastructure 层完成业务用例。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, TypeAlias

from django.core.exceptions import ValidationError

from apps.share.application.repository_provider import get_share_application_repository
from apps.share.domain.entities import (
    AccessResultStatus,
    ShareLevel,
    ShareLinkEntity,
    ShareTheme,
)
from apps.share.domain.interfaces import ShareApplicationRepositoryProtocol
from apps.share.domain.services import validate_short_code

JsonPayload: TypeAlias = dict[str, Any]


class _UnsetType:
    """Marker used to distinguish omitted updates from explicit null values."""


_UNSET = _UnsetType()


def _validate_title(title: str) -> str:
    """Return a normalized non-empty public title within the storage limit."""
    normalized = title.strip()
    if not normalized or len(normalized) > 100:
        raise ValidationError({"title": "标题必须为 1-100 个字符"})
    return normalized


def _validate_optional_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> None:
    """Validate an optional text field before persistence."""
    if value is not None and len(value) > max_length:
        raise ValidationError({field_name: f"长度不得超过 {max_length} 个字符"})


def _validate_share_choices(*, theme: str, share_level: str) -> None:
    """Validate public enum values before the repository mutates state."""
    try:
        ShareTheme(theme)
    except ValueError as exc:
        raise ValidationError({"theme": "不支持的页面风格"}) from exc
    try:
        ShareLevel(share_level)
    except ValueError as exc:
        raise ValidationError({"share_level": "不支持的分享级别"}) from exc


def _validate_expiration(expires_at: datetime | None) -> None:
    """Require a timezone-aware future expiration when configured."""
    if expires_at is None:
        return
    if expires_at.utcoffset() is None:
        raise ValidationError({"expires_at": "过期时间必须包含时区"})
    if expires_at <= datetime.now(UTC):
        raise ValidationError({"expires_at": "过期时间必须晚于当前时间"})


def _validate_max_access_count(max_access_count: int | None) -> None:
    """Require a positive non-boolean access limit when configured."""
    if max_access_count is None:
        return
    if isinstance(max_access_count, bool) or max_access_count < 1:
        raise ValidationError({"max_access_count": "最大访问次数必须为正整数"})


def _validate_json_payload(payload: JsonPayload, *, field_name: str) -> None:
    """Reject non-object, non-serializable, or non-finite public snapshot data."""
    if not isinstance(payload, dict):
        raise ValidationError({field_name: "快照数据必须为 JSON 对象"})
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "快照数据必须可序列化且不得包含 NaN/Inf"}) from exc


class ShareLinkUseCases:
    """
    分享链接用例

    处理分享链接的创建、查询、更新、撤销等操作。
    """

    def __init__(
        self,
        repository: ShareApplicationRepositoryProtocol | None = None,
    ) -> None:
        """Initialize the use case with an injectable repository."""

        self._repository = repository or get_share_application_repository()

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

        title = _validate_title(title)
        _validate_optional_text(subtitle, field_name="subtitle", max_length=200)
        _validate_optional_text(password, field_name="password", max_length=128)
        _validate_share_choices(theme=theme, share_level=share_level)
        _validate_expiration(expires_at)
        _validate_max_access_count(max_access_count)

        if not self._repository.user_exists(owner_id):
            raise ValidationError({"owner_id": "用户不存在"})

        if not self._repository.account_belongs_to_owner(owner_id=owner_id, account_id=account_id):
            raise ValidationError({"account_id": "模拟账户不存在或无权分享此账户"})

        if short_code is None:
            for _ in range(10):
                code = generate_short_code(10)
                if not self._repository.share_link_short_code_exists(code):
                    short_code = code
                    break
            else:
                raise ValidationError("无法生成唯一短码，请稍后重试")
        else:
            if not validate_short_code(short_code, min_length=6, max_length=16):
                raise ValidationError({"short_code": "短码必须为 6-16 位字母或数字"})
            if self._repository.share_link_short_code_exists(short_code):
                raise ValidationError({"short_code": "短码已存在"})

        password_hash = None
        if password:
            from django.contrib.auth.hashers import make_password

            password_hash = make_password(password)

        return self._repository.create_share_link(
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

    def get_share_link(self, share_link_id: int) -> ShareLinkEntity | None:
        """
        获取分享链接

        Args:
            share_link_id: 分享链接 ID

        Returns:
            ShareLinkEntity 或 None
        """
        return self._repository.get_share_link(share_link_id)

    def get_share_link_by_code(self, short_code: str) -> ShareLinkEntity | None:
        """
        通过短码获取分享链接

        Args:
            short_code: 短码

        Returns:
            ShareLinkEntity 或 None
        """
        return self._repository.get_share_link_by_code(short_code)

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
        return self._repository.list_share_links(
            owner_id=owner_id,
            account_id=account_id,
            status=status,
            share_level=share_level,
        )

    def update_share_link(
        self,
        share_link_id: int,
        owner_id: int,
        title: str | None = None,
        subtitle: str | None | _UnsetType = _UNSET,
        theme: str | None = None,
        share_level: str | None = None,
        password: str | None = None,
        expires_at: datetime | None | _UnsetType = _UNSET,
        max_access_count: int | None | _UnsetType = _UNSET,
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
        existing = self._repository.get_share_link(share_link_id)
        if existing is None:
            return None

        if existing.owner_id != owner_id:
            raise ValidationError("无权修改此分享链接")

        updates: dict[str, object] = {}
        if title is not None:
            updates["title"] = _validate_title(title)
        if not isinstance(subtitle, _UnsetType):
            _validate_optional_text(subtitle, field_name="subtitle", max_length=200)
            updates["subtitle"] = subtitle
        if theme is not None:
            _validate_share_choices(
                theme=theme,
                share_level=share_level or existing.share_level.value,
            )
            updates["theme"] = theme
        if share_level is not None:
            _validate_share_choices(
                theme=theme or existing.theme.value,
                share_level=share_level,
            )
            updates["share_level"] = share_level
        if not isinstance(expires_at, _UnsetType):
            _validate_expiration(expires_at)
            updates["expires_at"] = expires_at
        if not isinstance(max_access_count, _UnsetType):
            _validate_max_access_count(max_access_count)
            updates["max_access_count"] = max_access_count
        if allow_indexing is not None:
            updates["allow_indexing"] = allow_indexing
        if show_amounts is not None:
            updates["show_amounts"] = show_amounts
        if show_positions is not None:
            updates["show_positions"] = show_positions
        if show_transactions is not None:
            updates["show_transactions"] = show_transactions
        if show_decision_summary is not None:
            updates["show_decision_summary"] = show_decision_summary
        if show_decision_evidence is not None:
            updates["show_decision_evidence"] = show_decision_evidence
        if show_invalidation_logic is not None:
            updates["show_invalidation_logic"] = show_invalidation_logic

        if password is not None:
            _validate_optional_text(password, field_name="password", max_length=128)
            if password == "":
                updates["password_hash"] = None
            else:
                from django.contrib.auth.hashers import make_password

                updates["password_hash"] = make_password(password)
        if not updates:
            return existing
        return self._repository.update_share_link_fields(
            share_link_id=share_link_id,
            updates=updates,
        )

    def revoke_share_link(self, share_link_id: int, owner_id: int) -> bool:
        """
        撤销分享链接

        Args:
            share_link_id: 分享链接 ID
            owner_id: 所有者用户 ID

        Returns:
            是否成功
        """
        return self._repository.revoke_share_link(
            share_link_id=share_link_id,
            owner_id=owner_id,
        )

    def delete_share_link(self, share_link_id: int, owner_id: int) -> bool:
        """
        删除分享链接

        Args:
            share_link_id: 分享链接 ID
            owner_id: 所有者用户 ID

        Returns:
            是否成功
        """
        return self._repository.delete_share_link(
            share_link_id=share_link_id,
            owner_id=owner_id,
        )

    def verify_password(self, share_link_id: int, password: str) -> bool:
        """
        验证访问密码

        Args:
            share_link_id: 分享链接 ID
            password: 密码（明文）

        Returns:
            是否正确
        """
        share_link = self._repository.get_share_link(share_link_id)
        if share_link is None:
            return False
        if not share_link.password_hash:
            return True
        from django.contrib.auth.hashers import check_password

        return check_password(password, share_link.password_hash)


class ShareSnapshotUseCases:
    """
    分享快照用例

    处理快照的创建、查询等操作。
    """

    def __init__(
        self,
        repository: ShareApplicationRepositoryProtocol | None = None,
    ) -> None:
        """Initialize the use case with an injectable repository."""

        self._repository = repository or get_share_application_repository()

    def create_snapshot(
        self,
        share_link_id: int,
        summary_payload: JsonPayload,
        performance_payload: JsonPayload,
        positions_payload: JsonPayload,
        transactions_payload: JsonPayload,
        decision_payload: JsonPayload,
        source_range_start: date | None = None,
        source_range_end: date | None = None,
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
        payloads = {
            "summary_payload": summary_payload,
            "performance_payload": performance_payload,
            "positions_payload": positions_payload,
            "transactions_payload": transactions_payload,
            "decision_payload": decision_payload,
        }
        for field_name, payload in payloads.items():
            _validate_json_payload(payload, field_name=field_name)
        if (
            source_range_start is not None
            and source_range_end is not None
            and source_range_start > source_range_end
        ):
            raise ValidationError({"source_range_end": "数据结束日期不得早于起始日期"})
        return self._repository.create_snapshot(
            share_link_id=share_link_id,
            summary_payload=summary_payload,
            performance_payload=performance_payload,
            positions_payload=positions_payload,
            transactions_payload=transactions_payload,
            decision_payload=decision_payload,
            source_range_start=source_range_start,
            source_range_end=source_range_end,
        )

    def get_latest_snapshot(self, share_link_id: int) -> JsonPayload | None:
        """
        获取最新快照

        Args:
            share_link_id: 分享链接 ID

        Returns:
            快照数据字典或 None
        """
        return self._repository.get_latest_snapshot(share_link_id)


class ShareAccessUseCases:
    """
    分享访问用例

    处理访问验证、日志记录等操作。
    """

    def __init__(
        self,
        repository: ShareApplicationRepositoryProtocol | None = None,
    ) -> None:
        """Initialize the use case with an injectable repository."""

        self._repository = repository or get_share_application_repository()

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

        try:
            AccessResultStatus(result_status)
        except ValueError as exc:
            raise ValidationError({"result_status": "不支持的访问结果状态"}) from exc
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()
        return self._repository.log_access(
            share_link_id=share_link_id,
            ip_hash=ip_hash,
            user_agent=user_agent,
            referer=referer,
            is_verified=is_verified,
            result_status=result_status,
        )

    def get_access_logs(
        self,
        share_link_id: int,
        limit: int = 100,
    ) -> list[JsonPayload]:
        """
        获取访问日志

        Args:
            share_link_id: 分享链接 ID
            limit: 返回数量限制

        Returns:
            日志列表
        """
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValidationError({"limit": "返回数量必须为 1-1000 的整数"})
        return self._repository.get_access_logs(
            share_link_id=share_link_id,
            limit=limit,
        )

    def get_access_stats(self, share_link_id: int) -> dict[str, int]:
        """
        获取访问统计

        Args:
            share_link_id: 分享链接 ID

        Returns:
            统计数据
        """
        return self._repository.get_access_stats(share_link_id=share_link_id)
