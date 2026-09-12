"""Django persistence for canonical Account ownership re-observation v1.

The re-observation ledger is deliberately a small append-only projection.  A
record is accepted only after the immutable Binding-v2 and Physical-v2
evidence it names has been restored through their public repositories.  The
three ledgers are read and locked on one database alias and one transaction;
the re-observation record itself never creates a new authority or a logical
predecessor relationship.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1Conflict,
    CanonicalAccountOwnershipReobservationV1Corruption,
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.physical_account_row_observation_v2 import (
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Conflict,
    PhysicalAccountRowObservationV2Corruption,
    PhysicalAccountRowObservationV2Unavailable,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
    _activate_canonical_account_ownership_reobservation_v1_uow,
    _claim_canonical_account_ownership_reobservation_v1_insert,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_record_codec import (
    CanonicalAccountOwnershipReobservationV1RecordCodecError,
    decode_canonical_account_ownership_reobservation_v1_record,
    encode_canonical_account_ownership_reobservation_v1_record,
)
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)


class DjangoCanonicalAccountOwnershipReobservationV1Unavailable(
    CanonicalAccountOwnershipReobservationV1Corruption
):
    """The requested re-observation or one of its parents is unavailable."""


class DjangoCanonicalAccountOwnershipReobservationV1Conflict(
    CanonicalAccountOwnershipReobservationV1Conflict
):
    """An immutable re-observation anchor has another first winner."""


class DjangoCanonicalAccountOwnershipReobservationV1Corruption(
    CanonicalAccountOwnershipReobservationV1Corruption
):
    """A persisted re-observation or parent evidence failed closed-world checks."""


class CanonicalAccountOwnershipReobservationV1Clock(Protocol):
    """Provide the authoritative persistence clock."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoCanonicalAccountOwnershipReobservationV1Clock:
    """Django timezone-backed production clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class CanonicalAccountCreationBindingV2EvidenceReader(Protocol):
    """Restore exact immutable Binding-v2 evidence."""

    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Return the exact Binding-v2 known at ``as_of``."""


