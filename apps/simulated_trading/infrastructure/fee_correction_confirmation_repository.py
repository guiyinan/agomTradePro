"""Encrypted browser-session confirmation for simulated fee correction previews."""

from __future__ import annotations

import hashlib
import json
import re
from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NoReturn, cast

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.simulated_trading.application.fee_correction import (
    ApplySimulatedFeeCorrectionUseCase,
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionClockProtocol,
    FeeCorrectionReceipt,
    FeeCorrectionRepositoryProtocol,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_confirmation import (
    BrowserContext,
    FeeCorrectionConfirmationCommand,
    FeeCorrectionConfirmationPrepareResult,
    FeeCorrectionConfirmationRepositoryProtocol,
)
from apps.simulated_trading.application.fee_correction_evidence_contracts import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
)
from apps.simulated_trading.application.fee_correction_head import (
    FeeCorrectionHeadRepositoryProtocol,
)
from apps.simulated_trading.application.fee_correction_preview import (
    FeeCorrectionPreviewCommand,
    FeeCorrectionPreviewRepositoryProtocol,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceBindingModel,
)
from shared.config.secrets import get_secrets
from shared.infrastructure.crypto import FieldEncryptionService

from .fee_correction_evidence_repository import DjangoFeeCorrectionEvidenceRepository
from .fee_correction_head_repository import DjangoFeeCorrectionHeadRepository
from .fee_correction_preview_repository import DjangoFeeCorrectionPreviewRepository
from .fee_correction_runtime import (
    DjangoFeeCorrectionClock,
    build_django_fee_correction_repository,
)

_TOKEN_PURPOSE = "simulated-fee-correction-confirmation"
_TOKEN_SCHEMA = "simulated-fee-correction-confirmation.v1"
_MAX_TOKEN_CONTENT_BYTES = 16_384
_MAX_TOKEN_CHARACTERS = 32_768
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_KEYS = frozenset(
    {
        "purpose",
        "schema",
        "actor_user_id",
        "session_key_sha256",
        "auth_backend",
        "auth_session_hash_sha256",
        "account_id",
        "trade_id",
        "idempotency_key_sha256",
        "source_locator",
        "content_sha256",
        "payload_sha256",
        "expected_revision",
        "expected_predecessor_id",
        "stored_at",
        "expires_at",
    }
)


@dataclass(frozen=True, slots=True)
class _ConfirmationTokenContent:
    """Exact token claims; raw browser secrets never enter encrypted JSON."""

    actor_user_id: int
    session_key_sha256: str = field(repr=False)
    auth_backend: str
    auth_session_hash_sha256: str = field(repr=False)
    account_id: int
    trade_id: int
    idempotency_key_sha256: str = field(repr=False)
    source_locator: str
    content_sha256: str
    payload_sha256: str
    expected_revision: int
    expected_predecessor_id: int | None
    stored_at: datetime
    expires_at: datetime

    def validate(self) -> None:
        """Require exact identities, lowercase digests, and aware UTC expiry claims."""

        if any(
            type(value) is not int or value <= 0
            for value in (self.actor_user_id, self.account_id, self.trade_id)
        ):
            _raise_confirmation_error(
                "费用更正确认令牌身份无效",
                code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
            )
        if (
            type(self.expected_revision) is not int
            or self.expected_revision < 0
            or (
                self.expected_predecessor_id is not None
                and (
                    type(self.expected_predecessor_id) is not int
                    or self.expected_predecessor_id <= 0
                )
            )
            or (self.expected_revision == 0) != (self.expected_predecessor_id is None)
        ):
            _raise_confirmation_error(
                "费用更正确认令牌版本无效",
                code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
            )
        if (
            type(self.auth_backend) is not str
            or not self.auth_backend
            or len(self.auth_backend) > 255
            or self.auth_backend.strip() != self.auth_backend
        ):
            _raise_confirmation_error(
                "费用更正确认令牌后端无效",
                code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
            )
        if (
            type(self.source_locator) is not str
            or not self.source_locator
            or self.source_locator.strip() != self.source_locator
            or len(self.source_locator) > 512
            or "\\" in self.source_locator
            or "://" in self.source_locator
        ):
            _raise_confirmation_error(
                "费用更正确认令牌来源无效",
                code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
            )
        for digest in (
            self.session_key_sha256,
            self.auth_session_hash_sha256,
            self.idempotency_key_sha256,
            self.content_sha256,
            self.payload_sha256,
        ):
            if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
                _raise_confirmation_error(
                    "费用更正确认令牌摘要无效",
                    code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
                )
        stored_at = _require_utc_datetime(self.stored_at, "stored_at")
        expires_at = _require_utc_datetime(self.expires_at, "expires_at")
        if expires_at <= stored_at:
            _raise_confirmation_error(
                "费用更正确认令牌期限无效",
                code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
            )


