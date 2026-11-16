"""Session-bound C2 Owner permission revalidation for the isolated governance writer."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, router
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model
from django.utils.crypto import constant_time_compare

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityPermissionAuthorizerPort,
    FinancialAvailabilitySessionRequestProof,
    LockedFinancialAvailabilityPrincipal,
)
from apps.data_center.domain.financial_availability_governance import (
    FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL,
    FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
)
from apps.data_center.infrastructure.financial_availability_governance_models import (
    FinancialAvailabilityGovernanceRecordModel,
)
from core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    DataValidationError,
    ExternalServiceError,
)

_DATABASE_SESSION_ENGINE = "django.contrib.sessions.backends.db"
_C2_PERMISSION = (
    f"{FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL}."
    f"{FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME}"
)


def _utc(value: object, name: str) -> datetime:
    """Require one aware UTC server or session timestamp."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ExternalServiceError(f"{name} must be an aware UTC datetime.")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ExternalServiceError(f"{name} must be an explicit UTC datetime.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ExternalServiceError(f"{name} is outside the UTC range.") from error


def _db_clock(using: str) -> datetime:
    """Sample actual PostgreSQL wall time for an Owner event or lease check."""

    with connections[using].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    if row is None:
        raise ExternalServiceError("C2 Owner event clock is unavailable.")
    return _utc(row[0], "owner_event_database_clock")


def _require_read_committed_uow(using: str) -> None:
    """Require this authorizer to join an existing PostgreSQL RC UOW."""

    connection = connections[using]
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise ExternalServiceError("C2 Owner authorization requires a PostgreSQL caller UOW.")
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        row = cursor.fetchone()
    if row is None or row[0] != "read committed":
        raise ExternalServiceError("C2 Owner authorization requires READ COMMITTED isolation.")


class _FinancialAvailabilityPrincipalLease:
    """Expose an actual locked User and permission only during its RC UOW."""

    __slots__ = (
        "_active",
        "_connection",
        "_database_alias",
        "_expires_at",
        "_permission_app_label",
        "_permission_codename",
        "_permission_id",
        "_user_id",
        "_verified_at",
    )

    def __init__(
        self,
        *,
        connection: BaseDatabaseWrapper,
        database_alias: str,
        user_id: int,
        permission_id: int,
        verified_at: datetime,
        expires_at: datetime,
    ) -> None:
        """Create an internal lease after locks and standard ``has_perm`` succeed."""

        self._active = True
        self._connection = connection
        self._database_alias = database_alias
        self._user_id = user_id
        self._permission_id = permission_id
        self._permission_app_label = FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL
        self._permission_codename = FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME
        self._verified_at = _utc(verified_at, "permission_verified_at")
        self._expires_at = _utc(expires_at, "session_expires_at")

    @property
    def user_id(self) -> int:
        """Return the locked Django User primary key while the lease is active."""

        self.assert_live()
        return self._user_id

    @property
    def permission_id(self) -> int:
        """Return the locked dedicated Permission primary key while active."""

        self.assert_live()
        return self._permission_id

    @property
    def permission_app_label(self) -> str:
        """Return the exact locked Permission app label while active."""

        self.assert_live()
        return self._permission_app_label

    @property
    def permission_codename(self) -> str:
        """Return the exact locked Permission codename while active."""

        self.assert_live()
        return self._permission_codename

    @property
    def database_alias(self) -> str:
        """Return the alias holding the still-live User and grant locks."""

        self.assert_live()
        return self._database_alias

    @property
    def verified_at(self) -> datetime:
        """Return server verification time after the exact permission check."""

        self.assert_live()
        return self._verified_at

    def assert_live(self) -> None:
        """Require this lease's outer UOW and session expiry to remain valid."""

        if not self._active:
            raise AuthorizationError("C2 Owner authorization lease is no longer active.")
        if not self._connection.in_atomic_block:
            raise AuthorizationError("C2 Owner authorization locks are not held.")
        now = _db_clock(self._database_alias)
        if now >= self._expires_at:
            raise AuthenticationError("C2 Owner session expired during its operation.")

    def deactivate(self) -> None:
        """Expire the attribution object as soon as the caller UOW exits."""

        self._active = False