class PhysicalAccountRowObservationV2EvidenceReader(Protocol):
    """Restore exact Physical-v2 evidence and its point-in-time head."""

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
        """Return the exact Physical-v2 record known at ``as_of``."""

    def get_current_head(
        self,
        *,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        source_id: str,
        as_of: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
        """Return the final logical Physical-v2 head at ``as_of``."""


class DjangoCanonicalAccountOwnershipReobservationV1Repository:
    """Persist and restore immutable ownership re-observation first winners."""

    __slots__ = (
        "_binding_repository",
        "_clock",
        "_physical_repository",
        "_uow",
        "_using",
    )

    def __init__(
        self,
        *,
        using: str = "default",
        clock: CanonicalAccountOwnershipReobservationV1Clock | None = None,
        binding_repository: CanonicalAccountCreationBindingV2EvidenceReader | None = None,
        physical_repository: PhysicalAccountRowObservationV2EvidenceReader | None = None,
    ) -> None:
        """Bind all persistence collaborators to the same database alias."""

        if type(using) is not str or not using.strip():
            raise ValueError("using must be a non-empty database alias")
        self._using = using
        self._clock = clock or DjangoCanonicalAccountOwnershipReobservationV1Clock()
        self._binding_repository = binding_repository or (
            DjangoCanonicalAccountCreationConsumptionRepository(using=using)
        )
        self._physical_repository = physical_repository or (
            DjangoPhysicalAccountRowObservationV2Repository(using=using)
        )
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nestable private transaction on this repository alias."""

        if self._uow is not None:
            raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
                "nested ownership re-observation UOW"
            )
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_canonical_account_ownership_reobservation_v1_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the validated authoritative persistence clock."""

        value = self._clock.now()
        if not _is_aware(value):
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation repository clock is naive"
            )
        return value

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        """Return the identity first winner recorded by the historical cutoff."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        self._cutoff(as_of)
        records = self._restored_records(lock=False)
        matches = tuple(
            record
            for record in records
            if (
                record.reobservation.observation_id == observation_id
                and record.reobservation.observation_version == observation_version
                and record.reobservation.recorded_at <= as_of
            )
        )
        return _single(matches, "ownership re-observation identity")

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        """Return one exact historical record without TTL or current filtering."""

        _require_token(observation_id, "observation_id")
        _require_token(observation_version, "observation_version")
        _require_hash(expected_content_hash, "expected_content_hash")
        self._cutoff(as_of)
        records = self._restored_records(lock=False)
        anchors = tuple(
            record
            for record in records
            if (
                (
                    record.reobservation.observation_id == observation_id
                    and record.reobservation.observation_version == observation_version
                )
                or record.reobservation.identity_hash == expected_content_hash
                or record.reobservation.content_hash == expected_content_hash
            )
        )
        matches = tuple(
            record
            for record in anchors
            if (
                record.reobservation.observation_id == observation_id
                and record.reobservation.observation_version == observation_version
                and record.reobservation.content_hash == expected_content_hash
                and record.reobservation.recorded_at <= as_of
            )
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation exact anchors disagree"
            )
        return matches[0] if matches else None

    def append(
        self,
        record: PersistedCanonicalAccountOwnershipReobservationV1,
        *,
        recorded_at: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1:
        """Append or replay one exact first winner after parent proof verification."""

        token = self._require_uow()
        checked = _record(record)
        _require_aware(recorded_at, "recorded_at")
        observation = checked.reobservation
        if observation.recorded_at != recorded_at:
            raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
                "ownership re-observation recorded_at differs"
            )
        if recorded_at > self.now():
            raise DjangoCanonicalAccountOwnershipReobservationV1Unavailable(
                "ownership re-observation recorded_at is in the future"
            )

        binding_row = self._lock_binding(observation)
        self._restore_binding(observation, binding_row)
        physical_row = self._lock_physical(observation)
        physical = self._restore_physical(observation, physical_row)
        self._prove_physical_head(observation, physical)

        existing_rows = self._lock_reobservation_anchors(observation)
        existing = self._select_anchor_winner(existing_rows, checked)
        if existing is not None:
            return existing

        values = _model_values(
            checked,
            binding_pk=_required_pk(binding_row, "Binding-v2"),
            physical_pk=_required_pk(physical_row, "Physical-v2"),
            recorded_at=recorded_at,
        )
        model = CanonicalAccountOwnershipReobservationV1Model(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_canonical_account_ownership_reobservation_v1_insert(
                    token=token,
                    model_type=CanonicalAccountOwnershipReobservationV1Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            refreshed_rows = self._lock_reobservation_anchors(observation)
            winner = self._select_anchor_winner(refreshed_rows, checked)
            if winner is not None:
                return winner
            raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
                "concurrent ownership re-observation first winner differs"
            ) from error

        restored = self._restore(model)
        if restored != checked:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation append restore mismatch"
            )
        return restored

    def _lock_binding(
        self, observation: CanonicalAccountOwnershipReobservationV1
    ) -> CanonicalAccountCreationBindingV2Model:
        """Lock all Binding-v2 rows occupying the proof's immutable anchors."""

        binding = observation.binding
        query = (
            CanonicalAccountCreationBindingV2Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(binding_id=binding.binding_id, binding_version=binding.binding_version)
                | Q(identity_hash=binding.identity_hash)
                | Q(content_hash=binding.content_hash)
            )
            .order_by("pk")
        )
        rows = list(query)
        if len(rows) != 1:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation Binding-v2 proof is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_physical(
        self, observation: CanonicalAccountOwnershipReobservationV1
    ) -> PhysicalAccountRowObservationV2Model:
        """Lock all Physical-v2 rows occupying the proof's immutable anchors."""

        physical = observation.current_physical
        query = (
            PhysicalAccountRowObservationV2Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(
                    observation_id=physical.observation_id,
                    observation_version=physical.observation_version,
                )
                | Q(identity_hash=physical.identity_hash)
                | Q(content_hash=physical.content_hash)
            )
            .order_by("pk")
        )
        rows = list(query)
        if len(rows) != 1:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation Physical-v2 proof is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_reobservation_anchors(
        self, observation: CanonicalAccountOwnershipReobservationV1
    ) -> list[CanonicalAccountOwnershipReobservationV1Model]:
        """Lock every re-observation row occupying an identity/content anchor."""

        query = (
            CanonicalAccountOwnershipReobservationV1Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(
                    observation_id=observation.observation_id,
                    observation_version=observation.observation_version,
                )
                | Q(identity_hash=observation.identity_hash)
                | Q(content_hash=observation.content_hash)
            )
            .order_by("pk")
        )
        return list(query)

    def _restore_binding(
        self,
        observation: CanonicalAccountOwnershipReobservationV1,
        row: CanonicalAccountCreationBindingV2Model,
    ) -> CanonicalAccountCreationBindingV2:
        """Restore Binding-v2 through its existing closed-world repository."""

        try:
            value = self._binding_repository.get_exact_by_hash(
                binding_id=observation.binding.binding_id,
                binding_version=observation.binding.binding_version,
                expected_content_hash=observation.binding.content_hash,
                as_of=observation.recorded_at,
            )
        except (
            CanonicalAccountCreationBindingV2Corruption,
            CanonicalAccountCreationBindingV2Unavailable,
        ) as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "Binding-v2 parent could not be restored"
            ) from error
        if (
            type(value) is not CanonicalAccountCreationBindingV2
            or value != observation.binding
            or _required_pk(row, "Binding-v2") != row.pk
            or row.identity_hash != observation.binding.identity_hash
            or row.content_hash != observation.binding.content_hash
        ):
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation Binding-v2 proof differs"
            )
        return value

    def _restore_physical(
        self,
        observation: CanonicalAccountOwnershipReobservationV1,
        row: PhysicalAccountRowObservationV2Model,
    ) -> PersistedPhysicalAccountRowObservationV2:
        """Restore Physical-v2 through its existing closed-world repository."""

        try:
            value = self._physical_repository.get_exact_by_hash(
                observation_id=observation.current_physical.observation_id,
                observation_version=observation.current_physical.observation_version,
                expected_content_hash=observation.current_physical.content_hash,
                as_of=observation.recorded_at,
            )
        except (
            PhysicalAccountRowObservationV2Corruption,
            PhysicalAccountRowObservationV2Unavailable,
            PhysicalAccountRowObservationV2Conflict,
        ) as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "Physical-v2 parent could not be restored"
            ) from error
        if (
            type(value) is not PersistedPhysicalAccountRowObservationV2
            or value.observation != observation.current_physical
            or row.identity_hash != observation.current_physical.identity_hash
            or row.content_hash != observation.current_physical.content_hash
        ):
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation Physical-v2 proof differs"
            )
        return value

    def _prove_physical_head(
        self,
        observation: CanonicalAccountOwnershipReobservationV1,
        physical: PersistedPhysicalAccountRowObservationV2,
    ) -> None:
        """Prove the exact Physical-v2 parent was the logical head at recording."""

        try:
            head = self._physical_repository.get_current_head(
                account_namespace=physical.observation.account_namespace,
                account_id=physical.observation.account_id,
                underlying_unified_account_namespace=(
                    physical.observation.underlying_unified_account_namespace
                ),
                underlying_unified_account_id=(physical.observation.underlying_unified_account_id),
                source_id=physical.observation.source_id,
                as_of=observation.recorded_at,
            )
        except (
            PhysicalAccountRowObservationV2Corruption,
            PhysicalAccountRowObservationV2Unavailable,
            PhysicalAccountRowObservationV2Conflict,
        ) as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "Physical-v2 logical head could not be proven"
            ) from error
        if type(head) is not PersistedPhysicalAccountRowObservationV2:
            raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
                "ownership re-observation Physical-v2 parent is not the logical head"
            )
        if head != physical:
            raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
                "ownership re-observation Physical-v2 parent is not the logical head"
            )

    def _restore(
        self, model: CanonicalAccountOwnershipReobservationV1Model
    ) -> PersistedCanonicalAccountOwnershipReobservationV1:
        """Restore and cross-check one complete persisted record."""

        try:
            record = decode_canonical_account_ownership_reobservation_v1_record(
                model.canonical_payload
            )
        except CanonicalAccountOwnershipReobservationV1RecordCodecError as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation canonical payload cannot be restored"
            ) from error
        try:
            binding_row = self._binding_row(model.binding_id)
            physical_row = self._physical_row(model.current_physical_id)
            binding = self._restore_binding(record.reobservation, binding_row)
            physical = self._restore_physical(record.reobservation, physical_row)
            self._prove_physical_head(record.reobservation, physical)
            expected = _model_values(
                record,
                binding_pk=_required_pk(binding_row, "Binding-v2"),
                physical_pk=_required_pk(physical_row, "Physical-v2"),
                recorded_at=model.recorded_at,
            )
        except DjangoCanonicalAccountOwnershipReobservationV1Corruption:
            raise
        except (TypeError, ValueError) as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation model headers are invalid"
            ) from error
        _match_model(model, expected)
        if (
            binding != record.reobservation.binding
            or physical.observation != record.reobservation.current_physical
        ):
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation parent evidence differs"
            )
        return record

    def _binding_row(self, primary_key: int) -> CanonicalAccountCreationBindingV2Model:
        """Fetch one Binding-v2 foreign row through this repository alias."""

        try:
            return CanonicalAccountCreationBindingV2Model._base_manager.using(self._using).get(
                pk=primary_key
            )
        except CanonicalAccountCreationBindingV2Model.DoesNotExist as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation Binding-v2 foreign row is missing"
            ) from error

    def _physical_row(self, primary_key: int) -> PhysicalAccountRowObservationV2Model:
        """Fetch one Physical-v2 foreign row through this repository alias."""

        try:
            return PhysicalAccountRowObservationV2Model._base_manager.using(self._using).get(
                pk=primary_key
            )
        except PhysicalAccountRowObservationV2Model.DoesNotExist as error:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                "ownership re-observation Physical-v2 foreign row is missing"
            ) from error

    def _restored_records(
        self, *, lock: bool
    ) -> tuple[PersistedCanonicalAccountOwnershipReobservationV1, ...]:
        """Restore the complete re-observation table before applying selectors."""

        query = CanonicalAccountOwnershipReobservationV1Model._base_manager.using(self._using).all()
        if lock:
            query = query.select_for_update()
        rows = tuple(query.order_by("recorded_at", "pk"))
        return tuple(self._restore(row) for row in rows)

    def _select_anchor_winner(
        self,
        rows: list[CanonicalAccountOwnershipReobservationV1Model],
        expected: PersistedCanonicalAccountOwnershipReobservationV1,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        """Resolve closed-world immutable anchors to one exact first winner."""

        if not rows:
            return None
        restored = tuple(self._restore(row) for row in rows)
        exact = tuple(value for value in restored if value == expected)
        if len(restored) == 1 and len(exact) == 1:
            return exact[0]
        raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
            "ownership re-observation first-winner anchor differs"
        )

    def _require_uow(self) -> object:
        if self._uow is None:
            raise DjangoCanonicalAccountOwnershipReobservationV1Conflict(
                "ownership re-observation append requires private UOW"
            )
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "as_of")
        if as_of > self.now():
            raise DjangoCanonicalAccountOwnershipReobservationV1Unavailable(
                "future ownership re-observation as_of is forbidden"
            )


