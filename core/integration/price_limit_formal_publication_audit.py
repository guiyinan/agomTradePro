"""Core bridge for price-limit pointer transitions and closed Audit evidence."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from apps.audit.application.price_limit_publication_audit import (
    PriceLimitAuditPublisherPrincipal,
    PriceLimitPublicationAuditReadResult,
    PriceLimitPublicationAuditUnavailable,
    PriceLimitPublicationAuditUseCase,
    PriceLimitPublicationAuditValidationError,
)
from apps.audit.domain.price_limit_publication_audit import (
    PRICE_LIMIT_PUBLICATION_DATASET,
    PriceLimitPublicationAuditContractError,
    PriceLimitPublicationPublishedDetail,
    PriceLimitPublicationRecordEvidence,
    PriceLimitPublicationRollbackDetail,
    PriceLimitPublicationTransitionEvidence,
    validate_price_limit_publication_event,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.audit.price_limit_publication_composition import (
    PriceLimitPublicationAuditCoordinator,
    build_price_limit_publication_audit_coordinator,
)
from apps.data_center.application.price_limit_formal_publication_audit_port import (
    PriceLimitFormalPublicationAuditPort,
    PriceLimitPublicationAuditPair,
)
from apps.data_center.application.price_limit_publication_authority import (
    PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME,
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.domain.control_plane import PublicationRollback
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitPublicationError,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationTimelineEvent,
)
from core.exceptions import InvalidInputError

_ACTOR_RE = re.compile(r"^django-user:([1-9][0-9]{0,18})$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class PriceLimitPublicationAuditCoordinatorFactory(Protocol):
    """Alias-bound Audit coordinator factory accepted by this bridge."""

    def __call__(self, *, using: str) -> PriceLimitPublicationAuditCoordinator:
        """Build the exact same-alias Audit Application coordinator."""


class CorePriceLimitFormalPublicationAuditBridge(PriceLimitFormalPublicationAuditPort):
    """Implement Data Center's narrow port with Audit's exact pair use cases."""

    __slots__ = ("_using", "_coordinator")

    def __init__(
        self,
        *,
        using: str = "default",
        coordinator: PriceLimitPublicationAuditCoordinator | None = None,
        coordinator_factory: PriceLimitPublicationAuditCoordinatorFactory | None = None,
    ) -> None:
        """Bind one PriceLimit Audit coordinator to the caller's database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit bridge requires an explicit database alias"
            )
        if coordinator is not None and coordinator_factory is not None:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit bridge accepts one composition source"
            )
        if coordinator is None:
            factory = coordinator_factory or build_price_limit_publication_audit_coordinator
            try:
                coordinator = factory(using=using)
            except (InvalidInputError, TypeError, ValueError) as error:
                raise PriceLimitPublicationAuditUnavailable(
                    "price-limit Audit composition is unavailable"
                ) from error
        if coordinator.database_alias != using:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit coordinator uses another database alias"
            )
        self._using = using
        self._coordinator = coordinator

    @property
    def database_alias(self) -> str:
        """Return the alias shared with the caller-owned Data Center transaction."""

        return self._using

    def record_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Append a pointer transition and its full seal under the live lease."""

        self._validate_record_event(record, event)
        self._validate_principal(principal)
        _require_utc(server_now, "server_now")
        if server_now < principal.verified_at or server_now < event.transitioned_at:
            raise PriceLimitPublicationAuditValidationError(
                "price-limit Audit clock precedes the locked authorization or pointer transition"
            )
        principal.assert_live()
        detail = _detail_from_record_and_event(
            record,
            event,
            observed_server_at=server_now,
        )
        result = PriceLimitPublicationAuditUseCase(
            self._coordinator
        ).append_transition_in_caller_transaction(
            detail,
            principal=cast(PriceLimitAuditPublisherPrincipal, principal),
            server_now=server_now,
        )
        principal.assert_live()
        return self._pair_from_result(
            result,
            expected_transition=event,
            expected_actor_user_id=principal.user_id,
            server_now=server_now,
        )

    def get_first_transition(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Read a publication's exact first Audit event/outbox by immutable identity."""

        self._validate_principal(principal)
        _require_utc(server_now, "server_now")
        if type(publication_hash) is not str or _DIGEST_RE.fullmatch(publication_hash) is None:
            raise PriceLimitPublicationAuditValidationError("publication_hash is invalid")
        principal.assert_live()
        result = PriceLimitPublicationAuditUseCase(
            self._coordinator
        ).read_first_transition_in_caller_transaction(
            publication_id=publication_id,
            publication_hash=publication_hash,
            principal=cast(PriceLimitAuditPublisherPrincipal, principal),
            server_now=server_now,
        )
        principal.assert_live()
        return self._pair_from_result(
            result,
            expected_transition=None,
            expected_actor_user_id=None,
            server_now=server_now,
        )

    def verify_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Verify one exact stored transition and its outbox under current permission."""

        self._validate_record_event(record, event)
        self._validate_principal(principal)
        _require_utc(server_now, "server_now")
        if server_now < principal.verified_at or server_now < event.transitioned_at:
            raise PriceLimitPublicationAuditValidationError(
                "price-limit verification clock precedes permission or transition time"
            )
        principal.assert_live()
        expected = _detail_from_record_and_event(
            record,
            event,
            observed_server_at=server_now,
        )
        result = PriceLimitPublicationAuditUseCase(
            self._coordinator
        ).verify_transition_in_caller_transaction(
            expected,
            principal=cast(PriceLimitAuditPublisherPrincipal, principal),
            server_now=server_now,
        )
        principal.assert_live()
        return self._pair_from_result(
            result,
            expected_transition=event,
            expected_actor_user_id=None,
            server_now=server_now,
        )

    def _validate_record_event(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
    ) -> None:
        """Revalidate the exact target record and the transition that points to it."""

        _validate_typed_record_event(record, event)

    def _validate_principal(self, principal: LockedPriceLimitPublisherPrincipal) -> None:
        """Require the live session principal for this exact permission and alias."""

        try:
            principal.assert_live()
            valid = (
                type(principal.actor_type) is str
                and principal.actor_type == "django_user"
                and type(principal.user_id) is int
                and principal.user_id > 0
                and type(principal.actor_id) is str
                and principal.actor_id == f"django-user:{principal.user_id}"
                and _ACTOR_RE.fullmatch(principal.actor_id) is not None
                and type(principal.permission_codename) is str
                and principal.permission_codename == PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME
                and type(principal.permission_id) is int
                and principal.permission_id > 0
                and type(principal.database_alias) is str
                and principal.database_alias == self._using
                and _is_utc(principal.verified_at)
                and type(principal.authority_content_hash) is str
                and _AUTHORITY_HASH_RE.fullmatch(principal.authority_content_hash) is not None
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise PriceLimitPublicationAuditValidationError(
                "price-limit Audit bridge received an incomplete locked publisher lease"
            ) from error
        if not valid:
            raise PriceLimitPublicationAuditValidationError(
                "price-limit Audit bridge received another permission, actor, or database"
            )

    def _pair_from_result(
        self,
        result: PriceLimitPublicationAuditReadResult,
        *,
        expected_transition: PriceLimitPublicationTimelineEvent | None,
        expected_actor_user_id: int | None,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Map only an exact valid Audit event/outbox result to the DC receipt."""

        if type(result) is not PriceLimitPublicationAuditReadResult:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit use case returned no exact pair result"
            )
        try:
            PriceLimitPublicationAuditReadResult.__post_init__(result)
            event = result.commit.event
            validate_price_limit_publication_event(event)
            transition = _timeline_event_from_evidence(result.detail.transition)
        except (
            AttributeError,
            TypeError,
            ValueError,
            PriceLimitPublicationAuditContractError,
        ) as error:
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit event/outbox result failed exact validation"
            ) from error
        actor_match = _ACTOR_RE.fullmatch(event.actor.actor_id)
        if (
            type(event) is not SystemAuditEvent
            or event.scope is not None
            or event.dataset_key != PRICE_LIMIT_PUBLICATION_DATASET
            or event.recorded_at != result.detail.observed_server_at
            or event.recorded_at > server_now
            or event.observed_at != event.recorded_at
            or event.occurred_at != transition.transitioned_at
            or event.actor.actor_type != "django_user"
            or actor_match is None
            or event.event_id != result.commit.event_id
            or event.idempotency_key != result.commit.idempotency_key
            or event.idempotency_key != event.event_id
            or type(result.commit.outbox_id) is not UUID
            or _DIGEST_RE.fullmatch(event.content_hash) is None
            or (expected_transition is not None and transition != expected_transition)
            or (
                expected_actor_user_id is not None
                and int(actor_match.group(1)) != expected_actor_user_id
            )
        ):
            raise PriceLimitPublicationAuditUnavailable(
                "price-limit Audit pair does not bind the exact transition and server clock"
            )
        return PriceLimitPublicationAuditPair(
            database_alias=self._using,
            dataset_key=transition.dataset_key,
            publication_key=transition.publication_key,
            publication_id=transition.target_publication_id,
            publication_hash=transition.target_publication_hash,
            transition_event_id=transition.event_id,
            timeline_event=transition,
            audit_event_id=event.event_id,
            audit_event_content_hash=event.content_hash,
            actor_user_id=int(actor_match.group(1)),
            outbox_id=result.commit.outbox_id,
            idempotency_key=event.idempotency_key,
            recorded_at=event.recorded_at,
            observed_server_at=event.observed_at,
        )