class DjangoFinancialAvailabilityPermissionAuthorizer(
    FinancialAvailabilityPermissionAuthorizerPort
):
    """Recheck one authenticated database session and standard C2 permission."""

    def __init__(self, *, using: str) -> None:
        """Bind this fixed-purpose C2 authorizer to one explicit alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataValidationError("C2 permission authorizer requires one explicit alias.")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias holding the locked User and C2 permission facts."""

        return self._using

    @contextmanager
    def lock_authorized_principal(
        self,
        proof: FinancialAvailabilitySessionRequestProof,
    ) -> Iterator[LockedFinancialAvailabilityPrincipal]:
        """Hold actual session, User, Permission and applicable grant rows locked."""

        if type(proof) is not FinancialAvailabilitySessionRequestProof:
            raise AuthenticationError("C2 Owner operation requires the exact session proof.")
        try:
            proof.__post_init__()
        except (TypeError, ValueError) as error:
            raise AuthenticationError("C2 Owner session proof is invalid.") from error
        if proof.database_alias != self._using:
            raise AuthorizationError("C2 Owner proof targets a different database alias.")
        if settings.SESSION_ENGINE != _DATABASE_SESSION_ENGINE:
            raise ExternalServiceError("C2 Owner authorization requires database sessions.")
        connection = connections[self._using]
        if connection.vendor != "postgresql" or not connection.in_atomic_block:
            raise ExternalServiceError("C2 Owner authorization requires a PostgreSQL caller UOW.")
        _require_read_committed_uow(self._using)
        user_model = get_user_model()
        user_permission_through = user_model.user_permissions.through
        user_group_through = user_model.groups.through
        group_permission_through = Group.permissions.through
        _require_same_alias(
            self._using,
            (
                Session,
                user_model,
                ContentType,
                Permission,
                Group,
                user_permission_through,
                user_group_through,
                group_permission_through,
            ),
        )
        try:
            session = (
                Session.objects.using(self._using)
                .select_for_update()
                .get(session_key=proof.session_key)
            )
            user = (
                user_model._base_manager.using(self._using)
                .select_for_update()
                .get(pk=proof.user_id)
            )
            if user._state.db != self._using or user.is_active is not True:
                raise AuthenticationError("C2 Owner session user is inactive or on another alias.")
            content_type = (
                ContentType.objects.using(self._using)
                .select_for_update()
                .get(
                    app_label=FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL,
                    model=FinancialAvailabilityGovernanceRecordModel._meta.model_name,
                )
            )
            permission = (
                Permission.objects.using(self._using)
                .select_for_update()
                .get(
                    content_type=content_type,
                    codename=FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
                )
            )
            has_persisted_grant = True
            if not user.is_superuser:
                has_persisted_grant = _lock_applicable_grants(
                    user_model=user_model,
                    user_id=proof.user_id,
                    permission_id=permission.pk,
                    using=self._using,
                    user_permission_through=user_permission_through,
                    user_group_through=user_group_through,
                    group_permission_through=group_permission_through,
                )
            _clear_permission_cache(user)
            if user.has_perm(_C2_PERMISSION) is not True:
                raise AuthorizationError("C2 Owner lacks the dedicated Django permission.")
            if not has_persisted_grant:
                raise AuthorizationError("C2 Owner has no persisted direct or group grant.")
        except (Session.DoesNotExist, user_model.DoesNotExist) as error:
            raise AuthenticationError("C2 Owner session or User no longer exists.") from error
        except (ContentType.DoesNotExist, Permission.DoesNotExist) as error:
            raise AuthorizationError("Dedicated C2 Django permission is not configured.") from error
        except DatabaseError as error:
            raise ExternalServiceError("C2 Owner authentication storage is unavailable.") from error

        verified_at = _db_clock(self._using)
        _verify_stored_session(session, user, proof=proof, verified_at=verified_at)
        expires_at = _utc(session.expire_date, "session_expire_date")
        if verified_at < proof.request_authenticated_at:
            raise AuthenticationError("C2 request authentication time is in the future.")
        lease = _FinancialAvailabilityPrincipalLease(
            connection=connection,
            database_alias=self._using,
            user_id=proof.user_id,
            permission_id=permission.pk,
            verified_at=verified_at,
            expires_at=expires_at,
        )
        try:
            yield lease
            lease.assert_live()
        finally:
            lease.deactivate()


