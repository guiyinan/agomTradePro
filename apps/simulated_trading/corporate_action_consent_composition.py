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
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
    validate_simulated_corporate_action_write_capabilities,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.account.simulated_corporate_action_consent_composition import (
    prepare_simulated_action_consent_token,
    prepare_simulated_action_withdrawal_token,
    read_current_simulated_action_consent_metadata,
    read_exact_simulated_action_withdrawal_metadata,
    read_latest_simulated_action_withdrawal_metadata,
    restore_simulated_action_consent_token,
    restore_simulated_action_withdrawal_token,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SimulatedCorporateActionConsentTerms,
    require_simulated_corporate_action_consent_terms,
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
from core.exceptions import AuthorizationError, ConfigurationError


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
    grant_schema: str | None
    selected_capabilities: list[str]
    capability_labels: list[str]
    terms_version: str | None
    terms_sha256: str | None
    terms_text: str
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
        "grant_schema": None,
        "selected_capabilities": [],
        "capability_labels": [],
        "terms_version": None,
        "terms_sha256": None,
        "terms_text": "",
        "must_not_execute": True,
    }


def _requested_capabilities(
    *,
    grant_schema: str | None,
    requested: tuple[SimulatedCorporateActionWriteCapability, ...] | None,
) -> tuple[SimulatedCorporateActionWriteCapability, ...] | None:
    """Validate explicit choices before selecting the configured grant schema."""
    if grant_schema is None:
        if requested is None:
            raise ValueError("policy discovery requires an explicit capability choice")
        try:
            return validate_simulated_corporate_action_write_capabilities(requested)
        except (TypeError, ValueError) as error:
            raise ValueError("discovered consent capability set is invalid") from error
    if type(grant_schema) is not str:
        raise ValueError("simulated action grant schema is invalid")
    if grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
        if requested is not None:
            raise ValueError("V1 consent cannot select V2 capabilities")
        return None
    if grant_schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA or requested is None:
        raise ValueError("V2 consent requires an explicit supported capability set")
    try:
        return validate_simulated_corporate_action_write_capabilities(requested)
    except (TypeError, ValueError) as error:
        raise ValueError("V2 consent capability set is invalid") from error


def _v2_display_fields(
    *,
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...],
    terms: SimulatedCorporateActionConsentTerms,
) -> tuple[list[str], list[str], str]:
    """Build separate machine capability codes and human-readable consent text."""
    selected = validate_simulated_corporate_action_write_capabilities(capabilities)
    labels = {item.code: item.title for item in terms.capabilities}
    try:
        selected_labels = [labels[item.value] for item in selected]
    except KeyError as error:
        raise ValueError("pinned terms omit a selected capability") from error
    text = "\n\n".join(
        (
            terms.introduction,
            *(f"{item.title}\n{item.description}" for item in terms.capabilities),
            "授权范围与限制：\n" + "\n".join(terms.general_limits),
        )
    )
    return [item.value for item in selected], selected_labels, text


def _apply_v2_display(
    payload: SimulatedActionConsentPayload,
    *,
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...],
    terms: SimulatedCorporateActionConsentTerms,
) -> None:
    """Attach complete offered terms and a separately selected capability subset."""
    codes, labels, text = _v2_display_fields(capabilities=capabilities, terms=terms)
    payload.update(
        {
            "grant_schema": SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            "selected_capabilities": codes,
            "capability_labels": labels,
            "terms_version": terms.version,
            "terms_sha256": terms.sha256,
            "terms_text": text,
        }
    )


def _active_v2_summary(labels: list[str]) -> str:
    """Describe the exact active V2 capability selection without protocol codes."""
    return f"已有有限期的模拟授权，所选能力包括：{'、'.join(labels)}；可随时撤销。"


def _apply_historical_v2_display(
    payload: SimulatedActionConsentPayload, *, grant: SimulatedCorporateActionWriteGrant
) -> None:
    """Preserve withdrawal scope even when its old terms are no longer readable."""
    if grant.schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        return
    if grant.capabilities is None:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "historical V2 capabilities are missing"
        )
    payload["grant_schema"] = grant.schema
    payload["selected_capabilities"] = [item.value for item in grant.capabilities]
    if grant.terms_version is None or grant.terms_sha256 is None:
        return
    try:
        terms = require_simulated_corporate_action_consent_terms(
            grant.terms_version, grant.terms_sha256
        )
    except ConfigurationError:
        return
    _apply_v2_display(payload, capabilities=grant.capabilities, terms=terms)


