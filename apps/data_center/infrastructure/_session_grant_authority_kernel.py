"""Private fixed-purpose kernel for locking Django sessions and grants."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from threading import get_ident
from typing import Protocol, TypeAlias, cast

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, models, router, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist
from django.utils.crypto import constant_time_compare

from apps.data_center.application.calendar_audit_read_authority import (
    CALENDAR_AUDIT_READ_PERMISSION_CODENAME,
    CalendarAuditReaderSessionRequestProof,
    LockedCalendarAuditReaderPrincipal,
)
from apps.data_center.application.calendar_publication_authority import (
    CALENDAR_PUBLISH_PERMISSION_CODENAME,
    CalendarPublisherSessionRequestProof,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.price_limit_publication_authority import (
    PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME,
    LockedPriceLimitPublisherPrincipal,
    PriceLimitPublisherSessionRequestProof,
)
from core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ExternalServiceError,
    InvalidInputError,
)

_DATABASE_SESSION_ENGINE = "django.contrib.sessions.backends.db"


class _AuthorityPurpose(Enum):
    """Closed internal operation selector; no caller can choose a codename."""

    PUBLISH = "publish"
    AUDIT_READ = "audit_read"
    PRICE_LIMIT_PUBLISH = "publish_price_limit"

    @property
    def permission_codename(self) -> str:
        """Return the exact persisted permission bound to this fixed operation."""

        if self is _AuthorityPurpose.PUBLISH:
            return CALENDAR_PUBLISH_PERMISSION_CODENAME
        if self is _AuthorityPurpose.AUDIT_READ:
            return CALENDAR_AUDIT_READ_PERMISSION_CODENAME
        if self is _AuthorityPurpose.PRICE_LIMIT_PUBLISH:
            return PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME
        raise InvalidInputError(
            "Session authority received an unsupported internal purpose",
            code="SESSION_AUTHORITY_PURPOSE_INVALID",
        )

    def error_code(self, suffix: str) -> str:
        """Return a purpose-specific stable application code."""

        if self is _AuthorityPurpose.PUBLISH:
            return f"CALENDAR_PUBLISHER_{suffix}"
        if self is _AuthorityPurpose.AUDIT_READ:
            return f"CALENDAR_AUDIT_READER_{suffix}"
        if self is _AuthorityPurpose.PRICE_LIMIT_PUBLISH:
            return f"PRICE_LIMIT_PUBLISHER_{suffix}"
        raise InvalidInputError(
            "Session authority received an unsupported internal purpose",
            code="SESSION_AUTHORITY_PURPOSE_INVALID",
        )

    @property
    def content_type_model(self) -> str:
        """Return the exact model identity included in the witness hash."""

        if self is _AuthorityPurpose.PRICE_LIMIT_PUBLISH:
            return "pricelimitsnapshotfactmodel"
        return "exchangecalendarsnapshotfactmodel"

    @property
    def hash_schema(self) -> str:
        """Return the exact purpose-specific authority hash schema."""

        if self is _AuthorityPurpose.PRICE_LIMIT_PUBLISH:
            return "price-limit-permission-observation-v1"
        return "calendar-permission-observation-v1"

    @property
    def error_subject(self) -> str:
        """Return the fixed operation name used in stable errors."""

        if self is _AuthorityPurpose.PUBLISH:
            return "Calendar publisher"
        if self is _AuthorityPurpose.AUDIT_READ:
            return "Calendar audit reader"
        return "Price-limit publisher"


_SessionProof: TypeAlias = (
    CalendarPublisherSessionRequestProof
    | CalendarAuditReaderSessionRequestProof
    | PriceLimitPublisherSessionRequestProof
)
_LockedPrincipal: TypeAlias = (
    LockedCalendarPublisherPrincipal
    | LockedCalendarAuditReaderPrincipal
    | LockedPriceLimitPublisherPrincipal
)


class UtcClock(Protocol):
    """Provide an aware UTC clock for lock-time authorization checks."""

    def now(self) -> datetime:
        """Return the current timezone-aware instant."""


class _DjangoUtcClock:
    """Read Django's configured timezone-aware clock."""

    def now(self) -> datetime:
        """Return the current application instant."""

        return timezone.now()


