"""Prepare and explicitly confirm one owner's simulated dividend service consent."""

from __future__ import annotations

from typing import TypedDict
from uuid import uuid4

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction
from django.utils import timezone
from rest_framework.request import Request

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    SimulatedCorporateActionGrantConsent,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.account.simulated_corporate_action_consent_composition import (
    prepare_simulated_action_consent_token,
    prepare_simulated_action_withdrawal_token,
    read_current_simulated_action_consent_metadata,
    read_latest_simulated_action_withdrawal_metadata,
    restore_simulated_action_consent_token,
    restore_simulated_action_withdrawal_token,
)
from apps.account.simulated_corporate_action_policy_scope_composition import (
    read_current_simulated_action_write_policy,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    locked_simulated_action_trading_eligibility,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.execution_current_reference_composition import (
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import AuthorizationError


class SimulatedActionConsentPayload(TypedDict):
    """User-facing preparation or consent receipt; never an execution authorization."""

    account_id: int
    outcome: str
    consent_status: str
    summary: str
    blocking_reason: str | None
    source_observed_at: str | None
    source_valid_until: str | None
    consent_valid_until: str | None
    consent_token: str | None
    withdrawal_token: str | None
    grant_id: str | None
    grant_version: str | None
    grant_content_hash: str | None
    must_not_execute: bool


def _user_id(request: Request) -> int:
    """Accept only the actual authenticated positive user identity at this boundary."""
    identity: object = getattr(request.user, "pk", None)
    if request.user.is_authenticated is not True or type(identity) is not int or identity <= 0:
        raise AuthorizationError("Authenticated owner identity is required")
    return identity


def _empty(account_id: int) -> SimulatedActionConsentPayload:
    """Start with explicit unknown source clocks and a blocked preparation."""
    return {
        "account_id": account_id,
        "outcome": "blocked",
        "consent_status": "not_consented",
        "summary": "当前授权资料尚未核对完成。",
        "blocking_reason": "simulated_action_consent_unavailable",
        "source_observed_at": None,
        "source_valid_until": None,
        "consent_valid_until": None,
        "consent_token": None,
        "withdrawal_token": None,
        "grant_id": None,
        "grant_version": None,
        "grant_content_hash": None,
        "must_not_execute": True,
    }


def prepare_owner_simulated_action_consent(
    request: Request, *, account_id: int
) -> SimulatedActionConsentPayload:
    """Read current owner terms without issuing a grant or altering financial ledgers."""
    user_id = _user_id(request)
    if type(account_id) is not int or account_id <= 0:
        raise AuthorizationError("Owned simulated account is required")
    using = DEFAULT_DB_ALIAS
    if connections[using].vendor != "postgresql":
        raise SimulatedCorporateActionWriteGrantUnavailable("owner consent requires PostgreSQL")
    environment = get_simulated_execution_runtime_environment()
    payload = _empty(account_id)
    try:
        with transaction.atomic(using=using):
            eligible = True
            try:
                with locked_simulated_action_trading_eligibility(user_id=user_id, using=using):
                    pass
            except AuthorizationError:
                eligible = False
            row = (
                SimulatedAccountModel._base_manager.using(using)
                .select_for_update()
                .filter(pk=account_id, user_id=user_id, account_type="simulated")
                .first()
            )
            if row is None:
                raise AuthorizationError("This simulated account is not owned by the requester")
            repository = DjangoSimulatedAccountRowSourceV2Repository(using=using)
            repository.lock_current_sources_for_read()
            as_of = timezone.now()
            heads = repository.get_physical_account_heads(
                underlying_unified_account_id=account_id, as_of=as_of
            )
            if len(heads) != 1:
                payload["blocking_reason"] = "simulated_action_account_mapping_unavailable"
                return payload
            source = heads[0].source
            if (
                source.account_namespace != "account"
                or source.row_user_id != user_id
                or source.row_created_at != row.created_at
            ):
                payload["blocking_reason"] = "simulated_action_account_mapping_changed"
                return payload
            payload["source_observed_at"] = source.observed_at.isoformat()
            payload["source_valid_until"] = source.valid_until.isoformat()
            grant = read_current_simulated_action_consent_metadata(
                canonical_account_id=source.account_id,
                owner_user_id=user_id,
                as_of=as_of,
                using=using,
            )
            if grant is not None:
                origin = repository.get_exact_by_hash(
                    source_id=grant.binding.account_source_id,
                    source_version=grant.binding.account_source_version,
                    expected_content_hash=grant.binding.account_source_content_hash,
                    as_of=as_of,
                )
                if (
                    origin is None
                    or origin.source.account_namespace != "account"
                    or origin.source.account_id != source.account_id
                    or origin.source.underlying_unified_account_namespace != "simulated-account-row"
                    or origin.source.underlying_unified_account_id != account_id
                    or origin.source.row_user_id != user_id
                    or origin.source.row_created_at != row.created_at
                ):
                    raise SimulatedCorporateActionWriteGrantUnavailable(
                        "stored consent does not belong to this physical account"
                    )
                payload.update(
                    {
                        "outcome": "success",
                        "consent_status": "active",
                        "summary": "已有有限期的现金分红模拟入账授权，可随时撤销。",
                        "blocking_reason": None,
                        "consent_valid_until": grant.valid_until.isoformat(),
                        "grant_id": grant.grant_id,
                        "grant_version": grant.grant_version,
                        "grant_content_hash": grant.content_hash,
                        "withdrawal_token": prepare_simulated_action_withdrawal_token(
                            grant, physical_account_id=account_id
                        ),
                    }
                )
            if not eligible:
                payload["outcome"] = "blocked"
                payload["blocking_reason"] = "simulated_action_trading_role_required"
                payload["summary"] = "当前角色不能新增模拟入账授权。"
                return payload
            if (
                row.is_active is not True
                or not source.is_current_at(as_of)
                or source.raw_account_type != "simulated"
                or source.row_updated_at != row.updated_at
            ):
                payload["outcome"] = "blocked"
                payload["blocking_reason"] = "simulated_action_account_source_refresh_required"
                payload["summary"] = "请先核对并刷新该模拟账户的归属资料。"
                return payload
            policy = read_current_simulated_action_write_policy(
                canonical_account_id=source.account_id,
                owner_user_id=user_id,
                environment=environment,
                as_of=as_of,
            )
            binding = SimulatedCorporateActionWriteGrantBinding(
                account_namespace="simulated",
                account_id=source.account_id,
                owner_user_id=user_id,
                tenant_id=policy.tenant_id,
                owner_id=policy.owner_id,
                account_source_id=source.source_id,
                account_source_version=source.source_version,
                account_source_content_hash=source.content_hash,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_content_hash=policy.content_hash,
            )
            if grant is not None:
                if grant.binding != binding:
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_consent_basis_changed"
                    payload["summary"] = "该授权所依据的资料已更新，请撤销后重新核对并明确同意。"
                return payload
            valid_until = policy.grant_valid_until(
                as_of=as_of,
                source_valid_until=source.valid_until,
            )
            command = SimulatedCorporateActionGrantConsent(
                grant_id=f"owner-simulated-action-{uuid4().hex}",
                grant_version="1",
                physical_account_id=account_id,
                expected_binding=binding,
                valid_until=valid_until,
                consent=True,
            )
            payload.update(
                {
                    "outcome": "success",
                    "consent_status": "awaiting_confirmation",
                    "summary": "确认后，服务可在有效期内为本账户核对并记录现金分红模拟权益和模拟到账。",
                    "blocking_reason": None,
                    "consent_valid_until": valid_until.isoformat(),
                    "consent_token": prepare_simulated_action_consent_token(command, as_of=as_of),
                }
            )
            return payload
    except (
        SimulatedAccountRowSourceV2Unavailable,
        SimulatedAccountRowSourceV2Corruption,
        SimulatedAccountRowSourceV2Conflict,
    ) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "owner account source is unavailable"
        ) from error
    except (ValueError, OverflowError):
        payload["outcome"] = "blocked"
        payload["blocking_reason"] = "simulated_action_service_policy_unavailable"
        payload["summary"] = "缺少当前有效且范围明确的模拟入账政策，请先完成配置核对。"
        return payload
    except DatabaseError as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "owner consent data is unavailable"
        ) from error