def build_price_limit_publication_audit_detail(
    record: PriceLimitFormalPublicationRecord,
    event: PriceLimitPublicationTimelineEvent,
    *,
    observed_server_at: datetime,
) -> PriceLimitPublicationPublishedDetail | PriceLimitPublicationRollbackDetail:
    """Build the exact Audit detail from Data Center's typed seal and transition."""

    _validate_typed_record_event(record, event)
    _require_utc(observed_server_at, "observed_server_at")
    if observed_server_at < event.transitioned_at:
        raise PriceLimitPublicationAuditValidationError(
            "server observation precedes the PriceLimit pointer transition"
        )
    return _detail_from_record_and_event(
        record,
        event,
        observed_server_at=observed_server_at,
    )


def _validate_typed_record_event(
    record: PriceLimitFormalPublicationRecord,
    event: PriceLimitPublicationTimelineEvent,
) -> None:
    """Revalidate the exact target record and transition identity."""

    if type(record) is not PriceLimitFormalPublicationRecord:
        raise PriceLimitPublicationAuditValidationError(
            "price-limit Audit bridge requires a typed formal record"
        )
    if type(event) is not PriceLimitPublicationTimelineEvent:
        raise PriceLimitPublicationAuditValidationError(
            "price-limit Audit bridge requires a typed timeline event"
        )
    try:
        record.validate()
        event.validate()
    except (AttributeError, TypeError, ValueError, PriceLimitPublicationError) as error:
        raise PriceLimitPublicationAuditValidationError(
            "price-limit publication record or transition is invalid"
        ) from error
    if (
        event.dataset_key != record.seal.dataset_contract.key.value
        or event.publication_key != record.seal.publication_key
        or event.target_publication_id != record.publication_id
        or event.target_publication_hash != record.publication_hash
    ):
        raise PriceLimitPublicationAuditValidationError(
            "price-limit timeline target differs from the exact sealed record"
        )
    if event.kind in {
        PriceLimitPublicationEventKind.FIRST_PUBLISH,
        PriceLimitPublicationEventKind.FORWARD_PUBLISH,
    } and (
        record.first_published_at != event.transitioned_at
        or record.first_activation_id != event.event_id
    ):
        raise PriceLimitPublicationAuditValidationError(
            "price-limit forward record differs from its activation event"
        )