def _record(value: object) -> PersistedCanonicalAccountOwnershipReobservationV1:
    """Require and revalidate one exact persisted application record."""

    if type(value) is not PersistedCanonicalAccountOwnershipReobservationV1:
        raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
            "ownership re-observation record type is invalid"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
            "ownership re-observation record is invalid"
        ) from error
    return value


def _model_values(
    record: PersistedCanonicalAccountOwnershipReobservationV1,
    *,
    binding_pk: int,
    physical_pk: int,
    recorded_at: datetime,
) -> dict[str, object]:
    """Build every model column from the full canonical record envelope."""

    checked = _record(record)
    observation = checked.reobservation
    _require_aware(recorded_at, "recorded_at")
    if observation.recorded_at != recorded_at:
        raise ValueError("recorded_at differs from observation")
    if type(binding_pk) is not int or binding_pk <= 0:
        raise ValueError("binding_pk must be positive")
    if type(physical_pk) is not int or physical_pk <= 0:
        raise ValueError("physical_pk must be positive")
    return {
        "binding_id": binding_pk,
        "current_physical_id": physical_pk,
        "owner": observation.owner,
        "artifact_type": observation.artifact_type,
        "schema": observation.schema,
        "permission": observation.permission,
        "status": observation.status,
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "binding_identity_hash": observation.binding.identity_hash,
        "binding_content_hash": observation.binding.content_hash,
        "current_physical_identity_hash": observation.current_physical.identity_hash,
        "current_physical_content_hash": observation.current_physical.content_hash,
        "recorded_at": observation.recorded_at,
        "valid_until": observation.valid_until,
        "persisted_at": recorded_at,
        "canonical_payload": encode_canonical_account_ownership_reobservation_v1_record(checked),
        "identity_hash": checked.identity_hash,
        "content_hash": checked.content_hash,
        "record_seal": checked.record_seal,
        "ledger_seal": checked.ledger_seal,
    }


