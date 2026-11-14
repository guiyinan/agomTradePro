"""Read one actual owner's account mapping before preparing simulated actions."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone
from rest_framework.request import Request

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrant,
)
from apps.account.simulated_corporate_action_consent_composition import (
    read_current_simulated_action_consent_metadata,
)
from apps.account.simulated_corporate_action_current_grant_composition import (
    locked_current_simulated_corporate_action_write_grant,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    locked_simulated_action_trading_eligibility,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.execution_current_reference_composition import (
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from core.exceptions import AuthorizationError, BusinessLogicError


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionAccount:
    """Owner-scoped preparation facts; financial writes must recheck their own locks."""

    account_id: int
    owner_user_id: int
    source: SimulatedAccountRowSourceV2
    grant: SimulatedCorporateActionWriteGrant | None
    asset_codes: tuple[str, ...]
    checked_at: datetime
    preparation_valid_until: datetime | None
    source_matches_physical_row: bool
    grant_metadata_unavailable: bool


def _blocked(code: str) -> BusinessLogicError:
    return BusinessLogicError("当前账户资料或分项授权需要重新核对。", code=code)


def read_owner_corporate_action_confirmation_owner(request: Request, *, account_id: int) -> int:
    """Bind a confirmation to its actual session owner, without issuing write authority.

    The audited executor must independently acquire its financial locks and
    validate current role, grant, mapping and source. This preflight deliberately
    does not read or cache any of those authorization facts.
    """
    owner: object = getattr(request.user, "pk", None)
    if (
        request.user.is_authenticated is not True
        or request.user.is_active is not True
        or type(owner) is not int
        or owner <= 0
        or type(account_id) is not int
        or account_id <= 0
    ):
        raise AuthorizationError("需要本人已登录的模拟账户。")
    using = DEFAULT_DB_ALIAS
    if connections[using].vendor != "postgresql":
        raise _blocked("CORPORATE_ACTION_POSTGRES_REQUIRED")
    with transaction.atomic(using=using):
        owned = (
            SimulatedAccountModel._base_manager.using(using)
            .select_for_update()
            .filter(pk=account_id, user_id=owner, account_type="simulated", is_active=True)
            .values_list("pk", flat=True)
            .first()
        )
        if owned is None:
            raise AuthorizationError("仅可查看和操作本人启用中的模拟账户。")
    return owner


def _read_owner_grant_metadata(
    *,
    canonical_account_id: str,
    owner_user_id: int,
    as_of: datetime,
    using: str,
    required_capability: SimulatedCorporateActionWriteCapability | None,
) -> tuple[SimulatedCorporateActionWriteGrant | None, bool]:
    """Keep historical owner reads independent of current seal availability."""
    try:
        return (
            read_current_simulated_action_consent_metadata(
                canonical_account_id=canonical_account_id,
                owner_user_id=owner_user_id,
                as_of=as_of,
                using=using,
            ),
            False,
        )
    except SimulatedCorporateActionWriteGrantUnavailable:
        if required_capability is not None:
            raise
        return None, True


def read_owner_corporate_action_account(
    request: Request,
    *,
    account_id: int,
    capability: SimulatedCorporateActionWriteCapability | None = None,
    require_current_source: bool = False,
) -> OwnerCorporateActionAccount:
    """Read actual ownership and retained security scope without granting write authority.

    Preparation requires current row evidence. Confirmation deliberately leaves
    exact-replay source exceptions to the audited financial scope, which verifies
    the original receipt and still checks current owner, role and consent.
    """
    owner: object = getattr(request.user, "pk", None)
    if (
        request.user.is_authenticated is not True
        or type(owner) is not int
        or owner <= 0
        or type(account_id) is not int
        or account_id <= 0
    ):
        raise AuthorizationError("需要本人已登录的模拟账户。")
    using = DEFAULT_DB_ALIAS
    if connections[using].vendor != "postgresql":
        raise _blocked("CORPORATE_ACTION_POSTGRES_REQUIRED")
    if capability is not None and type(capability) is not SimulatedCorporateActionWriteCapability:
        raise ValueError("corporate action capability must be exact")
    with transaction.atomic(using=using):
        eligibility = (
            locked_simulated_action_trading_eligibility(user_id=owner, using=using)
            if capability is not None
            else nullcontext()
        )
        with eligibility:
            row = (
                SimulatedAccountModel._base_manager.using(using)
                .select_for_update()
                .filter(pk=account_id, user_id=owner, account_type="simulated", is_active=True)
                .first()
            )
            if row is None:
                raise AuthorizationError("仅可查看和操作本人启用中的模拟账户。")
            repository = DjangoSimulatedAccountRowSourceV2Repository(using=using)
            repository.lock_current_sources_for_read()
            observed = timezone.now()
            heads = repository.get_physical_account_heads(
                underlying_unified_account_id=account_id, as_of=observed
            )
            if len(heads) != 1:
                raise _blocked("CORPORATE_ACTION_ACCOUNT_MAPPING_UNAVAILABLE")
            source = heads[0].source
            source.__post_init__()
            if (
                source.account_namespace != "account"
                or source.underlying_unified_account_namespace != "simulated-account-row"
                or source.underlying_unified_account_id != account_id
                or source.row_user_id != owner
                or source.raw_account_type != "simulated"
                or source.row_created_at != row.created_at
                or source.row_updated_at > row.updated_at
                or source.is_active is not True
                or source.is_present is not True
                or source.is_tombstone is not False
            ):
                raise _blocked("CORPORATE_ACTION_ACCOUNT_MAPPING_CHANGED")
            grant, grant_metadata_unavailable = _read_owner_grant_metadata(
                canonical_account_id=source.account_id,
                owner_user_id=owner,
                as_of=observed,
                using=using,
                required_capability=capability,
            )
            if capability is not None and (
                grant is None
                or grant.schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
                or not grant.supports_capability(capability)
                or not grant.is_active_at(observed)
            ):
                raise _blocked("CORPORATE_ACTION_SELECTED_CAPABILITY_REQUIRED")
            preparation_valid_until: datetime | None = None
            if capability is not None:
                if grant is None:
                    raise _blocked("CORPORATE_ACTION_SELECTED_CAPABILITY_REQUIRED")
                locker = DjangoSimulatedCorporateActionWriteScopeLocker(
                    database_alias=using,
                    runtime_environment=get_simulated_execution_runtime_environment(),
                )
                with locker.lock_owned_scope(
                    physical_account_id=account_id,
                    owner_user_id=owner,
                    expected_binding=grant.binding,
                    expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
                ) as scope:
                    with locked_current_simulated_corporate_action_write_grant(
                        selector=grant.selector, using=using, required_capability=capability
                    ) as current:
                        if current != grant:
                            raise _blocked("CORPORATE_ACTION_CONSENT_CHANGED")
                        preparation_valid_until = min(
                            source.valid_until, scope.valid_until, grant.valid_until
                        )
            codes = set(
                PositionModel._base_manager.using(using)
                .filter(account_id=account_id)
                .values_list("asset_code", flat=True)
            )
            codes.update(
                SimulatedTradeModel._base_manager.using(using)
                .filter(account_id=account_id, status="executed")
                .values_list("asset_code", flat=True)
            )
            codes.update(
                CorporateActionPostingModel._base_manager.using(using)
                .filter(account_id=account_id)
                .values_list("asset_code", flat=True)
            )
        checked = timezone.now()
        if checked < observed:
            raise _blocked("CORPORATE_ACTION_PREPARATION_CLOCK_CHANGED")
        if require_current_source and (
            source.row_updated_at != row.updated_at or not source.is_current_at(checked)
        ):
            raise _blocked("CORPORATE_ACTION_ACCOUNT_REFRESH_REQUIRED")
        if preparation_valid_until is not None and checked >= preparation_valid_until:
            raise _blocked("CORPORATE_ACTION_PREPARATION_EXPIRED")
        return OwnerCorporateActionAccount(
            account_id,
            owner,
            source,
            grant,
            tuple(sorted(codes)),
            checked,
            preparation_valid_until,
            source.row_updated_at == row.updated_at,
            grant_metadata_unavailable,
        )