def _detail_from_record_and_event(
    record: PriceLimitFormalPublicationRecord,
    event: PriceLimitPublicationTimelineEvent,
    *,
    observed_server_at: datetime,
) -> PriceLimitPublicationPublishedDetail | PriceLimitPublicationRollbackDetail:
    """Translate Data Center's exact record and transition into Audit's closed DTO."""

    reference = record.seal.snapshot_reference
    publication = PriceLimitPublicationRecordEvidence.from_payload(
        {
            "publication_id": record.publication_id,
            "publication_hash": record.publication_hash,
            "publication_key": record.seal.publication_key,
            "provider_id": reference.provider_id,
            "provider_name": reference.provider_name,
            "asset_code": reference.asset_code,
            "effective_trade_date": reference.effective_trade_date.isoformat(),
            "request_scope_sha256": reference.request_scope_sha256,
            "first_published_at": _utc_text(record.first_published_at),
            "first_activation_id": record.first_activation_id,
            "seal": record.seal.to_payload(),
        }
    )
    rollback_payload: dict[str, object] | None = None
    if event.rollback is not None:
        rollback = event.rollback
        rollback_payload = {
            "target_publication_id": rollback.target_publication_id,
            "reason": rollback.reason,
            "operator": rollback.operator,
            "observed_at": _utc_text(rollback.observed_at),
            "previous_publication_id": rollback.previous_publication_id,
            "rollback_id": rollback.rollback_id,
        }
    transition = PriceLimitPublicationTransitionEvidence.from_payload(
        {
            "kind": event.kind.value,
            "event_id": event.event_id,
            "dataset_key": event.dataset_key,
            "publication_key": event.publication_key,
            "previous_publication_id": event.previous_publication_id,
            "previous_publication_hash": event.previous_publication_hash,
            "target_publication_id": event.target_publication_id,
            "target_publication_hash": event.target_publication_hash,
            "transitioned_at": _utc_text(event.transitioned_at),
            "rollback": rollback_payload,
        }
    )
    if event.kind is PriceLimitPublicationEventKind.ROLLBACK:
        return PriceLimitPublicationRollbackDetail(
            publication=publication,
            transition=transition,
            observed_server_at=observed_server_at,
        )
    return PriceLimitPublicationPublishedDetail(
        publication=publication,
        transition=transition,
        observed_server_at=observed_server_at,
    )


