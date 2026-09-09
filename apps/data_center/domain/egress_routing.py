"""Pure routing rules for regional data egress.

The domain layer deliberately knows nothing about Django, requests, frp, or
the configured endpoint store.  It only decides which transport candidates a
request may try.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

_DOMAIN_PATTERN = re.compile(
    r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_MAX_DATASET_KEY_LENGTH = 120
_MAX_REGION_LENGTH = 40


class EgressRoutingError(ValueError):
    """Raised when an egress request or rule cannot be safely routed."""

    def __init__(self, message: str, *, code: str = "EGRESS_INVALID_CONFIGURATION") -> None:
        super().__init__(message)
        self.code = code


class EgressStrategy(StrEnum):
    """Supported first-version egress policies."""

    DIRECT = "direct"
    FIXED = "fixed"
    DIRECT_FALLBACK = "direct_fallback"


def _positive_int(value: object, field_name: str) -> int:
    """Validate an identifier or priority at the domain boundary."""

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EgressRoutingError(
            f"{field_name} must be a positive integer",
            code="EGRESS_INVALID_CONFIGURATION",
        )
    return value


def _dimension(
    value: object,
    field_name: str,
    *,
    allow_wildcard: bool,
    max_length: int,
) -> str:
    """Validate a routing dimension and its optional whole-value wildcard."""

    if not isinstance(value, str):
        raise EgressRoutingError(
            f"{field_name} must be a string",
            code="EGRESS_INVALID_CONFIGURATION",
        )
    normalized = value.strip()
    if not normalized:
        raise EgressRoutingError(
            f"{field_name} cannot be empty",
            code="EGRESS_INVALID_CONFIGURATION",
        )
    if len(normalized) > max_length:
        raise EgressRoutingError(
            f"{field_name} cannot exceed {max_length} characters",
            code="EGRESS_INVALID_CONFIGURATION",
        )
    if "*" in normalized and (not allow_wildcard or normalized != "*"):
        raise EgressRoutingError(
            f"{field_name} may use only a whole-value wildcard",
            code="EGRESS_INVALID_CONFIGURATION",
        )
    return normalized


def _strategy(value: object) -> EgressStrategy:
    """Narrow an untrusted strategy value to the domain enum."""

    if not isinstance(value, EgressStrategy):
        raise EgressRoutingError(
            "strategy must be an EgressStrategy value",
            code="EGRESS_INVALID_STRATEGY",
        )
    return value


@dataclass(frozen=True, slots=True)
class EgressRequestContext:
    """The stable dimensions used to choose one egress route."""

    provider_id: int
    dataset_key: str
    target_url: str
    deployment_region: str

    def __post_init__(self) -> None:
        _positive_int(self.provider_id, "provider_id")
        dataset_key = _dimension(
            self.dataset_key,
            "dataset_key",
            allow_wildcard=False,
            max_length=_MAX_DATASET_KEY_LENGTH,
        )
        deployment_region = _dimension(
            self.deployment_region,
            "deployment_region",
            allow_wildcard=False,
            max_length=_MAX_REGION_LENGTH,
        )
        if not isinstance(self.target_url, str):
            raise EgressRoutingError(
                "target_url must be a string",
                code="EGRESS_INVALID_URL",
            )
        object.__setattr__(self, "dataset_key", dataset_key)
        object.__setattr__(self, "deployment_region", deployment_region)
        object.__setattr__(self, "target_url", self.target_url.strip())
        target_hostname(self.target_url)


@dataclass(frozen=True, slots=True)
class EgressRouteRule:
    """One persisted rule projected into the domain layer."""

    rule_id: int | None
    provider_id: int
    dataset_key: str
    domain_pattern: str
    deployment_region: str
    strategy: EgressStrategy
    fixed_egress_id: int | None
    priority: int
    enabled: bool = True

    @property
    def id(self) -> int | None:
        """Return the persistent identifier used by interface callers."""

        return self.rule_id

    def __post_init__(self) -> None:
        if self.rule_id is not None:
            _positive_int(self.rule_id, "rule_id")
        _positive_int(self.provider_id, "provider_id")
        _positive_int(self.priority, "priority")
        dataset_key = _dimension(
            self.dataset_key,
            "dataset_key",
            allow_wildcard=True,
            max_length=_MAX_DATASET_KEY_LENGTH,
        )
        deployment_region = _dimension(
            self.deployment_region,
            "deployment_region",
            allow_wildcard=True,
            max_length=_MAX_REGION_LENGTH,
        )
        strategy = _strategy(self.strategy)
        if not isinstance(self.enabled, bool):
            raise EgressRoutingError(
                "enabled must be a boolean",
                code="EGRESS_INVALID_CONFIGURATION",
            )
        if self.fixed_egress_id is not None:
            fixed_egress_id = _positive_int(self.fixed_egress_id, "fixed_egress_id")
        else:
            fixed_egress_id = None
        object.__setattr__(self, "dataset_key", dataset_key)
        object.__setattr__(self, "deployment_region", deployment_region)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "fixed_egress_id", fixed_egress_id)
        normalized_pattern = normalize_domain_pattern(self.domain_pattern)
        if normalized_pattern != self.domain_pattern:
            object.__setattr__(self, "domain_pattern", normalized_pattern)
        if strategy is EgressStrategy.DIRECT and fixed_egress_id is not None:
            raise EgressRoutingError(
                "direct strategy cannot select an egress endpoint",
                code="EGRESS_DIRECT_ENDPOINT_FORBIDDEN",
            )
        if strategy is not EgressStrategy.DIRECT and fixed_egress_id is None:
            raise EgressRoutingError(
                "fixed and direct_fallback strategies require fixed_egress_id",
                code="EGRESS_ENDPOINT_REQUIRED",
            )

    def to_dict(self) -> dict[str, object]:
        """Return a stable rule projection for API and diagnostics consumers."""

        return {
            "id": self.rule_id,
            "provider_id": self.provider_id,
            "dataset_key": self.dataset_key,
            "domain_pattern": self.domain_pattern,
            "deployment_region": self.deployment_region,
            "strategy": self.strategy.value,
            "strategy_label": strategy_label(self.strategy),
            "fixed_egress_id": self.fixed_egress_id,
            "priority": self.priority,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class EgressRouteDecision:
    """The ordered candidates selected for one request."""

    rule_id: int | None
    strategy: EgressStrategy
    candidates: tuple[int | None, ...]
    reason: str
    matched_domain: str | None = None

    def __post_init__(self) -> None:
        """Reject untyped route decisions before they reach transport code."""

        object.__setattr__(self, "strategy", _strategy(self.strategy))

    @property
    def egress_id(self) -> int | None:
        """Return the first configured endpoint, if the route has one."""

        return next((candidate for candidate in self.candidates if candidate is not None), None)

    def to_dict(self) -> dict[str, object]:
        """Return a safe route explanation without target credentials."""

        return {
            "rule_id": self.rule_id,
            "strategy": self.strategy.value,
            "strategy_label": strategy_label(self.strategy),
            "egress_id": self.egress_id,
            "candidates": list(self.candidates),
            "reason": self.reason,
            "matched_domain": self.matched_domain,
        }


def strategy_label(strategy: EgressStrategy) -> str:
    """Return the operator-facing label for one routing strategy."""

    _strategy(strategy)
    return {
        EgressStrategy.DIRECT: "直连",
        EgressStrategy.FIXED: "固定出口",
        EgressStrategy.DIRECT_FALLBACK: "直连失败后使用备用出口",
    }[strategy]


def normalize_domain_pattern(value: str) -> str:
    """Normalize and validate an exact host or explicit ``*.subdomain`` pattern."""

    if not isinstance(value, str):
        raise EgressRoutingError(
            "domain_pattern must be a string",
            code="EGRESS_INVALID_DOMAIN_PATTERN",
        )
    normalized = value.strip().lower().rstrip(".")
    if (
        not normalized
        or "/" in normalized
        or ":" in normalized
        or not _DOMAIN_PATTERN.fullmatch(normalized)
    ):
        raise EgressRoutingError(
            "domain_pattern must be a hostname or explicit wildcard hostname",
            code="EGRESS_INVALID_DOMAIN_PATTERN",
        )
    return normalized


def target_hostname(target_url: str) -> str:
    """Extract the normalized host used for deterministic route matching."""

    if not isinstance(target_url, str):
        raise EgressRoutingError("target_url must be a string", code="EGRESS_INVALID_URL")
    normalized_url = target_url.strip()
    try:
        parts = urlsplit(normalized_url)
        host = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise EgressRoutingError(
            "target_url must be a valid HTTP(S) URL",
            code="EGRESS_INVALID_URL",
        ) from error
    normalized_host = (host or "").strip().lower().rstrip(".")
    if (
        parts.scheme not in {"http", "https"}
        or not normalized_host
        or "*" in normalized_host
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise EgressRoutingError("target_url must be an HTTP(S) URL", code="EGRESS_INVALID_URL")
    return normalized_host


def domain_pattern_matches(pattern: str, hostname: str) -> bool:
    """Match an exact hostname or a wildcard that excludes its bare suffix."""

    normalized_pattern = normalize_domain_pattern(pattern)
    if not isinstance(hostname, str):
        raise EgressRoutingError(
            "hostname must be a string",
            code="EGRESS_INVALID_DOMAIN_PATTERN",
        )
    normalized_host = hostname.strip().lower().rstrip(".")
    if not normalized_host:
        return False
    if normalized_pattern == normalized_host:
        return True
    if normalized_pattern.startswith("*."):
        suffix = normalized_pattern[1:]
        return normalized_host.endswith(suffix) and normalized_host != suffix[1:]
    return False


def _dimension_overlaps(left: str, right: str) -> bool:
    """Return whether two equality-or-star rule dimensions can overlap."""

    return left == right or left == "*" or right == "*"


def _domain_patterns_overlap(left: str, right: str) -> bool:
    """Return whether two supported host patterns can select the same host."""

    left_value = normalize_domain_pattern(left)
    right_value = normalize_domain_pattern(right)
    if left_value == right_value:
        return True
    if left_value.startswith("*.") and domain_pattern_matches(left_value, right_value):
        return True
    if right_value.startswith("*.") and domain_pattern_matches(right_value, left_value):
        return True
    if left_value.startswith("*.") and right_value.startswith("*."):
        return left_value.endswith(right_value[1:]) or right_value.endswith(left_value[1:])
    return False


def validate_rule_set(rules: tuple[EgressRouteRule, ...]) -> None:
    """Reject enabled rules whose same-priority match spaces overlap."""

    enabled = [rule for rule in rules if rule.enabled]
    for index, left in enumerate(enabled):
        for right in enabled[index + 1 :]:
            if left.priority != right.priority:
                continue
            if (
                left.provider_id == right.provider_id
                and _dimension_overlaps(left.dataset_key, right.dataset_key)
                and _dimension_overlaps(left.deployment_region, right.deployment_region)
                and _domain_patterns_overlap(left.domain_pattern, right.domain_pattern)
            ):
                raise EgressRoutingError(
                    "same-priority egress rules overlap",
                    code="EGRESS_RULE_PRIORITY_CONFLICT",
                )


def resolve_egress_route(
    rules: tuple[EgressRouteRule, ...], context: EgressRequestContext
) -> EgressRouteDecision:
    """Select the highest-priority matching route, defaulting to direct access."""

    validate_rule_set(rules)
    hostname = target_hostname(context.target_url)
    matching = [
        rule
        for rule in rules
        if rule.enabled
        and rule.provider_id == context.provider_id
        and (rule.dataset_key == "*" or rule.dataset_key == context.dataset_key)
        and (rule.deployment_region == "*" or rule.deployment_region == context.deployment_region)
        and domain_pattern_matches(rule.domain_pattern, hostname)
    ]
    if not matching:
        return EgressRouteDecision(
            rule_id=None,
            strategy=EgressStrategy.DIRECT,
            candidates=(None,),
            reason="no_matching_rule",
        )
    selected = min(matching, key=lambda rule: (rule.priority, rule.rule_id or 0))
    if selected.strategy is EgressStrategy.DIRECT:
        candidates: tuple[int | None, ...] = (None,)
    elif selected.strategy is EgressStrategy.FIXED:
        candidates = (selected.fixed_egress_id,)
    else:
        candidates = (None, selected.fixed_egress_id)
    return EgressRouteDecision(
        rule_id=selected.rule_id,
        strategy=selected.strategy,
        candidates=candidates,
        reason="matched_rule",
        matched_domain=hostname,
    )


__all__ = [
    "EgressRequestContext",
    "EgressRouteDecision",
    "EgressRouteRule",
    "EgressRoutingError",
    "EgressStrategy",
    "domain_pattern_matches",
    "normalize_domain_pattern",
    "resolve_egress_route",
    "strategy_label",
    "target_hostname",
    "validate_rule_set",
]