def _scope_block_summary(payload: SimulatedActionConsentPayload, message: str) -> str:
    """Retain an existing V2 grant's human-readable scope in blocked responses."""
    if payload["grant_schema"] != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        return message
    labels = payload["capability_labels"]
    if labels:
        return f"现有授权所选能力：{'、'.join(labels)}。{message}"
    return f"现有分项授权条款暂时无法核对。{message}"


def _apply_active_grant_payload(
    payload: SimulatedActionConsentPayload,
    *,
    grant: SimulatedCorporateActionWriteGrant,
    physical_account_id: int,
) -> None:
    """Display the exact stored grant and keep its independent withdrawal locator."""
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
                grant, physical_account_id=physical_account_id
            ),
        }
    )
    if grant.schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        return
    if grant.capabilities is None:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "active V2 grant has no explicit capabilities"
        )
    payload["grant_schema"] = grant.schema
    payload["selected_capabilities"] = [item.value for item in grant.capabilities]
    if grant.terms_version is None or grant.terms_sha256 is None:
        payload.update(
            {
                "outcome": "blocked",
                "blocking_reason": "simulated_action_consent_terms_unavailable",
                "summary": "已有有限期的分项模拟授权；条款暂时无法核对，但仍可撤销。",
            }
        )
        return
    try:
        terms = require_simulated_corporate_action_consent_terms(
            grant.terms_version, grant.terms_sha256
        )
    except ConfigurationError:
        payload.update(
            {
                "outcome": "blocked",
                "blocking_reason": "simulated_action_consent_terms_unavailable",
                "summary": "已有有限期的分项模拟授权；条款暂时无法核对，但仍可撤销。",
            }
        )
        return
    _apply_v2_display(payload, capabilities=grant.capabilities, terms=terms)
    payload["summary"] = _active_v2_summary(payload["capability_labels"])


def _same_grant_owner_chain(
    grant: SimulatedCorporateActionWriteGrant,
    binding: SimulatedCorporateActionWriteGrantBinding,
) -> bool:
    """Allow version successors only inside the stable owner/account/tenant chain."""
    previous = grant.binding
    return (
        grant.service_actor_id == SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        and previous.account_namespace == binding.account_namespace == "simulated"
        and previous.account_id == binding.account_id
        and previous.owner_user_id == binding.owner_user_id
        and previous.tenant_id == binding.tenant_id
        and previous.owner_id == binding.owner_id
    )