def prepare_owner_simulated_action_withdrawal(
    request: Request, *, account_id: int
) -> SimulatedActionConsentPayload:
    """Prepare only withdrawal; loss of trading eligibility cannot prevent removing consent."""
    user_id = _user_id(request)
    if type(account_id) is not int or account_id <= 0:
        raise AuthorizationError("Owned simulated account is required")
    using = DEFAULT_DB_ALIAS
    if connections[using].vendor != "postgresql":
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "withdrawal discovery requires PostgreSQL"
        )
    payload = _empty(account_id)
    with transaction.atomic(using=using):
        row = (
            SimulatedAccountModel._base_manager.using(using)
            .select_for_update()
            .filter(pk=account_id, user_id=user_id, account_type="simulated")
            .first()
        )
        if row is None:
            raise AuthorizationError("This simulated account is not owned by the requester")
        repository = DjangoSimulatedAccountRowSourceV2Repository(using=using)
        repository.lock_current_sources_for_read()
        as_of = timezone.now()
        heads = repository.get_physical_account_heads(
            underlying_unified_account_id=account_id, as_of=as_of
        )
        if len(heads) != 1 or heads[0].source.account_namespace != "account":
            payload["blocking_reason"] = "simulated_action_account_mapping_unavailable"
            return payload
        source = heads[0].source
        payload["source_observed_at"] = source.observed_at.isoformat()
        payload["source_valid_until"] = source.valid_until.isoformat()
        record = read_latest_simulated_action_withdrawal_metadata(
            canonical_account_id=source.account_id, owner_user_id=user_id, as_of=as_of, using=using
        )
        if record is None:
            payload.update(
                {
                    "outcome": "noop",
                    "blocking_reason": None,
                    "summary": "当前未发现本人尚未撤销的授权记录。",
                }
            )
            return payload
        grant = record.grant
        origin = repository.get_historical_exact_metadata(
            source_id=grant.binding.account_source_id,
            source_version=grant.binding.account_source_version,
            expected_content_hash=grant.binding.account_source_content_hash,
            as_of=as_of,
        )
        if (
            origin is None
            or origin.source.account_namespace != "account"
            or origin.source.account_id != source.account_id
            or origin.source.underlying_unified_account_namespace != "simulated-account-row"
            or origin.source.underlying_unified_account_id != account_id
            or origin.source.row_user_id != user_id
            or origin.source.row_created_at != row.created_at
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "historical consent has another physical account"
            )
        payload.update(
            {
                "outcome": "success",
                "blocking_reason": None,
                "consent_status": "expired" if as_of >= grant.valid_until else "stored",
                "summary": "已找到本人尚未撤销的原授权，请核对后明确撤销；准备不会延长原授权期限。",
                "consent_valid_until": grant.valid_until.isoformat(),
                "grant_id": grant.grant_id,
                "grant_version": grant.grant_version,
                "grant_content_hash": grant.content_hash,
                "withdrawal_token": prepare_simulated_action_withdrawal_token(
                    grant, physical_account_id=account_id
                ),
            }
        )
        return payload