class DjangoFeeCorrectionConfirmationRepository(FeeCorrectionConfirmationRepositoryProtocol):
    """Bind preview confirmation to the live database session and original evidence."""

    def __init__(
        self,
        *,
        preview_repository: FeeCorrectionPreviewRepositoryProtocol | None = None,
        head_repository: FeeCorrectionHeadRepositoryProtocol | None = None,
        evidence_repository: DjangoFeeCorrectionEvidenceRepository | None = None,
        correction_repository: FeeCorrectionRepositoryProtocol | None = None,
        clock: FeeCorrectionClockProtocol | None = None,
    ) -> None:
        """Reuse existing history, evidence, and atomic correction repositories."""

        self._head_repository = (
            head_repository if head_repository is not None else DjangoFeeCorrectionHeadRepository()
        )
        self._evidence_repository = (
            evidence_repository
            if evidence_repository is not None
            else DjangoFeeCorrectionEvidenceRepository()
        )
        self._preview_repository = (
            preview_repository
            if preview_repository is not None
            else DjangoFeeCorrectionPreviewRepository(
                head_repository=self._head_repository,
                evidence_repository=self._evidence_repository,
            )
        )
        self._correction_repository = (
            correction_repository
            if correction_repository is not None
            else build_django_fee_correction_repository(
                evidence_repository=self._evidence_repository
            )
        )
        self._clock = clock if clock is not None else DjangoFeeCorrectionClock()

    def prepare_preview(
        self,
        command: FeeCorrectionPreviewCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        browser_context: BrowserContext,
    ) -> FeeCorrectionConfirmationPrepareResult:
        """Keep evidence creation and token issuance in one session-locked transaction."""

        _validate_browser_context(principal, browser_context)
        if type(command) is not FeeCorrectionPreviewCommand:
            _raise_confirmation_error("费用更正预览命令无效", code="FEE_CORRECTION_PREVIEW_INVALID")
        command.__post_init__()
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            stored_session = self._lock_session(browser_context)
            self._verify_session_basics(
                stored_session=stored_session,
                browser_context=browser_context,
                verified_at=timezone.now(),
            )
            preview_result = self._preview_repository.preview(
                command,
                principal=principal,
            )
            user = self._lock_current_user(browser_context.actor_user_id)
            now = timezone.now()
            self._verify_live_session(
                stored_session=stored_session,
                user=user,
                browser_context=browser_context,
                verified_at=now,
            )
            if preview_result.status == "already_applied":
                return FeeCorrectionConfirmationPrepareResult(
                    preview=preview_result,
                    confirmation_token=None,
                    expires_at=None,
                )
            preview = preview_result.preview
            if preview is None:
                _raise_confirmation_error(
                    "费用更正预览响应缺少比较内容",
                    code="FEE_CORRECTION_CONFIRMATION_INVALID",
                )
            expires_at = _original_token_expiry(
                stored_at=preview.stored_at,
            )
            if expires_at <= now:
                _raise_confirmation_error(
                    "费用更正预览已超出原始确认期限",
                    code="FEE_CORRECTION_CONFIRMATION_EXPIRED",
                )
            token_content = _ConfirmationTokenContent(
                actor_user_id=browser_context.actor_user_id,
                session_key_sha256=_sha256(browser_context.session_key),
                auth_backend=browser_context.auth_backend,
                auth_session_hash_sha256=_sha256(browser_context.auth_session_hash),
                account_id=preview.account_id,
                trade_id=preview.trade_id,
                idempotency_key_sha256=_sha256(command.idempotency_key),
                source_locator=preview.source_locator,
                content_sha256=preview.content_sha256,
                payload_sha256=preview.payload_sha256,
                expected_revision=preview.expected_revision,
                expected_predecessor_id=preview.expected_predecessor_id,
                stored_at=preview.stored_at,
                expires_at=expires_at,
            )
            token = _encode_confirmation_token(token_content)
            return FeeCorrectionConfirmationPrepareResult(
                preview=preview_result,
                confirmation_token=token,
                expires_at=expires_at,
            )

    def confirm(
        self,
        command: FeeCorrectionConfirmationCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        browser_context: BrowserContext,
    ) -> FeeCorrectionReceipt:
        """Validate original token/session, then reuse the atomic fee correction writer."""

        _validate_browser_context(principal, browser_context)
        if type(command) is not FeeCorrectionConfirmationCommand:
            _raise_confirmation_error(
                "费用更正确认命令无效",
                code="FEE_CORRECTION_CONFIRMATION_INPUT_INVALID",
            )
        command.__post_init__()
        claims = _decode_confirmation_token(command.confirmation_token)
        _validate_token_request_binding(
            claims=claims,
            command=command,
            browser_context=browser_context,
        )

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            stored_session = self._lock_session(browser_context)
            self._verify_session_basics(
                stored_session=stored_session,
                browser_context=browser_context,
                verified_at=timezone.now(),
            )
            head = self._head_repository.get_head(
                command.account_id,
                command.trade_id,
                principal=principal,
                request_key=command.idempotency_key,
            )
            user = self._lock_current_user(browser_context.actor_user_id)
            now = timezone.now()
            self._verify_live_session(
                stored_session=stored_session,
                user=user,
                browser_context=browser_context,
                verified_at=now,
            )
            if now >= claims.expires_at:
                _raise_confirmation_error(
                    "费用更正确认令牌已过期",
                    code="FEE_CORRECTION_CONFIRMATION_EXPIRED",
                )
            if head.request_receipt is not None:
                self._validate_completed_token_binding(
                    claims=claims,
                    command=command,
                    principal_user_id=browser_context.actor_user_id,
                    receipt=head.request_receipt,
                )
                return head.request_receipt
            if (
                head.revision != claims.expected_revision
                or head.expected_predecessor_id != claims.expected_predecessor_id
            ):
                _raise_confirmation_error(
                    "费用更正 head 已变化，请重新预览",
                    code="FEE_CORRECTION_REVISION_CONFLICT",
                )
            request = FeeCorrectionRequest(
                account_id=claims.account_id,
                trade_id=claims.trade_id,
                idempotency_key=command.idempotency_key,
                expected_revision=claims.expected_revision,
                source_locator=claims.source_locator,
            )
            self._validate_token_evidence_binding(
                claims=claims,
                idempotency_key=command.idempotency_key,
                principal_user_id=browser_context.actor_user_id,
            )
            applied_receipt = ApplySimulatedFeeCorrectionUseCase(
                repository=self._correction_repository,
                evidence_verifier=self._evidence_repository,
                authority=self._evidence_repository,
                clock=self._clock,
            ).execute(
                request,
                principal=principal,
            )
            completed_at = timezone.now()
            if (
                completed_at >= claims.expires_at
                or not _is_aware(stored_session.expire_date)
                or completed_at >= stored_session.expire_date
            ):
                _raise_confirmation_error(
                    "费用更正确认在原会话或令牌期限之后完成",
                    code="FEE_CORRECTION_CONFIRMATION_EXPIRED",
                )
            return applied_receipt

    @staticmethod
    def _lock_session(browser_context: BrowserContext) -> Session:
        """Lock the exact default-database session supplied by SessionAuthentication."""

        if settings.SESSION_ENGINE != "django.contrib.sessions.backends.db":
            _raise_confirmation_error(
                "费用更正确认要求数据库会话",
                code="FEE_CORRECTION_CONFIRMATION_SESSION_UNAVAILABLE",
            )
        session = (
            Session._default_manager.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(session_key=browser_context.session_key)
            .first()
        )
        if session is None or session._state.db != DEFAULT_DB_ALIAS:
            _raise_confirmation_error(
                "浏览器会话已失效",
                code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
            )
        return session

    @staticmethod
    def _lock_current_user(actor_user_id: int) -> AbstractBaseUser:
        """Reload and lock the active request user after account/owner locks."""

        user_model = get_user_model()
        user = (
            user_model._base_manager.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(pk=actor_user_id)
            .first()
        )
        if (
            user is None
            or user._state.db != DEFAULT_DB_ALIAS
            or getattr(user, "is_active", None) is not True
        ):
            _raise_confirmation_error(
                "浏览器会话主体已失效",
                code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
            )
        return cast(AbstractBaseUser, user)

    @staticmethod
    def _verify_session_basics(
        *,
        stored_session: Session,
        browser_context: BrowserContext,
        verified_at: datetime,
    ) -> dict[str, object]:
        """Validate decoded session identity and expiry before taking owner locks."""

        decoded = _decode_session(stored_session)
        backend_path = decoded.get(BACKEND_SESSION_KEY)
        session_user_id = decoded.get(SESSION_KEY)
        session_auth_hash = decoded.get(HASH_SESSION_KEY)
        if (
            type(session_user_id) is not str
            or session_user_id != str(browser_context.actor_user_id)
            or type(backend_path) is not str
            or backend_path != browser_context.auth_backend
            or backend_path not in settings.AUTHENTICATION_BACKENDS
            or type(session_auth_hash) is not str
            or not constant_time_compare(session_auth_hash, browser_context.auth_session_hash)
            or not _is_aware(stored_session.expire_date)
            or stored_session.expire_date <= verified_at
        ):
            _raise_confirmation_error(
                "浏览器会话认证信息与数据库记录不匹配",
                code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
            )
        return decoded

    @staticmethod
    def _verify_live_session(
        *,
        stored_session: Session,
        user: AbstractBaseUser,
        browser_context: BrowserContext,
        verified_at: datetime,
    ) -> None:
        """Recheck current User auth hash and database expiry after all locks are held."""

        decoded = _decode_session(stored_session)
        backend_path = decoded.get(BACKEND_SESSION_KEY)
        session_user_id = decoded.get(SESSION_KEY)
        session_auth_hash = decoded.get(HASH_SESSION_KEY)
        current_auth_hash = user.get_session_auth_hash()
        if (
            type(user.pk) is not int
            or user.pk != browser_context.actor_user_id
            or user.is_active is not True
            or type(session_user_id) is not str
            or session_user_id != str(user.pk)
            or type(backend_path) is not str
            or backend_path != browser_context.auth_backend
            or backend_path not in settings.AUTHENTICATION_BACKENDS
            or type(session_auth_hash) is not str
            or type(current_auth_hash) is not str
            or not constant_time_compare(session_auth_hash, browser_context.auth_session_hash)
            or not constant_time_compare(session_auth_hash, current_auth_hash)
            or not _is_aware(stored_session.expire_date)
            or stored_session.expire_date <= verified_at
            or stored_session._state.db != DEFAULT_DB_ALIAS
        ):
            _raise_confirmation_error(
                "浏览器会话在确认期间已失效",
                code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
            )

    @staticmethod
    def _validate_completed_token_binding(
        *,
        claims: _ConfirmationTokenContent,
        command: FeeCorrectionConfirmationCommand,
        principal_user_id: int,
        receipt: FeeCorrectionReceipt,
    ) -> None:
        """Recover only a completed event linked to this token's exact original binding."""

        DjangoFeeCorrectionConfirmationRepository._validate_token_evidence_binding(
            claims=claims,
            idempotency_key=command.idempotency_key,
            principal_user_id=principal_user_id,
        )
        event = (
            SimulatedFeeCorrectionEventModel._base_manager.using(DEFAULT_DB_ALIAS)
            .filter(pk=receipt.event_id)
            .first()
        )
        if (
            event is None
            or receipt.replayed is not True
            or receipt.account_id != claims.account_id
            or receipt.trade_id != claims.trade_id
            or receipt.revision != claims.expected_revision + 1
            or event.account_id != claims.account_id
            or event.trade_id != claims.trade_id
            or event.actor_user_id != principal_user_id
            or event.idempotency_key != command.idempotency_key
            or event.revision != receipt.revision
            or event.request_payload_hash != receipt.payload_hash
            or event.source_namespace != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or event.source_record_id != claims.source_locator
            or event.previous_event_id != claims.expected_predecessor_id
        ):
            _raise_confirmation_error(
                "已完成费用更正与原确认材料不匹配",
                code="FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH",
            )

    @staticmethod
    def _validate_token_evidence_binding(
        *,
        claims: _ConfirmationTokenContent,
        idempotency_key: str,
        principal_user_id: int,
    ) -> FeeCorrectionEvidenceBindingModel:
        """Match token claims to the immutable binding and original artifact clocks."""

        binding = (
            FeeCorrectionEvidenceBindingModel._base_manager.using(DEFAULT_DB_ALIAS)
            .select_related("artifact")
            .filter(account_id=claims.account_id, idempotency_key=idempotency_key)
            .first()
        )
        if binding is None:
            _raise_confirmation_error(
                "费用更正确认缺少原始材料绑定",
                code="FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH",
            )
        try:
            artifact = binding.artifact
        except ObjectDoesNotExist:
            _raise_confirmation_error(
                "费用更正确认缺少原始上传材料",
                code="FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH",
            )
        if (
            binding.account_id != claims.account_id
            or binding.trade_id != claims.trade_id
            or binding.idempotency_key != idempotency_key
            or binding.public_id is None
            or str(binding.public_id) != claims.source_locator
            or binding.attested_by_id != principal_user_id
            or binding.attestation_version != OPERATOR_ATTESTATION_VERSION
            or binding.attestation_acknowledged is not True
            or binding.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or binding.expected_revision != claims.expected_revision
            or binding.expected_predecessor_id != claims.expected_predecessor_id
            or binding.content_sha256 != claims.content_sha256
            or binding.payload_sha256 != claims.payload_sha256
            or artifact.account_id != claims.account_id
            or artifact.uploaded_by_id != principal_user_id
            or artifact.assurance_class != ASSURANCE_OPERATOR_ATTESTED_UPLOAD
            or artifact.schema_version != OPERATOR_FEE_CSV_SCHEMA
            or artifact.content_sha256 != claims.content_sha256
            or artifact.payload_sha256 != claims.payload_sha256
            or artifact.uploaded_at != claims.stored_at
        ):
            _raise_confirmation_error(
                "费用更正确认令牌与原始材料绑定不一致",
                code="FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH",
            )
        return binding


