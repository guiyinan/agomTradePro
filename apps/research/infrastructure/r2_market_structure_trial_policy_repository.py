"""Exact PIT reads and private append persistence for R2 trial policies."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r2_market_structure_trial_policy_registry import (
    ExactR2TrialPolicyDefinitionProvider,
    R2TrialPolicyRegistryClock,
    R2TrialPolicyRegistryConflict,
    R2TrialPolicyRegistryCorruption,
    R2TrialPolicyRegistryUnavailable,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2MarketStructureTrialPolicy,
)
from apps.research.domain.r2_market_structure_trial_policy_registry import (
    PersistedR2MarketStructureTrialPolicy,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_codec import (
    R2TrialPolicyRegistryCodecError,
    decode_r2_trial_policy_record,
    encode_r2_trial_policy_record,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_models import (
    R2MarketStructureTrialPolicyLedgerModel,
    _activate_r2_trial_policy_uow,
    _claim_r2_trial_policy_insert,
    _require_active_r2_trial_policy_uow,
)


class DjangoR2TrialPolicyRegistryClock:
    """Django timezone-backed trusted clock bound to one database alias."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return one server-controlled timezone-aware timestamp."""

        return timezone.now()


class DjangoR2TrialPolicyDefinitionProvider:
    """UoW-gated adapter around the canonical Research definition owner."""

    __slots__ = ("_source",)

    def __init__(self, source: ExactR2TrialPolicyDefinitionProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Return the wrapped owner transaction identity."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        """Reread the owner only while the append transaction is active."""

        _require_active_r2_trial_policy_uow()
        return self._source.get_exact(
            policy_id=policy_id,
            policy_version=policy_version,
            as_of=as_of,
        )


class DjangoR2TrialPolicyRegistryRepository:
    """Read-only exact/PIT repository with codec and redundant-header checks."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R2TrialPolicyRegistryClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR2TrialPolicyRegistryClock(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return f"django:{self._using}"

    def get_record_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR2MarketStructureTrialPolicy | None:
        """Restore one exact identity/hash that was knowable and active at PIT."""

        _require_token(policy_id, "policy_id")
        _require_token(policy_version, "policy_version")
        _require_hash(expected_content_hash, "expected_content_hash")
        self._require_pit_cutoff(as_of)
        rows = list(
            R2MarketStructureTrialPolicyLedgerModel._default_manager.using(self._using).filter(
                Q(policy_id=policy_id, policy_version=policy_version)
                | Q(policy_content_hash=expected_content_hash.lower())
            )
        )
        records = tuple(_restore_model(row) for row in rows)
        matches = tuple(
            record
            for record in records
            if record.policy.policy_id == policy_id
            and record.policy.policy_version == policy_version
            and record.policy.content_hash.lower() == expected_content_hash.lower()
        )
        if len(matches) > 1:
            raise R2TrialPolicyRegistryCorruption(
                "multiple rows match one exact R2 trial-policy selector"
            )
        if not matches:
            return None
        record = matches[0]
        if record.ledger_recorded_at > as_of or not record.policy.is_active_at(as_of):
            return None
        return record

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "as_of")
        try:
            now = self._clock.now()
            _require_aware(now, "clock.now")
        except R2TrialPolicyRegistryUnavailable:
            raise
        except Exception as error:
            raise R2TrialPolicyRegistryUnavailable(
                "R2 trial-policy trusted clock is unavailable"
            ) from error
        if as_of > now:
            raise R2TrialPolicyRegistryUnavailable("future R2 trial-policy cutoff is forbidden")