class _PrincipalLease:
    """Expose immutable attribution only while the authority context is open."""

    __slots__ = (
        "_active",
        "_authority_content_hash",
        "_database_alias",
        "_expires_at",
        "_error_subject",
        "_error_prefix",
        "_last_verified_at",
        "_owner_thread_id",
        "_permission_id",
        "_permission_codename",
        "_user_id",
        "_verified_at",
        "_clock",
        "_connection",
    )

    def __init__(
        self,
        *,
        user_id: int,
        permission_id: int,
        permission_codename: str,
        database_alias: str,
        verified_at: datetime,
        expires_at: datetime,
        authority_content_hash: str,
        purpose: _AuthorityPurpose,
        clock: UtcClock,
        connection: BaseDatabaseWrapper,
    ) -> None:
        """Create an internal lease from rows already locked and revalidated."""

        self._active = True
        self._user_id = user_id
        self._permission_id = permission_id
        self._permission_codename = permission_codename
        self._database_alias = database_alias
        self._verified_at = verified_at
        self._last_verified_at = verified_at
        self._expires_at = expires_at
        self._authority_content_hash = authority_content_hash
        self._error_prefix = purpose.error_code("").rstrip("_")
        self._error_subject = purpose.error_subject
        self._clock = clock
        self._connection = connection
        self._owner_thread_id = get_ident()

    @property
    def actor_type(self) -> str:
        """Return the fixed actor kind while authorization remains live."""

        self.assert_live()
        return "django_user"

    @property
    def actor_id(self) -> str:
        """Return a stable Django user actor id while authorization remains live."""

        self.assert_live()
        return f"django-user:{self._user_id}"

    @property
    def permission_codename(self) -> str:
        """Return the exact custom permission that was checked under lock."""

        self.assert_live()
        return self._permission_codename

    @property
    def database_alias(self) -> str:
        """Return the alias holding the session, identity, and grant locks."""

        self.assert_live()
        return self._database_alias

    @property
    def user_id(self) -> int:
        """Return the authenticated primary key while authorization remains live."""

        self.assert_live()
        return self._user_id

    @property
    def permission_id(self) -> int:
        """Return the exact persisted permission primary key while live."""

        self.assert_live()
        return self._permission_id

    @property
    def verified_at(self) -> datetime:
        """Return the post-lock authorization time while the lease remains live."""

        self.assert_live()
        return self._verified_at

    @property
    def session_expires_at(self) -> datetime:
        """Return the locked Django session expiry while the lease is active."""

        self.assert_live()
        return self._expires_at

    @property
    def authority_content_hash(self) -> str:
        """Return the digest of locked permission and grant witnesses."""

        self.assert_live()
        return self._authority_content_hash

    def assert_live(self) -> None:
        """Reject use after expiry, clock rollback, or transaction lock release."""

        if not self._active:
            raise AuthorizationError(
                f"{self._error_subject} principal is outside its locked transaction",
                code=f"{self._error_prefix}_PRINCIPAL_EXPIRED",
            )
        if get_ident() != self._owner_thread_id:
            raise AuthorizationError(
                f"{self._error_subject} principal cannot cross transaction threads",
                code=f"{self._error_prefix}_TRANSACTION_THREAD_MISMATCH",
            )
        if self._connection.needs_rollback:
            raise AuthorizationError(
                f"{self._error_subject} transaction was marked rollback-only",
                code=f"{self._error_prefix}_TRANSACTION_ROLLBACK_ONLY",
            )
        current = self._clock.now()
        if not _is_aware_utc(current) or current < self._last_verified_at:
            raise AuthenticationError(
                f"{self._error_subject} clock is invalid or moved backwards",
                code=f"{self._error_prefix}_CLOCK_INVALID",
            )
        if current >= self._expires_at:
            raise AuthenticationError(
                f"{self._error_subject} session expired before authorization completed",
                code=f"{self._error_prefix}_SESSION_EXPIRED",
            )
        self._last_verified_at = current

    def deactivate(self) -> None:
        """Invalidate the principal when the lock-owning context exits."""

        self._active = False


