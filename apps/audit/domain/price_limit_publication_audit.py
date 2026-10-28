"""Closed System Audit contracts for global price-limit publication transitions.

Price-limit snapshots have no tenant/run scope. This module registers only the
exact unscoped publish and rollback event families; it neither grants
publication authority nor assigns decision or execution eligibility.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, NoReturn
from uuid import UUID

from .system_audit_event import (
    AuditCategory,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)

PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT: Final[str] = "data.price_limit.publication.published"
PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT: Final[str] = "data.price_limit.publication.rolled_back"
PRICE_LIMIT_PUBLICATION_PUBLISHED_SCHEMA: Final[str] = "data.price_limit.publication.published.v1"
PRICE_LIMIT_PUBLICATION_ROLLED_BACK_SCHEMA: Final[str] = (
    "data.price_limit.publication.rolled_back.v1"
)
PRICE_LIMIT_PUBLICATION_DATASET: Final[str] = "equity.price.limit"
PRICE_LIMIT_PUBLICATION_OWNER: Final[str] = "data_center"
PRICE_LIMIT_PUBLICATION_COMPONENT: Final[str] = "price_limit_publication"
PRICE_LIMIT_PUBLICATION_STREAM_PREFIX: Final[str] = "data.price_limit.publication:"
PRICE_LIMIT_PUBLISH_PERMISSION: Final[str] = "publish_price_limit"
PRICE_LIMIT_SESSION_AUTHENTICATION: Final[str] = "session"
PRICE_LIMIT_PUBLISHED_REASON: Final[str] = "price_limit_publication_published"
PRICE_LIMIT_ROLLBACK_REASON: Final[str] = "price_limit_publication_rolled_back"
_EVENT_VERSION: Final[str] = "1"
_SYSTEM_SCHEMA_VERSION: Final[str] = "system-audit-event.v1"
_PLAIN_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$")
_ACTOR_RE: Final[re.Pattern[str]] = re.compile(r"^django-user:([1-9][0-9]{0,18})$")
_SEAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "encoding",
        "dataset_contract",
        "contract_recorded_at",
        "policy",
        "policy_recorded_at",
        "publication_key",
        "coverage_scope",
        "member_codec_version",
        "member_manifest_hash",
        "member_evidence",
        "snapshot",
        "snapshot_reference",
        "response_completed_at",
        "recorded_at",
        "source_clocks",
        "currency",
        "must_not_use_for_decision",
        "must_not_execute",
    }
)
_RECORD_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "publication_id",
        "publication_hash",
        "publication_key",
        "provider_id",
        "provider_name",
        "asset_code",
        "effective_trade_date",
        "request_scope_sha256",
        "first_published_at",
        "first_activation_id",
        "seal",
    }
)
_TRANSITION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "event_id",
        "dataset_key",
        "publication_key",
        "previous_publication_id",
        "previous_publication_hash",
        "target_publication_id",
        "target_publication_hash",
        "transitioned_at",
        "rollback",
    }
)
_ROLLBACK_KEYS: Final[frozenset[str]] = frozenset(
    {
        "target_publication_id",
        "reason",
        "operator",
        "observed_at",
        "previous_publication_id",
        "rollback_id",
    }
)
_DETAIL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "authentication_mode",
        "permission_codename",
        "publication",
        "transition",
        "observed_server_at",
    }
)


class PriceLimitPublicationAuditContractError(ValueError):
    """Recognized invalid PriceLimit Audit detail or event contract."""

    def __init__(self, code: str, message: str) -> None:
        """Keep a stable contract code for application error mapping."""

        self.code = code
        super().__init__(message)


def price_limit_publication_stream_id(dataset_key: str, publication_key: str) -> str:
    """Return the deterministic unscoped Audit stream for one price-limit pointer."""

    _require_token(dataset_key, "dataset_key")
    _require_token(publication_key, "publication_key")
    if dataset_key != PRICE_LIMIT_PUBLICATION_DATASET:
        raise PriceLimitPublicationAuditContractError(
            "PRICE_LIMIT_AUDIT_DATASET_INVALID", "price-limit Audit dataset is unsupported"
        )
    material = f"audit-price-limit-stream-v1\0{dataset_key}\0{publication_key}".encode()
    return f"{PRICE_LIMIT_PUBLICATION_STREAM_PREFIX}{hashlib.sha256(material).hexdigest()}"


def price_limit_publication_event_identity(
    *,
    publication_id: str | None = None,
    publication_hash: str | None = None,
    rollback_id: str | None = None,
) -> tuple[str, str]:
    """Return a stable Audit identity keyed by immutable publication or rollback identity.

    Publication events are keyed independently of the business activation ID,
    allowing a stored publication row to find its first transition. Rollbacks
    use their immutable rollback ID.
    """

    if rollback_id is not None:
        if publication_id is not None or publication_hash is not None:
            raise PriceLimitPublicationAuditContractError(
                "PRICE_LIMIT_AUDIT_EVENT_IDENTITY_INVALID",
                "rollback identity cannot be mixed with publication identity",
            )
        _require_uuid(rollback_id, "rollback_id")
        kind = "rollback"
        request_identity = rollback_id
    else:
        if publication_id is None or publication_hash is None:
            raise PriceLimitPublicationAuditContractError(
                "PRICE_LIMIT_AUDIT_EVENT_IDENTITY_INVALID",
                "published identity needs both publication ID and hash",
            )
        _require_uuid(publication_id, "publication_id")
        _require_plain_digest(publication_hash, "publication_hash")
        kind = "published"
        request_identity = f"{publication_id}\0{publication_hash}"
    material = "\0".join(("audit-price-limit-event-v1", kind, request_identity)).encode()
    identity = f"price-limit:{kind}:{hashlib.sha256(material).hexdigest()}"
    return identity, identity


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationRecordEvidence:
    """Full immutable publication seal plus its first business activation."""

    publication_id: str
    publication_hash: str
    publication_key: str
    provider_id: int
    provider_name: str
    asset_code: str
    effective_trade_date: date
    request_scope_sha256: str
    first_published_at: datetime
    first_activation_id: str
    seal: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        """Reject incomplete identity, mismatched scope, or damaged raw evidence."""

        _require_uuid(self.publication_id, "publication_id")
        _require_plain_digest(self.publication_hash, "publication_hash")
        _require_token(self.publication_key, "publication_key")
        if type(self.provider_id) is not int or self.provider_id <= 0:
            _fail("PRICE_LIMIT_AUDIT_SCOPE_INVALID", "provider_id must be a positive integer")
        _require_token(self.provider_name, "provider_name", maximum=100)
        _require_token(self.asset_code, "asset_code", maximum=32)
        _require_date(self.effective_trade_date, "effective_trade_date")
        _require_plain_digest(self.request_scope_sha256, "request_scope_sha256")
        _require_utc(self.first_published_at, "first_published_at")
        _require_token(self.first_activation_id, "first_activation_id")
        seal = _validate_seal_payload(self.seal)
        if seal["publication_key"] != self.publication_key:
            _fail("PRICE_LIMIT_AUDIT_SCOPE_MISMATCH", "seal pointer key differs from detail")
        reference = _mapping(seal["snapshot_reference"], "seal.snapshot_reference")
        snapshot = _mapping(seal["snapshot"], "seal.snapshot")
        if (
            reference.get("provider_id") != self.provider_id
            or reference.get("provider_name") != self.provider_name
            or reference.get("asset_code") != self.asset_code
            or reference.get("effective_trade_date") != self.effective_trade_date.isoformat()
            or reference.get("request_scope_sha256") != self.request_scope_sha256
            or snapshot.get("provider_id") != self.provider_id
            or snapshot.get("provider_name") != self.provider_name
            or snapshot.get("asset_code") != self.asset_code
            or snapshot.get("effective_trade_date") != self.effective_trade_date.isoformat()
            or snapshot.get("request_scope_sha256") != self.request_scope_sha256
        ):
            _fail("PRICE_LIMIT_AUDIT_SCOPE_MISMATCH", "scope differs from the sealed snapshot")
        _validate_source_evidence(seal, self.publication_hash)
        known_at = max(
            _parse_seal_utc(seal["response_completed_at"], "seal.response_completed_at"),
            _parse_seal_utc(seal["recorded_at"], "seal.recorded_at"),
            _parse_seal_utc(seal["contract_recorded_at"], "seal.contract_recorded_at"),
            _parse_seal_utc(seal["policy_recorded_at"], "seal.policy_recorded_at"),
        )
        if self.first_published_at < known_at:
            _fail(
                "PRICE_LIMIT_AUDIT_KNOWLEDGE_TIME_INVALID",
                "first publication precedes sealed evidence knowledge",
            )

    def to_payload(self) -> dict[str, JSONValue]:
        """Return exact publication, request scope, and full seal evidence."""

        self.__post_init__()
        return {
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
            "publication_key": self.publication_key,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "asset_code": self.asset_code,
            "effective_trade_date": self.effective_trade_date.isoformat(),
            "request_scope_sha256": self.request_scope_sha256,
            "first_published_at": _utc_text(self.first_published_at),
            "first_activation_id": self.first_activation_id,
            "seal": _json_copy(self.seal),
        }

    @classmethod
    def from_payload(cls, payload: object) -> PriceLimitPublicationRecordEvidence:
        """Parse one closed publication evidence object from canonical JSON."""

        value = _mapping(payload, "publication", _RECORD_EVIDENCE_KEYS)
        return cls(
            publication_id=_text(value["publication_id"], "publication.publication_id"),
            publication_hash=_text(value["publication_hash"], "publication.publication_hash"),
            publication_key=_text(value["publication_key"], "publication.publication_key"),
            provider_id=_positive_int(value["provider_id"], "publication.provider_id"),
            provider_name=_text(value["provider_name"], "publication.provider_name"),
            asset_code=_text(value["asset_code"], "publication.asset_code"),
            effective_trade_date=_parse_date(
                value["effective_trade_date"], "publication.effective_trade_date"
            ),
            request_scope_sha256=_text(
                value["request_scope_sha256"], "publication.request_scope_sha256"
            ),
            first_published_at=_parse_utc(
                value["first_published_at"], "publication.first_published_at"
            ),
            first_activation_id=_text(
                value["first_activation_id"], "publication.first_activation_id"
            ),
            seal=_mapping(value["seal"], "publication.seal"),
        )


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationTransitionEvidence:
    """Exact before/after pointer fact; event_id is the business transition identity."""

    kind: str
    event_id: str
    dataset_key: str
    publication_key: str
    previous_publication_id: str | None
    previous_publication_hash: str | None
    target_publication_id: str
    target_publication_hash: str
    transitioned_at: datetime
    rollback: Mapping[str, JSONValue] | None

    def __post_init__(self) -> None:
        """Validate transition ordering fields and the optional rollback fact."""

        if self.kind not in {"first_publish", "forward_publish", "rollback"}:
            _fail("PRICE_LIMIT_AUDIT_TRANSITION_INVALID", "transition kind is not registered")
        _require_token(self.event_id, "transition.event_id")
        _require_token(self.dataset_key, "transition.dataset_key", maximum=160)
        if self.dataset_key != PRICE_LIMIT_PUBLICATION_DATASET:
            _fail("PRICE_LIMIT_AUDIT_DATASET_INVALID", "transition dataset is not price-limit")
        _require_token(self.publication_key, "transition.publication_key")
        _require_uuid(self.target_publication_id, "transition.target_publication_id")
        _require_plain_digest(self.target_publication_hash, "transition.target_publication_hash")
        _require_utc(self.transitioned_at, "transition.transitioned_at")
        if (self.previous_publication_id is None) != (self.previous_publication_hash is None):
            _fail("PRICE_LIMIT_AUDIT_PREVIOUS_INVALID", "previous ID and hash must be paired")
        if self.previous_publication_id is not None:
            _require_uuid(self.previous_publication_id, "transition.previous_publication_id")
            _require_plain_digest(
                self.previous_publication_hash, "transition.previous_publication_hash"
            )
            if self.previous_publication_id == self.target_publication_id:
                _fail("PRICE_LIMIT_AUDIT_TRANSITION_NOOP", "transition cannot target itself")
        if self.kind == "first_publish":
            if self.previous_publication_id is not None or self.rollback is not None:
                _fail("PRICE_LIMIT_AUDIT_PREVIOUS_INVALID", "first publication has no predecessor")
        elif self.previous_publication_id is None:
            _fail(
                "PRICE_LIMIT_AUDIT_PREVIOUS_INVALID", "noninitial transition needs its predecessor"
            )
        if self.kind == "rollback":
            _validate_rollback_payload(self.rollback, self)
        elif self.rollback is not None:
            _fail(
                "PRICE_LIMIT_AUDIT_ROLLBACK_INVALID",
                "publish transition cannot carry rollback data",
            )

    def to_payload(self) -> dict[str, JSONValue]:
        """Return the exact timeline detail with business and audit IDs distinct."""

        self.__post_init__()
        return {
            "kind": self.kind,
            "event_id": self.event_id,
            "dataset_key": self.dataset_key,
            "publication_key": self.publication_key,
            "previous_publication_id": self.previous_publication_id,
            "previous_publication_hash": self.previous_publication_hash,
            "target_publication_id": self.target_publication_id,
            "target_publication_hash": self.target_publication_hash,
            "transitioned_at": _utc_text(self.transitioned_at),
            "rollback": _json_copy(self.rollback) if self.rollback is not None else None,
        }

    @classmethod
    def from_payload(cls, payload: object) -> PriceLimitPublicationTransitionEvidence:
        """Parse a transition with no ignored or unknown fields."""

        value = _mapping(payload, "transition", _TRANSITION_KEYS)
        return cls(
            kind=_text(value["kind"], "transition.kind"),
            event_id=_text(value["event_id"], "transition.event_id"),
            dataset_key=_text(value["dataset_key"], "transition.dataset_key"),
            publication_key=_text(value["publication_key"], "transition.publication_key"),
            previous_publication_id=(
                None
                if value["previous_publication_id"] is None
                else _text(value["previous_publication_id"], "transition.previous_publication_id")
            ),
            previous_publication_hash=(
                None
                if value["previous_publication_hash"] is None
                else _text(
                    value["previous_publication_hash"], "transition.previous_publication_hash"
                )
            ),
            target_publication_id=_text(
                value["target_publication_id"], "transition.target_publication_id"
            ),
            target_publication_hash=_text(
                value["target_publication_hash"], "transition.target_publication_hash"
            ),
            transitioned_at=_parse_utc(value["transitioned_at"], "transition.transitioned_at"),
            rollback=(
                None
                if value["rollback"] is None
                else _mapping(value["rollback"], "transition.rollback", _ROLLBACK_KEYS)
            ),
        )


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationPublishedDetail:
    """Closed v1 detail for first or forward publication transitions."""

    publication: PriceLimitPublicationRecordEvidence
    transition: PriceLimitPublicationTransitionEvidence
    observed_server_at: datetime

    def __post_init__(self) -> None:
        """Require one new publication and its exact first-activation identity."""

        if type(self.publication) is not PriceLimitPublicationRecordEvidence:
            _fail("PRICE_LIMIT_AUDIT_PUBLICATION_INVALID", "publication evidence must be typed")
        PriceLimitPublicationRecordEvidence.__post_init__(self.publication)
        if type(self.transition) is not PriceLimitPublicationTransitionEvidence:
            _fail("PRICE_LIMIT_AUDIT_TRANSITION_INVALID", "transition evidence must be typed")
        PriceLimitPublicationTransitionEvidence.__post_init__(self.transition)
        if self.transition.kind not in {"first_publish", "forward_publish"}:
            _fail(
                "PRICE_LIMIT_AUDIT_TRANSITION_INVALID",
                "published detail needs a publish transition",
            )
        if (
            self.transition.target_publication_id != self.publication.publication_id
            or self.transition.target_publication_hash != self.publication.publication_hash
            or self.transition.publication_key != self.publication.publication_key
            or self.transition.event_id != self.publication.first_activation_id
            or self.transition.transitioned_at != self.publication.first_published_at
        ):
            _fail("PRICE_LIMIT_AUDIT_TRANSITION_MISMATCH", "publish transition differs from record")
        _require_utc(self.observed_server_at, "observed_server_at")
        if self.observed_server_at < self.transition.transitioned_at:
            _fail("PRICE_LIMIT_AUDIT_CLOCK_INVALID", "server observation precedes transition")

    def to_payload(self) -> dict[str, JSONValue]:
        """Return the fixed session-authorized published detail schema."""

        self.__post_init__()
        return {
            "authentication_mode": PRICE_LIMIT_SESSION_AUTHENTICATION,
            "permission_codename": PRICE_LIMIT_PUBLISH_PERMISSION,
            "publication": self.publication.to_payload(),
            "transition": self.transition.to_payload(),
            "observed_server_at": _utc_text(self.observed_server_at),
        }

    @classmethod
    def from_payload(cls, payload: object) -> PriceLimitPublicationPublishedDetail:
        """Parse only the exact published schema and fixed permission labels."""

        value = _mapping(payload, "price_limit_publication_published.detail", _DETAIL_KEYS)
        _require_fixed(value, "authentication_mode", PRICE_LIMIT_SESSION_AUTHENTICATION)
        _require_fixed(value, "permission_codename", PRICE_LIMIT_PUBLISH_PERMISSION)
        return cls(
            publication=PriceLimitPublicationRecordEvidence.from_payload(value["publication"]),
            transition=PriceLimitPublicationTransitionEvidence.from_payload(value["transition"]),
            observed_server_at=_parse_utc(value["observed_server_at"], "observed_server_at"),
        )


@dataclass(frozen=True, slots=True)
class PriceLimitPublicationRollbackDetail:
    """Closed v1 detail for restoring a previously published price-limit snapshot."""

    publication: PriceLimitPublicationRecordEvidence
    transition: PriceLimitPublicationTransitionEvidence
    observed_server_at: datetime

    def __post_init__(self) -> None:
        """Bind rollback target seal, current predecessor, and operator fact."""

        if type(self.publication) is not PriceLimitPublicationRecordEvidence:
            _fail("PRICE_LIMIT_AUDIT_PUBLICATION_INVALID", "publication evidence must be typed")
        PriceLimitPublicationRecordEvidence.__post_init__(self.publication)
        if type(self.transition) is not PriceLimitPublicationTransitionEvidence:
            _fail("PRICE_LIMIT_AUDIT_TRANSITION_INVALID", "transition evidence must be typed")
        PriceLimitPublicationTransitionEvidence.__post_init__(self.transition)
        if self.transition.kind != "rollback":
            _fail(
                "PRICE_LIMIT_AUDIT_TRANSITION_INVALID", "rollback detail needs rollback transition"
            )
        if (
            self.transition.target_publication_id != self.publication.publication_id
            or self.transition.target_publication_hash != self.publication.publication_hash
            or self.transition.publication_key != self.publication.publication_key
        ):
            _fail(
                "PRICE_LIMIT_AUDIT_TRANSITION_MISMATCH",
                "rollback target differs from sealed record",
            )
        _require_utc(self.observed_server_at, "observed_server_at")
        if self.observed_server_at < self.transition.transitioned_at:
            _fail("PRICE_LIMIT_AUDIT_CLOCK_INVALID", "server observation precedes rollback")

    def to_payload(self) -> dict[str, JSONValue]:
        """Return the separate fixed rollback event schema."""

        self.__post_init__()
        return {
            "authentication_mode": PRICE_LIMIT_SESSION_AUTHENTICATION,
            "permission_codename": PRICE_LIMIT_PUBLISH_PERMISSION,
            "publication": self.publication.to_payload(),
            "transition": self.transition.to_payload(),
            "observed_server_at": _utc_text(self.observed_server_at),
        }

    @classmethod
    def from_payload(cls, payload: object) -> PriceLimitPublicationRollbackDetail:
        """Parse only the exact rollback schema and fixed permission labels."""

        value = _mapping(payload, "price_limit_publication_rollback.detail", _DETAIL_KEYS)
        _require_fixed(value, "authentication_mode", PRICE_LIMIT_SESSION_AUTHENTICATION)
        _require_fixed(value, "permission_codename", PRICE_LIMIT_PUBLISH_PERMISSION)
        return cls(
            publication=PriceLimitPublicationRecordEvidence.from_payload(value["publication"]),
            transition=PriceLimitPublicationTransitionEvidence.from_payload(value["transition"]),
            observed_server_at=_parse_utc(value["observed_server_at"], "observed_server_at"),
        )


PriceLimitPublicationDetail = (
    PriceLimitPublicationPublishedDetail | PriceLimitPublicationRollbackDetail
)


def validate_price_limit_publication_event(event: SystemAuditEvent) -> None:
    """Validate an exact registered unscoped publication or rollback event."""

    if type(event) is not SystemAuditEvent:
        _fail("PRICE_LIMIT_AUDIT_EVENT_INVALID", "event must be an exact SystemAuditEvent")
    try:
        event.validate_hashes()
    except (AttributeError, TypeError, ValueError) as error:
        raise PriceLimitPublicationAuditContractError(
            "PRICE_LIMIT_AUDIT_EVENT_HASH_INVALID", "event hashes are invalid"
        ) from error
    if event.event_type == PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT:
        if event.detail_schema != PRICE_LIMIT_PUBLICATION_PUBLISHED_SCHEMA:
            _fail("PRICE_LIMIT_AUDIT_EVENT_INVALID", "published event schema differs")
        detail: PriceLimitPublicationDetail = PriceLimitPublicationPublishedDetail.from_payload(
            event.detail
        )
        expected_outcome = AuditOutcome.PUBLISHED
        expected_reason = PRICE_LIMIT_PUBLISHED_REASON
        identity = price_limit_publication_event_identity(
            publication_id=detail.publication.publication_id,
            publication_hash=detail.publication.publication_hash,
        )
    elif event.event_type == PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT:
        if event.detail_schema != PRICE_LIMIT_PUBLICATION_ROLLED_BACK_SCHEMA:
            _fail("PRICE_LIMIT_AUDIT_EVENT_INVALID", "rollback event schema differs")
        detail = PriceLimitPublicationRollbackDetail.from_payload(event.detail)
        expected_outcome = AuditOutcome.ROLLED_BACK
        expected_reason = PRICE_LIMIT_ROLLBACK_REASON
        rollback = detail.transition.rollback
        if rollback is None:
            _fail("PRICE_LIMIT_AUDIT_ROLLBACK_INVALID", "rollback detail has no rollback fact")
        identity = price_limit_publication_event_identity(
            rollback_id=_text(rollback["rollback_id"], "rollback_id")
        )
    else:
        _fail(
            "PRICE_LIMIT_AUDIT_EVENT_UNREGISTERED", "event is outside the PriceLimit closed family"
        )
    publication = detail.publication
    transition = detail.transition
    actor_match = (
        _ACTOR_RE.fullmatch(event.actor.actor_id)
        if event.actor.actor_type == "django_user"
        else None
    )
    if (
        event.event_version != _EVENT_VERSION
        or event.schema_version != _SYSTEM_SCHEMA_VERSION
        or event.category is not AuditCategory.DATA_RELIABILITY
        or event.owner != PRICE_LIMIT_PUBLICATION_OWNER
        or event.write_policy is not AuditWritePolicy.TRANSACTIONAL_OUTBOX
        or event.outcome is not expected_outcome
        or event.severity is not AuditSeverity.INFO
        or event.reason_codes != (expected_reason,)
        or event.actor.actor_type != "django_user"
        or actor_match is None
        or event.scope is not None
        or event.source_app != PRICE_LIMIT_PUBLICATION_OWNER
        or event.source_component != PRICE_LIMIT_PUBLICATION_COMPONENT
        or event.source_surface != "application"
        or event.dataset_key != PRICE_LIMIT_PUBLICATION_DATASET
        or event.provider_key != str(publication.provider_id)
        or event.capability != "price_limit.publication"
        or event.publication_id != publication.publication_id
        or event.resource
        != AuditResourceRef("price_limit_publication", publication.publication_id, "v1")
        or event.evidence_refs
        != (
            AuditEvidenceRef(
                owner=PRICE_LIMIT_PUBLICATION_OWNER,
                artifact_type="price_limit_publication_seal",
                artifact_id=publication.publication_id,
                artifact_version="price-limit-publication.v1",
                content_hash=publication.publication_hash,
            ),
        )
        or event.stream_id
        != price_limit_publication_stream_id(transition.dataset_key, transition.publication_key)
        or event.event_id != identity[0]
        or event.idempotency_key != identity[1]
        or event.recorded_at != detail.observed_server_at
        or event.observed_at != detail.observed_server_at
        or event.occurred_at != transition.transitioned_at
        or event.recorded_at < event.occurred_at
        or event.correlations.dataset_key != PRICE_LIMIT_PUBLICATION_DATASET
        or event.correlations.provider_key != str(publication.provider_id)
        or event.correlations.capability != "price_limit.publication"
        or event.correlations.publication_id != publication.publication_id
        or event.correlations.evidence_ref
        != f"price-limit-publication:{publication.publication_id}:{publication.publication_hash}"
        or event.correlations.request_id is not None
        or event.correlations.task_id is not None
        or event.correlations.run_id is not None
        or event.correlations.ingested_run_id is not None
    ):
        _fail(
            "PRICE_LIMIT_AUDIT_EVENT_INVALID", "event envelope differs from closed detail contract"
        )


def _validate_source_evidence(seal: Mapping[str, JSONValue], publication_hash: str) -> None:
    """Cross-check the full original response, member, and snapshot identities."""

    _require_plain_digest(publication_hash, "publication_hash")
    if seal.get("encoding") != "price-limit-formal-publication.v1":
        _fail("PRICE_LIMIT_AUDIT_SEAL_INVALID", "seal encoding is not the price-limit v1 contract")
    if set(seal) != _SEAL_KEYS:
        _fail("PRICE_LIMIT_AUDIT_SEAL_INVALID", "seal has unknown or missing keys")
    if (
        seal.get("publication_key") is None
        or seal.get("coverage_scope") != "single_explicit_provider_security_date"
        or seal.get("must_not_use_for_decision") is not True
        or seal.get("must_not_execute") is not True
        or seal.get("currency") is not None
    ):
        _fail("PRICE_LIMIT_AUDIT_SEAL_INVALID", "seal eligibility and currency markers differ")
    source_clocks = _mapping(
        seal.get("source_clocks"),
        "seal.source_clocks",
        {"observed_at", "available_at", "published_at"},
    )
    if any(source_clocks.get(field) is not None for field in source_clocks):
        _fail("PRICE_LIMIT_AUDIT_SEAL_INVALID", "unknown provider clocks must remain unknown")
    contract = _mapping(seal.get("dataset_contract"), "seal.dataset_contract")
    contract_key = _mapping(contract.get("key"), "seal.dataset_contract.key")
    policy = _mapping(seal.get("policy"), "seal.policy")
    policy_dataset = _mapping(policy.get("dataset"), "seal.policy.dataset")
    if (
        contract_key.get("value") != PRICE_LIMIT_PUBLICATION_DATASET
        or policy_dataset.get("value") != PRICE_LIMIT_PUBLICATION_DATASET
    ):
        _fail("PRICE_LIMIT_AUDIT_SEAL_INVALID", "seal contract or policy is not price-limit")
    _require_plain_digest(seal.get("member_manifest_hash"), "seal.member_manifest_hash")
    snapshot = _mapping(seal.get("snapshot"), "seal.snapshot")
    raw = _mapping(snapshot.get("raw_reference"), "seal.snapshot.raw_reference")
    reference = _mapping(seal.get("snapshot_reference"), "seal.snapshot_reference")
    member_evidence = _mapping(seal.get("member_evidence"), "seal.member_evidence")
    member = _mapping(member_evidence.get("member"), "seal.member_evidence.member")
    member_reference = _mapping(
        member_evidence.get("snapshot_reference"), "seal.member_evidence.snapshot_reference"
    )
    body_hash = _require_plain_digest(
        raw.get("body_sha256"), "seal.snapshot.raw_reference.body_sha256"
    )
    raw_payload_hash = _require_prefixed_digest(
        raw.get("payload_hash"), "seal.snapshot.raw_reference.payload_hash"
    )
    raw_record_digest = _require_prefixed_digest(
        raw.get("record_digest"), "seal.snapshot.raw_reference.record_digest"
    )
    response_completed_at = raw.get("response_completed_at")
    if (
        raw.get("original_body_retained") is not True
        or raw.get("retained_content_encoding") != "exact_original_utf8_json"
        or raw.get("time_semantics") != "local_response_body_completion"
        or raw.get("dataset_key") != PRICE_LIMIT_PUBLICATION_DATASET
        or raw.get("provider_name") != snapshot.get("provider_name")
        or raw.get("request_scope_sha256") != snapshot.get("request_scope_sha256")
        or snapshot.get("dataset_key") != PRICE_LIMIT_PUBLICATION_DATASET
        or reference != member_reference
        or member_evidence.get("dataset_key") != PRICE_LIMIT_PUBLICATION_DATASET
        or member_evidence.get("publication_key") != seal.get("publication_key")
        or member.get("raw_payload_hash") != body_hash
        or member.get("raw_payload_scope") != "record_response_body"
        or member.get("fact_table") != "data_center_price_limit_snapshot_fact"
        or member.get("fact_pk") != snapshot.get("snapshot_id")
        or member.get("source_record_id") != snapshot.get("snapshot_id")
        or member.get("fact_content_hash") is None
        or reference.get("snapshot_id") != snapshot.get("snapshot_id")
        or reference.get("content_hash") != snapshot.get("content_hash")
        or reference.get("record_digest") != snapshot.get("record_digest")
        or reference.get("raw_payload_id") != raw.get("payload_id")
        or reference.get("raw_payload_hash") != raw_payload_hash
        or reference.get("raw_record_digest") != raw_record_digest
        or member.get("fetched_at") != response_completed_at
        or snapshot.get("response_completed_at") != response_completed_at
        or seal.get("response_completed_at") != response_completed_at
    ):
        _fail("PRICE_LIMIT_AUDIT_RAW_BINDING_INVALID", "full response and exact fact member differ")
    _require_plain_digest(member.get("fact_content_hash"), "seal.member.fact_content_hash")
    if seal.get("publication_hash") not in {None, publication_hash}:
        _fail("PRICE_LIMIT_AUDIT_SEAL_INVALID", "seal publication hash differs")


def _validate_seal_payload(value: object) -> Mapping[str, JSONValue]:
    """Copy a JSON seal and require the exact price-limit seal envelope."""

    seal = _mapping(value, "publication.seal", _SEAL_KEYS)
    return _json_copy(seal)


def _validate_rollback_payload(
    value: Mapping[str, JSONValue] | None,
    transition: PriceLimitPublicationTransitionEvidence,
) -> None:
    """Bind operator rollback evidence to the exact before/after transition."""

    rollback = _mapping(value, "transition.rollback", _ROLLBACK_KEYS)
    if (
        _text(rollback["rollback_id"], "transition.rollback.rollback_id") != transition.event_id
        or _text(rollback["target_publication_id"], "transition.rollback.target_publication_id")
        != transition.target_publication_id
        or _text(rollback["previous_publication_id"], "transition.rollback.previous_publication_id")
        != transition.previous_publication_id
        or _parse_utc(rollback["observed_at"], "transition.rollback.observed_at")
        != transition.transitioned_at
    ):
        _fail(
            "PRICE_LIMIT_AUDIT_ROLLBACK_MISMATCH", "rollback fact differs from pointer transition"
        )
    reason = _text(rollback["reason"], "transition.rollback.reason")
    _require_nonblank_text(reason, "rollback.reason")
    _require_token(_text(rollback["operator"], "transition.rollback.operator"), "rollback.operator")


def _mapping(
    value: object,
    field_name: str,
    expected_keys: set[str] | frozenset[str] | None = None,
) -> Mapping[str, JSONValue]:
    """Require a JSON object and optionally its exact field set."""

    if not isinstance(value, Mapping):
        _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{field_name} must be an object")
    normalized: dict[str, JSONValue] = {}
    for key, child in value.items():
        if type(key) is not str:
            _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{field_name} has a non-text key")
        normalized[key] = _json_value(child, f"{field_name}.{key}")
    if expected_keys is not None and set(normalized) != expected_keys:
        _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{field_name} has unknown or missing keys")
    return normalized


def _json_copy(value: object) -> dict[str, JSONValue]:
    """Deep-copy one object into SystemAudit's JSON vocabulary."""

    mapping = _mapping(value, "payload")
    copied: dict[str, JSONValue] = {}
    for key, child in mapping.items():
        copied[key] = _json_value(child, f"payload.{key}")
    return copied


