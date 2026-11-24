"""Issue and revalidate an owner-signed mandate for one exact prebuilt broker order."""

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from django.db import connections
from django.utils import timezone
from rest_framework.request import Request

from apps.broker_execution.application.authorization import require_action, role_can_approve_order
from apps.broker_execution.application.checkpoint_authority import BrokerCheckpointIntent
from apps.broker_execution.application.evidence_gate import broker_order_evidence_integrated
from apps.broker_execution.application.order_scope_sources import (
    OrderArtifactRef,
    OrderBenchmarkPin,
    OrderMaterialSelector,
    OrderScopeOwner,
    order_scope_sources,
)
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.ash09_checkpoint_composition import resolve_current_intent
from apps.broker_execution.infrastructure.broker_account_identity_snapshot_repository import (
    DjangoBrokerAccountIdentitySnapshotRepository,
)
from apps.broker_execution.infrastructure.broker_order_scope_seal import (
    BrokerReferenceDigester,
    owner_signature_mac,
)
from apps.broker_execution.infrastructure.models import BrokerAccountBindingModel
from apps.broker_execution.infrastructure.order_execution_scope_models import (
    BrokerOrderExecutionScopeModel,
)


@dataclass(frozen=True, slots=True)
class OrderExecutionScopeReceipt:
    """Finite human mandate. Every upstream version is pinned at first issuance."""

    execution_scope_id: str
    execution_scope_version: str
    execution_scope_hash: str
    client_order_id: UUID
    order_version: int
    account_id: int
    owner_user_id: int
    tenant_id: str
    owner_id: str
    authority_policy_id: str
    authority_policy_version: str
    authority_policy_hash: str
    account_identity_hash: str
    broker_identity_hash: str
    account_binding_hash: str
    order_content_hash: str
    plan_binding_hash: str
    pre_risk_hash: str
    benchmark_approval_id: UUID
    benchmark_approval_version: int
    benchmark_content_hash: str
    output: OrderArtifactRef
    envelope_content_hash: str
    operator: OrderArtifactRef
    track: OrderArtifactRef
    activation_hash: str
    read_scope_hashes: tuple[str, ...]
    review_hash: str
    signer_role: str
    research_permission: str
    recorded_at: datetime
    valid_until: datetime


def _manifest(receipt: OrderExecutionScopeReceipt) -> dict[str, object]:
    payload = asdict(receipt)
    del payload["execution_scope_hash"]
    for field in ("client_order_id", "benchmark_approval_id"):
        payload[field] = str(payload[field])
    for field in ("recorded_at", "valid_until"):
        payload[field] = payload[field].astimezone(UTC).isoformat()
    payload["read_scope_hashes"] = list(receipt.read_scope_hashes)
    return payload


@dataclass(frozen=True, slots=True)
class _PreparedScope:
    receipt: OrderExecutionScopeReceipt
    review: dict[str, object]


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _database_time(using: str) -> datetime:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        value: datetime = cursor.fetchone()[0]
        return value


def _require_scope_fence(using: str) -> None:
    with connections[using].cursor() as cursor:
        cursor.execute("LOCK TABLE broker_execution_order_scope IN ACCESS SHARE MODE NOWAIT")
        cursor.execute("""
            SELECT count(*) FROM pg_catalog.pg_trigger
            WHERE tgrelid='broker_execution_order_scope'::regclass
              AND tgname IN ('broker_execution_order_scope_guard','broker_execution_order_scope_truncate')
              AND tgenabled='A'
        """)
        if cursor.fetchone() != (2,):
            raise BrokerExecutionConflictError("broker_order_scope_fence_unavailable")


