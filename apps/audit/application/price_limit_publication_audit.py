"""Application use cases for the closed price-limit publication Audit family."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.price_limit_publication_audit import (
    PRICE_LIMIT_PUBLICATION_DATASET,
    PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT,
    PRICE_LIMIT_PUBLICATION_PUBLISHED_SCHEMA,
    PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT,
    PRICE_LIMIT_PUBLICATION_ROLLED_BACK_SCHEMA,
    PRICE_LIMIT_PUBLISH_PERMISSION,
    PriceLimitPublicationAuditContractError,
    PriceLimitPublicationDetail,
    PriceLimitPublicationPublishedDetail,
    PriceLimitPublicationRollbackDetail,
    price_limit_publication_event_identity,
    price_limit_publication_stream_id,
    validate_price_limit_publication_event,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)
from core.exceptions import (
    AgomTradeProException,
    AuthenticationError,
    AuthorizationError,
    BusinessLogicError,
    DuplicateResourceError,
    MissingConfigError,
)

_ACTOR_RE = re.compile(r"^django-user:([1-9][0-9]{0,18})$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class PriceLimitPublicationAuditUnavailable(MissingConfigError):
    """The exact price-limit Audit port or persisted pair is unavailable."""

    default_message = "Price-limit publication Audit is unavailable"
    default_code = "PRICE_LIMIT_PUBLICATION_AUDIT_UNAVAILABLE"
    default_status_code = 503


class PriceLimitPublicationAuditDenied(AuthorizationError):
    """The caller has no live price-limit publisher capability for this alias."""

    default_message = "Price-limit publication permission is denied"
    default_code = "PRICE_LIMIT_PUBLICATION_AUDIT_DENIED"


class PriceLimitPublicationAuditConflict(DuplicateResourceError):
    """A transition identity or pointer predecessor conflicts with its winner."""

    default_message = "Price-limit publication Audit identity conflicts with its winner"
    default_code = "PRICE_LIMIT_PUBLICATION_AUDIT_CONFLICT"


class PriceLimitPublicationAuditCorruption(AgomTradeProException):
    """A persisted PriceLimit event or outbox pair violates the closed contract."""

    default_message = "Price-limit publication Audit evidence is corrupt"
    default_code = "PRICE_LIMIT_PUBLICATION_AUDIT_CORRUPTION"
    default_status_code = 500


class PriceLimitPublicationAuditValidationError(BusinessLogicError):
    """The typed caller observation is invalid for the PriceLimit Audit family."""

    default_message = "Price-limit publication Audit input is invalid"
    default_code = "PRICE_LIMIT_PUBLICATION_AUDIT_VALIDATION_ERROR"


class PriceLimitAuditPublisherPrincipal(Protocol):
    """Structural view of the locked Data Center price-limit lease."""

    @property
    def actor_type(self) -> str:
        """Return the authenticated actor kind while the lease remains live."""

    @property
    def actor_id(self) -> str:
        """Return the canonical authenticated actor identity."""

    @property
    def permission_codename(self) -> str:
        """Return the fixed price-limit publication permission codename."""

    @property
    def database_alias(self) -> str:
        """Return the same alias locked by the publication transaction."""

    @property
    def user_id(self) -> int:
        """Return the authenticated session user ID."""

    @property
    def permission_id(self) -> int:
        """Return the exact permission row identity."""

    @property
    def verified_at(self) -> datetime:
        """Return the UTC time at which the current grant was locked and checked."""

    @property
    def authority_content_hash(self) -> str:
        """Return the grant's exact content hash without exposing session material."""

    def assert_live(self) -> None:
        """Revalidate the live locked permission lease."""