class DjangoExactR2TrialPolicyProvider:
    """Narrow adapter implementing the existing R2 trial evaluator port."""

    __slots__ = ("_repository",)

    def __init__(self, repository: DjangoR2TrialPolicyRegistryRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the read repository transaction identity."""

        return self._repository.unit_of_work_key

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        """Return only the complete live-restored policy or explicit absence."""

        record = self._repository.get_record_exact(
            policy_id=policy_id,
            policy_version=policy_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
        return None if record is None else record.policy


class _DjangoR2TrialPolicyRegistryStore:
    """Private exact-winner append capability and shared transaction boundary."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one atomic database/UoW context."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with (
            transaction.atomic(using=self._using),
            _activate_r2_trial_policy_uow(self._token),
        ):
            yield

    def append(
        self,
        record: PersistedR2MarketStructureTrialPolicy,
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Append, return an identical winner, or reject an immutable fork."""

        validated = decode_r2_trial_policy_record(encode_r2_trial_policy_record(record))
        rows = list(
            R2MarketStructureTrialPolicyLedgerModel._default_manager.using(self._using).filter(
                Q(
                    policy_id=validated.policy.policy_id,
                    policy_version=validated.policy.policy_version,
                )
                | Q(policy_content_hash=validated.policy.content_hash)
                | Q(record_hash=validated.record_hash)
            )
        )
        if len(rows) > 1:
            raise R2TrialPolicyRegistryCorruption(
                "multiple rows collide with one R2 trial-policy append"
            )
        if rows:
            winner = _restore_model(rows[0])
            if winner == validated:
                return winner
            raise R2TrialPolicyRegistryConflict(
                "R2 trial-policy identity already has another winner"
            )
        values = _record_values(validated)
        try:
            with _claim_r2_trial_policy_insert(
                token=self._token,
                expected_values=values,
            ):
                R2MarketStructureTrialPolicyLedgerModel._default_manager.using(self._using).create(
                    **values
                )
        except IntegrityError as error:
            raise R2TrialPolicyRegistryConflict(
                "R2 trial-policy append lost an immutable race"
            ) from error
        return validated


def _record_values(
    record: PersistedR2MarketStructureTrialPolicy,
) -> dict[str, object]:
    policy = record.policy
    taxonomy = policy.taxonomy_publication_ref
    calendar = policy.calendar_publication_ref
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "taxonomy_publication_id": taxonomy.publication_id,
        "taxonomy_publication_version": taxonomy.publication_version,
        "taxonomy_publication_hash": taxonomy.publication_hash.lower(),
        "taxonomy_artifact_hash": taxonomy.artifact_hash.lower(),
        "calendar_publication_id": calendar.publication_id,
        "calendar_publication_version": calendar.publication_version,
        "calendar_publication_hash": calendar.publication_hash.lower(),
        "calendar_artifact_hash": calendar.artifact_hash.lower(),
        "policy_registered_at": policy.registered_at,
        "ledger_recorded_at": record.ledger_recorded_at,
        "selection_as_of": policy.selection_as_of,
        "active_from": policy.active_from,
        "active_until": policy.active_until,
        "canonical_payload": encode_r2_trial_policy_record(record),
        "policy_content_hash": policy.content_hash.lower(),
        "record_hash": record.record_hash,
        "research_only": record.research_only,
        "must_not_publish_current": record.must_not_publish_current,
        "must_not_use_for_decision": record.must_not_use_for_decision,
        "must_not_execute": record.must_not_execute,
    }


_HEADER_NAMES = (
    "policy_id",
    "policy_version",
    "taxonomy_publication_id",
    "taxonomy_publication_version",
    "taxonomy_publication_hash",
    "taxonomy_artifact_hash",
    "calendar_publication_id",
    "calendar_publication_version",
    "calendar_publication_hash",
    "calendar_artifact_hash",
    "policy_registered_at",
    "ledger_recorded_at",
    "selection_as_of",
    "active_from",
    "active_until",
    "policy_content_hash",
    "record_hash",
    "research_only",
    "must_not_publish_current",
    "must_not_use_for_decision",
    "must_not_execute",
)


def _restore_model(
    model: R2MarketStructureTrialPolicyLedgerModel,
) -> PersistedR2MarketStructureTrialPolicy:
    try:
        record = decode_r2_trial_policy_record(model.canonical_payload)
    except R2TrialPolicyRegistryCodecError as error:
        raise R2TrialPolicyRegistryCorruption(
            "R2 trial-policy canonical payload is corrupt"
        ) from error
    values = _record_values(record)
    if any(getattr(model, name) != values[name] for name in _HEADER_NAMES):
        raise R2TrialPolicyRegistryCorruption(
            "R2 trial-policy header differs from canonical payload"
        )
    return record


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise R2TrialPolicyRegistryUnavailable(f"{field_name} is invalid")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise R2TrialPolicyRegistryUnavailable(f"{field_name} is invalid")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R2TrialPolicyRegistryUnavailable(f"{field_name} must be timezone-aware")


__all__ = [
    "DjangoExactR2TrialPolicyProvider",
    "DjangoR2TrialPolicyDefinitionProvider",
    "DjangoR2TrialPolicyRegistryClock",
    "DjangoR2TrialPolicyRegistryRepository",
]