def _json_value(value: object, path: str) -> JSONValue:
    """Reject non-JSON numbers or typed objects before event creation."""

    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{path} is not finite")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JSONValue] = {}
        for key, child in value.items():
            if type(key) is not str or not key:
                _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{path} has a non-text key")
            result[key] = _json_value(child, f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child, f"{path}[{index}]") for index, child in enumerate(value)]
    _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{path} is not JSON")


def _text(value: object, field_name: str) -> str:
    """Require an exact text value."""

    if type(value) is not str:
        _fail("PRICE_LIMIT_AUDIT_PAYLOAD_INVALID", f"{field_name} must be a string")
    return value


def _positive_int(value: object, field_name: str) -> int:
    """Require a positive integer without accepting booleans."""

    if type(value) is not int or value <= 0:
        _fail("PRICE_LIMIT_AUDIT_SCOPE_INVALID", f"{field_name} must be a positive integer")
    return value


def _require_token(value: object, field_name: str, *, maximum: int = 300) -> str:
    """Require canonical bounded token text."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or _TOKEN_RE.fullmatch(value) is None
    ):
        _fail("PRICE_LIMIT_AUDIT_TOKEN_INVALID", f"{field_name} is not canonical")
    return value


def _require_nonblank_text(value: object, field_name: str) -> str:
    """Preserve rollback prose under the source contract's nonblank rule."""

    if type(value) is not str or not value.strip():
        _fail("PRICE_LIMIT_AUDIT_TEXT_INVALID", f"{field_name} must be nonblank text")
    return value


