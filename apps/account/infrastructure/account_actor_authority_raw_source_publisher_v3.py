"""Django gateway for publishing Account raw authority facts from a session request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    load_backend,
)
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db import DatabaseError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist
from django.utils.crypto import constant_time_compare

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_capture,
)
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    AccountActorAuthorityRawSourcePublicationReceiptV3,
    AccountActorAuthorityRawSourcePublisherGatewayV3,
    AccountActorAuthorityRawSourceSelectorV3,
)
from apps.account.application.account_authentication_context_source_v3 import (
    PersistedAccountAuthenticationContextSourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.application.account_user_authority_source_v3 import (
    PersistedAccountUserAuthoritySourceV3,
)
from apps.account.application.rbac import get_user_role
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
    root_claim_hash_for_account_authentication_context_source_v3,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
    root_claim_hash_for_account_user_authority_source_v3,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    DjangoAccountActorAuthorityRawSourceRepositoriesFactoryV3,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_repository import (
    DjangoAccountRbacAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_user_authority_source_v3_repository import (
    DjangoAccountUserAuthoritySourceV3Repository,
)
from apps.account.infrastructure.identity_models import (
    AccountProfileModel,
)


class SessionProofV3(Protocol):
    """Minimal server-side session contract needed for authentication proof."""

    session_key: str | None

    def get(self, key: str, default: object = None) -> object:
        """Read one session value without exposing the session representation."""


class AccountAuthorityClockV3(Protocol):
    """Provide the source observation clock used by the gateway."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


@dataclass(frozen=True, slots=True)
class _AuthenticatedRuntimeFacts:
    """Validated request facts retained only inside the persistence gateway."""

    user: User
    profile: AccountProfileModel
    user_id: int
    actor_id: str
    principal_id: str
    observed_at: datetime
    recorded_at: datetime
    session_valid_until: datetime
    rbac_role: str
    is_staff: bool
    is_superuser: bool


@dataclass(frozen=True, slots=True)
class _EffectiveRoleInput:
    """Application RBAC view of the fresh User/Profile rows."""

    is_authenticated: bool
    is_superuser: bool
    account_profile: AccountProfileModel


@dataclass(frozen=True, slots=True)
class _RawSourceRecords:
    """The three exact raw records returned by their own repositories."""

    authentication: PersistedAccountAuthenticationContextSourceV3
    user: PersistedAccountUserAuthoritySourceV3
    rbac: PersistedAccountRbacAuthoritySourceV3


