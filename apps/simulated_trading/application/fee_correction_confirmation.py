"""Session-bound confirmation contracts for simulated fee correction previews."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
)
from apps.simulated_trading.application.fee_correction_preview import (
    FeeCorrectionPreviewCommand,
    FeeCorrectionPreviewInput,
    FeeCorrectionPreviewResult,
    FeeCorrectionRecoveryPreviewCommand,
)


@dataclass(frozen=True, slots=True)
class BrowserContext:
    """Request-derived database session facts; secrets are excluded from repr/equality."""

    actor_user_id: int
    session_key: str = field(repr=False, compare=False)
    auth_backend: str
    auth_session_hash: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """Reject malformed request facts before Infrastructure loads a session row."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise FeeCorrectionBlockedError(
                "浏览器会话主体无效", code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID"
            )
        if (
            type(self.session_key) is not str
            or not self.session_key
            or len(self.session_key) > 40
            or self.session_key.strip() != self.session_key
            or any(character.isspace() for character in self.session_key)
        ):
            raise FeeCorrectionBlockedError(
                "浏览器会话不可用", code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID"
            )
        if (
            type(self.auth_backend) is not str
            or not self.auth_backend
            or len(self.auth_backend) > 255
            or self.auth_backend.strip() != self.auth_backend
            or any(character.isspace() for character in self.auth_backend)
        ):
            raise FeeCorrectionBlockedError(
                "浏览器认证后端无效", code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID"
            )
        if (
            type(self.auth_session_hash) is not str
            or not self.auth_session_hash
            or len(self.auth_session_hash) > 256
            or self.auth_session_hash.strip() != self.auth_session_hash
        ):
            raise FeeCorrectionBlockedError(
                "浏览器认证摘要无效", code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID"
            )


@dataclass(frozen=True, slots=True)
class FeeCorrectionConfirmationCommand:
    """Confirm one exact account/trade/key using its opaque session-bound token."""

    account_id: int
    trade_id: int
    idempotency_key: str = field(repr=False)
    confirmation_token: str = field(repr=False)

    def __post_init__(self) -> None:
        """Validate route identity and bound opaque confirmation inputs."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.trade_id) is not int
            or self.trade_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用更正确认账户或成交无效",
                code="FEE_CORRECTION_CONFIRMATION_INPUT_INVALID",
            )
        if (
            type(self.idempotency_key) is not str
            or not self.idempotency_key
            or self.idempotency_key.strip() != self.idempotency_key
            or len(self.idempotency_key) > 128
            or any(character.isspace() for character in self.idempotency_key)
        ):
            raise FeeCorrectionBlockedError(
                "费用更正确认幂等键无效",
                code="FEE_CORRECTION_CONFIRMATION_INPUT_INVALID",
            )
        if (
            type(self.confirmation_token) is not str
            or not self.confirmation_token
            or len(self.confirmation_token) > 32768
            or not self.confirmation_token.isascii()
            or any(character.isspace() for character in self.confirmation_token)
        ):
            raise FeeCorrectionBlockedError(
                "费用更正确认令牌无效",
                code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
            )


@dataclass(frozen=True, slots=True)
class FeeCorrectionConfirmationPrepareResult:
    """Preview response and its original confirmation window, when pending."""

    preview: FeeCorrectionPreviewResult
    confirmation_token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        """Require one token window for pending previews and none for completed keys."""

        if type(self.preview) is not FeeCorrectionPreviewResult:
            raise FeeCorrectionBlockedError(
                "费用更正准备结果无效", code="FEE_CORRECTION_CONFIRMATION_INVALID"
            )
        if self.preview.status == "already_applied":
            if self.confirmation_token is not None or self.expires_at is not None:
                raise FeeCorrectionBlockedError(
                    "已完成请求不能签发新的确认令牌",
                    code="FEE_CORRECTION_CONFIRMATION_INVALID",
                )
            return
        if (
            type(self.confirmation_token) is not str
            or not self.confirmation_token
            or len(self.confirmation_token) > 32768
            or type(self.expires_at) is not datetime
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise FeeCorrectionBlockedError(
                "费用更正确认令牌或期限无效",
                code="FEE_CORRECTION_CONFIRMATION_INVALID",
            )


class FeeCorrectionConfirmationRepositoryProtocol(Protocol):
    """Prepare an exact preview or confirm its original session-bound token."""

    def prepare_preview(
        self,
        command: FeeCorrectionPreviewInput,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        browser_context: BrowserContext,
    ) -> FeeCorrectionConfirmationPrepareResult:
        """Prepare evidence and issue a token only for an unfinished preview."""
        ...

    def confirm(
        self,
        command: FeeCorrectionConfirmationCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        browser_context: BrowserContext,
    ) -> FeeCorrectionReceipt:
        """Revalidate and atomically apply the preview's original request."""
        ...


class FeeCorrectionConfirmationUseCase:
    """Validate actor/context agreement and delegate session-bound confirmation."""

    def __init__(self, repository: FeeCorrectionConfirmationRepositoryProtocol) -> None:
        """Use the supplied database-backed confirmation repository."""

        self._repository = repository

    def prepare_preview(
        self,
        command: FeeCorrectionPreviewInput,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        browser_context: BrowserContext,
    ) -> FeeCorrectionConfirmationPrepareResult:
        """Prepare a preview for the exact authenticated browser session."""

        if type(command) not in (FeeCorrectionPreviewCommand, FeeCorrectionRecoveryPreviewCommand):
            raise FeeCorrectionBlockedError(
                "费用更正预览命令无效", code="FEE_CORRECTION_PREVIEW_INVALID"
            )
        command.__post_init__()
        _validate_principal_context(principal, browser_context)
        return self._repository.prepare_preview(
            command,
            principal=principal,
            browser_context=browser_context,
        )

    def confirm(
        self,
        command: FeeCorrectionConfirmationCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        browser_context: BrowserContext,
    ) -> FeeCorrectionReceipt:
        """Confirm one preview without allowing client-selected fee or revision data."""

        if type(command) is not FeeCorrectionConfirmationCommand:
            raise FeeCorrectionBlockedError(
                "费用更正确认命令无效",
                code="FEE_CORRECTION_CONFIRMATION_INPUT_INVALID",
            )
        command.__post_init__()
        _validate_principal_context(principal, browser_context)
        return self._repository.confirm(
            command,
            principal=principal,
            browser_context=browser_context,
        )


def _validate_principal_context(
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    browser_context: BrowserContext,
) -> None:
    """Require the server-derived session context to name the request principal."""

    if type(browser_context) is not BrowserContext:
        raise FeeCorrectionBlockedError(
            "费用更正确认缺少真实浏览器会话上下文",
            code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
        )
    browser_context.__post_init__()
    principal_id = getattr(principal, "pk", None)
    if (
        getattr(principal, "is_authenticated", None) is not True
        or type(principal_id) is not int
        or principal_id != browser_context.actor_user_id
    ):
        raise FeeCorrectionBlockedError(
            "费用更正确认主体与浏览器会话不匹配",
            code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
        )


__all__ = [
    "BrowserContext",
    "FeeCorrectionConfirmationCommand",
    "FeeCorrectionConfirmationPrepareResult",
    "FeeCorrectionConfirmationRepositoryProtocol",
    "FeeCorrectionConfirmationUseCase",
]