def _require_same_alias(using: str, route_models: tuple[type[Model], ...]) -> None:
    """Reject auth routers that split locked identity rows across databases."""

    for model in route_models:
        read_alias = router.db_for_read(model) or DEFAULT_DB_ALIAS
        write_alias = router.db_for_write(model) or DEFAULT_DB_ALIAS
        if read_alias != using or write_alias != using:
            raise ExternalServiceError("C2 Owner identity and grants do not share one alias.")


def _related_id_field(model: type[Model], target: type[Model]) -> str:
    """Return the one concrete FK attname in a Django auth through model."""

    matches = tuple(
        field.attname
        for field in model._meta.fields
        if getattr(getattr(field, "remote_field", None), "model", None) is target
    )
    if len(matches) != 1:
        raise ExternalServiceError("C2 Owner permission through model has an unknown shape.")
    return matches[0]


def _lock_applicable_grants(
    *,
    user_model: type[User],
    user_id: int,
    permission_id: int,
    using: str,
    user_permission_through: type[Model],
    user_group_through: type[Model],
    group_permission_through: type[Model],
) -> bool:
    """Lock real grants and return the locked result without a second query."""

    user_field = _related_id_field(user_permission_through, user_model)
    direct_permission_field = _related_id_field(user_permission_through, Permission)
    membership_user_field = _related_id_field(user_group_through, user_model)
    membership_group_field = _related_id_field(user_group_through, Group)
    group_permission_field = _related_id_field(group_permission_through, Group)
    group_permission_id_field = _related_id_field(group_permission_through, Permission)
    direct_rows = tuple(
        user_permission_through._default_manager.using(using)
        .select_for_update()
        .filter(**{user_field: user_id, direct_permission_field: permission_id})
        .order_by("pk")
    )
    membership_rows = tuple(
        user_group_through._default_manager.using(using)
        .select_for_update()
        .filter(**{membership_user_field: user_id})
        .order_by("pk")
    )
    group_ids = tuple(
        sorted({cast(int, getattr(row, membership_group_field)) for row in membership_rows})
    )
    if not group_ids:
        return bool(direct_rows)
    group_rows = tuple(
        group_permission_through._default_manager.using(using)
        .select_for_update()
        .filter(
            **{
                f"{group_permission_field}__in": group_ids,
                group_permission_id_field: permission_id,
            }
        )
        .order_by("pk")
    )
    return bool(direct_rows or group_rows)


def _clear_permission_cache(user: User) -> None:
    """Make Django ``has_perm`` read grants after the exact row locks are held."""

    for name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(user, name):
            delattr(user, name)


def _verify_stored_session(
    session: Session,
    user: User,
    *,
    proof: FinancialAvailabilitySessionRequestProof,
    verified_at: datetime,
) -> None:
    """Bind the locked session row to request user, backend, auth hash and expiry."""

    decoded = session.get_decoded()
    if type(decoded) is not dict or any(type(key) is not str for key in decoded):
        raise AuthenticationError("C2 Owner session payload is invalid.")
    session_user_id = decoded.get(SESSION_KEY)
    backend_path = decoded.get(BACKEND_SESSION_KEY)
    session_auth_hash = decoded.get(HASH_SESSION_KEY)
    if (
        type(session_user_id) is not str
        or session_user_id != str(proof.user_id)
        or type(backend_path) is not str
        or backend_path not in settings.AUTHENTICATION_BACKENDS
        or type(session_auth_hash) is not str
        or not constant_time_compare(session_auth_hash, user.get_session_auth_hash())
        or session._state.db != proof.database_alias
        or _utc(session.expire_date, "session.expire_date") <= verified_at
    ):
        raise AuthenticationError("C2 Owner session no longer authenticates this User.")


__all__ = ["DjangoFinancialAvailabilityPermissionAuthorizer"]
