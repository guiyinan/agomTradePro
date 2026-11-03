"""Config Center-backed reader for the active simulation portfolio-risk policy."""

from __future__ import annotations

from datetime import date, datetime

from apps.config_center.application.runtime_value_evidence import (
    read_active_runtime_value_evidence,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyConfigurationError,
    PortfolioRiskPolicyReadResult,
    parse_portfolio_risk_policy_bundle,
)


class ConfiguredPortfolioRiskPolicyReader:
    """Read one exact active runtime policy without defaults or older revisions."""

    def __init__(self, *, environment: str) -> None:
        """Bind the environment explicitly at the composition root."""

        if type(environment) is not str or not environment or environment.strip() != environment:
            raise ValueError("environment must be a nonempty canonical token")
        self._environment = environment

    def read_policy(
        self,
        *,
        as_of: datetime,
        business_date: date,
        account_id: int,
    ) -> PortfolioRiskPolicyReadResult:
        """Read, parse and scope-check the active typed runtime snapshot."""

        if (
            not _is_aware(as_of)
            or type(business_date) is not date
            or type(account_id) is not int
            or account_id < 1
        ):
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_REQUEST_INVALID",),
            )
        try:
            runtime_evidence = read_active_runtime_value_evidence(
                environment=self._environment,
                definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
                as_of=as_of,
            )
        except (RuntimeError, TypeError, ValueError):
            runtime_evidence = None
        if runtime_evidence is None:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_RUNTIME_VALUE_UNAVAILABLE",),
            )
        if runtime_evidence.environment != self._environment:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_RUNTIME_ENVIRONMENT_MISMATCH",),
            )
        try:
            policy = parse_portfolio_risk_policy_bundle(
                runtime_evidence,
                business_date=business_date,
                as_of=as_of,
            )
        except PortfolioRiskPolicyConfigurationError as exc:
            return PortfolioRiskPolicyReadResult(policy=None, reason_codes=(exc.reason_code,))
        if account_id not in policy.account_ids:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_ACCOUNT_OUT_OF_SCOPE",),
            )
        return PortfolioRiskPolicyReadResult(policy=policy, reason_codes=())


def _is_aware(value: datetime) -> bool:
    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


__all__ = ("ConfiguredPortfolioRiskPolicyReader",)