class SessionGrantAuthorityKernel:
    """Lock one fixed-purpose permission and its session/grant witnesses."""

    def __init__(self, *, using: str, clock: UtcClock | None = None) -> None:
        """Bind this internal kernel to one explicit alias and optional clock."""

        self._using = using
        self._clock = clock if clock is not None else _DjangoUtcClock()

    @contextmanager
    def locked_calendar_publisher(
        self,
        proof: CalendarPublisherSessionRequestProof,
    ) -> Iterator[LockedCalendarPublisherPrincipal]:
        """Verify session, active user, and direct or group grant under row locks."""

        with self._locked_authority(
            proof,
            purpose=_AuthorityPurpose.PUBLISH,
        ) as principal:
            yield principal

    @contextmanager
    def locked_calendar_audit_reader(
        self,
        proof: CalendarAuditReaderSessionRequestProof,
    ) -> Iterator[LockedCalendarAuditReaderPrincipal]:
        """Verify the dedicated read grant under the same session and row locks."""

        with self._locked_authority(
            proof,
            purpose=_AuthorityPurpose.AUDIT_READ,
        ) as principal:
            yield cast(LockedCalendarAuditReaderPrincipal, principal)

    @contextmanager
    def locked_price_limit_publisher(
        self,
        proof: PriceLimitPublisherSessionRequestProof,
    ) -> Iterator[LockedPriceLimitPublisherPrincipal]:
        """Verify the fixed price-limit grant under the same locked witnesses."""

        with self._locked_authority(
            proof,
            purpose=_AuthorityPurpose.PRICE_LIMIT_PUBLISH,
        ) as principal:
            yield cast(LockedPriceLimitPublisherPrincipal, principal)

    @contextmanager
    def _locked_authority(
        self,
        proof: _SessionProof,
        *,
        purpose: _AuthorityPurpose,
    ) -> Iterator[_LockedPrincipal]:
        """Share lock-time verification behind its fixed-purpose methods."""

        if type(purpose) is not _AuthorityPurpose or purpose not in (
            _AuthorityPurpose.PUBLISH,
            _AuthorityPurpose.AUDIT_READ,
            _AuthorityPurpose.PRICE_LIMIT_PUBLISH,
        ):
            raise InvalidInputError(
                "Session authority received an unsupported internal purpose",
                code="SESSION_AUTHORITY_PURPOSE_INVALID",
            )
        if purpose is _AuthorityPurpose.PUBLISH:
            expected_type: type[object] = CalendarPublisherSessionRequestProof
        elif purpose is _AuthorityPurpose.AUDIT_READ:
            expected_type = CalendarAuditReaderSessionRequestProof
        else:
            expected_type = PriceLimitPublisherSessionRequestProof
        if type(proof) is not expected_type:
            raise AuthenticationError(
                f"{purpose.error_subject} authorization requires its exact session proof",
                code=purpose.error_code("PROOF_INVALID"),
            )
        proof.validate()
        if proof.database_alias != self._using:
            raise AuthorizationError(
                f"{purpose.error_subject} proof targets a different database",
                code=purpose.error_code("ALIAS_MISMATCH"),
            )
        if settings.SESSION_ENGINE != _DATABASE_SESSION_ENGINE:
            raise ExternalServiceError(
                f"{purpose.error_subject} authorization requires a lockable database session backend",
                code=purpose.error_code("SESSION_BACKEND_UNAVAILABLE"),
            )

        connection = self._connection(purpose)
        self._require_owned_transaction(connection, purpose)
        user_model = get_user_model()
        through_user_permissions = user_model.user_permissions.through
        through_user_groups = user_model.groups.through
        through_group_permissions = Group.permissions.through
        self._require_same_alias_routes(
            user_model,
            through_user_permissions,
            through_user_groups,
            through_group_permissions,
            purpose,
        )

        try:
            with transaction.atomic(using=self._using):
                self._set_bounded_postgres_lock_wait(connection, purpose)
                stored_session = self._lock_session(proof, purpose)
                user = self._lock_user(user_model, proof, purpose)
                permission = self._lock_permission(purpose)
                direct_grant_ids, membership_witnesses, group_ids = (
                    self._lock_direct_and_group_memberships(
                        through_user_permissions,
                        through_user_groups,
                        user_id=proof.user_id,
                        permission_id=permission.pk,
                        purpose=purpose,
                    )
                )
                group_grant_ids = self._lock_group_permissions(
                    through_group_permissions,
                    group_ids=group_ids,
                    permission_id=permission.pk,
                    purpose=purpose,
                )
                if not direct_grant_ids and not group_grant_ids:
                    raise AuthorizationError(
                        f"{purpose.error_subject} permission is not explicitly granted",
                        code=purpose.error_code("PERMISSION_REQUIRED"),
                    )
                verified_at = self._clock.now()
                self._verify_utc_clock(verified_at, proof, purpose)
                self._verify_session(stored_session, user, proof, verified_at, purpose)
                authority_hash = _build_authority_content_hash(
                    purpose=purpose,
                    database_alias=self._using,
                    user_id=proof.user_id,
                    permission=permission,
                    direct_grant_ids=direct_grant_ids,
                    membership_witnesses=membership_witnesses,
                    group_grant_ids=group_grant_ids,
                    verified_at=verified_at,
                    session_expires_at=stored_session.expire_date,
                )
                lease = _PrincipalLease(
                    user_id=proof.user_id,
                    permission_id=permission.pk,
                    permission_codename=purpose.permission_codename,
                    database_alias=self._using,
                    verified_at=verified_at,
                    expires_at=stored_session.expire_date,
                    authority_content_hash=authority_hash,
                    purpose=purpose,
                    clock=self._clock,
                    connection=connection,
                )
                try:
                    yield lease
                    lease.assert_live()
                finally:
                    lease.deactivate()
        except (AuthenticationError, AuthorizationError, ExternalServiceError):
            raise
        except (ConnectionDoesNotExist, DatabaseError) as exc:
            raise ExternalServiceError(
                f"{purpose.error_subject} authority storage is unavailable",
                code=purpose.error_code("AUTHORITY_STORAGE_UNAVAILABLE"),
            ) from exc

    def _connection(self, purpose: _AuthorityPurpose) -> BaseDatabaseWrapper:
        """Resolve the selected connection without leaking unknown-alias errors."""

        try:
            return connections[self._using]
        except ConnectionDoesNotExist as exc:
            raise ExternalServiceError(
                f"{purpose.error_subject} database alias is unavailable",
                code=purpose.error_code("ALIAS_UNAVAILABLE"),
            ) from exc

    def _require_owned_transaction(
        self,
        connection: BaseDatabaseWrapper,
        purpose: _AuthorityPurpose,
    ) -> None:
        """Require this context manager to own the outermost commit boundary."""

        if connection.in_atomic_block or not connection.get_autocommit():
            raise ExternalServiceError(
                f"{purpose.error_subject} requires an outer owned transaction",
                code=purpose.error_code("TRANSACTION_NOT_OWNED"),
            )

    def _require_same_alias_routes(
        self,
        user_model: type[User],
        through_user_permissions: type[models.Model],
        through_user_groups: type[models.Model],
        through_group_permissions: type[models.Model],
        purpose: _AuthorityPurpose,
    ) -> None:
        """Reject session or auth routers that resolve witnesses elsewhere."""

        route_models: tuple[type[models.Model], ...] = (
            Session,
            ContentType,
            Permission,
            Group,
            user_model,
            through_user_permissions,
            through_user_groups,
            through_group_permissions,
        )
        for model in route_models:
            read_alias = router.db_for_read(model) or DEFAULT_DB_ALIAS
            write_alias = router.db_for_write(model) or DEFAULT_DB_ALIAS
            if read_alias != self._using or write_alias != self._using:
                raise ExternalServiceError(
                    f"{purpose.error_subject} models do not share one database alias",
                    code=purpose.error_code("ALIAS_MISMATCH"),
                )

    def _set_bounded_postgres_lock_wait(
        self,
        connection: BaseDatabaseWrapper,
        purpose: _AuthorityPurpose,
    ) -> None:
        """Use READ COMMITTED and cap PostgreSQL lock waits at two seconds."""

        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation = cursor.fetchone()
            if not isolation or isolation[0] != "read committed":
                raise ExternalServiceError(
                    f"{purpose.error_subject} requires READ COMMITTED isolation",
                    code=purpose.error_code("ISOLATION_UNAVAILABLE"),
                )
            cursor.execute(
                "SELECT current_setting('lock_timeout')::interval = interval '0' "
                "OR current_setting('lock_timeout')::interval > interval '2 seconds'"
            )
            should_cap_wait = cursor.fetchone()
            if should_cap_wait and should_cap_wait[0]:
                cursor.execute("SET LOCAL lock_timeout = '2s'")

    def _lock_session(self, proof: _SessionProof, purpose: _AuthorityPurpose) -> Session:
        """Lock the exact DB session used by Django session authentication."""

        try:
            return (
                Session.objects.using(self._using)
                .select_for_update()
                .get(session_key=proof.session_key)
            )
        except Session.DoesNotExist as exc:
            raise AuthenticationError(
                f"{purpose.error_subject} session is no longer present",
                code=purpose.error_code("SESSION_INVALID"),
            ) from exc

    def _lock_user(
        self,
        user_model: type[User],
        proof: _SessionProof,
        purpose: _AuthorityPurpose,
    ) -> User:
        """Reload and lock the request user from the selected database."""

        try:
            user = (
                user_model._base_manager.using(self._using)
                .select_for_update()
                .get(pk=proof.user_id)
            )
        except user_model.DoesNotExist as exc:
            raise AuthenticationError(
                f"{purpose.error_subject} identity is no longer present",
                code=purpose.error_code("IDENTITY_INVALID"),
            ) from exc
        if user._state.db != self._using or user.is_active is not True:
            raise AuthenticationError(
                f"{purpose.error_subject} identity is inactive or on another database",
                code=purpose.error_code("IDENTITY_INVALID"),
            )
        return user

    def _verify_session(
        self,
        stored_session: Session,
        user: User,
        proof: _SessionProof,
        verified_at: datetime,
        purpose: _AuthorityPurpose,
    ) -> None:
        """Compare session user, configured backend, auth hash, and expiry."""

        decoded = stored_session.get_decoded()
        if type(decoded) is not dict or any(type(key) is not str for key in decoded):
            raise AuthenticationError(
                f"{purpose.error_subject} session data is invalid",
                code=purpose.error_code("SESSION_INVALID"),
            )
        session_data = cast(dict[str, object], decoded)
        session_user_id = session_data.get(SESSION_KEY)
        backend_path = session_data.get(BACKEND_SESSION_KEY)
        session_auth_hash = session_data.get(HASH_SESSION_KEY)
        if (
            type(session_user_id) is not str
            or session_user_id != str(proof.user_id)
            or type(backend_path) is not str
            or backend_path not in settings.AUTHENTICATION_BACKENDS
            or type(session_auth_hash) is not str
            or not constant_time_compare(session_auth_hash, user.get_session_auth_hash())
            or not _is_aware_utc(stored_session.expire_date)
            or stored_session.expire_date <= verified_at
            or stored_session._state.db != self._using
        ):
            raise AuthenticationError(
                f"{purpose.error_subject} session no longer authenticates this user",
                code=purpose.error_code("SESSION_INVALID"),
            )

    def _lock_permission(self, purpose: _AuthorityPurpose) -> Permission:
        """Lock the exact custom permission definition or fail closed."""

        try:
            content_type = (
                ContentType.objects.using(self._using)
                .select_for_update()
                .get(
                    app_label="data_center",
                    model=purpose.content_type_model,
                )
            )
            return (
                Permission.objects.using(self._using)
                .select_for_update()
                .get(
                    content_type=content_type,
                    codename=purpose.permission_codename,
                )
            )
        except (ContentType.DoesNotExist, Permission.DoesNotExist) as exc:
            raise AuthorizationError(
                f"{purpose.error_subject} permission is not configured",
                code=purpose.error_code("PERMISSION_UNAVAILABLE"),
            ) from exc

    def _lock_direct_and_group_memberships(
        self,
        through_user_permissions: type[models.Model],
        through_user_groups: type[models.Model],
        *,
        user_id: int,
        permission_id: int,
        purpose: _AuthorityPurpose,
    ) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...], tuple[int, ...]]:
        """Lock direct grants before ordered group membership witnesses."""

        direct_rows = list(
            through_user_permissions._default_manager.using(self._using)
            .select_for_update()
            .filter(user_id=user_id, permission_id=permission_id)
            .order_by("pk")
        )
        membership_rows = list(
            through_user_groups._default_manager.using(self._using)
            .select_for_update()
            .filter(user_id=user_id)
            .order_by("group_id", "pk")
        )
        direct_ids = tuple(self._witness_id(row, purpose) for row in direct_rows)
        memberships: list[tuple[int, int]] = []
        group_ids: set[int] = set()
        for row in membership_rows:
            witness_id = self._witness_id(row, purpose)
            group_id = getattr(row, "group_id", None)
            if type(group_id) is not int or group_id <= 0:
                raise ExternalServiceError(
                    f"{purpose.error_subject} membership witness is invalid",
                    code=purpose.error_code("WITNESS_INVALID"),
                )
            memberships.append((witness_id, group_id))
            group_ids.add(group_id)
        return direct_ids, tuple(memberships), tuple(sorted(group_ids))

    def _lock_group_permissions(
        self,
        through_group_permissions: type[models.Model],
        *,
        group_ids: tuple[int, ...],
        permission_id: int,
        purpose: _AuthorityPurpose,
    ) -> tuple[int, ...]:
        """Lock all sorted group grant witnesses for the exact permission."""

        if not group_ids:
            return ()
        grant_rows = list(
            through_group_permissions._default_manager.using(self._using)
            .select_for_update()
            .filter(group_id__in=group_ids, permission_id=permission_id)
            .order_by("group_id", "pk")
        )
        return tuple(self._witness_id(row, purpose) for row in grant_rows)

    @staticmethod
    def _witness_id(row: models.Model, purpose: _AuthorityPurpose) -> int:
        """Require a persisted positive integer key for an exact grant witness."""

        value = getattr(row, "pk", None)
        if type(value) is not int or value <= 0:
            raise ExternalServiceError(
                f"{purpose.error_subject} grant witness has an invalid identity",
                code=purpose.error_code("WITNESS_INVALID"),
            )
        return value

    def _verify_utc_clock(
        self,
        verified_at: datetime,
        proof: _SessionProof,
        purpose: _AuthorityPurpose,
    ) -> None:
        """Reject naive time and wall-clock rollback after request authentication."""

        if not _is_aware_utc(verified_at) or verified_at < proof.request_authenticated_at:
            raise AuthenticationError(
                f"{purpose.error_subject} clock moved before request authentication",
                code=purpose.error_code("CLOCK_INVALID"),
            )