def prepare_owner_simulated_action_consent(
    request: Request,
    *,
    account_id: int,
    grant_schema: str | None = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    requested_capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None,
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
    selected_capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None
    invalid_selection = False
    try:
        selected_capabilities = _requested_capabilities(
            grant_schema=grant_schema,
            requested=requested_capabilities,
        )
    except (TypeError, ValueError):
        invalid_selection = True
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
                _apply_active_grant_payload(
                    payload,
                    grant=grant,
                    physical_account_id=account_id,
                )
            active_v2_status_read = (
                grant is not None
                and grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
                and grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
            )
            if not eligible:
                payload["outcome"] = "blocked"
                payload["blocking_reason"] = "simulated_action_trading_role_required"
                payload["summary"] = _scope_block_summary(payload, "当前角色不能新增模拟入账授权。")
                return payload
            if (
                row.is_active is not True
                or not source.is_current_at(as_of)
                or source.raw_account_type != "simulated"
                or source.row_updated_at != row.updated_at
            ):
                payload["outcome"] = "blocked"
                payload["blocking_reason"] = "simulated_action_account_source_refresh_required"
                payload["summary"] = _scope_block_summary(
                    payload, "请先核对并刷新该模拟账户的归属资料。"
                )
                return payload
            if invalid_selection:
                payload["outcome"] = "blocked"
                payload["blocking_reason"] = "simulated_action_consent_selection_invalid"
                payload["summary"] = _scope_block_summary(
                    payload, "授权版本或明确选择的能力无效，未准备新的授权。"
                )
                return payload
            policy_schema = (
                grant.schema if active_v2_status_read and grant is not None else grant_schema
            )
            policy = read_current_simulated_action_write_policy(
                canonical_account_id=source.account_id,
                owner_user_id=user_id,
                environment=environment,
                as_of=as_of,
                expected_grant_schema=policy_schema,
            )
            if policy_schema is not None and policy.grant_schema != policy_schema:
                raise ValueError("current service policy differs from requested grant schema")
            selected_grant_schema = policy.grant_schema
            command_capabilities = selected_capabilities
            if (
                grant_schema is None
                and selected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
            ):
                if selected_capabilities != (
                    SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
                ):
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_consent_capability_not_permitted"
                    payload["summary"] = _scope_block_summary(
                        payload,
                        "当前政策仅支持现金分红模拟权益与模拟到账，未准备所选税务能力。",
                    )
                    return payload
                command_capabilities = None
            terms: SimulatedCorporateActionConsentTerms | None = None
            if active_v2_status_read:
                if (
                    grant is None
                    or grant.capabilities is None
                    or policy.capabilities is None
                    or policy.terms_version is None
                    or policy.terms_sha256 is None
                ):
                    raise ValueError("current V2 grant and policy terms are required")
                try:
                    terms = require_simulated_corporate_action_consent_terms(
                        policy.terms_version,
                        policy.terms_sha256,
                    )
                except ConfigurationError:
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_service_policy_unavailable"
                    payload["summary"] = _scope_block_summary(
                        payload, "授权条款版本无法核对，当前授权不能用于新增操作。"
                    )
                    return payload
            elif selected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
                if selected_capabilities is None or policy.capabilities is None:
                    raise ValueError("V2 policy and explicit capability selection are required")
                if not set(selected_capabilities).issubset(policy.capabilities):
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_consent_capability_not_permitted"
                    payload["summary"] = _scope_block_summary(
                        payload, "当前政策不允许全部所选能力，未准备新的授权。"
                    )
                    return payload
                if policy.terms_version is None or policy.terms_sha256 is None:
                    raise ValueError("V2 service policy terms are missing")
                try:
                    terms = require_simulated_corporate_action_consent_terms(
                        policy.terms_version,
                        policy.terms_sha256,
                    )
                except ConfigurationError:
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_service_policy_unavailable"
                    payload["summary"] = _scope_block_summary(
                        payload, "授权条款版本无法核对，未准备新的授权。"
                    )
                    return payload
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
            if active_v2_status_read:
                if (
                    grant is None
                    or grant.capabilities is None
                    or policy.capabilities is None
                    or terms is None
                    or grant.binding != binding
                    or grant.terms_version != terms.version
                    or grant.terms_sha256 != terms.sha256
                    or not set(grant.capabilities).issubset(policy.capabilities)
                ):
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_consent_basis_changed"
                    payload["summary"] = _scope_block_summary(
                        payload, "当前政策或账户资料已变化，请选择所需能力并重新核对授权。"
                    )
                return payload
            if grant is not None:
                same_exact_scope = (
                    grant.schema == selected_grant_schema
                    and grant.binding == binding
                    and (
                        selected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
                        or (
                            selected_grant_schema
                            == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
                            and grant.capabilities == selected_capabilities
                            and terms is not None
                            and grant.terms_version == terms.version
                            and grant.terms_sha256 == terms.sha256
                        )
                    )
                )
                if same_exact_scope:
                    return payload
                if selected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_consent_basis_changed"
                    payload["summary"] = "该授权所依据的资料已更新，请撤销后重新核对并明确同意。"
                    return payload
                if not _same_grant_owner_chain(grant, binding):
                    payload["outcome"] = "blocked"
                    payload["blocking_reason"] = "simulated_action_consent_chain_scope_changed"
                    payload["summary"] = _scope_block_summary(
                        payload, "账户所有者或租户范围已变化，不能续接原授权链。"
                    )
                    return payload
            valid_until = policy.grant_valid_until(
                as_of=as_of,
                source_valid_until=source.valid_until,
            )
            predecessor_hash = grant.content_hash if grant is not None else None
            command = SimulatedCorporateActionGrantConsent(
                grant_id=(
                    grant.grant_id if grant is not None else f"owner-simulated-action-{uuid4().hex}"
                ),
                grant_version=uuid4().hex if grant is not None else "1",
                physical_account_id=account_id,
                expected_binding=binding,
                valid_until=valid_until,
                consent=True,
                expected_predecessor_content_hash=predecessor_hash,
                grant_schema=selected_grant_schema,
                capabilities=command_capabilities,
                terms_version=terms.version if terms is not None else None,
                terms_sha256=terms.sha256 if terms is not None else None,
            )
            consent_token = prepare_simulated_action_consent_token(command, as_of=as_of)
            if selected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
                if selected_capabilities is None or terms is None:
                    raise ValueError("V2 consent document is unavailable")
                _apply_v2_display(
                    payload,
                    capabilities=selected_capabilities,
                    terms=terms,
                )
                labels = payload["capability_labels"]
                summary = (
                    "确认后，本账户将在有限有效期内获得所选模拟能力："
                    f"{'、'.join(labels)}。本次仅准备授权，不会立即执行。"
                )
                if grant is not None:
                    summary = (
                        "确认后，将以本次选择替换原授权范围："
                        f"{'、'.join(labels)}。请核对新有效期；本次仅准备授权，不会立即执行。"
                    )
            else:
                summary = "确认后，服务可在有效期内为本账户核对并记录现金分红模拟权益和模拟到账。"
            payload.update(
                {
                    "outcome": "success",
                    "consent_status": "awaiting_confirmation",
                    "summary": summary,
                    "blocking_reason": None,
                    "consent_valid_until": valid_until.isoformat(),
                    "consent_token": consent_token,
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
        payload["summary"] = _scope_block_summary(
            payload, "缺少当前有效且范围明确的模拟入账政策，请先完成配置核对。"
        )
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
        _apply_historical_v2_display(payload, grant=grant)
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
    terms: SimulatedCorporateActionConsentTerms | None = None
    if command.grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        if command.terms_version is None or command.terms_sha256 is None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "confirmed V2 consent has no exact terms identity"
            )
        try:
            terms = require_simulated_corporate_action_consent_terms(
                command.terms_version,
                command.terms_sha256,
            )
        except ConfigurationError as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "confirmed consent terms are unavailable"
            ) from error
    environment = get_simulated_execution_runtime_environment()
    grant = issue_authenticated_simulated_corporate_action_grant(
        request,
        command=command,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias=DEFAULT_DB_ALIAS, runtime_environment=environment
        ),
        using=DEFAULT_DB_ALIAS,
    )
    if (
        grant.grant_id != command.grant_id
        or grant.grant_version != command.grant_version
        or grant.schema != command.grant_schema
        or grant.binding != command.expected_binding
        or grant.capabilities != command.capabilities
        or grant.terms_version != command.terms_version
        or grant.terms_sha256 != command.terms_sha256
        or grant.supersedes_content_hash != command.expected_predecessor_content_hash
        or grant.valid_until != command.valid_until
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "issued grant differs from the exact confirmed consent"
        )
    payload = _empty(account_id)
    summary = "现金分红模拟入账授权已保存；本次操作仅保存授权。"
    if grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        if grant.capabilities is None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "issued V2 grant has no explicit capabilities"
            )
        if terms is None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "confirmed V2 consent terms are unavailable"
            )
        _apply_v2_display(payload, capabilities=grant.capabilities, terms=terms)
        summary = (
            "所选模拟能力授权已保存："
            f"{'、'.join(payload['capability_labels'])}。本次操作仅保存授权；可随时撤销。"
        )
    payload.update(
        {
            "outcome": "success",
            "consent_status": "active",
            "blocking_reason": None,
            "summary": summary,
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
    grant = read_exact_simulated_action_withdrawal_metadata(
        selector=selector, as_of=timezone.now(), using=DEFAULT_DB_ALIAS
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
            "summary": "该次模拟公司行为授权已撤销。",
            "grant_id": selector.grant_id,
            "grant_version": selector.grant_version,
            "grant_content_hash": selector.content_hash,
        }
    )
    _apply_historical_v2_display(payload, grant=grant)
    return payload