def _validate_browser_context(
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    browser_context: BrowserContext,
) -> None:
    """Revalidate principal identity and secret context before token operations."""

    if type(browser_context) is not BrowserContext:
        _raise_confirmation_error(
            "缺少真实浏览器会话上下文",
            code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
        )
    browser_context.__post_init__()
    principal_id = getattr(principal, "pk", None)
    if (
        getattr(principal, "is_authenticated", None) is not True
        or type(principal_id) is not int
        or principal_id != browser_context.actor_user_id
    ):
        _raise_confirmation_error(
            "请求主体与浏览器会话不匹配",
            code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
        )


def _encode_confirmation_token(content: _ConfirmationTokenContent) -> str:
    """Encrypt a bounded canonical claim set with the existing field key."""

    content.validate()
    plaintext = _canonical_json(_token_payload(content))
    encoded = plaintext.encode("utf-8")
    if len(encoded) > _MAX_TOKEN_CONTENT_BYTES:
        _raise_confirmation_error(
            "费用更正确认令牌内容超出长度限制",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_TOO_LARGE",
        )
    token = _encryption_service().encrypt(plaintext)
    if len(token) > _MAX_TOKEN_CHARACTERS:
        _raise_confirmation_error(
            "费用更正确认令牌超出长度限制",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_TOO_LARGE",
        )
    return token