def _timeline_event_from_evidence(
    transition: PriceLimitPublicationTransitionEvidence,
) -> PriceLimitPublicationTimelineEvent:
    """Restore the business timeline type from its verified detail projection."""

    rollback = None
    if transition.rollback is not None:
        payload = transition.rollback
        rollback = PublicationRollback(
            target_publication_id=cast(str, payload["target_publication_id"]),
            reason=cast(str, payload["reason"]),
            operator=cast(str, payload["operator"]),
            observed_at=_parse_utc(cast(str, payload["observed_at"])),
            previous_publication_id=cast(str, payload["previous_publication_id"]),
            rollback_id=cast(str, payload["rollback_id"]),
        )
    return PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind(transition.kind),
        event_id=transition.event_id,
        dataset_key=transition.dataset_key,
        publication_key=transition.publication_key,
        previous_publication_id=transition.previous_publication_id,
        previous_publication_hash=transition.previous_publication_hash,
        target_publication_id=transition.target_publication_id,
        target_publication_hash=transition.target_publication_hash,
        transitioned_at=transition.transitioned_at,
        rollback=rollback,
    )


def _require_utc(value: object, field_name: str) -> None:
    """Require an aware zero-offset clock without normalizing caller input."""

    if not _is_utc(value):
        raise PriceLimitPublicationAuditValidationError(f"{field_name} must be UTC")


def _is_utc(value: object) -> bool:
    """Return whether a value is a zero-offset timezone-aware datetime."""

    return (
        type(value) is datetime and value.tzinfo is not None and value.utcoffset() == timedelta(0)
    )


def _utc_text(value: datetime) -> str:
    """Serialize exact UTC time at microsecond precision."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    """Parse canonical UTC timestamp emitted by this bridge."""

    if not value.endswith("Z"):
        raise PriceLimitPublicationAuditUnavailable(
            "PriceLimit rollback clock is not canonical UTC"
        )
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
    except ValueError as error:
        raise PriceLimitPublicationAuditUnavailable(
            "PriceLimit rollback clock is invalid"
        ) from error


__all__ = [
    "CorePriceLimitFormalPublicationAuditBridge",
    "build_price_limit_publication_audit_detail",
]