def _match_model(
    model: CanonicalAccountOwnershipReobservationV1Model,
    expected: dict[str, object],
) -> None:
    """Reject any model column or foreign-key substitution."""

    for field_name, expected_value in expected.items():
        if getattr(model, field_name) != expected_value:
            raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
                f"ownership re-observation model field {field_name} differs"
            )


def _required_pk(model: object, label: str) -> int:
    """Read one concrete persisted foreign-key primary key."""

    value = getattr(model, "pk", None)
    if type(value) is not int or value <= 0:
        raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(
            f"{label} foreign evidence has no primary key"
        )
    return value


def _single(
    values: tuple[PersistedCanonicalAccountOwnershipReobservationV1, ...],
    label: str,
) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
    """Return zero or one immutable match and reject ambiguity."""

    if len(values) > 1:
        raise DjangoCanonicalAccountOwnershipReobservationV1Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _require_token(value: object, field_name: str) -> None:
    """Validate one bounded canonical selector token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    """Validate one lowercase SHA-256 selector."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    """Validate one timezone-aware datetime."""

    if type(value) is not datetime or not _is_aware(value):
        raise ValueError(f"{field_name} must be timezone-aware")


def _is_aware(value: object) -> bool:
    """Return whether an object is a timezone-aware datetime."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "CanonicalAccountCreationBindingV2EvidenceReader",
    "CanonicalAccountOwnershipReobservationV1Clock",
    "DjangoCanonicalAccountOwnershipReobservationV1Clock",
    "DjangoCanonicalAccountOwnershipReobservationV1Conflict",
    "DjangoCanonicalAccountOwnershipReobservationV1Corruption",
    "DjangoCanonicalAccountOwnershipReobservationV1Repository",
    "DjangoCanonicalAccountOwnershipReobservationV1Unavailable",
    "PhysicalAccountRowObservationV2EvidenceReader",
]