def _decode_confirmation_token(token: str) -> _ConfirmationTokenContent:
    """Decrypt exact token schema and reject duplicate, extra, or coerced JSON values."""

    if (
        type(token) is not str
        or not token
        or len(token) > _MAX_TOKEN_CHARACTERS
        or not token.isascii()
        or not token.startswith(FieldEncryptionService.PREFIX)
    ):
        _raise_confirmation_error(
            "费用更正确认令牌格式无效",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
        )
    try:
        _validate_canonical_encryption_encoding(token)
        plaintext = _encryption_service().decrypt(token, suppress_warning=True)
        encoded = plaintext.encode("utf-8")
    except (Base64DecodeError, InvalidToken, UnicodeError, TypeError, ValueError):
        _raise_confirmation_error(
            "费用更正确认令牌无法解密",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
        )
    if len(encoded) > _MAX_TOKEN_CONTENT_BYTES:
        _raise_confirmation_error(
            "费用更正确认令牌内容超出长度限制",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_TOO_LARGE",
        )
    try:
        parsed = json.loads(
            plaintext,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
        )
        content = _token_from_payload(parsed)
    except (
        _DuplicateJsonKeyError,
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        TypeError,
        ValueError,
    ):
        _raise_confirmation_error(
            "费用更正确认令牌内容无效",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
        )
    if _canonical_json(_token_payload(content)) != plaintext:
        _raise_confirmation_error(
            "费用更正确认令牌编码非规范",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
        )
    return content