def _bound_owner(intent: BrokerCheckpointIntent, *, using: str) -> OrderScopeOwner | None:
    sources = intent.sources.account
    binding = (
        BrokerAccountBindingModel.objects.using(using)
        .select_related("agent")
        .select_for_update(nowait=True)
        .filter(
            account_id=sources.broker_account_id,
            user_id=intent.owner_user_id,
            is_active=True,
            agent__user_id=intent.owner_user_id,
            agent__is_active=True,
        )
        .first()
    )
    if binding is None or binding.agent.agent_id != intent.snapshot.agent_id:
        return None
    current = DjangoBrokerAccountIdentitySnapshotRepository(using=using).get_current_head(
        broker_account_namespace=intent.broker_account_namespace,
        broker_account_id=binding.account_id,
        as_of=timezone.now(),
    )
    if current is None:
        return None
    broker = current.snapshot
    if (
        (broker.snapshot_id, broker.snapshot_version, broker.content_hash)
        != (
            sources.broker_source_id,
            sources.broker_source_version,
            sources.broker_source_content_hash,
        )
        or not broker.is_knowable_at(timezone.now())
        or broker.agent_id != binding.agent.agent_id
        or broker.owner_user_id != binding.user_id
        or broker.broker_account_category != binding.account_type
        or broker.qmt_account_ref_digest
        != BrokerReferenceDigester().digest(opaque_reference=binding.broker_account_ref.encode())
    ):
        return None
    ref = broker.account_source_ref
    if (
        ref.account_namespace,
        ref.account_id,
        ref.source_id,
        ref.source_version,
        ref.content_hash,
    ) != (
        sources.portfolio_account_namespace,
        sources.portfolio_account_id,
        sources.portfolio_source_id,
        sources.portfolio_source_version,
        sources.portfolio_source_content_hash,
    ):
        return None
    owner = order_scope_sources().owner(
        account_namespace=ref.account_namespace,
        account_id=ref.account_id,
        owner_user_id=intent.owner_user_id,
        using=using,
    )
    if (
        owner is None
        or (owner.account_namespace, owner.account_id, owner.owner_user_id)
        != (ref.account_namespace, ref.account_id, intent.owner_user_id)
        or owner.physical_row_pk != binding.account_id
        or not role_can_approve_order(owner.role)
        or (owner.source_id, owner.source_version, owner.identity_hash)
        != (ref.source_id, ref.source_version, ref.content_hash)
    ):
        return None
    return owner