class DjangoAccountActorAuthorityRawSourcePublisherGatewayV3(
    AccountActorAuthorityRawSourcePublisherGatewayV3
):
    """Publish one authenticated session's existing Account authority facts."""

    _RAW_RECORDER_SERVICE_ID = "account-actor-authority-raw-publisher-v3"
    _ACTOR_RECORDER_SERVICE_ID = "account-actor-authority-actor-publisher-v3"
    _ACTOR_VALIDITY_PERIOD = timedelta(minutes=5)
    _SOURCE_VERSION = "v1"

    def __init__(
        self,
        *,
        authenticated_user: object,
        session: SessionProofV3,
        using: str = "default",
        clock: AccountAuthorityClockV3 | None = None,
    ) -> None:
        """Bind the gateway to the request's session and one explicit DB alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be one exact database alias")
        if authenticated_user is None or session is None:
            raise TypeError("authenticated user and session are required")
        self._authenticated_user = authenticated_user
        self._session = session
        self._using = using
        self._clock = clock or _DjangoAccountAuthorityClock()

    def publish(self) -> AccountActorAuthorityRawSourcePublicationReceiptV3:
        """Validate the live session and append all four raw sources atomically."""

        _require_postgresql_alias(self._using)
        try:
            with transaction.atomic(using=self._using):
                facts = self._read_authenticated_facts()
                records = self._append_raw_sources(facts)
                actor = self._capture_actor(facts, records)
                return _receipt(facts, records, actor)
        except (
            AccountActorAuthorityRawSourceV3Conflict,
            AccountActorAuthorityRawSourceV3Corruption,
            AccountActorAuthorityRawSourceV3Unavailable,
        ):
            raise
        except (
            AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
        ) as error:
            raise _translate_actor_error(error) from error
        except ObjectDoesNotExist as error:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "authenticated Account profile is unavailable"
            ) from error
        except DatabaseError as error:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "authenticated Account authority persistence is unavailable"
            ) from error
        except (AttributeError, ImproperlyConfigured, TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "authenticated Account authority facts are invalid"
            ) from error

    def _read_authenticated_facts(self) -> _AuthenticatedRuntimeFacts:
        """Lock and read fresh User/Profile rows after proving the current session."""

        _require_user_database_alias(self._authenticated_user, self._using)
        request_user_id = _request_user_id(self._authenticated_user)
        observed_at, session_valid_until = _prove_session(
            authenticated_user=self._authenticated_user,
            session=self._session,
            using=self._using,
            now=self._clock.now(),
        )
        user = User._default_manager.using(self._using).select_for_update().get(pk=request_user_id)
        if type(user.is_active) is not bool or user.is_active is not True:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "authenticated Account user is inactive"
            )
        profile = (
            AccountProfileModel._default_manager.using(self._using)
            .select_for_update()
            .get(user_id=request_user_id)
        )
        if profile.user_id != request_user_id:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "authenticated Account profile belongs to another user"
            )
        _verify_session_user_hash(self._session, user)
        recorded_at = self._clock.now()
        _require_clock_window(observed_at, recorded_at, session_valid_until)
        role = _effective_rbac_role(user, profile)
        is_staff = _exact_bool(user.is_staff, "is_staff")
        is_superuser = _exact_bool(user.is_superuser, "is_superuser")
        principal_id = _new_principal_id()
        user_id = _positive_user_id(user.pk)
        return _AuthenticatedRuntimeFacts(
            user=user,
            profile=profile,
            user_id=user_id,
            actor_id=f"django-user:{user_id}",
            principal_id=principal_id,
            observed_at=observed_at,
            recorded_at=recorded_at,
            session_valid_until=session_valid_until,
            rbac_role=role,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def _append_raw_sources(self, facts: _AuthenticatedRuntimeFacts) -> _RawSourceRecords:
        """Append the auth, User, and RBAC roots inside the caller's transaction."""

        repositories = DjangoAccountActorAuthorityRawSourceRepositoriesFactoryV3().build(
            using=self._using
        )
        recorder = AccountActorAuthorityRawSourceV3Recorder(self._RAW_RECORDER_SERVICE_ID)
        authentication, user, rbac = _build_raw_sources(facts)
        authentication_repository = cast(
            DjangoAccountAuthenticationContextSourceV3Repository, repositories.authentication
        )
        user_repository = cast(DjangoAccountUserAuthoritySourceV3Repository, repositories.user)
        rbac_repository = cast(DjangoAccountRbacAuthoritySourceV3Repository, repositories.rbac)
        with authentication_repository.atomic():
            authentication_record = authentication_repository.append(
                PersistedAccountAuthenticationContextSourceV3(authentication, recorder),
                expected_predecessor_hash=None,
                recorded_at=authentication.clock.recorded_at,
            )
        with user_repository.atomic():
            user_record = user_repository.append(
                PersistedAccountUserAuthoritySourceV3(user, recorder),
                expected_predecessor_hash=None,
                recorded_at=user.clock.recorded_at,
            )
        with rbac_repository.atomic():
            rbac_record = rbac_repository.append(
                PersistedAccountRbacAuthoritySourceV3(rbac, recorder),
                expected_predecessor_hash=None,
                recorded_at=rbac.clock.recorded_at,
            )
        return _RawSourceRecords(authentication_record, user_record, rbac_record)

    def _capture_actor(
        self, facts: _AuthenticatedRuntimeFacts, records: _RawSourceRecords
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3:
        """Capture the actor source from the three just-persisted exact roots."""

        actor_id = _source_id("actor", facts.principal_id)
        capture = build_account_actor_authority_capture(
            recorder_service_id=self._ACTOR_RECORDER_SERVICE_ID,
            validity_period=self._ACTOR_VALIDITY_PERIOD,
            using=self._using,
        )
        command = CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
            source_id=actor_id,
            source_version=self._SOURCE_VERSION,
            principal_id=facts.principal_id,
            user_id=facts.user_id,
            authentication_context_id=records.authentication.source.identity.source_id,
            authentication_context_version=records.authentication.source.identity.source_version,
            expected_authentication_context_content_hash=records.authentication.source.content_hash,
            user_source_id=records.user.source.identity.source_id,
            user_source_version=records.user.source.identity.source_version,
            expected_user_source_content_hash=records.user.source.content_hash,
            rbac_source_id=records.rbac.source.identity.source_id,
            rbac_source_version=records.rbac.source.identity.source_version,
            expected_rbac_source_content_hash=records.rbac.source.content_hash,
        )
        actor = capture.execute(command)
        _verify_actor_source(actor, facts, records)
        return actor


