"""Django persistence for exact-current simulated corporate-action write grants."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeGuard

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantCorruption,
    SimulatedCorporateActionWriteGrantRepository,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
    validate_simulated_corporate_action_write_capabilities,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_REVOCATION_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantCurrent,
    SimulatedCorporateActionWriteGrantRecord,
    SimulatedCorporateActionWriteGrantRevocation,
    SimulatedCorporateActionWriteGrantSelector,
    validate_simulated_corporate_action_write_grant_revocation,
    validate_simulated_corporate_action_write_grant_successor,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
    SimulatedCorporateActionWriteGrantRevocationModel,
    _activate_simulated_corporate_action_write_grant_uow,
    _claim_simulated_corporate_action_write_grant_insert,
)


class SimulatedCorporateActionWriteGrantClock(Protocol):
    """Supply the trusted persistence clock for one Account grant repository."""

    def now(self) -> datetime:
        """Return an exact timezone-aware timestamp."""


class DjangoSimulatedCorporateActionWriteGrantClock:
    """Use Django's timezone-aware server clock."""

    def now(self) -> datetime:
        """Return current server time as an aware timestamp."""

        return timezone.now()


class DjangoSimulatedCorporateActionWriteGrantRepository(
    SimulatedCorporateActionWriteGrantRepository
):
    """Append immutable grant and revocation rows and read exact current heads."""

    __slots__ = ("_clock", "_token", "_using")

    def __init__(
        self,
        using: str = "default",
        clock: SimulatedCorporateActionWriteGrantClock | None = None,
    ) -> None:
        """Bind all grant and revocation operations to one database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("simulated corporate-action write grant database alias is invalid")
        self._using = using
        self._clock = clock or DjangoSimulatedCorporateActionWriteGrantClock()
        self._token = object()

    def now(self) -> datetime:
        """Return and validate the repository's timezone-aware server clock."""

        try:
            value = self._clock.now()
        except (AttributeError, TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant clock is unavailable"
            ) from error
        if not _is_aware(value):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant clock must be timezone-aware"
            )
        return value

    def append_grant(
        self,
        grant: SimulatedCorporateActionWriteGrant,
        *,
        expected_predecessor_content_hash: str | None,
    ) -> SimulatedCorporateActionWriteGrant:
        """Append one exact grant root/successor with predecessor CAS and replay safety."""

        checked = _grant(grant)
        if expected_predecessor_content_hash is not None:
            _digest(expected_predecessor_content_hash, "expected_predecessor_content_hash")
        now = self.now()
        if checked.recorded_at != now:
            raise SimulatedCorporateActionWriteGrantConflict(
                "grant recorded_at must equal the repository server clock"
            )
        if checked.supersedes_content_hash != expected_predecessor_content_hash:
            raise SimulatedCorporateActionWriteGrantConflict(
                "grant predecessor content hash differs from the expected value"
            )
        try:
            with transaction.atomic(using=self._using):
                return self._append_grant(checked, expected_predecessor_content_hash)
        except SimulatedCorporateActionWriteGrantConflict:
            raise
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant append is unavailable"
            ) from error

    def append_revocation(
        self,
        revocation: SimulatedCorporateActionWriteGrantRevocation,
    ) -> SimulatedCorporateActionWriteGrantRevocation:
        """Append one exact immutable revocation against its durable grant version."""

        checked = _revocation(revocation)
        now = self.now()
        if checked.recorded_at != now:
            raise SimulatedCorporateActionWriteGrantConflict(
                "revocation recorded_at must equal the repository server clock"
            )
        try:
            with transaction.atomic(using=self._using):
                return self._append_revocation(checked)
        except SimulatedCorporateActionWriteGrantConflict:
            raise
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated corporate-action write grant revocation append is unavailable"
            ) from error

    def get_exact_record(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteGrantRecord | None:
        """Read an exact known record for owner withdrawal, including expired history.

        This method does not establish a current head or permission. Financial
        consumers must continue to call get_current_grant and verify issuance.
        """
        checked = _selector(selector)
        cutoff = _cutoff(as_of)
        try:
            matches = tuple(
                SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
                .filter(content_hash=checked.content_hash)
                .order_by("pk")[:2]
            )
            if len(matches) > 1:
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "exact grant selector is ambiguous"
                )
            if not matches:
                return None
            row = matches[0]
            grant = _restore_grant(row)
            if grant.selector != checked:
                raise SimulatedCorporateActionWriteGrantCorruption("exact grant selector differs")
            if grant.recorded_at > cutoff:
                return None
            rows = tuple(
                SimulatedCorporateActionWriteGrantRevocationModel._default_manager.using(
                    self._using
                )
                .filter(target_grant_id=row.pk)
                .order_by("pk")[:2]
            )
            if len(rows) > 1:
                raise SimulatedCorporateActionWriteGrantCorruption("grant has multiple revocations")
            revocation = _restore_revocation(rows[0], grant, _pk(row)) if rows else None
            return SimulatedCorporateActionWriteGrantRecord(grant=grant, revocation=revocation)
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "exact grant metadata read is unavailable"
            ) from error

    def get_scope_records(
        self, account_namespace: str, account_id: str, *, as_of: datetime
    ) -> tuple[SimulatedCorporateActionWriteGrantRecord, ...]:
        """Discover known historical records for withdrawal, preserving the current-write gate.

        Scope chains are validated before reading exact historical DTOs. Expired,
        superseded and revoked records remain metadata and never become Current.
        """
        cutoff = _cutoff(as_of)
        self.get_current_for_scope(account_namespace, account_id, as_of=cutoff)
        if account_namespace != "simulated":
            return ()
        try:
            rows = tuple(
                SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
                .filter(
                    account_namespace=account_namespace,
                    account_id=account_id,
                    recorded_at__lte=cutoff,
                )
                .order_by("recorded_at", "pk")
            )
            records: list[SimulatedCorporateActionWriteGrantRecord] = []
            for row in rows:
                grant = _restore_grant(row)
                record = self.get_exact_record(selector=grant.selector, as_of=cutoff)
                if record is None:
                    raise SimulatedCorporateActionWriteGrantCorruption(
                        "known historical grant disappeared"
                    )
                records.append(record)
            return tuple(records)
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "historical consent read is unavailable"
            ) from error

    def get_current_grant(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        as_of: datetime,
    ) -> SimulatedCorporateActionWriteGrantCurrent | None:
        """Return only the requested exact chain head; never scan backward to an older version."""

        checked = _selector(selector)
        _cutoff(as_of)
        try:
            rows = tuple(
                SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
                .filter(content_hash=checked.content_hash)
                .order_by("pk")[:2]
            )
            if len(rows) > 1:
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "exact simulated write grant selector is ambiguous"
                )
            if not rows:
                return None
            row = rows[0]
            grant = _restore_grant(row)
            if grant.selector != checked:
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "restored simulated write grant selector differs"
                )
            if (
                SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
                .filter(predecessor_id=row.pk)
                .exists()
            ):
                return None
            revocation_rows = tuple(
                SimulatedCorporateActionWriteGrantRevocationModel._default_manager.using(
                    self._using
                )
                .filter(target_grant_id=row.pk)
                .order_by("pk")[:2]
            )
            if len(revocation_rows) > 1:
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "simulated write grant has multiple revocations"
                )
            if revocation_rows:
                _restore_revocation(revocation_rows[0], grant, _pk(row))
                return None
            current = SimulatedCorporateActionWriteGrantCurrent(grant=grant)
            return current if current.is_active_at(as_of) else None
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "exact simulated write grant read is unavailable"
            ) from error

    def get_current_for_scope(
        self,
        account_namespace: str,
        account_id: str,
        *,
        as_of: datetime,
    ) -> tuple[SimulatedCorporateActionWriteGrant, ...]:
        """Return all unrevoked, unexpired heads for one account without owner filtering."""

        namespace = _scope_token(account_namespace, "account_namespace")
        _scope_token(account_id, "account_id")
        cutoff = _cutoff(as_of)
        if namespace != "simulated":
            return ()
        try:
            rows = tuple(
                SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
                .filter(account_namespace=account_namespace, account_id=account_id)
                .order_by("grant_id", "recorded_at", "pk")
            )
            if not rows:
                return ()
            by_pk: dict[
                int,
                tuple[
                    SimulatedCorporateActionWriteGrantModel,
                    SimulatedCorporateActionWriteGrant,
                ],
            ] = {}
            chains: dict[
                str,
                list[
                    tuple[
                        SimulatedCorporateActionWriteGrantModel,
                        SimulatedCorporateActionWriteGrant,
                    ]
                ],
            ] = {}
            for row in rows:
                grant = _restore_grant(row)
                row_id = _pk(row)
                by_pk[row_id] = (row, grant)
                chains.setdefault(grant.grant_id, []).append((row, grant))

            row_ids = tuple(by_pk)
            if (
                SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
                .filter(predecessor_id__in=row_ids)
                .exclude(pk__in=row_ids)
                .exists()
            ):
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "simulated write grant successor is outside its exact account scope"
                )

            predecessor_ids: set[int] = set()
            for row, grant in by_pk.values():
                if row.predecessor_id is None:
                    continue
                predecessor = by_pk.get(row.predecessor_id)
                if predecessor is None:
                    raise SimulatedCorporateActionWriteGrantCorruption(
                        "simulated write grant predecessor is outside its exact account scope"
                    )
                try:
                    validate_simulated_corporate_action_write_grant_successor(predecessor[1], grant)
                except (TypeError, ValueError) as error:
                    raise SimulatedCorporateActionWriteGrantCorruption(
                        "simulated write grant successor chain is invalid"
                    ) from error
                predecessor_ids.add(row.predecessor_id)

            heads: list[
                tuple[
                    SimulatedCorporateActionWriteGrantModel,
                    SimulatedCorporateActionWriteGrant,
                ]
            ] = []
            for grant_id, chain in chains.items():
                roots = tuple(row for row, _ in chain if row.predecessor_id is None)
                current_heads = tuple(
                    (row, grant) for row, grant in chain if _pk(row) not in predecessor_ids
                )
                if len(roots) != 1 or len(current_heads) != 1:
                    raise SimulatedCorporateActionWriteGrantCorruption(
                        f"simulated write grant chain {grant_id} has an invalid root or head"
                    )
                heads.append(current_heads[0])

            head_ids = tuple(_pk(row) for row, _ in heads)
            revocations = tuple(
                SimulatedCorporateActionWriteGrantRevocationModel._default_manager.using(
                    self._using
                )
                .filter(target_grant_id__in=head_ids)
                .order_by("pk")
            )
            revoked_ids: set[int] = set()
            for revocation_row in revocations:
                target_id = revocation_row.target_grant_id
                target = by_pk.get(target_id)
                if target is None:
                    raise SimulatedCorporateActionWriteGrantCorruption(
                        "simulated write grant revocation target is outside its exact scope"
                    )
                if target_id in revoked_ids:
                    raise SimulatedCorporateActionWriteGrantCorruption(
                        "simulated write grant has multiple revocations"
                    )
                _restore_revocation(revocation_row, target[1], target_id)
                revoked_ids.add(target_id)

            current = tuple(
                grant
                for row, grant in heads
                if _pk(row) not in revoked_ids and grant.is_active_at(cutoff)
            )
            return tuple(
                sorted(
                    current,
                    key=lambda grant: (grant.grant_id, grant.grant_version, grant.content_hash),
                )
            )
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated write grant scope read is unavailable"
            ) from error

    def _append_grant(
        self,
        grant: SimulatedCorporateActionWriteGrant,
        expected_predecessor_content_hash: str | None,
    ) -> SimulatedCorporateActionWriteGrant:
        """Lock the exact grant chain, validate its head, then append or replay one row."""

        query = SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using)
        exact = query.filter(content_hash=grant.content_hash).first()
        if exact is not None:
            restored = _restore_grant(exact)
            if restored != grant:
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "simulated write grant content hash has conflicting facts"
                )
            return restored

        rows = tuple(
            query.select_for_update().filter(grant_id=grant.grant_id).order_by("recorded_at", "pk")
        )
        chain = tuple((row, _restore_grant(row)) for row in rows)
        predecessor_ids = {row.predecessor_id for row, _ in chain if row.predecessor_id is not None}
        heads = tuple((row, value) for row, value in chain if row.pk not in predecessor_ids)
        if len(heads) > 1:
            raise SimulatedCorporateActionWriteGrantCorruption(
                "simulated write grant chain has multiple heads"
            )
        predecessor_row, predecessor = heads[0] if heads else (None, None)
        actual_hash = predecessor.content_hash if predecessor is not None else None
        if actual_hash != expected_predecessor_content_hash:
            raise SimulatedCorporateActionWriteGrantConflict(
                "simulated write grant predecessor compare-and-swap differs"
            )
        try:
            if predecessor is None:
                if grant.supersedes_content_hash is not None:
                    raise ValueError("grant root has a predecessor hash")
            else:
                validate_simulated_corporate_action_write_grant_successor(predecessor, grant)
            values = _grant_values(grant, predecessor_row.pk if predecessor_row else None)
            with transaction.atomic(using=self._using):
                self._insert(SimulatedCorporateActionWriteGrantModel, values)
        except IntegrityError as error:
            exact_after_race = query.filter(content_hash=grant.content_hash).first()
            if exact_after_race is not None and _restore_grant(exact_after_race) == grant:
                return grant
            raise SimulatedCorporateActionWriteGrantConflict(
                "concurrent simulated write grant winner differs"
            ) from error
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantConflict(
                "invalid simulated write grant chain append"
            ) from error
        restored_row = query.get(content_hash=grant.content_hash)
        restored = _restore_grant(restored_row)
        if restored != grant:
            raise SimulatedCorporateActionWriteGrantCorruption(
                "simulated write grant restore differs after append"
            )
        return restored

    def _append_revocation(
        self,
        revocation: SimulatedCorporateActionWriteGrantRevocation,
    ) -> SimulatedCorporateActionWriteGrantRevocation:
        """Lock the exact target and append or replay its single revocation event."""

        revocation_query = SimulatedCorporateActionWriteGrantRevocationModel._default_manager.using(
            self._using
        )
        existing = revocation_query.filter(content_hash=revocation.content_hash).first()
        if existing is not None:
            target_row = self._grant_row_by_hash(revocation.grant_content_hash, lock=True)
            target = _restore_grant(target_row)
            restored = _restore_revocation(existing, target, _pk(target_row))
            if restored != revocation:
                raise SimulatedCorporateActionWriteGrantCorruption(
                    "simulated write grant revocation content hash has conflicting facts"
                )
            return restored

        grant_row = self._grant_row_by_hash(revocation.grant_content_hash, lock=True)
        grant = _restore_grant(grant_row)
        try:
            validate_simulated_corporate_action_write_grant_revocation(grant, revocation)
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantConflict(
                "simulated write grant revocation target is invalid"
            ) from error
        existing_for_target = revocation_query.filter(target_grant_id=grant_row.pk).first()
        if existing_for_target is not None:
            restored = _restore_revocation(existing_for_target, grant, _pk(grant_row))
            if restored == revocation:
                return restored
            raise SimulatedCorporateActionWriteGrantConflict(
                "simulated write grant already has a different revocation"
            )
        values = _revocation_values(revocation, _pk(grant_row))
        try:
            with transaction.atomic(using=self._using):
                self._insert(SimulatedCorporateActionWriteGrantRevocationModel, values)
        except IntegrityError as error:
            exact_after_race = revocation_query.filter(content_hash=revocation.content_hash).first()
            if exact_after_race is not None:
                return _restore_revocation(exact_after_race, grant, _pk(grant_row))
            raise SimulatedCorporateActionWriteGrantConflict(
                "concurrent simulated write grant revocation differs"
            ) from error
        restored_row = revocation_query.get(content_hash=revocation.content_hash)
        restored = _restore_revocation(restored_row, grant, _pk(grant_row))
        if restored != revocation:
            raise SimulatedCorporateActionWriteGrantCorruption(
                "simulated write grant revocation restore differs after append"
            )
        return restored

    def _grant_row_by_hash(
        self, content_hash: str, *, lock: bool
    ) -> SimulatedCorporateActionWriteGrantModel:
        """Load one durable grant row or fail closed when its exact hash is absent."""

        query = SimulatedCorporateActionWriteGrantModel._default_manager.using(self._using).filter(
            content_hash=content_hash
        )
        if lock:
            query = query.select_for_update()
        try:
            return query.get()
        except SimulatedCorporateActionWriteGrantModel.DoesNotExist as error:
            raise SimulatedCorporateActionWriteGrantConflict(
                "simulated write grant target does not exist"
            ) from error

    def _insert(
        self,
        model_type: (
            type[SimulatedCorporateActionWriteGrantModel]
            | type[SimulatedCorporateActionWriteGrantRevocationModel]
        ),
        values: dict[str, object],
    ) -> None:
        """Insert one exact typed model row under the repository's private claim."""

        model = model_type(**values)
        with _activate_simulated_corporate_action_write_grant_uow(self._token):
            with _claim_simulated_corporate_action_write_grant_insert(
                token=self._token,
                using=self._using,
                model_type=model_type,
                values=values,
            ):
                model.save(force_insert=True, using=self._using)


