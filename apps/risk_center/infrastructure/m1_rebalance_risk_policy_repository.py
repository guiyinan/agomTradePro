"""Django repository and JSON boundary codecs for M1 risk revisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.risk_center.application.m1_rebalance_risk_policy import (
    M1RiskPolicyAlreadyRevokedError,
    M1RiskPolicyIdempotencyConflictError,
    M1RiskPolicyIdempotencyContext,
    M1RiskPolicyNotFoundError,
    M1RiskPolicyOperation,
    M1RiskPolicyRevisionRepository,
    M1RiskPolicySourceCorruptError,
    M1RiskPolicyValidationError,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    AccountType,
    M1RiskCondition,
    M1RiskPolicyPublishCommand,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
    RevocationState,
    RiskApplicability,
    RiskSourceLimitField,
    StrategySelectionState,
)
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    _AUDITED_REPOSITORY_CREATE_TOKEN,
    M1RebalanceRiskPolicyRevisionModel,
)
from apps.risk_center.infrastructure.models import _M1_RISK_AUDIT_WRITE_TOKEN, RiskPolicyAuditModel


class DjangoM1RiskPolicyRevisionRepository(M1RiskPolicyRevisionRepository):
    """Persist immutable revisions and reuse RiskPolicyAuditModel for publish events."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Bind an explicit database alias for reads and the atomic write."""

        self._using = using

    def find_revision_by_idempotency(
        self,
        *,
        context: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision | None:
        """Replay the exact committed audit result, rejecting changed request bodies."""

        _validate_idempotency_context(context=context)
        event = _find_idempotency_event(using=self._using, context=context)
        if event is None:
            return None
        return _revision_for_idempotency_event(
            using=self._using,
            context=context,
            event=event,
        )

    def create_revision(
        self,
        command: M1RiskPolicyPublishCommand,
        *,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Write one new policy row and its existing audit event in one transaction."""

        _validate_idempotency_context(
            context=idempotency,
            account_id=command.account_id,
            actor_user_id=command.actor_user_id,
            operation="publish",
        )
        with transaction.atomic(using=self._using):
            _lock_account_policy_writes(using=self._using, account_id=command.account_id)
            prior_event = _find_idempotency_event(using=self._using, context=idempotency)
            if prior_event is not None:
                return _revision_for_idempotency_event(
                    using=self._using,
                    context=idempotency,
                    event=prior_event,
                )
            existing = tuple(
                M1RebalanceRiskPolicyRevisionModel.objects.using(self._using)
                .select_for_update()
                .filter(
                    account_id=command.account_id,
                    effective_from__lt=command.effective_until,
                    effective_until__gt=command.effective_from,
                )
            )
            for prior in existing:
                prior_audits = tuple(
                    RiskPolicyAuditModel.objects.using(self._using).filter(
                        target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
                        target_id=str(prior.risk_policy_version),
                        action="revoke",
                    )
                )
                if len(prior_audits) != 1:
                    raise M1RiskPolicyValidationError(
                        ("M1_RISK_POLICY_WINDOW_OVERLAPS_EXISTING_REVISION",)
                    )
                state, revoked_at, _actor_id, _reason = _revocation_event(prior_audits[0])
                if state != "revoked" or revoked_at is None or revoked_at > command.effective_from:
                    raise M1RiskPolicyValidationError(
                        ("M1_RISK_POLICY_WINDOW_OVERLAPS_EXISTING_REVISION",)
                    )
            row = M1RebalanceRiskPolicyRevisionModel(
                account_id=command.account_id,
                actor_id=command.actor_user_id,
                effective_from=command.effective_from,
                effective_until=command.effective_until,
                reason=command.reason.strip(),
                max_single_position_state=command.max_single_position.applicability.value,
                max_single_position_pct=command.max_single_position.limit_pct,
                max_single_position_reason=command.max_single_position.not_applicable_reason,
                max_total_position_state=command.max_total_position.applicability.value,
                max_total_position_pct=command.max_total_position.limit_pct,
                max_total_position_reason=command.max_total_position.not_applicable_reason,
                max_stop_loss_state=command.max_stop_loss.applicability.value,
                max_stop_loss_pct=command.max_stop_loss.limit_pct,
                max_stop_loss_reason=command.max_stop_loss.not_applicable_reason,
                source_snapshot_schema_version="m1-risk-source.v2",
                source_snapshot=_source_snapshot_payload(command.source_snapshot),
                risk_falsification_schema_version="m1-risk-falsification.v1",
                risk_falsification_rules=_falsification_rules(command),
            )
            row._repository_create_token = _AUDITED_REPOSITORY_CREATE_TOKEN
            row.save(using=self._using, force_insert=True)
            if command.effective_from < row.known_at:
                raise M1RiskPolicyValidationError(
                    ("M1_RISK_POLICY_RETROACTIVE_EFFECTIVE_WINDOW_FORBIDDEN",)
                )
            publish_audit = RiskPolicyAuditModel(
                target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
                target_id=str(row.risk_policy_version),
                action="publish",
                actor_id=command.actor_user_id,
                before={},
                after={
                    "risk_policy_version": str(row.risk_policy_version),
                    "account_id": command.account_id,
                    "effective_from": command.effective_from.isoformat(),
                    "effective_until": command.effective_until.isoformat(),
                    "source_snapshot_schema_version": row.source_snapshot_schema_version,
                    "risk_falsification_schema_version": row.risk_falsification_schema_version,
                    "idempotency_identity_sha256": idempotency.identity_sha256,
                    "idempotency_request_sha256": idempotency.request_sha256,
                },
                reason=command.reason.strip(),
            )
            publish_audit._m1_repository_write_token = _M1_RISK_AUDIT_WRITE_TOKEN
            publish_audit.save(using=self._using, force_insert=True)
            return _revision_from_model(row)

    def list_revisions(self, *, account_id: int) -> tuple[M1RiskPolicyRevision, ...]:
        """Return all immutable revisions ordered by actual effective start."""

        rows = tuple(
            M1RebalanceRiskPolicyRevisionModel.objects.using(self._using)
            .filter(account_id=account_id)
            .order_by("effective_from", "risk_policy_version")
        )
        if not rows:
            return ()
        target_ids = tuple(str(row.risk_policy_version) for row in rows)
        revocation_by_version: dict[
            str,
            tuple[RevocationState, datetime | None, int | None, str | None],
        ] = {}
        audits = (
            RiskPolicyAuditModel.objects.using(self._using)
            .filter(
                target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
                target_id__in=target_ids,
                action="revoke",
            )
            .order_by("created_at", "id")
        )
        for audit in audits:
            event = _revocation_event(audit)
            if audit.target_id in revocation_by_version:
                prior = revocation_by_version[audit.target_id]
                revocation_by_version[audit.target_id] = (
                    "unknown",
                    prior[1],
                    prior[2],
                    "Multiple revocation audit events exist for this M1 risk version.",
                )
            else:
                revocation_by_version[audit.target_id] = event
        revisions: list[M1RiskPolicyRevision] = []
        for row in rows:
            try:
                revision = _revision_from_model(row)
            except ValueError as exc:
                raise M1RiskPolicySourceCorruptError(
                    "Stored M1 risk revision source is inconsistent."
                ) from exc
            revocation = revocation_by_version.get(revision.risk_policy_version)
            if revocation is not None:
                state, revoked_at, actor_id, reason = revocation
                revisions.append(
                    replace(
                        revision,
                        revocation_state=state,
                        revoked_at=revoked_at,
                        revoked_by_user_id=actor_id,
                        revocation_reason=reason,
                    )
                )
            else:
                revisions.append(revision)
        return tuple(revisions)

    def revoke_revision(
        self,
        *,
        account_id: int,
        risk_policy_version: str,
        actor_user_id: int,
        reason: str,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Append the sole revoke event for one exact account/version pair."""

        _validate_idempotency_context(
            context=idempotency,
            account_id=account_id,
            actor_user_id=actor_user_id,
            operation="revoke",
        )
        with transaction.atomic(using=self._using):
            # Serialize every account-scoped revoke request, including retries that
            # target different versions with a reused Idempotency-Key. On the
            # production PostgreSQL backend this closes the audit JSON uniqueness
            # race without introducing a second idempotency table.
            _lock_account_policy_writes(using=self._using, account_id=account_id)
            try:
                row = (
                    M1RebalanceRiskPolicyRevisionModel.objects.using(self._using)
                    .select_for_update()
                    .get(
                        account_id=account_id,
                        risk_policy_version=risk_policy_version,
                    )
                )
            except M1RebalanceRiskPolicyRevisionModel.DoesNotExist as exc:
                raise M1RiskPolicyNotFoundError("M1 risk policy version not found.") from exc
            prior_event = _find_idempotency_event(using=self._using, context=idempotency)
            if prior_event is not None:
                return _revision_for_idempotency_event(
                    using=self._using,
                    context=idempotency,
                    event=prior_event,
                )
            revoke_queryset = RiskPolicyAuditModel.objects.using(self._using).filter(
                target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
                target_id=str(row.risk_policy_version),
                action="revoke",
            )
            if revoke_queryset.exists():
                raise M1RiskPolicyAlreadyRevokedError("M1 risk policy version is already revoked.")
            effective_at = timezone.now()
            audit = RiskPolicyAuditModel(
                target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
                target_id=str(row.risk_policy_version),
                action="revoke",
                actor_id=actor_user_id,
                before={},
                after={
                    "risk_policy_version": str(row.risk_policy_version),
                    "account_id": account_id,
                    "status": "revoked",
                    "effective_at": effective_at.isoformat(),
                    "idempotency_identity_sha256": idempotency.identity_sha256,
                    "idempotency_request_sha256": idempotency.request_sha256,
                },
                reason=reason,
            )
            audit._m1_repository_write_token = _M1_RISK_AUDIT_WRITE_TOKEN
            audit.save(using=self._using, force_insert=True)
            revision = _revision_from_model(row)
            return replace(
                revision,
                revocation_state="revoked",
                revoked_at=effective_at,
                revoked_by_user_id=(audit.actor_id if type(audit.actor_id) is int else None),
                revocation_reason=audit.reason,
            )


def _validate_idempotency_context(
    *,
    context: M1RiskPolicyIdempotencyContext,
    account_id: int | None = None,
    actor_user_id: int | None = None,
    operation: M1RiskPolicyOperation | None = None,
) -> None:
    """Require exact scope agreement before reading or writing a retry result."""

    if type(context) is not M1RiskPolicyIdempotencyContext:
        raise M1RiskPolicyValidationError(("M1_RISK_POLICY_IDEMPOTENCY_CONTEXT_INVALID",))
    if (
        account_id is not None
        and context.account_id != account_id
        or actor_user_id is not None
        and context.actor_user_id != actor_user_id
        or operation is not None
        and context.operation != operation
    ):
        raise M1RiskPolicyValidationError(("M1_RISK_POLICY_IDEMPOTENCY_SCOPE_MISMATCH",))


def _find_idempotency_event(
    *,
    using: str,
    context: M1RiskPolicyIdempotencyContext,
) -> RiskPolicyAuditModel | None:
    """Find one append-only event by scoped digest, never by a raw client key."""

    matches: list[RiskPolicyAuditModel] = []
    events: QuerySet[RiskPolicyAuditModel] = RiskPolicyAuditModel.objects.using(using).filter(
        target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
        action=context.operation,
    )
    for event in events:
        after = event.after
        identity = after.get("idempotency_identity_sha256") if isinstance(after, Mapping) else None
        if identity == context.identity_sha256:
            matches.append(event)
    if len(matches) > 1:
        raise M1RiskPolicySourceCorruptError(
            "More than one M1 risk audit event claims the same idempotency identity."
        )
    if not matches:
        return None
    event = matches[0]
    after = event.after
    if not isinstance(after, Mapping):
        raise M1RiskPolicySourceCorruptError("M1 risk audit event payload is not an object.")
    if event.actor_id != context.actor_user_id or after.get("account_id") != context.account_id:
        raise M1RiskPolicySourceCorruptError(
            "M1 idempotency event escaped its owner/account scope."
        )
    stored_request_hash = after.get("idempotency_request_sha256")
    if type(stored_request_hash) is not str or len(stored_request_hash) != 64:
        raise M1RiskPolicySourceCorruptError("M1 idempotency request hash is malformed.")
    if stored_request_hash != context.request_sha256:
        raise M1RiskPolicyIdempotencyConflictError(
            "The idempotency key is already bound to a different request body."
        )
    version = after.get("risk_policy_version")
    if type(version) is not str or version != event.target_id:
        raise M1RiskPolicySourceCorruptError(
            "M1 idempotency event version identity is inconsistent."
        )
    return event


def _revision_for_idempotency_event(
    *,
    using: str,
    context: M1RiskPolicyIdempotencyContext,
    event: RiskPolicyAuditModel,
) -> M1RiskPolicyRevision:
    """Reconstruct the exact committed publish/revoke response from immutable sources."""

    try:
        row = M1RebalanceRiskPolicyRevisionModel.objects.using(using).get(
            account_id=context.account_id,
            risk_policy_version=event.target_id,
        )
    except M1RebalanceRiskPolicyRevisionModel.DoesNotExist as error:
        raise M1RiskPolicySourceCorruptError(
            "M1 idempotency event points to a missing revision."
        ) from error
    try:
        revision = _revision_from_model(row)
    except ValueError as error:
        raise M1RiskPolicySourceCorruptError(
            "M1 idempotency revision source is inconsistent."
        ) from error
    if revision.actor_user_id != context.actor_user_id:
        raise M1RiskPolicySourceCorruptError("M1 idempotency revision actor is inconsistent.")
    if context.operation == "publish":
        return revision
    state, revoked_at, actor_id, reason = _revocation_event(event)
    if state != "revoked" or revoked_at is None or actor_id != context.actor_user_id:
        raise M1RiskPolicySourceCorruptError("M1 revoke retry points to an invalid audit event.")
    return replace(
        revision,
        revocation_state="revoked",
        revoked_at=revoked_at,
        revoked_by_user_id=actor_id,
        revocation_reason=reason,
    )


def _revision_from_model(row: M1RebalanceRiskPolicyRevisionModel) -> M1RiskPolicyRevision:
    """Decode one ORM row into a complete Domain object or reject corrupt JSON."""

    if row.source_snapshot_schema_version != "m1-risk-source.v2":
        raise ValueError("unsupported stored source snapshot schema")
    if row.risk_falsification_schema_version != "m1-risk-falsification.v1":
        raise ValueError("unsupported stored falsification schema")
    revision = M1RiskPolicyRevision(
        risk_policy_version=str(row.risk_policy_version),
        account_id=int(row.account_id),
        actor_user_id=int(row.actor_id),
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        known_at=row.known_at,
        reason=row.reason,
        max_single_position=_condition(
            row.max_single_position_state,
            row.max_single_position_pct,
            row.max_single_position_reason,
        ),
        max_total_position=_condition(
            row.max_total_position_state,
            row.max_total_position_pct,
            row.max_total_position_reason,
        ),
        max_stop_loss=_condition(
            row.max_stop_loss_state,
            row.max_stop_loss_pct,
            row.max_stop_loss_reason,
        ),
        source_snapshot=_source_snapshot_from_payload(row.source_snapshot),
    )
    if row.risk_falsification_rules != _falsification_rules_from_revision(revision):
        raise ValueError("stored predicates differ from the immutable condition columns")
    return revision


def _lock_account_policy_writes(*, using: str, account_id: int) -> None:
    """Serialize concurrent PostgreSQL publish operations for one account scope."""

    connection = connections[using]
    if connection.vendor != "postgresql":
        return
    account_lock_key = account_id % 2_147_483_647
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [1_296_773_712, account_lock_key],
        )


def _revocation_event(
    audit: RiskPolicyAuditModel,
) -> tuple[RevocationState, datetime | None, int | None, str | None]:
    """Read explicit audit effective_at; created_at remains record time only."""

    after = audit.after
    event_value: object = after.get("effective_at") if isinstance(after, Mapping) else None
    effective_at: datetime | None = None
    if type(event_value) is str:
        try:
            parsed = datetime.fromisoformat(event_value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None and parsed.utcoffset() is not None:
            effective_at = parsed
    actor_id = audit.actor_id if type(audit.actor_id) is int and audit.actor_id > 0 else None
    reason = audit.reason if type(audit.reason) is str and audit.reason.strip() else None
    state: RevocationState = (
        "revoked" if effective_at is not None and actor_id is not None and reason else "unknown"
    )
    return state, effective_at, actor_id, reason


def _condition(state: str, limit: Decimal | None, reason: str | None) -> M1RiskCondition:
    """Narrow one stored choice and its decimal to a valid Domain condition."""

    try:
        applicability = RiskApplicability(state)
    except ValueError as exc:
        raise ValueError("stored M1 risk applicability is invalid") from exc
    return M1RiskCondition(
        applicability=applicability,
        limit_pct=Decimal(limit) if limit is not None else None,
        not_applicable_reason=reason,
    )


def _source_snapshot_payload(snapshot: M1RiskSourceSnapshot) -> dict[str, object]:
    """Serialize exact reviewed source values with Decimal strings, never floats."""

    return {
        "schema_version": "m1-risk-source.v2",
        "account_id": snapshot.account_id,
        "account_owner_user_id": snapshot.account_owner_user_id,
        "account_type": snapshot.account_type,
        "account_is_active": snapshot.account_is_active,
        "account_max_single_position_pct": _decimal_text(snapshot.account_max_single_position_pct),
        "account_max_total_position_pct": _decimal_text(snapshot.account_max_total_position_pct),
        "account_stop_loss_pct": _decimal_text(snapshot.account_stop_loss_pct),
        "strategy_selection_state": snapshot.strategy_selection_state,
        "strategy_id": snapshot.strategy_id,
        "strategy_version": snapshot.strategy_version,
        "strategy_max_single_position_pct": _decimal_text(
            snapshot.strategy_max_single_position_pct
        ),
        "strategy_max_total_position_pct": _decimal_text(snapshot.strategy_max_total_position_pct),
        "strategy_stop_loss_pct": _decimal_text(snapshot.strategy_stop_loss_pct),
        "position_rule_id": snapshot.position_rule_id,
        "position_rule_source_json": snapshot.position_rule_source_json,
        "account_invalid_limit_fields": list(snapshot.account_invalid_limit_fields),
        "strategy_invalid_limit_fields": list(snapshot.strategy_invalid_limit_fields),
    }


def _source_snapshot_from_payload(value: object) -> M1RiskSourceSnapshot:
    """Decode an ORM JSON object into an exact, finite typed source snapshot."""

    mapping = _mapping(value)
    if mapping.get("schema_version") != "m1-risk-source.v2":
        raise ValueError("unsupported stored M1 risk source snapshot schema")
    state = _strategy_selection_state(mapping.get("strategy_selection_state"))
    return M1RiskSourceSnapshot(
        account_id=_exact_positive_int(mapping.get("account_id"), "account_id"),
        account_owner_user_id=_optional_positive_int(
            mapping.get("account_owner_user_id"), "account_owner_user_id"
        ),
        account_type=_account_type(mapping.get("account_type")),
        account_is_active=_optional_bool(mapping.get("account_is_active")),
        account_max_single_position_pct=_optional_decimal(
            mapping.get("account_max_single_position_pct")
        ),
        account_max_total_position_pct=_optional_decimal(
            mapping.get("account_max_total_position_pct")
        ),
        account_stop_loss_pct=_optional_decimal(mapping.get("account_stop_loss_pct")),
        strategy_selection_state=state,
        strategy_id=_optional_positive_int(mapping.get("strategy_id"), "strategy_id"),
        strategy_version=_optional_positive_int(
            mapping.get("strategy_version"), "strategy_version"
        ),
        strategy_max_single_position_pct=_optional_decimal(
            mapping.get("strategy_max_single_position_pct")
        ),
        strategy_max_total_position_pct=_optional_decimal(
            mapping.get("strategy_max_total_position_pct")
        ),
        strategy_stop_loss_pct=_optional_decimal(mapping.get("strategy_stop_loss_pct")),
        position_rule_id=_optional_positive_int(
            mapping.get("position_rule_id"), "position_rule_id"
        ),
        position_rule_source_json=_optional_string(mapping.get("position_rule_source_json")),
        account_invalid_limit_fields=_risk_source_limit_fields(
            mapping.get("account_invalid_limit_fields")
        ),
        strategy_invalid_limit_fields=_risk_source_limit_fields(
            mapping.get("strategy_invalid_limit_fields")
        ),
    )


def _falsification_rules(command: M1RiskPolicyPublishCommand) -> list[dict[str, object]]:
    """Persist server-generated comparison rules; clients cannot submit formulas."""

    return _falsification_rules_for_conditions(
        (
            ("max_single_position", command.max_single_position),
            ("max_total_position", command.max_total_position),
            ("max_stop_loss", command.max_stop_loss),
        )
    )


def _falsification_rules_from_revision(
    revision: M1RiskPolicyRevision,
) -> list[dict[str, object]]:
    """Rebuild exact predicates from stored Domain fields for integrity checks."""

    return _falsification_rules_for_conditions(
        (
            ("max_single_position", revision.max_single_position),
            ("max_total_position", revision.max_total_position),
            ("max_stop_loss", revision.max_stop_loss),
        )
    )


def _falsification_rules_for_conditions(
    conditions: tuple[tuple[str, M1RiskCondition], ...],
) -> list[dict[str, object]]:
    """Serialize canonical threshold predicates for typed condition columns."""

    predicate_by_dimension: dict[str, str] = {
        "max_single_position": "target_single_position_pct <= limit_pct",
        "max_total_position": "projected_total_position_pct <= limit_pct",
        "max_stop_loss": "observed_loss_pct < stop_loss_limit_pct",
    }
    return [
        {
            "dimension": name,
            "applicability": condition.applicability.value,
            "predicate": predicate_by_dimension[name],
            "limit_pct": _risk_limit_text(condition.limit_pct),
            "not_applicable_reason": condition.not_applicable_reason,
        }
        for name, condition in conditions
    ]


def _risk_limit_text(value: Decimal | None) -> str | None:
    """Serialize thresholds at the exact three-decimal database scale."""

    if value is None:
        return None
    return format(value.quantize(Decimal("0.001")), "f")


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow JSONField data before it enters Application and Domain."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError("stored M1 source snapshot must be a JSON object")
    return cast(Mapping[str, object], value)


def _exact_positive_int(value: object, field_name: str) -> int:
    """Require an exact positive JSON integer."""

    if type(value) is not int or value <= 0:
        raise ValueError(f"stored {field_name} must be an exact positive integer")
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    """Require a nullable exact positive JSON integer."""

    if value is None:
        return None
    return _exact_positive_int(value, field_name)


def _string(value: object) -> str:
    """Require a JSON string before constructing a source DTO."""

    if type(value) is not str:
        raise ValueError("stored M1 source state must be a string")
    return value


def _strategy_selection_state(value: object) -> StrategySelectionState:
    """Narrow persisted JSON to a supported source-state literal."""

    raw_state = _string(value)
    if raw_state not in {"configured", "confirmed_unconfigured", "unavailable"}:
        raise ValueError("stored M1 strategy selection state is invalid")
    return cast(StrategySelectionState, raw_state)


def _account_type(value: object) -> AccountType:
    """Narrow persisted account type to a supported snapshot literal."""

    raw_type = _string(value)
    if raw_type not in {"simulated", "real", "unknown"}:
        raise ValueError("stored M1 account type is invalid")
    return cast(AccountType, raw_type)


def _optional_bool(value: object) -> bool | None:
    """Preserve a nullable exact JSON boolean without truthiness coercion."""

    if value is None:
        return None
    if type(value) is not bool:
        raise ValueError("stored M1 active state must be a boolean or null")
    return value


def _optional_string(value: object) -> str | None:
    """Require a nullable JSON string."""

    if value is None:
        return None
    return _string(value)


def _risk_source_limit_fields(value: object) -> tuple[RiskSourceLimitField, ...]:
    """Decode an exact JSON list of known account/strategy risk field names."""

    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError("stored M1 source corruption fields must be a JSON string list")
    allowed: dict[str, RiskSourceLimitField] = {
        "max_single_position_pct": "max_single_position_pct",
        "max_total_position_pct": "max_total_position_pct",
        "stop_loss_pct": "stop_loss_pct",
    }
    if len(value) != len(set(value)) or any(item not in allowed for item in value):
        raise ValueError("stored M1 source corruption fields contain unsupported values")
    return tuple(allowed[item] for item in value)


def _optional_decimal(value: object) -> Decimal | None:
    """Decode a finite decimal string while rejecting float snapshots."""

    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("stored M1 percentage must be a decimal string or null")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("stored M1 percentage is invalid") from exc
    if not result.is_finite():
        raise ValueError("stored M1 percentage must be finite")
    return result


def _decimal_text(value: Decimal | None) -> str | None:
    """Serialize decimal data without binary floating point conversion."""

    return str(value) if value is not None else None


__all__: tuple[str, ...] = ("DjangoM1RiskPolicyRevisionRepository",)