class _DjangoAccountAuthorityClock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return the current aware server timestamp."""

        return timezone.now()


def build_account_actor_authority_raw_source_publisher_gateway(
    *,
    authenticated_user: object,
    session: SessionProofV3,
    using: str = "default",
) -> AccountActorAuthorityRawSourcePublisherGatewayV3:
    """Build the session-bound infrastructure gateway for the Account use case."""

    return DjangoAccountActorAuthorityRawSourcePublisherGatewayV3(
        authenticated_user=authenticated_user,
        session=session,
        using=using,
    )


def _require_postgresql_alias(using: str) -> None:
    """Require the requested alias to be PostgreSQL before opening the write boundary."""

    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError, ImproperlyConfigured) as error:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority database alias is unavailable"
        ) from error
    if connection.vendor != "postgresql":
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "raw authority publication requires PostgreSQL"
        )


def _request_user_id(authenticated_user: object) -> int:
    """Read the request user's positive primary key without trusting request data."""

    if getattr(authenticated_user, "is_authenticated", False) is not True:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "raw authority publication requires an authenticated session"
        )
    return _positive_user_id(getattr(authenticated_user, "pk", None))


def _require_user_database_alias(authenticated_user: object, using: str) -> None:
    """Reject a request User object loaded from a different database alias."""

    state = getattr(authenticated_user, "_state", None)
    bound_alias = getattr(state, "db", None)
    if type(bound_alias) is not str or bound_alias != using:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authenticated Account user is bound to another database alias"
        )


def _positive_user_id(value: object) -> int:
    """Validate one exact positive Django user primary key."""

    if type(value) is not int or value <= 0:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authenticated Account user has no stable identity"
        )
    return value


def _prove_session(
    *, authenticated_user: object, session: SessionProofV3, using: str, now: datetime
) -> tuple[datetime, datetime]:
    """Lock and prove the database session row that authenticates this request."""

    if not _is_aware(now):
        raise AccountActorAuthorityRawSourceV3Corruption("authority clock is naive")
    key = session.session_key
    if type(key) is not str or not key:
        raise AccountActorAuthorityRawSourceV3Unavailable("authenticated session is unavailable")
    try:
        stored = Session._default_manager.using(using).select_for_update().get(session_key=key)
    except Session.DoesNotExist as error:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authenticated session is unavailable"
        ) from error
    expiry = stored.expire_date
    if not _is_aware(expiry) or expiry <= now:
        raise AccountActorAuthorityRawSourceV3Unavailable("authenticated session is expired")
    decoded = stored.get_decoded()
    if type(decoded) is not dict:
        raise AccountActorAuthorityRawSourceV3Unavailable("authenticated session is invalid")
    request_values = {
        SESSION_KEY: session.get(SESSION_KEY, None),
        BACKEND_SESSION_KEY: session.get(BACKEND_SESSION_KEY, None),
        HASH_SESSION_KEY: session.get(HASH_SESSION_KEY, None),
    }
    if any(decoded.get(name) != value for name, value in request_values.items()):
        raise AccountActorAuthorityRawSourceV3Unavailable("authenticated session is stale")
    session_user_id = session.get(SESSION_KEY, None)
    stored_user_id = decoded.get(SESSION_KEY)
    if type(session_user_id) is not str or stored_user_id != session_user_id:
        raise AccountActorAuthorityRawSourceV3Unavailable("session user binding is invalid")
    request_user_id = _request_user_id(authenticated_user)
    if session_user_id != str(request_user_id):
        raise AccountActorAuthorityRawSourceV3Unavailable("session user binding differs")
    backend = session.get(BACKEND_SESSION_KEY, None)
    stored_backend = decoded.get(BACKEND_SESSION_KEY)
    if type(backend) is not str or not backend or stored_backend != backend:
        raise AccountActorAuthorityRawSourceV3Unavailable("session backend binding is invalid")
    configured_backends = getattr(settings, "AUTHENTICATION_BACKENDS", ())
    if type(configured_backends) not in (tuple, list) or backend not in configured_backends:
        raise AccountActorAuthorityRawSourceV3Unavailable("session backend binding is invalid")
    try:
        load_backend(backend)
    except (ImportError, ImproperlyConfigured) as error:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "session backend binding is unavailable"
        ) from error
    session_hash = session.get(HASH_SESSION_KEY, None)
    stored_hash = decoded.get(HASH_SESSION_KEY)
    if type(session_hash) is not str or not session_hash or stored_hash != session_hash:
        raise AccountActorAuthorityRawSourceV3Unavailable("session authentication proof is invalid")
    return now, expiry