def _require_uuid(value: object, field_name: str) -> str:
    """Require a canonical lowercase UUID."""

    if type(value) is not str:
        _fail("PRICE_LIMIT_AUDIT_UUID_INVALID", f"{field_name} must be a UUID")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise PriceLimitPublicationAuditContractError(
            "PRICE_LIMIT_AUDIT_UUID_INVALID", f"{field_name} must be a UUID"
        ) from error
    if str(parsed) != value:
        _fail("PRICE_LIMIT_AUDIT_UUID_INVALID", f"{field_name} must be canonical")
    return value


def _require_plain_digest(value: object, field_name: str) -> str:
    """Require a bare SHA-256 digest."""

    if type(value) is not str or _PLAIN_SHA256_RE.fullmatch(value) is None:
        _fail("PRICE_LIMIT_AUDIT_HASH_INVALID", f"{field_name} must be bare SHA-256")
    return value


def _require_prefixed_digest(value: object, field_name: str) -> str:
    """Require a prefixed raw/snapshot digest without normalizing it."""

    if type(value) is not str or _PREFIXED_SHA256_RE.fullmatch(value) is None:
        _fail("PRICE_LIMIT_AUDIT_HASH_INVALID", f"{field_name} must be sha256-prefixed")
    return value


def _require_date(value: object, field_name: str) -> date:
    """Require a date, not a datetime subclass."""

    if type(value) is not date:
        _fail("PRICE_LIMIT_AUDIT_DATE_INVALID", f"{field_name} must be a date")
    return value