def _grant(value: SimulatedCorporateActionWriteGrant) -> SimulatedCorporateActionWriteGrant:
    """Validate one exact grant value before it reaches ORM serialization."""

    if type(value) is not SimulatedCorporateActionWriteGrant:
        raise SimulatedCorporateActionWriteGrantConflict("grant must be the exact domain record")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantConflict(
            "grant domain validation failed"
        ) from error
    return value


def _revocation(
    value: SimulatedCorporateActionWriteGrantRevocation,
) -> SimulatedCorporateActionWriteGrantRevocation:
    """Validate one exact revocation value before it reaches ORM serialization."""

    if type(value) is not SimulatedCorporateActionWriteGrantRevocation:
        raise SimulatedCorporateActionWriteGrantConflict(
            "revocation must be the exact domain record"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantConflict(
            "revocation domain validation failed"
        ) from error
    return value


def _selector(
    value: SimulatedCorporateActionWriteGrantSelector,
) -> SimulatedCorporateActionWriteGrantSelector:
    """Validate one exact grant selector at the repository boundary."""

    if type(value) is not SimulatedCorporateActionWriteGrantSelector:
        raise SimulatedCorporateActionWriteGrantConflict("selector type is invalid")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantConflict("selector values are invalid") from error
    return value


def _grant_values(
    grant: SimulatedCorporateActionWriteGrant,
    predecessor_id: int | None,
) -> dict[str, object]:
    """Map one validated grant to its typed columns and canonical payload."""

    binding = grant.binding
    capabilities = grant.capabilities
    return {
        "owner": "account",
        "artifact_type": "simulated_corporate_action_write_grant",
        "schema": grant.schema,
        "permission": grant.permission,
        "service_actor_id": SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
        "status": "active",
        "identity_hash": grant.identity_hash,
        "content_hash": grant.content_hash,
        "canonical_payload": grant.to_payload(),
        "grant_id": grant.grant_id,
        "grant_version": grant.grant_version,
        "account_namespace": binding.account_namespace,
        "account_id": binding.account_id,
        "owner_user_id": binding.owner_user_id,
        "tenant_id": binding.tenant_id,
        "owner_id": binding.owner_id,
        "account_source_id": binding.account_source_id,
        "account_source_version": binding.account_source_version,
        "account_source_content_hash": binding.account_source_content_hash,
        "policy_id": binding.policy_id,
        "policy_version": binding.policy_version,
        "policy_content_hash": binding.policy_content_hash,
        "consent_evidence_id": grant.consent_evidence_id,
        "consent_evidence_version": grant.consent_evidence_version,
        "consent_evidence_hash": grant.consent_evidence_hash,
        "issuer_evidence_id": grant.issuer_evidence_id,
        "issuer_evidence_version": grant.issuer_evidence_version,
        "issuer_evidence_hash": grant.issuer_evidence_hash,
        "consented_at": grant.consented_at,
        "issued_at": grant.issued_at,
        "recorded_at": grant.recorded_at,
        "valid_until": grant.valid_until,
        "supersedes_content_hash": grant.supersedes_content_hash,
        "capabilities": (
            [capability.value for capability in capabilities] if capabilities is not None else None
        ),
        "terms_version": grant.terms_version,
        "terms_sha256": grant.terms_sha256,
        "predecessor_id": predecessor_id,
    }


def _revocation_values(
    revocation: SimulatedCorporateActionWriteGrantRevocation,
    target_grant_id: int,
) -> dict[str, object]:
    """Map one validated revocation to its typed columns and canonical payload."""

    return {
        "owner": "account",
        "artifact_type": "simulated_corporate_action_write_grant_revocation",
        "schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_REVOCATION_SCHEMA,
        "permission": SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
        "service_actor_id": SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
        "status": "revoked",
        "identity_hash": revocation.identity_hash,
        "content_hash": revocation.content_hash,
        "canonical_payload": revocation.to_payload(),
        "revocation_id": revocation.revocation_id,
        "revocation_version": revocation.revocation_version,
        "target_grant_id": target_grant_id,
        "grant_id": revocation.grant_id,
        "grant_version": revocation.grant_version,
        "grant_identity_hash": revocation.grant_identity_hash,
        "grant_content_hash": revocation.grant_content_hash,
        "revocation_evidence_id": revocation.revocation_evidence_id,
        "revocation_evidence_version": revocation.revocation_evidence_version,
        "revocation_evidence_hash": revocation.revocation_evidence_hash,
        "issuer_evidence_id": revocation.issuer_evidence_id,
        "issuer_evidence_version": revocation.issuer_evidence_version,
        "issuer_evidence_hash": revocation.issuer_evidence_hash,
        "revoked_at": revocation.revoked_at,
        "recorded_at": revocation.recorded_at,
    }


def _restore_grant(
    row: SimulatedCorporateActionWriteGrantModel,
) -> SimulatedCorporateActionWriteGrant:
    """Restore one row and reject any typed-column or canonical-payload disagreement."""

    try:
        capabilities = _restore_capabilities(row.capabilities)
        grant = SimulatedCorporateActionWriteGrant(
            grant_id=row.grant_id,
            grant_version=row.grant_version,
            binding=SimulatedCorporateActionWriteGrantBinding(
                account_namespace=row.account_namespace,
                account_id=row.account_id,
                owner_user_id=row.owner_user_id,
                tenant_id=row.tenant_id,
                owner_id=row.owner_id,
                account_source_id=row.account_source_id,
                account_source_version=row.account_source_version,
                account_source_content_hash=row.account_source_content_hash,
                policy_id=row.policy_id,
                policy_version=row.policy_version,
                policy_content_hash=row.policy_content_hash,
            ),
            consent_evidence_id=row.consent_evidence_id,
            consent_evidence_version=row.consent_evidence_version,
            consent_evidence_hash=row.consent_evidence_hash,
            issuer_evidence_id=row.issuer_evidence_id,
            issuer_evidence_version=row.issuer_evidence_version,
            issuer_evidence_hash=row.issuer_evidence_hash,
            consented_at=row.consented_at,
            issued_at=row.issued_at,
            recorded_at=row.recorded_at,
            valid_until=row.valid_until,
            supersedes_content_hash=row.supersedes_content_hash,
            permission=row.permission,
            service_actor_id=row.service_actor_id,
            schema=row.schema,
            identity_hash=row.identity_hash,
            content_hash=row.content_hash,
            capabilities=capabilities,
            terms_version=row.terms_version,
            terms_sha256=row.terms_sha256,
        )
        if (
            row.owner != "account"
            or row.artifact_type != "simulated_corporate_action_write_grant"
            or row.status != "active"
            or row.canonical_payload != grant.to_payload()
        ):
            raise ValueError("grant row envelope or canonical payload differs")
        return grant
    except (AttributeError, TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantCorruption(
            "stored simulated corporate-action write grant is invalid"
        ) from error


def _restore_capabilities(
    value: object,
) -> tuple[SimulatedCorporateActionWriteCapability, ...] | None:
    """Decode one nullable JSON array without coercion or canonical-order repair."""

    if value is None:
        return None
    if type(value) is not list:
        raise TypeError("stored grant capabilities must be an exact JSON array")
    capabilities: list[SimulatedCorporateActionWriteCapability] = []
    for item in value:
        if type(item) is not str:
            raise TypeError("stored grant capability must be an exact string")
        try:
            capabilities.append(SimulatedCorporateActionWriteCapability(item))
        except ValueError as error:
            raise ValueError("stored grant capability is unknown") from error
    return validate_simulated_corporate_action_write_capabilities(tuple(capabilities))


def _restore_revocation(
    row: SimulatedCorporateActionWriteGrantRevocationModel,
    grant: SimulatedCorporateActionWriteGrant,
    expected_target_id: int,
) -> SimulatedCorporateActionWriteGrantRevocation:
    """Restore one revocation row and verify its target, typed values and payload."""

    try:
        revocation = SimulatedCorporateActionWriteGrantRevocation(
            revocation_id=row.revocation_id,
            revocation_version=row.revocation_version,
            grant_id=row.grant_id,
            grant_version=row.grant_version,
            grant_identity_hash=row.grant_identity_hash,
            grant_content_hash=row.grant_content_hash,
            revocation_evidence_id=row.revocation_evidence_id,
            revocation_evidence_version=row.revocation_evidence_version,
            revocation_evidence_hash=row.revocation_evidence_hash,
            issuer_evidence_id=row.issuer_evidence_id,
            issuer_evidence_version=row.issuer_evidence_version,
            issuer_evidence_hash=row.issuer_evidence_hash,
            revoked_at=row.revoked_at,
            recorded_at=row.recorded_at,
            permission=row.permission,
            service_actor_id=row.service_actor_id,
            schema=row.schema,
            identity_hash=row.identity_hash,
            content_hash=row.content_hash,
        )
        validate_simulated_corporate_action_write_grant_revocation(grant, revocation)
        if (
            row.owner != "account"
            or row.artifact_type != "simulated_corporate_action_write_grant_revocation"
            or row.status != "revoked"
            or row.target_grant_id != expected_target_id
            or row.canonical_payload != revocation.to_payload()
        ):
            raise ValueError("revocation row envelope, target or canonical payload differs")
        return revocation
    except (AttributeError, TypeError, ValueError) as error:
        raise SimulatedCorporateActionWriteGrantCorruption(
            "stored simulated corporate-action write grant revocation is invalid"
        ) from error


def _digest(value: object, name: str) -> str:
    """Validate one lowercase SHA-256 digest at an infrastructure boundary."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SimulatedCorporateActionWriteGrantConflict(f"{name} must be a SHA-256 digest")
    return value


def _scope_token(value: object, name: str) -> str:
    """Validate one bounded token used to select an exact account scope."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise SimulatedCorporateActionWriteGrantConflict(
            f"{name} must be a bounded canonical token"
        )
    return value


def _cutoff(value: object) -> datetime:
    """Require one exact timezone-aware repository cutoff."""

    if not _is_aware(value):
        raise SimulatedCorporateActionWriteGrantConflict("as_of must be timezone-aware")
    return value


def _is_aware(value: object) -> TypeGuard[datetime]:
    """Return whether one exact datetime has a usable timezone offset."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _pk(row: SimulatedCorporateActionWriteGrantModel) -> int:
    """Return one exact persisted primary key."""

    if type(row.pk) is not int:
        raise SimulatedCorporateActionWriteGrantCorruption(
            "persisted simulated write grant row has no exact primary key"
        )
    return row.pk


__all__ = [
    "DjangoSimulatedCorporateActionWriteGrantClock",
    "DjangoSimulatedCorporateActionWriteGrantRepository",
    "SimulatedCorporateActionWriteGrantClock",
]
