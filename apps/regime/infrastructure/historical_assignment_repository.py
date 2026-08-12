"""Django persistence for canonical historical Regime assignments."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.regime.application.historical_assignment import (
    HistoricalRegimeAssignmentConflict,
)
from apps.regime.domain.historical_assignment import (
    HistoricalRegimeAssignmentReceipt,
    PersistedHistoricalRegimeAssignmentDefinition,
)
from apps.regime.infrastructure.historical_assignment_codec import (
    decode_definition,
    decode_receipt,
    encode_definition,
    encode_receipt,
)
from apps.regime.infrastructure.historical_assignment_models import (
    HistoricalRegimeAssignmentDefinitionModel,
    HistoricalRegimeAssignmentReceiptModel,
    historical_assignment_insert_claim,
    historical_assignment_write_uow,
)


class HistoricalRegimeAssignmentPersistenceCorruption(RuntimeError):
    """Persisted historical assignment evidence is forked or tampered."""


class DjangoHistoricalRegimeAssignmentClock:
    """Trusted Django server clock sharing one database identity."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the trusted timezone-aware server time."""

        return timezone.now()


class DjangoHistoricalRegimeAssignmentRepository:
    """Private append store and public exact PIT read repository."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open the single shared transaction for owner reads and writes."""

        return transaction.atomic(using=self._using)

    def get_exact_definition(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedHistoricalRegimeAssignmentDefinition | None:
        """Return one exact active definition receipt at the PIT cutoff."""

        _aware(as_of, "definition as_of")
        _digest(expected_content_hash, "definition expected_content_hash")
        rows = list(
            HistoricalRegimeAssignmentDefinitionModel._base_manager.using(self._using)
            .filter(
                definition_id=definition_id,
                definition_version=definition_version,
                definition_content_hash=expected_content_hash.lower(),
                ledger_recorded_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("ledger_recorded_at", "record_hash")[:2]
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment definition has multiple PIT winners"
            )
        value = decode_definition(rows[0].canonical_payload)
        self._verify_definition_row(rows[0], value)
        if value.definition.content_hash != expected_content_hash.lower():
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment definition seal differs"
            )
        return value

    def append_definition(
        self,
        value: PersistedHistoricalRegimeAssignmentDefinition,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        """Append or exactly replay one immutable definition winner."""

        value = value.validated_copy()
        payload = encode_definition(value)
        definition = value.definition
        fields: dict[str, object] = {
            "definition_id": definition.definition_id,
            "definition_version": definition.definition_version,
            "definition_content_hash": definition.content_hash,
            "artifact_id": definition.artifact_id,
            "artifact_hash": definition.artifact_hash,
            "pit_manifest_id": definition.pit_manifest_id,
            "pit_manifest_hash": definition.pit_manifest_hash,
            "policy_id": definition.policy.policy_id,
            "policy_version": definition.policy.policy_version,
            "policy_content_hash": definition.policy.content_hash,
            "source_contract_id": definition.policy.source_contract_id,
            "source_contract_version": definition.policy.source_contract_version,
            "source_contract_hash": definition.policy.source_contract_hash,
            "registered_at": definition.registered_at,
            "valid_until": definition.valid_until,
            "ledger_recorded_at": value.ledger_recorded_at,
            "canonical_payload": payload,
            "record_hash": value.content_hash,
            "owner": "regime",
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
        try:
            with transaction.atomic(using=self._using):
                token: object
                with historical_assignment_write_uow() as token:
                    row = HistoricalRegimeAssignmentDefinitionModel(**fields)
                    expected = tuple(sorted(fields.items()))
                    with historical_assignment_insert_claim(
                        token=token,
                        model=HistoricalRegimeAssignmentDefinitionModel,
                        expected_values=expected,
                    ):
                        row.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._definition_identity_winner(
                definition.definition_id,
                definition.definition_version,
            )
            if winner != value:
                raise HistoricalRegimeAssignmentConflict(
                    "historical assignment definition identity is already forked"
                ) from None
            return winner
        return self._definition_identity_winner(
            definition.definition_id,
            definition.definition_version,
        )

    def get_exact_receipt(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> HistoricalRegimeAssignmentReceipt | None:
        """Return the server-selected latest receipt known at the PIT cutoff."""

        _aware(as_of, "receipt as_of")
        _digest(artifact_id, "receipt artifact_id")
        _digest(expected_artifact_hash, "receipt expected_artifact_hash")
        rows = list(
            HistoricalRegimeAssignmentReceiptModel._base_manager.using(self._using)
            .select_related("definition")
            .filter(
                artifact_id=artifact_id.lower(),
                artifact_hash=expected_artifact_hash.lower(),
                pit_as_of__lte=as_of,
                recorded_at__lte=as_of,
                definition__ledger_recorded_at__lte=as_of,
                definition__valid_until__gt=as_of,
            )
            .order_by("-pit_as_of", "-recorded_at", "receipt_content_hash")
        )
        if not rows:
            return None
        winner = rows[0]
        rank = (winner.pit_as_of, winner.recorded_at)
        if sum((item.pit_as_of, item.recorded_at) == rank for item in rows) != 1:
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment receipt has a same-rank fork"
            )
        value = decode_receipt(winner.canonical_payload)
        self._verify_receipt_row(winner, value)
        return value

    def append_receipt(
        self,
        value: HistoricalRegimeAssignmentReceipt,
    ) -> HistoricalRegimeAssignmentReceipt:
        """Append or exactly replay one exhaustive assignment receipt."""

        value = value.validated_copy()
        definition_row = (
            HistoricalRegimeAssignmentDefinitionModel._base_manager.using(self._using)
            .filter(
                definition_id=value.definition_id,
                definition_version=value.definition_version,
                definition_content_hash=value.definition_content_hash,
                ledger_recorded_at__lte=value.pit_as_of,
                valid_until__gt=value.pit_as_of,
            )
            .order_by("ledger_recorded_at", "record_hash")
            .first()
        )
        if definition_row is None:
            raise HistoricalRegimeAssignmentConflict(
                "historical assignment receipt definition is unavailable"
            )
        fields: dict[str, object] = {
            "definition_id": definition_row.pk,
            "receipt_id": value.receipt_id,
            "receipt_version": value.receipt_version,
            "receipt_content_hash": value.content_hash,
            "artifact_id": value.artifact_id,
            "artifact_hash": value.artifact_hash,
            "source_result_hash": value.source_result_hash,
            "pit_manifest_id": value.pit_manifest_id,
            "pit_manifest_hash": value.pit_manifest_hash,
            "pit_as_of": value.pit_as_of,
            "recorded_at": value.recorded_at,
            "assignment_count": len(value.assignments),
            "canonical_payload": encode_receipt(value),
            "owner": "regime",
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
        try:
            with transaction.atomic(using=self._using):
                token: object
                with historical_assignment_write_uow() as token:
                    row = HistoricalRegimeAssignmentReceiptModel(**fields)
                    expected = tuple(sorted(fields.items()))
                    with historical_assignment_insert_claim(
                        token=token,
                        model=HistoricalRegimeAssignmentReceiptModel,
                        expected_values=expected,
                    ):
                        row.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._receipt_identity_winner(definition_row.pk, value.pit_as_of)
            if winner != value:
                raise HistoricalRegimeAssignmentConflict(
                    "historical assignment receipt identity is already forked"
                ) from None
            return winner
        return self._receipt_identity_winner(definition_row.pk, value.pit_as_of)

    def _definition_identity_winner(
        self,
        definition_id: str,
        definition_version: str,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        rows = list(
            HistoricalRegimeAssignmentDefinitionModel._base_manager.using(self._using)
            .filter(
                definition_id=definition_id,
                definition_version=definition_version,
            )
            .order_by("record_hash")[:2]
        )
        if len(rows) != 1:
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment definition winner is absent or forked"
            )
        value = decode_definition(rows[0].canonical_payload)
        self._verify_definition_row(rows[0], value)
        return value

    def _receipt_identity_winner(
        self,
        definition_pk: int,
        pit_as_of: datetime,
    ) -> HistoricalRegimeAssignmentReceipt:
        rows = list(
            HistoricalRegimeAssignmentReceiptModel._base_manager.using(self._using)
            .filter(definition_id=definition_pk, pit_as_of=pit_as_of)
            .order_by("receipt_content_hash")[:2]
        )
        if len(rows) != 1:
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment receipt winner is absent or forked"
            )
        value = decode_receipt(rows[0].canonical_payload)
        self._verify_receipt_row(rows[0], value)
        return value

    @staticmethod
    def _verify_definition_row(
        row: HistoricalRegimeAssignmentDefinitionModel,
        value: PersistedHistoricalRegimeAssignmentDefinition,
    ) -> None:
        definition = value.definition
        if (
            row.definition_id != definition.definition_id
            or row.definition_version != definition.definition_version
            or row.definition_content_hash != definition.content_hash
            or row.artifact_id != definition.artifact_id
            or row.artifact_hash != definition.artifact_hash
            or row.pit_manifest_id != definition.pit_manifest_id
            or row.pit_manifest_hash != definition.pit_manifest_hash
            or row.policy_id != definition.policy.policy_id
            or row.policy_version != definition.policy.policy_version
            or row.policy_content_hash != definition.policy.content_hash
            or row.source_contract_id != definition.policy.source_contract_id
            or row.source_contract_version != definition.policy.source_contract_version
            or row.source_contract_hash != definition.policy.source_contract_hash
            or row.registered_at != definition.registered_at
            or row.valid_until != definition.valid_until
            or row.ledger_recorded_at != value.ledger_recorded_at
            or row.record_hash != value.content_hash
            or row.owner != "regime"
            or not row.research_only
            or not row.must_not_publish_current
            or not row.must_not_use_for_decision
            or not row.must_not_execute
        ):
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment definition row/header differs"
            )

    @staticmethod
    def _verify_receipt_row(
        row: HistoricalRegimeAssignmentReceiptModel,
        value: HistoricalRegimeAssignmentReceipt,
    ) -> None:
        if (
            row.definition.definition_id != value.definition_id
            or row.definition.definition_version != value.definition_version
            or row.definition.definition_content_hash != value.definition_content_hash
            or row.receipt_id != value.receipt_id
            or row.receipt_version != value.receipt_version
            or row.receipt_content_hash != value.content_hash
            or row.artifact_id != value.artifact_id
            or row.artifact_hash != value.artifact_hash
            or row.source_result_hash != value.source_result_hash
            or row.pit_manifest_id != value.pit_manifest_id
            or row.pit_manifest_hash != value.pit_manifest_hash
            or row.pit_as_of != value.pit_as_of
            or row.recorded_at != value.recorded_at
            or row.assignment_count != len(value.assignments)
            or row.owner != "regime"
            or not row.research_only
            or not row.must_not_publish_current
            or not row.must_not_use_for_decision
            or not row.must_not_execute
        ):
            raise HistoricalRegimeAssignmentPersistenceCorruption(
                "historical assignment receipt row/header differs"
            )


class DjangoHistoricalRegimeAssignmentReadRepository:
    """Narrow public exact-read repository with no append capability."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database read identity."""

        return f"django:{self._using}"

    def get_exact_definition(
        self,
        *,
        definition_id: str,
        definition_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedHistoricalRegimeAssignmentDefinition | None:
        """Delegate one exact PIT definition read."""

        return DjangoHistoricalRegimeAssignmentRepository(using=self._using).get_exact_definition(
            definition_id=definition_id,
            definition_version=definition_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def get_exact_receipt(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> HistoricalRegimeAssignmentReceipt | None:
        """Delegate one exact PIT receipt read."""

        return DjangoHistoricalRegimeAssignmentRepository(using=self._using).get_exact_receipt(
            artifact_id=artifact_id,
            expected_artifact_hash=expected_artifact_hash,
            as_of=as_of,
        )


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value.lower()


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


__all__ = [
    "DjangoHistoricalRegimeAssignmentClock",
    "DjangoHistoricalRegimeAssignmentRepository",
    "HistoricalRegimeAssignmentPersistenceCorruption",
]