def _locked_scope(
    *,
    client_order_id: UUID,
    account_id: int,
    owner_user_id: int,
    using: str,
    mode: Literal["preview", "sign", "read"],
    expected_review_hash: str | None = None,
    selection: OrderMaterialSelector | None = None,
) -> _PreparedScope | None:
    db = connections[using]
    if (
        db.vendor != "postgresql"
        or not db.in_atomic_block
        or type(client_order_id) is not UUID
        or type(account_id) is not int
        or type(owner_user_id) is not int
    ):
        return None
    if (
        not BrokerAccountBindingModel.objects.using(using)
        .filter(account_id=account_id, user_id=owner_user_id, is_active=True)
        .exists()
    ):
        return None
    with db.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone()[0] != "read committed":
            return None
        cursor.execute(
            "LOCK TABLE broker_execution_order_approval_artifact, broker_execution_plan_order_binding, broker_execution_portfolio_account_binding, broker_execution_pre_risk_scope, broker_execution_account_identity_snapshot IN SHARE MODE NOWAIT"
        )
    _require_scope_fence(using)
    intent = resolve_current_intent(
        client_order_id=client_order_id, account_id=account_id, using=using
    )
    if intent.owner_user_id != owner_user_id:
        return None
    owner = _bound_owner(intent, using=using)
    if owner is None:
        return None
    rows = BrokerOrderExecutionScopeModel.objects.using(using)
    row = (
        rows.select_for_update(nowait=True)
        .filter(client_order_id=client_order_id, order_version=intent.order_version)
        .first()
    )
    if row is None and mode == "read":
        return None
    if row is not None and (
        row.account_id != account_id
        or row.owner_user_id != owner_user_id
        or row.revoked_at is not None
        or row.valid_until <= timezone.now()
    ):
        return None
    pin = (
        None
        if row is None
        else OrderBenchmarkPin(
            row.benchmark_approval_id, row.benchmark_approval_version, row.benchmark_content_hash
        )
    )
    if row is not None:
        if (
            type(row.manifest) is not dict
            or type(row.manifest.get("output")) is not dict
            or not hmac.compare_digest(row.issuer_mac, owner_signature_mac(row.content_hash))
            or _digest(row.manifest) != row.content_hash
        ):
            return None
        pinned = OrderMaterialSelector.parse(
            {
                **row.manifest["output"],
                "envelope_content_hash": row.manifest.get("envelope_content_hash"),
            }
        )
        if selection is not None and selection != pinned:
            return None
        selection = pinned
    material = order_scope_sources().materials(
        intent=intent, owner=owner, pin=pin, selection=selection, using=using
    )
    if material is None or material.research_permission != "display_only":
        return None
    src, snapshot = intent.sources, intent.snapshot
    order = src.order
    deadline = min(
        owner.valid_until,
        src.account.valid_until,
        order.valid_until,
        src.plan.valid_until,
        src.pre_risk.valid_until,
        material.valid_until,
    )
    review: dict[str, object] = {
        "schema": "broker-order-owner-review.v1",
        "client_order_id": str(client_order_id),
        "account_id": account_id,
        "order_version": intent.order_version,
        "expected_order_hash": order.content_hash,
        "owner_user_id": owner_user_id,
        "tenant_id": owner.tenant_id,
        "owner_id": owner.owner_id,
        "signer_role": owner.role,
        "authority_policy": [owner.policy_id, owner.policy_version, owner.policy_hash],
        "account_identity": [owner.source_id, owner.source_version, owner.identity_hash],
        "broker_identity_hash": src.account.broker_source_content_hash,
        "account_binding_hash": src.account.content_hash,
        "pre_risk_hash": src.pre_risk.content_hash,
        "order": {
            "agent_id": snapshot.agent_id,
            "asset_code": snapshot.asset_code,
            "market": snapshot.market,
            "side": snapshot.side.value,
            "order_type": snapshot.order_type.value,
            "quantity": str(snapshot.quantity),
            "limit_price": str(snapshot.limit_price) if snapshot.limit_price is not None else None,
            "estimated_amount": str(snapshot.estimated_amount),
            "expires_at": snapshot.expires_at,
            "approval_mode": snapshot.approval_mode,
            "risk_policy_version": snapshot.risk_policy_version,
            "risk_snapshot": json.loads(snapshot.risk_snapshot_json),
            "recommendation_ids": list(snapshot.source_recommendation_ids),
            "signal_ids": list(snapshot.source_signal_ids),
        },
        "plan": {
            "id": intent.plan_id,
            "version": intent.plan_version,
            "ordinal": intent.plan_order_ordinal,
            "content_hash": src.plan.portfolio_plan_content_hash,
            "order_hash": src.plan.plan_order_content_hash,
            "binding_hash": src.plan.content_hash,
            "approval_id": src.plan.portfolio_receipt_id,
            "approval_version": src.plan.portfolio_receipt_version,
            "approval_hash": src.plan.portfolio_receipt_content_hash,
        },
        "materials": {
            "benchmark": {
                "id": str(material.benchmark.approval_id),
                "version": material.benchmark.approval_version,
                "hash": material.benchmark.content_hash,
            },
            "research": {
                "permission": material.research_permission,
                "must_not_execute": True,
                "governance": material.research_governance,
                "blockers": list(material.research_blockers),
                "summary": material.research_summary,
                "linked_order_sources": [asdict(r) for r in material.linked_order_sources],
                "output": asdict(material.output),
                "envelope_hash": material.envelope_content_hash,
                "operator": asdict(material.operator),
                "track": asdict(material.track),
                "activation_hash": material.activation_hash,
                "read_scope_hashes": list(material.read_scope_hashes),
            },
        },
        "valid_until": deadline.astimezone(UTC).isoformat(),
    }
    review_hash = _digest(review)
    if mode == "sign" and (
        type(expected_review_hash) is not str
        or not expected_review_hash.isascii()
        or not hmac.compare_digest(expected_review_hash, review_hash)
    ):
        raise BrokerExecutionConflictError("broker_order_scope_review_changed")
    now = _database_time(using)
    if now >= deadline:
        return None
    receipt = OrderExecutionScopeReceipt(
        execution_scope_id=str(row.scope_id if row else uuid4()),
        execution_scope_version="broker-order-execution-scope.v1",
        execution_scope_hash="",
        client_order_id=client_order_id,
        order_version=intent.order_version,
        account_id=account_id,
        owner_user_id=owner_user_id,
        tenant_id=owner.tenant_id,
        owner_id=owner.owner_id,
        authority_policy_id=owner.policy_id,
        authority_policy_version=owner.policy_version,
        authority_policy_hash=owner.policy_hash,
        account_identity_hash=owner.identity_hash,
        broker_identity_hash=src.account.broker_source_content_hash,
        account_binding_hash=src.account.content_hash,
        order_content_hash=order.content_hash,
        plan_binding_hash=src.plan.content_hash,
        pre_risk_hash=src.pre_risk.content_hash,
        benchmark_approval_id=material.benchmark.approval_id,
        benchmark_approval_version=material.benchmark.approval_version,
        benchmark_content_hash=material.benchmark.content_hash,
        output=material.output,
        envelope_content_hash=material.envelope_content_hash,
        operator=material.operator,
        track=material.track,
        activation_hash=material.activation_hash,
        read_scope_hashes=material.read_scope_hashes,
        review_hash=review_hash,
        signer_role=owner.role,
        research_permission=material.research_permission,
        recorded_at=row.recorded_at if row else now,
        valid_until=deadline,
    )
    manifest = _manifest(receipt)
    digest = hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    receipt = replace(receipt, execution_scope_hash=digest)
    mac = owner_signature_mac(receipt.execution_scope_hash)
    if row is None and mode == "sign":
        rows.create(
            scope_id=UUID(receipt.execution_scope_id),
            client_order_id=client_order_id,
            order_version=intent.order_version,
            account_id=account_id,
            owner_user_id=owner_user_id,
            recorded_at=now,
            valid_until=deadline,
            benchmark_approval_id=material.benchmark.approval_id,
            benchmark_approval_version=material.benchmark.approval_version,
            benchmark_content_hash=material.benchmark.content_hash,
            manifest=manifest,
            content_hash=receipt.execution_scope_hash,
            issuer_mac=mac,
        )
    elif row is not None and (
        row.recorded_at > now
        or row.valid_until != deadline
        or row.manifest != manifest
        or row.content_hash != receipt.execution_scope_hash
        or not hmac.compare_digest(row.issuer_mac, mac)
    ):
        return None
    return _PreparedScope(receipt, {**review, "expected_review_hash": review_hash})