def _build_authority_content_hash(
    *,
    purpose: _AuthorityPurpose,
    database_alias: str,
    user_id: int,
    permission: Permission,
    direct_grant_ids: tuple[int, ...],
    membership_witnesses: tuple[tuple[int, int], ...],
    group_grant_ids: tuple[int, ...],
    verified_at: datetime,
    session_expires_at: datetime,
) -> str:
    """Digest the exact live permission definition and locked grant witnesses."""

    payload: dict[str, object] = {
        "schema": purpose.hash_schema,
        "purpose": purpose.value,
        "database_alias": database_alias,
        "user_id": user_id,
        "content_type": {
            "id": permission.content_type_id,
            "app_label": "data_center",
            "model": purpose.content_type_model,
        },
        "permission": {
            "id": permission.pk,
            "codename": permission.codename,
        },
        "direct_grant_ids": list(direct_grant_ids),
        "group_memberships": [
            {"id": membership_id, "group_id": group_id}
            for membership_id, group_id in membership_witnesses
        ],
        "group_grant_ids": list(group_grant_ids),
        "verified_at": verified_at.isoformat(),
        "session_expires_at": session_expires_at.isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(canonical.encode('ascii')).hexdigest()}"


__all__ = ["SessionGrantAuthorityKernel", "UtcClock"]


def _is_aware_utc(value: object) -> bool:
    """Return whether a database or injected clock value is a UTC instant."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0