def _parse_date(value: object, field_name: str) -> date:
    """Parse only canonical ISO date text."""

    text = _text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise PriceLimitPublicationAuditContractError(
            "PRICE_LIMIT_AUDIT_DATE_INVALID", f"{field_name} is not an ISO date"
        ) from error
    if parsed.isoformat() != text:
        _fail("PRICE_LIMIT_AUDIT_DATE_INVALID", f"{field_name} is not canonical")
    return parsed


def _require_utc(value: object, field_name: str) -> datetime:
    """Require an aware UTC timestamp without silently converting offsets."""

    if type(value) is not datetime or value.tzinfo is None:
        _fail("PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} must be UTC-aware")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        _fail("PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} must have zero UTC offset")
    return value


def _parse_utc(value: object, field_name: str) -> datetime:
    """Parse canonical UTC text emitted by this contract."""

    text = _text(value, field_name)
    if not text.endswith("Z"):
        _fail("PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} must use canonical UTC text")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise PriceLimitPublicationAuditContractError(
            "PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} is invalid"
        ) from error
    if _utc_text(parsed) != text:
        _fail("PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} is not canonical")
    return parsed


def _parse_seal_utc(value: object, field_name: str) -> datetime:
    """Parse the source Domain's exact UTC ``datetime.isoformat`` form."""

    text = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise PriceLimitPublicationAuditContractError(
            "PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} is invalid"
        ) from error
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0 or parsed.isoformat() != text:
        _fail("PRICE_LIMIT_AUDIT_TIME_INVALID", f"{field_name} is not exact UTC")
    return parsed