def _verify_session_user_hash(session: SessionProofV3, user: User) -> None:
    """Compare the live User auth hash with the server session's private proof."""

    session_hash = session.get(HASH_SESSION_KEY, None)
    if type(session_hash) is not str or not session_hash:
        raise AccountActorAuthorityRawSourceV3Unavailable("session authentication proof is invalid")
    if not constant_time_compare(session_hash, user.get_session_auth_hash()):
        raise AccountActorAuthorityRawSourceV3Unavailable("session authentication proof is stale")


def _effective_rbac_role(user: User, profile: AccountProfileModel) -> str:
    """Use the existing RBAC precedence, including superuser-to-admin mapping."""

    if type(profile.rbac_role) is not str:
        raise AccountActorAuthorityRawSourceV3Corruption("Account profile RBAC role is invalid")
    role = get_user_role(
        _EffectiveRoleInput(
            is_authenticated=_exact_bool(user.is_authenticated, "is_authenticated"),
            is_superuser=_exact_bool(user.is_superuser, "is_superuser"),
            account_profile=profile,
        )
    )
    if type(role) is not str or not role:
        raise AccountActorAuthorityRawSourceV3Corruption("Account RBAC role is invalid")
    return role


def _exact_bool(value: object, name: str) -> bool:
    """Require one Django BooleanField fact to remain an exact boolean."""

    if type(value) is not bool:
        raise AccountActorAuthorityRawSourceV3Corruption(f"Account {name} fact is invalid")
    return value


def _require_clock_window(
    observed_at: datetime, recorded_at: datetime, valid_until: datetime
) -> None:
    """Ensure recording occurs during the still-valid authenticated session."""

    if not (_is_aware(observed_at) and _is_aware(recorded_at) and _is_aware(valid_until)):
        raise AccountActorAuthorityRawSourceV3Corruption("authority source clock is invalid")
    if not observed_at <= recorded_at < valid_until:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "session expired during authority capture"
        )


def _build_raw_sources(
    facts: _AuthenticatedRuntimeFacts,
) -> tuple[
    AccountAuthenticationContextSourceV3, AccountUserAuthoritySourceV3, AccountRbacAuthoritySourceV3
]:
    """Create three Domain roots from only locked server-side facts."""

    auth_source_id = _source_id("authentication", facts.principal_id)
    user_source_id = _source_id("user", facts.principal_id)
    rbac_source_id = _source_id("rbac", facts.principal_id)
    clock = AccountAuthorityRawSourceClockV3(
        observed_at=facts.observed_at,
        recorded_at=facts.recorded_at,
        valid_until=facts.session_valid_until,
    )
    auth = AccountAuthenticationContextSourceV3(
        identity=AccountAuthorityRawSourceIdentityV3(auth_source_id, "v1"),
        clock=clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_authentication_context_source_v3(
                source_id=auth_source_id,
                principal_id=facts.principal_id,
                user_id=facts.user_id,
                actor_id=facts.actor_id,
            )
        ),
        principal_id=facts.principal_id,
        user_id=facts.user_id,
        actor_id=facts.actor_id,
        is_authenticated=True,
        authority_state="authenticated",
        authenticated_at=facts.observed_at,
    )
    user = AccountUserAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3(user_source_id, "v1"),
        clock=clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_user_authority_source_v3(
                source_id=user_source_id,
                user_id=facts.user_id,
                actor_id=facts.actor_id,
            )
        ),
        user_id=facts.user_id,
        actor_id=facts.actor_id,
        is_active=True,
        is_staff=facts.is_staff,
        is_superuser=facts.is_superuser,
        authority_state="current",
    )
    rbac = AccountRbacAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3(rbac_source_id, "v1"),
        clock=clock,
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id=rbac_source_id,
                user_id=facts.user_id,
                actor_id=facts.actor_id,
            )
        ),
        user_id=facts.user_id,
        actor_id=facts.actor_id,
        rbac_role=facts.rbac_role,
        authority_state="current",
    )
    return auth, user, rbac


def _source_id(kind: str, principal_id: str) -> str:
    """Return a bounded session-bound source identity without carrying a secret."""

    return f"django-session-{kind}-authority-v3:{principal_id}"


def _new_principal_id() -> str:
    """Create an opaque request principal label without deriving it from session secrets."""

    return f"django-session-principal-v3:{uuid4().hex}"


