"""Read existing explicit baseline rows without creating fallback records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol, cast

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.db.models import Q
from django.utils.connection import ConnectionDoesNotExist

from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicyReadResult,
)
from apps.risk_center.domain.portfolio_baseline_risk import (
    BaselineRiskException,
    BaselineRiskParameters,
    PortfolioBaselinePolicy,
    resolve_portfolio_baseline_parameters,
)
from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskExceptionModel,
    RiskTemplateModel,
)


class _PersistedRow(Protocol):
    """A selected row with a database-generated integer primary key."""

    pk: int | None


class _RiskParameterSource(_PersistedRow, Protocol):
    """Only the columns used from the three existing parameter row models."""

    created_at: datetime
    updated_at: datetime
    max_total_position_pct: object
    max_single_position_pct: object
    min_cash_pct: object
    hard_exclusions: object


class DjangoPortfolioBaselinePolicyReader:
    """Qualify actual floor/template/account/exception rows at a server cutoff."""

    def __init__(self, *, using: str) -> None:
        """Use the same explicit database alias as simulated execution."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using

    def read_baseline_policy(
        self, *, account_id: int, as_of: datetime
    ) -> PortfolioBaselinePolicyReadResult:
        """Read real rows only; missing or ambiguous configuration stays unknown."""

        if type(account_id) is not int or account_id <= 0:
            return _unavailable("PORTFOLIO_BASELINE_ACCOUNT_ID_INVALID")
        if not _is_aware(as_of):
            return _unavailable("PORTFOLIO_BASELINE_CUTOFF_INVALID")
        try:
            return self._read_existing_rows(account_id=account_id, as_of=as_of)
        except (DatabaseError, ImproperlyConfigured, ConnectionDoesNotExist):
            return _unavailable("PORTFOLIO_BASELINE_DATABASE_UNAVAILABLE")

    def _read_existing_rows(
        self, *, account_id: int, as_of: datetime
    ) -> PortfolioBaselinePolicyReadResult:
        floors = tuple(
            GlobalRiskFloorModel.objects.using(self._using)
            .filter(is_active=True)
            .order_by("pk")[:2]
        )
        if len(floors) != 1:
            return _unavailable("PORTFOLIO_BASELINE_FLOOR_MISSING_OR_AMBIGUOUS")

        account = (
            AccountRiskPolicyModel.objects.using(self._using)
            .select_related("template")
            .filter(account_id=account_id, is_active=True)
            .first()
        )
        if account is None:
            return _unavailable("PORTFOLIO_BASELINE_ACCOUNT_POLICY_MISSING")

        template = account.template
        if template is None and account.risk_profile:
            templates = tuple(
                RiskTemplateModel.objects.using(self._using)
                .filter(risk_profile=account.risk_profile, is_active=True)
                .order_by("pk")[:2]
            )
            if len(templates) == 1:
                template = templates[0]
            elif len(templates) > 1:
                return _unavailable("PORTFOLIO_BASELINE_TEMPLATE_MISSING_OR_AMBIGUOUS")
        if template is None or not template.is_active:
            return _unavailable("PORTFOLIO_BASELINE_TEMPLATE_MISSING_OR_AMBIGUOUS")

        exceptions = tuple(
            RiskExceptionModel.objects.using(self._using)
            .filter(
                (Q(account_id=account_id) | Q(account_id__isnull=True)),
                is_active=True,
                expires_at__gt=as_of,
                field_name__in=(
                    "max_total_position_pct",
                    "max_single_position_pct",
                    "min_cash_pct",
                    "hard_exclusions",
                ),
            )
            .order_by("pk")
        )
        floor = floors[0]
        clocks = (
            floor.created_at,
            floor.updated_at,
            account.created_at,
            account.updated_at,
            template.created_at,
            template.updated_at,
            *(clock for row in exceptions for clock in (row.created_at, row.updated_at)),
        )
        if any(not _is_aware(clock) for clock in clocks):
            return _unavailable("PORTFOLIO_BASELINE_SOURCE_CLOCK_UNKNOWN")
        if any(clock > as_of for clock in clocks):
            return _unavailable("PORTFOLIO_BASELINE_SOURCE_AFTER_CUTOFF")
        if any(not _is_aware(row.expires_at) for row in exceptions):
            return _unavailable("PORTFOLIO_BASELINE_EXCEPTION_CLOCK_UNKNOWN")

        try:
            parsed_exceptions = tuple(_exception(row) for row in exceptions)
            resolved = resolve_portfolio_baseline_parameters(
                template=_parameters(cast(_RiskParameterSource, template)),
                overrides=_parameters(cast(_RiskParameterSource, account)),
                floor=_parameters(cast(_RiskParameterSource, floor)),
                exceptions=parsed_exceptions,
            )
            material = _binding_material(
                account_id=account_id,
                floor=floor,
                account=account,
                template=template,
                exceptions=exceptions,
            )
            content = json.dumps(
                material,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            policy = PortfolioBaselinePolicy(
                account_id=account_id,
                account_policy_id=_row_id(cast(_PersistedRow, account)),
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                known_at=max(clocks),
                effective_until=min(
                    (row.expires_at for row in exceptions),
                    default=None,
                ),
                max_total_weight=resolved.max_total_weight,
                max_single_weight=resolved.max_single_weight,
                min_cash_weight=resolved.min_cash_weight,
                hard_exclusions=resolved.hard_exclusions,
            )
        except (ArithmeticError, TypeError, ValueError):
            return _unavailable("PORTFOLIO_BASELINE_SOURCE_INVALID_OR_AMBIGUOUS")
        return PortfolioBaselinePolicyReadResult(policy=policy, reason_codes=())


def _parameters(row: _RiskParameterSource) -> BaselineRiskParameters:
    return BaselineRiskParameters(
        max_total_weight=_fraction(row.max_total_position_pct),
        max_single_weight=_fraction(row.max_single_position_pct),
        min_cash_weight=_fraction(row.min_cash_pct),
        hard_exclusions=_codes(row.hard_exclusions),
    )


def _exception(row: RiskExceptionModel) -> BaselineRiskException:
    name: Literal[
        "max_total_weight",
        "max_single_weight",
        "min_cash_weight",
        "hard_exclusions",
    ]
    if row.field_name == "max_total_position_pct":
        name = "max_total_weight"
    elif row.field_name == "max_single_position_pct":
        name = "max_single_weight"
    elif row.field_name == "min_cash_pct":
        name = "min_cash_weight"
    elif row.field_name == "hard_exclusions":
        return BaselineRiskException("hard_exclusions", None, _codes(row.allowed_value))
    else:
        raise ValueError("queried exception is outside the four baseline fields")
    return BaselineRiskException(name, _fraction(row.allowed_value), None)


def _fraction(value: object) -> Decimal | None:
    if value is None:
        return None
    if type(value) not in (str, int, float, Decimal):
        raise ValueError("baseline limits must be exact numeric values")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("baseline limit is invalid") from error
    if not result.is_finite() or not 0 <= result <= 1:
        raise ValueError("baseline limit is outside [0, 1]")
    return result


def _codes(value: object) -> tuple[str, ...]:
    if type(value) is not list and type(value) is not tuple:
        raise ValueError("hard exclusions must be an explicit list")
    codes = tuple(value)
    if any(
        type(item) is not str
        or not item
        or item.strip() != item
        or any(character.isspace() for character in item)
        for item in codes
    ):
        raise ValueError("hard exclusions contain invalid codes")
    if len({item.upper() for item in codes}) != len(codes):
        raise ValueError("hard exclusions repeat an asset code")
    return codes


def _binding_material(
    *,
    account_id: int,
    floor: GlobalRiskFloorModel,
    account: AccountRiskPolicyModel,
    template: RiskTemplateModel,
    exceptions: tuple[RiskExceptionModel, ...],
) -> dict[str, object]:
    return {
        "account_id": account_id,
        "floor": _row_payload(cast(_RiskParameterSource, floor)),
        "account_policy": {
            **_row_payload(cast(_RiskParameterSource, account)),
            "is_active": account.is_active,
            "template_id": account.template_id,
            "risk_profile": account.risk_profile,
        },
        "template": {
            **_row_payload(cast(_RiskParameterSource, template)),
            "key": template.key,
            "risk_profile": template.risk_profile,
            "is_active": template.is_active,
        },
        "exceptions": [
            {
                "id": _row_id(cast(_PersistedRow, row)),
                "field": row.field_name,
                "allowed_value": _json_safe_value(row.allowed_value),
                "account_id": row.account_id,
                "expires_at": row.expires_at.isoformat(),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "created_by_id": row.created_by_id,
                "reason": row.reason,
                "is_active": row.is_active,
            }
            for row in exceptions
        ],
    }


def _row_payload(row: _RiskParameterSource) -> dict[str, object]:
    parameters = _parameters(row)
    return {
        "id": _row_id(row),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "max_total_weight": _text(parameters.max_total_weight),
        "max_single_weight": _text(parameters.max_single_weight),
        "min_cash_weight": _text(parameters.min_cash_weight),
        "hard_exclusions": list(parameters.hard_exclusions),
    }


def _json_safe_value(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        decimal_value = _fraction(value)
        if decimal_value is None:
            raise ValueError("exception numeric value is missing")
        return str(decimal_value)
    if type(value) is list:
        return [_json_safe_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("exception object keys must be strings")
        return {key: _json_safe_value(item) for key, item in value.items()}
    raise ValueError("exception value is not JSON-safe")


def _row_id(row: _PersistedRow) -> int:
    if type(row.pk) is not int or row.pk < 1:
        raise ValueError("persisted baseline row needs a positive integer primary key")
    return row.pk


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _is_aware(value: datetime) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _unavailable(reason: str) -> PortfolioBaselinePolicyReadResult:
    return PortfolioBaselinePolicyReadResult(policy=None, reason_codes=(reason,))


__all__ = ("DjangoPortfolioBaselinePolicyReader",)