def _utc_text(value: datetime) -> str:
    """Serialize an exact UTC timestamp at microsecond precision."""

    _require_utc(value, "datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_fixed(value: Mapping[str, JSONValue], key: str, expected: str) -> None:
    """Require one exact closed-vocabulary label."""

    if value.get(key) != expected:
        _fail("PRICE_LIMIT_AUDIT_LABEL_INVALID", f"{key} is not the fixed PriceLimit label")


def _fail(code: str, message: str) -> NoReturn:
    """Raise the stable PriceLimit Audit contract failure."""

    raise PriceLimitPublicationAuditContractError(code, message)


__all__ = [
    "PRICE_LIMIT_PUBLICATION_DATASET",
    "PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT",
    "PRICE_LIMIT_PUBLICATION_PUBLISHED_SCHEMA",
    "PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT",
    "PRICE_LIMIT_PUBLICATION_ROLLED_BACK_SCHEMA",
    "PRICE_LIMIT_PUBLISH_PERMISSION",
    "PriceLimitPublicationAuditContractError",
    "PriceLimitPublicationDetail",
    "PriceLimitPublicationPublishedDetail",
    "PriceLimitPublicationRecordEvidence",
    "PriceLimitPublicationRollbackDetail",
    "PriceLimitPublicationTransitionEvidence",
    "price_limit_publication_event_identity",
    "price_limit_publication_stream_id",
    "validate_price_limit_publication_event",
]