def _validate_canonical_encryption_encoding(token: str) -> None:
    """Require canonical base64 for the wrapper and nested Fernet token."""

    outer_text = token[len(FieldEncryptionService.PREFIX) :]
    try:
        outer_bytes = b64decode(outer_text, altchars=b"-_", validate=True)
        canonical_outer = urlsafe_b64encode(outer_bytes).decode("ascii")
        inner_text = outer_bytes.decode("ascii")
        inner_bytes = b64decode(inner_text, altchars=b"-_", validate=True)
        canonical_inner = urlsafe_b64encode(inner_bytes).decode("ascii")
    except (Base64DecodeError, UnicodeError, ValueError):
        _raise_confirmation_error(
            "费用更正确认令牌编码无效",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
        )
    if canonical_outer != outer_text or canonical_inner != inner_text:
        _raise_confirmation_error(
            "费用更正确认令牌编码非规范",
            code="FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID",
        )


def _token_payload(content: _ConfirmationTokenContent) -> dict[str, object]:
    """Encode a stable exact field set without raw key or session credentials."""

    return {
        "purpose": _TOKEN_PURPOSE,
        "schema": _TOKEN_SCHEMA,
        "actor_user_id": content.actor_user_id,
        "session_key_sha256": content.session_key_sha256,
        "auth_backend": content.auth_backend,
        "auth_session_hash_sha256": content.auth_session_hash_sha256,
        "account_id": content.account_id,
        "trade_id": content.trade_id,
        "idempotency_key_sha256": content.idempotency_key_sha256,
        "source_locator": content.source_locator,
        "content_sha256": content.content_sha256,
        "payload_sha256": content.payload_sha256,
        "expected_revision": content.expected_revision,
        "expected_predecessor_id": content.expected_predecessor_id,
        "stored_at": _format_utc(content.stored_at),
        "expires_at": _format_utc(content.expires_at),
    }