def _resolve(
    *,
    client_order_id: UUID,
    account_id: int,
    owner_user_id: int,
    using: str,
    mode: Literal["preview", "sign", "read"],
    expected_review_hash: str | None = None,
    selection: OrderMaterialSelector | None = None,
) -> _PreparedScope | None:
    try:
        return _locked_scope(
            client_order_id=client_order_id,
            account_id=account_id,
            owner_user_id=owner_user_id,
            using=using,
            mode=mode,
            expected_review_hash=expected_review_hash,
            selection=selection,
        )
    except (ValueError, RuntimeError) as error:
        # Owner ledgers raise typed ValueError/RuntimeError on corrupt or unavailable graphs.
        raise BrokerExecutionConflictError("broker_order_scope_sources_unavailable") from error


def read_current_order_execution_scope(
    *, client_order_id: UUID, account_id: int, owner_user_id: int, using: str
) -> OrderExecutionScopeReceipt | None:
    """Recompute the originally signed receipt under current source locks."""
    if using != "default" or not broker_order_evidence_integrated():
        return None
    result = _resolve(
        client_order_id=client_order_id,
        account_id=account_id,
        owner_user_id=owner_user_id,
        using=using,
        mode="read",
    )
    return None if result is None else result.receipt


def preview_order_scope(
    *,
    actor: Request,
    client_order_id: UUID,
    account_id: int,
    using: str,
    selection: OrderMaterialSelector | None = None,
) -> dict[str, object]:
    """Show the authenticated owner the exact economics and hash needed for consent."""
    if using != "default" or not broker_order_evidence_integrated():
        raise BrokerExecutionConflictError("broker_order_scope_issuance_closed")
    with order_scope_sources().signer(
        request=actor, using=using, before_commit=lambda: None
    ) as user:
        uid, _, _ = require_action(user, "approve")
        result = _resolve(
            client_order_id=client_order_id,
            account_id=account_id,
            owner_user_id=uid,
            using=using,
            mode="preview",
            selection=selection,
        )
        if result is None:
            raise BrokerExecutionConflictError("broker_order_scope_sources_unavailable")
        return result.review


def issue_order_execution_scope(
    *,
    actor: Request,
    client_order_id: UUID,
    account_id: int,
    expected_review_hash: str,
    using: str,
    selection: OrderMaterialSelector | None = None,
) -> OrderExecutionScopeReceipt:
    """Sign one prebuilt version under the authenticated owner's actual Session."""
    if using != "default" or not broker_order_evidence_integrated():
        raise BrokerExecutionConflictError("broker_order_scope_issuance_closed")
    signed: OrderExecutionScopeReceipt | None = None

    def verify_deadline() -> None:
        if signed is None or signed.valid_until <= _database_time(using):
            raise BrokerExecutionConflictError("broker_order_scope_expired")

    with order_scope_sources().signer(
        request=actor, using=using, before_commit=verify_deadline
    ) as user:
        owner_user_id, _, _ = require_action(user, "approve")
        prepared = _resolve(
            client_order_id=client_order_id,
            account_id=account_id,
            owner_user_id=owner_user_id,
            using=using,
            mode="sign",
            expected_review_hash=expected_review_hash,
            selection=selection,
        )
        if prepared is None:
            raise BrokerExecutionConflictError("broker_order_scope_sources_unavailable")
        signed = prepared.receipt
    return signed


def revoke_order_execution_scope(
    *,
    actor: Request,
    client_order_id: UUID,
    account_id: int,
    expected_content_hash: str,
    using: str,
) -> None:
    """Irrevocably cancel the owner's exact mandate even after an upstream expires."""
    with order_scope_sources().signer(
        request=actor, using=using, before_commit=lambda: None
    ) as user:
        row = (
            BrokerOrderExecutionScopeModel.objects.using(using)
            .select_for_update(nowait=True)
            .filter(
                client_order_id=client_order_id,
                account_id=account_id,
                owner_user_id=user.pk,
                content_hash=expected_content_hash,
            )
            .first()
        )
        if row is None:
            raise BrokerExecutionPermissionError("broker_order_scope_not_owned")
        if row.revoked_at is None:
            row.revoked_at = _database_time(using)
            row.save(using=using, update_fields=["revoked_at"])