class PriceLimitPublicationAuditWriter(Protocol):
    """Same-alias caller-owned SystemAudit/outbox capabilities for price limits."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared by event and outbox repositories."""

    def caller_owned_atomic(self) -> AbstractContextManager[None]:
        """Join the already-open Data Center publication transaction."""

    def lock_stream(self, stream_id: str) -> None:
        """Serialize the exact provider/security/date Audit stream."""

    def get_price_limit_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        publication_key: str | None,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read only the one stable price-limit event identity."""

    def get_price_limit_publication_head_targeted(
        self,
        *,
        dataset_key: str,
        publication_key: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read the current head of one deterministic pointer stream."""

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read only the outbox row paired with the supplied exact event."""

    def append_and_enqueue_price_limit_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        principal: PriceLimitAuditPublisherPrincipal,
    ) -> SystemAuditEventOutboxCommit:
        """Atomically append one closed price-limit event/outbox pair."""


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationAuditReadResult:
    """Exact parsed detail and event/outbox identity returned by a targeted read."""

    detail: PriceLimitPublicationDetail
    commit: SystemAuditEventOutboxCommit

    def __post_init__(self) -> None:
        """Prove the read result still contains the exact complete pair."""

        if type(self.commit) is not SystemAuditEventOutboxCommit:
            raise PriceLimitPublicationAuditCorruption(
                "price-limit Audit result has no exact commit"
            )
        try:
            SystemAuditEventOutboxCommit.__post_init__(self.commit)
            validate_price_limit_publication_event(self.commit.event)
        except (AttributeError, TypeError, ValueError) as error:
            raise PriceLimitPublicationAuditCorruption(
                "price-limit Audit result failed event contract validation"
            ) from error
        if self.commit.event.detail != self.detail.to_payload():
            raise PriceLimitPublicationAuditCorruption(
                "price-limit Audit result detail differs from its event"
            )


def build_price_limit_publication_event(
    detail: PriceLimitPublicationDetail,
    *,
    principal: PriceLimitAuditPublisherPrincipal,
    database_alias: str,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one exact global publish or rollback event under the live lease."""

    detail = _validated_detail(detail)
    if (
        type(database_alias) is not str
        or not database_alias
        or database_alias.strip() != database_alias
    ):
        raise PriceLimitPublicationAuditValidationError("Audit database alias is invalid")
    if type(sequence_no) is not int or sequence_no <= 0:
        raise PriceLimitPublicationAuditValidationError("Audit sequence number must be positive")
    if predecessor_hash is not None and _DIGEST_RE.fullmatch(predecessor_hash) is None:
        raise PriceLimitPublicationAuditValidationError("Audit predecessor hash is invalid")
    principal_values = _validated_publisher_principal(principal, database_alias)
    if detail.observed_server_at < principal_values[1]:
        raise PriceLimitPublicationAuditDenied(
            "price-limit event clock precedes the locked publisher verification"
        )
    publication = detail.publication
    transition = detail.transition
    is_rollback = type(detail) is PriceLimitPublicationRollbackDetail
    if is_rollback:
        identity = price_limit_publication_event_identity(rollback_id=transition.event_id)
        event_type = PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT
        detail_schema = PRICE_LIMIT_PUBLICATION_ROLLED_BACK_SCHEMA
        outcome = AuditOutcome.ROLLED_BACK
        reason = "price_limit_publication_rolled_back"
    else:
        identity = price_limit_publication_event_identity(
            publication_id=publication.publication_id,
            publication_hash=publication.publication_hash,
        )
        event_type = PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT
        detail_schema = PRICE_LIMIT_PUBLICATION_PUBLISHED_SCHEMA
        outcome = AuditOutcome.PUBLISHED
        reason = "price_limit_publication_published"
    actor = AuditActorRef(
        actor_type="django_user",
        actor_id=principal_values[0],
    )
    event = SystemAuditEvent.create(
        event_id=identity[0],
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=event_type,
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=outcome,
        severity=AuditSeverity.INFO,
        reason_codes=(reason,),
        occurred_at=transition.transitioned_at,
        recorded_at=detail.observed_server_at,
        observed_at=detail.observed_server_at,
        actor=actor,
        source_app="data_center",
        source_component="price_limit_publication",
        source_surface="application",
        correlations=AuditCorrelations(
            dataset_key=PRICE_LIMIT_PUBLICATION_DATASET,
            provider_key=str(publication.provider_id),
            capability="price_limit.publication",
            publication_id=publication.publication_id,
            evidence_ref=(
                f"price-limit-publication:{publication.publication_id}:"
                f"{publication.publication_hash}"
            ),
        ),
        resource=AuditResourceRef("price_limit_publication", publication.publication_id, "v1"),
        dataset_key=PRICE_LIMIT_PUBLICATION_DATASET,
        provider_key=str(publication.provider_id),
        capability="price_limit.publication",
        publication_id=publication.publication_id,
        evidence_refs=(
            AuditEvidenceRef(
                owner="data_center",
                artifact_type="price_limit_publication_seal",
                artifact_id=publication.publication_id,
                artifact_version="price-limit-publication.v1",
                content_hash=publication.publication_hash,
            ),
        ),
        detail_schema=detail_schema,
        detail=detail.to_payload(),
        stream_id=price_limit_publication_stream_id(
            transition.dataset_key, transition.publication_key
        ),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=identity[1],
        scope=None,
    )
    try:
        validate_price_limit_publication_event(event)
    except PriceLimitPublicationAuditContractError as error:
        raise PriceLimitPublicationAuditValidationError(str(error), code=error.code) from error
    return event