def _token_from_payload(payload: object) -> _ConfirmationTokenContent:
    """Reconstruct token claims from exact JSON types without coercion."""

    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise ValueError("token payload must be an object")
    value = cast(dict[str, object], payload)
    if frozenset(value) != _TOKEN_KEYS:
        raise ValueError("token payload keys are not exact")
    if value["purpose"] != _TOKEN_PURPOSE or value["schema"] != _TOKEN_SCHEMA:
        raise ValueError("token purpose or schema is unsupported")
    return _ConfirmationTokenContent(
        actor_user_id=_expect_int(value["actor_user_id"]),
        session_key_sha256=_expect_text(value["session_key_sha256"]),
        auth_backend=_expect_text(value["auth_backend"]),
        auth_session_hash_sha256=_expect_text(value["auth_session_hash_sha256"]),
        account_id=_expect_int(value["account_id"]),
        trade_id=_expect_int(value["trade_id"]),
        idempotency_key_sha256=_expect_text(value["idempotency_key_sha256"]),
        source_locator=_expect_text(value["source_locator"]),
        content_sha256=_expect_text(value["content_sha256"]),
        payload_sha256=_expect_text(value["payload_sha256"]),
        expected_revision=_expect_int(value["expected_revision"]),
        expected_predecessor_id=_expect_optional_int(value["expected_predecessor_id"]),
        stored_at=_parse_utc(value["stored_at"]),
        expires_at=_parse_utc(value["expires_at"]),
    )