def _verify_actor_source(
    actor: AccountOwnerAssignmentActorAuthoritySourceV3,
    facts: _AuthenticatedRuntimeFacts,
    records: _RawSourceRecords,
) -> None:
    """Ensure actor capture returned the exact roots and current request facts."""

    if type(actor) is not AccountOwnerAssignmentActorAuthoritySourceV3:
        raise AccountActorAuthorityRawSourceV3Corruption("actor source type was substituted")
    try:
        actor.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("actor source is corrupt") from error
    expected = (
        actor.principal_id,
        actor.user_id,
        actor.authentication_context_id,
        actor.authentication_context_version,
        actor.authentication_context_content_hash,
        actor.user_source_id,
        actor.user_source_version,
        actor.user_source_content_hash,
        actor.rbac_source_id,
        actor.rbac_source_version,
        actor.rbac_source_content_hash,
        actor.actor_id,
        actor.rbac_role,
        actor.is_authenticated,
        actor.is_active,
        actor.is_staff,
        actor.is_superuser,
    )
    actual = (
        facts.principal_id,
        facts.user_id,
        records.authentication.source.identity.source_id,
        records.authentication.source.identity.source_version,
        records.authentication.source.content_hash,
        records.user.source.identity.source_id,
        records.user.source.identity.source_version,
        records.user.source.content_hash,
        records.rbac.source.identity.source_id,
        records.rbac.source.identity.source_version,
        records.rbac.source.content_hash,
        facts.actor_id,
        facts.rbac_role,
        True,
        True,
        facts.is_staff,
        facts.is_superuser,
    )
    if expected != actual or actor.valid_until > facts.session_valid_until:
        raise AccountActorAuthorityRawSourceV3Corruption("actor source facts were substituted")


def _receipt(
    facts: _AuthenticatedRuntimeFacts,
    records: _RawSourceRecords,
    actor: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> AccountActorAuthorityRawSourcePublicationReceiptV3:
    """Project only exact selectors and public timing metadata into the response DTO."""

    return AccountActorAuthorityRawSourcePublicationReceiptV3(
        authentication_context=_selector(records.authentication.source),
        user=_selector(records.user.source),
        rbac=_selector(records.rbac.source),
        actor=_selector(actor),
        user_id=facts.user_id,
        principal_id=facts.principal_id,
        observed_at=facts.observed_at,
        valid_until=actor.valid_until,
    )


def _selector(
    source: (
        AccountAuthenticationContextSourceV3
        | AccountUserAuthoritySourceV3
        | AccountRbacAuthoritySourceV3
        | AccountOwnerAssignmentActorAuthoritySourceV3
    ),
) -> AccountActorAuthorityRawSourceSelectorV3:
    """Project one exact source identity and content hash into a safe selector."""

    if isinstance(source, AccountOwnerAssignmentActorAuthoritySourceV3):
        if type(source) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "authority source selector type was substituted"
            )
        source_id = source.source_id
        source_version = source.source_version
    else:
        source_id = source.identity.source_id
        source_version = source.identity.source_version
    try:
        return AccountActorAuthorityRawSourceSelectorV3(
            source_id, source_version, source.content_hash
        )
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority source selector is corrupt"
        ) from error


def _translate_actor_error(
    error: (
        AccountOwnerAssignmentActorAuthoritySourceV3Conflict
        | AccountOwnerAssignmentActorAuthoritySourceV3Corruption
        | AccountOwnerAssignmentActorAuthoritySourceV3Unavailable
    ),
) -> (
    AccountActorAuthorityRawSourceV3Conflict
    | AccountActorAuthorityRawSourceV3Corruption
    | AccountActorAuthorityRawSourceV3Unavailable
):
    """Map actor Application failures to the publisher's public error boundary."""

    if isinstance(error, AccountOwnerAssignmentActorAuthoritySourceV3Conflict):
        return AccountActorAuthorityRawSourceV3Conflict("actor authority capture conflicted")
    if isinstance(error, AccountOwnerAssignmentActorAuthoritySourceV3Unavailable):
        return AccountActorAuthorityRawSourceV3Unavailable("actor authority capture unavailable")
    return AccountActorAuthorityRawSourceV3Corruption("actor authority capture is corrupt")


def _is_aware(value: object) -> bool:
    """Return whether a value is an exact timezone-aware datetime."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "DjangoAccountActorAuthorityRawSourcePublisherGatewayV3",
    "SessionProofV3",
    "build_account_actor_authority_raw_source_publisher_gateway",
]