class PriceLimitPublicationAuditUseCase:
    """Append or verify exact PriceLimit transitions within caller-owned UOWs."""

    __slots__ = ("_writer",)

    def __init__(self, writer: PriceLimitPublicationAuditWriter) -> None:
        """Bind the use case to an explicit same-alias Audit port."""

        self._writer = writer

    def append_transition_in_caller_transaction(
        self,
        detail: PriceLimitPublicationDetail,
        *,
        principal: PriceLimitAuditPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditReadResult:
        """Append a first-winner transition and its exact transactional outbox."""

        detail = _validated_detail(detail)
        server_now = _require_server_clock(server_now, detail=detail)
        alias = self._validate_composition()
        _validated_publisher_principal(principal, alias)
        transition = detail.transition
        identity = _event_identity(detail)
        stream_id = price_limit_publication_stream_id(
            transition.dataset_key, transition.publication_key
        )
        try:
            principal.assert_live()
            with self._writer.caller_owned_atomic():
                principal.assert_live()
                self._writer.lock_stream(stream_id)
                winner = self._writer.get_price_limit_publication_winner_targeted(
                    event_id=identity[0],
                    event_version="1",
                    dataset_key=transition.dataset_key,
                    publication_key=transition.publication_key,
                    as_of=server_now,
                )
                if winner is not None:
                    raise PriceLimitPublicationAuditConflict(
                        "price-limit Audit identity already has a first event winner"
                    )
                head = self._writer.get_price_limit_publication_head_targeted(
                    dataset_key=transition.dataset_key,
                    publication_key=transition.publication_key,
                    as_of=server_now,
                )
                self._validate_predecessor(detail, head, server_now)
                if type(detail) is PriceLimitPublicationRollbackDetail:
                    self._validate_rollback_target(detail, principal, server_now)
                sequence_no = head.sequence_no + 1 if head is not None else 1
                predecessor_hash = head.content_hash if head is not None else None
                event = build_price_limit_publication_event(
                    detail,
                    principal=principal,
                    database_alias=alias,
                    sequence_no=sequence_no,
                    predecessor_hash=predecessor_hash,
                )
                orphan = self._writer.get_exact_outbox_winner_targeted(event)
                if orphan is not None:
                    raise PriceLimitPublicationAuditCorruption(
                        "price-limit outbox identity exists without its event winner"
                    )
                principal.assert_live()
                commit = self._writer.append_and_enqueue_price_limit_targeted(
                    event,
                    expected_predecessor_hash=predecessor_hash,
                    recorded_at=server_now,
                    principal=principal,
                )
                if commit.event != event:
                    raise PriceLimitPublicationAuditCorruption(
                        "price-limit Audit writer substituted the transition event"
                    )
                result = PriceLimitPublicationAuditReadResult(detail=detail, commit=commit)
                principal.assert_live()
                return result
        except (
            PriceLimitPublicationAuditUnavailable,
            PriceLimitPublicationAuditDenied,
            PriceLimitPublicationAuditConflict,
            PriceLimitPublicationAuditCorruption,
            PriceLimitPublicationAuditValidationError,
        ):
            raise
        except AuthorizationError as error:
            raise PriceLimitPublicationAuditDenied() from error
        except SystemAuditEventOutboxConflict as error:
            raise PriceLimitPublicationAuditConflict() from error
        except SystemAuditEventOutboxCorruption as error:
            raise PriceLimitPublicationAuditCorruption() from error
        except SystemAuditEventOutboxUnavailable as error:
            raise PriceLimitPublicationAuditUnavailable() from error
        except Exception as error:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit append failed"
            ) from error

    def read_first_transition_in_caller_transaction(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        principal: PriceLimitAuditPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditReadResult:
        """Read one publication's stable first/forward event and exact outbox pair."""

        alias = self._validate_composition()
        _validated_publisher_principal(principal, alias)
        _require_utc(server_now, "server_now")
        try:
            identity = price_limit_publication_event_identity(
                publication_id=publication_id,
                publication_hash=publication_hash,
            )
        except PriceLimitPublicationAuditContractError as error:
            raise PriceLimitPublicationAuditValidationError(str(error), code=error.code) from error
        try:
            principal.assert_live()
            with self._writer.caller_owned_atomic():
                principal.assert_live()
                winner = self._writer.get_price_limit_publication_winner_targeted(
                    event_id=identity[0],
                    event_version="1",
                    dataset_key=PRICE_LIMIT_PUBLICATION_DATASET,
                    publication_key=None,
                    as_of=server_now,
                )
                if winner is None:
                    raise PriceLimitPublicationAuditCorruption(
                        "publication has no exact first PriceLimit Audit event"
                    )
                parsed_detail = _detail_from_event(winner)
                self._writer.lock_stream(
                    price_limit_publication_stream_id(
                        parsed_detail.transition.dataset_key,
                        parsed_detail.transition.publication_key,
                    )
                )
                winner = self._writer.get_price_limit_publication_winner_targeted(
                    event_id=identity[0],
                    event_version="1",
                    dataset_key=PRICE_LIMIT_PUBLICATION_DATASET,
                    publication_key=parsed_detail.transition.publication_key,
                    as_of=server_now,
                )
                if winner is None:
                    raise PriceLimitPublicationAuditCorruption(
                        "publication event disappeared while locking its exact stream"
                    )
                result = self._read_winner(winner, server_now)
                detail = result.detail
                if (
                    type(detail) is not PriceLimitPublicationPublishedDetail
                    or detail.publication.publication_id != publication_id
                    or detail.publication.publication_hash != publication_hash
                    or detail.transition.kind not in {"first_publish", "forward_publish"}
                ):
                    raise PriceLimitPublicationAuditCorruption(
                        "publication Audit winner differs from the exact publication selector"
                    )
                principal.assert_live()
                return result
        except (
            PriceLimitPublicationAuditUnavailable,
            PriceLimitPublicationAuditDenied,
            PriceLimitPublicationAuditConflict,
            PriceLimitPublicationAuditCorruption,
            PriceLimitPublicationAuditValidationError,
        ):
            raise
        except AuthorizationError as error:
            raise PriceLimitPublicationAuditDenied() from error
        except SystemAuditEventOutboxConflict as error:
            raise PriceLimitPublicationAuditCorruption() from error
        except SystemAuditEventOutboxCorruption as error:
            raise PriceLimitPublicationAuditCorruption() from error
        except SystemAuditEventOutboxUnavailable as error:
            raise PriceLimitPublicationAuditUnavailable() from error
        except Exception as error:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit exact read failed"
            ) from error

    def verify_transition_in_caller_transaction(
        self,
        expected_detail: PriceLimitPublicationDetail,
        *,
        principal: PriceLimitAuditPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditReadResult:
        """Verify an exact stored event/outbox without repairing a missing half-pair."""

        expected_detail = _validated_detail(expected_detail)
        alias = self._validate_composition()
        _validated_publisher_principal(principal, alias)
        _require_utc(server_now, "server_now")
        identity = _event_identity(expected_detail)
        transition = expected_detail.transition
        try:
            principal.assert_live()
            with self._writer.caller_owned_atomic():
                principal.assert_live()
                self._writer.lock_stream(
                    price_limit_publication_stream_id(
                        transition.dataset_key, transition.publication_key
                    )
                )
                winner = self._writer.get_price_limit_publication_winner_targeted(
                    event_id=identity[0],
                    event_version="1",
                    dataset_key=transition.dataset_key,
                    publication_key=transition.publication_key,
                    as_of=server_now,
                )
                if winner is None:
                    raise PriceLimitPublicationAuditCorruption(
                        "exact PriceLimit Audit replay has no event winner"
                    )
                result = self._read_winner(winner, server_now)
                if _detail_without_server_clock(result.detail) != _detail_without_server_clock(
                    expected_detail
                ):
                    raise PriceLimitPublicationAuditCorruption(
                        "stored PriceLimit Audit detail differs from the exact pointer transition"
                    )
                principal.assert_live()
                return result
        except (
            PriceLimitPublicationAuditUnavailable,
            PriceLimitPublicationAuditDenied,
            PriceLimitPublicationAuditConflict,
            PriceLimitPublicationAuditCorruption,
            PriceLimitPublicationAuditValidationError,
        ):
            raise
        except AuthorizationError as error:
            raise PriceLimitPublicationAuditDenied() from error
        except SystemAuditEventOutboxConflict as error:
            raise PriceLimitPublicationAuditCorruption() from error
        except SystemAuditEventOutboxCorruption as error:
            raise PriceLimitPublicationAuditCorruption() from error
        except SystemAuditEventOutboxUnavailable as error:
            raise PriceLimitPublicationAuditUnavailable() from error
        except Exception as error:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit verification failed"
            ) from error

    def _validate_composition(self) -> str:
        """Require a concrete, explicit alias from the composed writer."""

        alias = self._writer.database_alias
        if type(alias) is not str or not alias or alias.strip() != alias:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit writer has no exact database alias"
            )
        return alias

    def _read_winner(
        self,
        winner: SystemAuditEvent,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditReadResult:
        """Revalidate one targeted event and its exact outbox row."""

        if type(winner) is not SystemAuditEvent:
            raise PriceLimitPublicationAuditCorruption(
                "price-limit Audit selector returned an invalid event"
            )
        try:
            validate_price_limit_publication_event(winner)
            detail = _detail_from_event(winner)
        except (
            AttributeError,
            TypeError,
            ValueError,
            PriceLimitPublicationAuditContractError,
        ) as error:
            raise PriceLimitPublicationAuditCorruption(
                "stored PriceLimit Audit event violates its closed contract"
            ) from error
        if winner.recorded_at > server_now or winner.observed_at != winner.recorded_at:
            raise PriceLimitPublicationAuditCorruption(
                "stored PriceLimit Audit event is outside the current server cutoff"
            )
        outbox = self._writer.get_exact_outbox_winner_targeted(winner)
        commit = _commit_from_outbox(outbox, winner)
        return PriceLimitPublicationAuditReadResult(detail=detail, commit=commit)

    def _validate_predecessor(
        self,
        detail: PriceLimitPublicationDetail,
        head: SystemAuditEvent | None,
        server_now: datetime,
    ) -> None:
        """Require the pointer transition to follow the current Audit winner exactly."""

        transition = detail.transition
        if transition.kind == "first_publish":
            if head is not None:
                raise PriceLimitPublicationAuditConflict(
                    "first price-limit publication has an existing stream predecessor"
                )
            return
        if head is None:
            raise PriceLimitPublicationAuditCorruption(
                "price-limit transition has no prior publication Audit event"
            )
        prior_detail = self._read_winner(head, server_now).detail
        if (
            prior_detail.transition.target_publication_id != transition.previous_publication_id
            or prior_detail.transition.target_publication_hash
            != transition.previous_publication_hash
            or transition.transitioned_at <= prior_detail.transition.transitioned_at
        ):
            raise PriceLimitPublicationAuditConflict(
                "price-limit pointer predecessor differs from the locked Audit head"
            )

    def _validate_rollback_target(
        self,
        detail: PriceLimitPublicationRollbackDetail,
        principal: PriceLimitAuditPublisherPrincipal,
        server_now: datetime,
    ) -> None:
        """Require rollback target to be an exact, previously published seal."""

        identity = price_limit_publication_event_identity(
            publication_id=detail.publication.publication_id,
            publication_hash=detail.publication.publication_hash,
        )
        winner = self._writer.get_price_limit_publication_winner_targeted(
            event_id=identity[0],
            event_version="1",
            dataset_key=detail.transition.dataset_key,
            publication_key=detail.transition.publication_key,
            as_of=server_now,
        )
        if winner is None:
            raise PriceLimitPublicationAuditConflict(
                "rollback target has no previously published event"
            )
        result = self._read_winner(winner, server_now)
        if (
            type(result.detail) is not PriceLimitPublicationPublishedDetail
            or result.detail.publication != detail.publication
        ):
            raise PriceLimitPublicationAuditCorruption(
                "rollback target event does not bind the exact prior publication seal"
            )
        principal.assert_live()


def _detail_without_server_clock(detail: PriceLimitPublicationDetail) -> tuple[object, ...]:
    """Return the exact business content excluding the time of this read or append."""

    return (type(detail), detail.publication, detail.transition)


def _detail_from_event(event: SystemAuditEvent) -> PriceLimitPublicationDetail:
    """Parse the one recognized registered detail schema."""

    if event.event_type == PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT:
        return PriceLimitPublicationPublishedDetail.from_payload(event.detail)
    if event.event_type == PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT:
        return PriceLimitPublicationRollbackDetail.from_payload(event.detail)
    raise PriceLimitPublicationAuditCorruption("event is outside the PriceLimit family")


def _commit_from_outbox(
    outbox: ExactSystemAuditOutboxWinner | None,
    event: SystemAuditEvent,
) -> SystemAuditEventOutboxCommit:
    """Require the exact outbox record; never repair a half-pair on read/replay."""

    if type(outbox) is not ExactSystemAuditOutboxWinner:
        raise PriceLimitPublicationAuditCorruption(
            "PriceLimit Audit event has no exact outbox winner"
        )
    try:
        ExactSystemAuditOutboxWinner.__post_init__(outbox)
    except (AttributeError, TypeError, ValueError) as error:
        raise PriceLimitPublicationAuditCorruption(
            "PriceLimit outbox winner is malformed"
        ) from error
    if (
        outbox.event != event
        or outbox.event_id != event.event_id
        or outbox.idempotency_key != event.idempotency_key
        or outbox.payload_hash != event.content_hash
    ):
        raise PriceLimitPublicationAuditCorruption(
            "PriceLimit Audit outbox does not pair with its exact event"
        )
    return SystemAuditEventOutboxCommit(
        event=event,
        outbox_id=outbox.outbox_id,
        event_id=outbox.event_id,
        idempotency_key=outbox.idempotency_key,
    )


def _event_identity(detail: PriceLimitPublicationDetail) -> tuple[str, str]:
    """Return the deterministic event ID for one typed detail."""

    if type(detail) is PriceLimitPublicationRollbackDetail:
        return price_limit_publication_event_identity(rollback_id=detail.transition.event_id)
    return price_limit_publication_event_identity(
        publication_id=detail.publication.publication_id,
        publication_hash=detail.publication.publication_hash,
    )


def _validated_detail(value: object) -> PriceLimitPublicationDetail:
    """Revalidate an exact registered detail before any persistence access."""

    detail: PriceLimitPublicationDetail
    if type(value) is PriceLimitPublicationPublishedDetail:
        detail = value
    elif type(value) is PriceLimitPublicationRollbackDetail:
        detail = value
    else:
        raise PriceLimitPublicationAuditValidationError("price-limit Audit detail is invalid")
    try:
        detail.__post_init__()
    except (
        AttributeError,
        TypeError,
        ValueError,
        PriceLimitPublicationAuditContractError,
    ) as error:
        raise PriceLimitPublicationAuditValidationError(
            "price-limit Audit detail violates its closed contract"
        ) from error
    return detail


def _validated_publisher_principal(
    principal: PriceLimitAuditPublisherPrincipal,
    database_alias: str,
) -> tuple[str, datetime]:
    """Require a live locked user grant for this exact alias and fixed codename."""

    try:
        principal.assert_live()
        actor_type = principal.actor_type
        actor_id = principal.actor_id
        permission_codename = principal.permission_codename
        user_id = principal.user_id
        permission_id = principal.permission_id
        principal_alias = principal.database_alias
        verified_at = principal.verified_at
        authority_hash = principal.authority_content_hash
    except (
        AttributeError,
        TypeError,
        ValueError,
        AuthenticationError,
        AuthorizationError,
    ) as error:
        raise PriceLimitPublicationAuditDenied(
            "price-limit publisher lease is missing or expired"
        ) from error
    if (
        type(actor_type) is not str
        or actor_type != "django_user"
        or type(user_id) is not int
        or user_id <= 0
        or type(actor_id) is not str
        or actor_id != f"django-user:{user_id}"
        or _ACTOR_RE.fullmatch(actor_id) is None
        or type(permission_codename) is not str
        or permission_codename != PRICE_LIMIT_PUBLISH_PERMISSION
        or type(permission_id) is not int
        or permission_id <= 0
        or type(principal_alias) is not str
        or principal_alias != database_alias
        or type(authority_hash) is not str
        or _AUTHORITY_HASH_RE.fullmatch(authority_hash) is None
        or not _is_utc(verified_at)
    ):
        raise PriceLimitPublicationAuditDenied(
            "price-limit publisher lease differs from the exact permission and alias"
        )
    return actor_id, verified_at


def _require_server_clock(
    value: object,
    *,
    detail: PriceLimitPublicationDetail,
) -> datetime:
    """Require the exact actual server clock carried in this event detail."""

    if type(value) is not datetime or not _is_utc(value):
        raise PriceLimitPublicationAuditValidationError("server_now must be an aware UTC instant")
    if detail.observed_server_at != value:
        raise PriceLimitPublicationAuditValidationError(
            "detail observed clock must equal the supplied server clock"
        )
    if value < detail.transition.transitioned_at:
        raise PriceLimitPublicationAuditValidationError(
            "server clock precedes the pointer transition"
        )
    return value


def _require_utc(value: object, field_name: str) -> datetime:
    """Require an aware zero-offset datetime."""

    if type(value) is not datetime or not _is_utc(value):
        raise PriceLimitPublicationAuditValidationError(f"{field_name} must be UTC-aware")
    return value


def _is_utc(value: object) -> bool:
    """Return whether the value is a UTC-aware datetime."""

    return (
        type(value) is datetime and value.tzinfo is not None and value.utcoffset() == timedelta(0)
    )


__all__ = [
    "PriceLimitAuditPublisherPrincipal",
    "PriceLimitPublicationAuditConflict",
    "PriceLimitPublicationAuditCorruption",
    "PriceLimitPublicationAuditDenied",
    "PriceLimitPublicationAuditReadResult",
    "PriceLimitPublicationAuditUnavailable",
    "PriceLimitPublicationAuditValidationError",
    "PriceLimitPublicationAuditUseCase",
    "PriceLimitPublicationAuditWriter",
    "build_price_limit_publication_event",
]