def _decode_session(stored_session: Session) -> dict[str, object]:
    """Narrow Django's decoded session at the dynamic storage boundary."""

    decoded = stored_session.get_decoded()
    if type(decoded) is not dict or any(type(key) is not str for key in decoded):
        _raise_confirmation_error(
            "数据库会话内容无效",
            code="FEE_CORRECTION_CONFIRMATION_SESSION_INVALID",
        )
    return cast(dict[str, object], decoded)


def _encryption_service() -> FieldEncryptionService:
    """Use only the existing field-encryption secret, without a new key source."""

    try:
        key = get_secrets(require_tushare_token=False).field_encryption_key
    except (OSError, TypeError, ValueError):
        _raise_confirmation_error(
            "费用更正确认加密密钥不可用",
            code="FEE_CORRECTION_CONFIRMATION_KEY_UNAVAILABLE",
        )
    if type(key) is not str or not key.strip():
        _raise_confirmation_error(
            "费用更正确认加密密钥不可用",
            code="FEE_CORRECTION_CONFIRMATION_KEY_UNAVAILABLE",
        )
    try:
        return FieldEncryptionService(encryption_key=key)
    except (ImproperlyConfigured, TypeError, ValueError):
        _raise_confirmation_error(
            "费用更正确认加密密钥无效",
            code="FEE_CORRECTION_CONFIRMATION_KEY_UNAVAILABLE",
        )


def _validate_token_request_binding(
    *,
    claims: _ConfirmationTokenContent,
    command: FeeCorrectionConfirmationCommand,
    browser_context: BrowserContext,
) -> None:
    """Bind decoded claims to exact URL, key, actor, and current request session."""

    if (
        claims.account_id != command.account_id
        or claims.trade_id != command.trade_id
        or claims.actor_user_id != browser_context.actor_user_id
        or claims.auth_backend != browser_context.auth_backend
        or not constant_time_compare(
            claims.session_key_sha256,
            _sha256(browser_context.session_key),
        )
        or not constant_time_compare(
            claims.auth_session_hash_sha256,
            _sha256(browser_context.auth_session_hash),
        )
        or not constant_time_compare(
            claims.idempotency_key_sha256,
            _sha256(command.idempotency_key),
        )
    ):
        _raise_confirmation_error(
            "费用更正确认令牌不属于该账户、主体、会话或幂等请求",
            code="FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH",
        )