def confirm_owner_simulated_action_consent(
    request: Request, *, account_id: int, consent_token: str, confirmed: bool
) -> SimulatedActionConsentPayload:
    """Authenticate explicit confirmation of the exact displayed finite terms."""
    command = restore_simulated_action_consent_token(
        consent_token,
        owner_user_id=_user_id(request),
        physical_account_id=account_id,
        confirmed=confirmed,
        as_of=timezone.now(),
    )
    environment = get_simulated_execution_runtime_environment()
    grant = issue_authenticated_simulated_corporate_action_grant(
        request,
        command=command,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias=DEFAULT_DB_ALIAS, runtime_environment=environment
        ),
        using=DEFAULT_DB_ALIAS,
    )
    payload = _empty(account_id)
    payload.update(
        {
            "outcome": "success",
            "consent_status": "active",
            "blocking_reason": None,
            "summary": "现金分红模拟入账授权已保存；本次操作仅保存授权。",
            "consent_valid_until": grant.valid_until.isoformat(),
            "grant_id": grant.grant_id,
            "grant_version": grant.grant_version,
            "grant_content_hash": grant.content_hash,
            "withdrawal_token": prepare_simulated_action_withdrawal_token(
                grant, physical_account_id=account_id
            ),
        }
    )
    return payload


def withdraw_owner_simulated_action_consent(
    request: Request, *, account_id: int, withdrawal_token: str, confirmed: bool
) -> SimulatedActionConsentPayload:
    """Withdraw an exact stored consent even after its source or policy becomes unavailable."""
    if confirmed is not True:
        raise AuthorizationError("Explicit withdrawal confirmation is required")
    selector = restore_simulated_action_withdrawal_token(
        withdrawal_token, owner_user_id=_user_id(request), physical_account_id=account_id
    )
    revoke_authenticated_simulated_corporate_action_grant(
        request,
        selector=selector,
        revocation_id=f"owner-withdrawal-{selector.content_hash}",
        revocation_version="1",
        using=DEFAULT_DB_ALIAS,
    )
    payload = _empty(account_id)
    payload.update(
        {
            "outcome": "success",
            "consent_status": "revoked",
            "blocking_reason": None,
            "summary": "该次模拟入账授权已撤销。",
            "grant_id": selector.grant_id,
            "grant_version": selector.grant_version,
            "grant_content_hash": selector.content_hash,
        }
    )
    return payload