def _original_token_expiry(*, stored_at: datetime) -> datetime:
    """Fix the token deadline to the original artifact time and configured session age."""

    if not _is_aware(stored_at):
        _raise_confirmation_error(
            "费用材料时钟无效",
            code="FEE_CORRECTION_CONFIRMATION_CLOCK_INVALID",
        )
    max_age = getattr(settings, "SESSION_COOKIE_AGE", None)
    if type(max_age) is not int or max_age <= 0:
        _raise_confirmation_error(
            "浏览器会话期限配置无效",
            code="FEE_CORRECTION_CONFIRMATION_SESSION_UNAVAILABLE",
        )
    try:
        artifact_expiry = stored_at + timedelta(seconds=max_age)
    except (OverflowError, TypeError, ValueError):
        _raise_confirmation_error(
            "费用材料确认期限超出时间范围",
            code="FEE_CORRECTION_CONFIRMATION_CLOCK_INVALID",
        )
    return artifact_expiry


def _parse_utc(value: object) -> datetime:
    """Parse one canonical UTC timestamp from the encrypted token."""

    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("timestamp must be canonical UTC text")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if _format_utc(parsed) != value:
        raise ValueError("timestamp is not canonical")
    return parsed


def _format_utc(value: datetime) -> str:
    """Serialize an aware instant as exact UTC microsecond precision."""

    aware = _require_utc_datetime(value, "timestamp")
    return aware.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_utc_datetime(value: object, field_name: str) -> datetime:
    """Require a UTC-aware datetime for token claims and expiry comparisons."""

    if type(value) is not datetime or value.tzinfo is None:
        _raise_confirmation_error(
            f"费用更正确认令牌 {field_name} 必须是 UTC 时钟",
            code="FEE_CORRECTION_CONFIRMATION_CLOCK_INVALID",
        )
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError):
        _raise_confirmation_error(
            f"费用更正确认令牌 {field_name} 必须是 UTC 时钟",
            code="FEE_CORRECTION_CONFIRMATION_CLOCK_INVALID",
        )
    if offset != timedelta(0):
        _raise_confirmation_error(
            f"费用更正确认令牌 {field_name} 必须是 UTC 时钟",
            code="FEE_CORRECTION_CONFIRMATION_CLOCK_INVALID",
        )
    return value.astimezone(UTC)


def _is_aware(value: datetime) -> bool:
    """Return whether the supplied database clock is timezone-aware."""

    return value.tzinfo is not None and value.utcoffset() is not None


def _sha256(value: str) -> str:
    """Return a lowercase one-way digest for a secret binding value."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expect_int(value: object) -> int:
    """Accept an exact JSON integer and reject bool coercion."""

    if type(value) is not int:
        raise ValueError("integer claim has the wrong type")
    return value


def _expect_optional_int(value: object) -> int | None:
    """Accept an exact JSON integer or JSON null."""

    if value is None:
        return None
    return _expect_int(value)


def _expect_text(value: object) -> str:
    """Accept a non-empty exact JSON string."""

    if type(value) is not str or not value:
        raise ValueError("text claim has the wrong type")
    return value


def _canonical_json(payload: dict[str, object]) -> str:
    """Serialize exact token claims deterministically with no non-finite values."""

    return json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys before token claims are reconstructed."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError("duplicate token key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    """Reject non-standard JSON constants such as NaN and Infinity."""

    raise ValueError(f"non-standard token constant: {value}")


def _reject_json_float(value: str) -> NoReturn:
    """Reject floating-point JSON claims; token schema contains none."""

    raise ValueError(f"floating-point token value is unsupported: {value}")


class _DuplicateJsonKeyError(ValueError):
    """Internal signal raised when token JSON repeats a key."""


def _raise_confirmation_error(message: str, *, code: str) -> NoReturn:
    """Raise a safe application error without echoing tokens or session secrets."""

    raise FeeCorrectionBlockedError(message, code=code)


__all__ = ["DjangoFeeCorrectionConfirmationRepository"]
