"""Pure domain safeguards for regional egress route selection."""

import pytest

from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteDecision,
    EgressRouteRule,
    EgressRoutingError,
    EgressStrategy,
    resolve_egress_route,
)


def _rule(
    *,
    dataset_key: str = "equity.price.bar",
    deployment_region: str = "overseas",
    strategy: EgressStrategy = EgressStrategy.FIXED,
    fixed_egress_id: int | None = 9,
) -> EgressRouteRule:
    """Build a valid rule for route-selection tests."""

    return EgressRouteRule(
        rule_id=1,
        provider_id=7,
        dataset_key=dataset_key,
        domain_pattern="data.example.com",
        deployment_region=deployment_region,
        strategy=strategy,
        fixed_egress_id=fixed_egress_id,
        priority=10,
        enabled=True,
    )


def _context(
    *, dataset_key: str = "equity.price.bar", deployment_region: str = "overseas"
) -> EgressRequestContext:
    """Build a concrete request context for route-selection tests."""

    return EgressRequestContext(
        provider_id=7,
        dataset_key=dataset_key,
        target_url="https://data.example.com/daily",
        deployment_region=deployment_region,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_id", 1.5),
        ("provider_id", "7"),
        ("dataset_key", None),
        ("deployment_region", None),
        ("target_url", None),
        ("dataset_key", "*"),
        ("deployment_region", "*"),
    ),
)
def test_request_context_rejects_untyped_or_wildcard_dimensions(field: str, value: object) -> None:
    """A request must carry concrete, bounded dimensions into routing."""

    values: dict[str, object] = {
        "provider_id": 7,
        "dataset_key": "equity.price.bar",
        "target_url": "https://data.example.com/daily",
        "deployment_region": "overseas",
    }
    values[field] = value

    with pytest.raises(EgressRoutingError) as error:
        EgressRequestContext(**values)  # type: ignore[arg-type]

    assert error.value.code in {"EGRESS_INVALID_CONFIGURATION", "EGRESS_INVALID_URL"}


def test_rule_wildcards_match_concrete_context_only() -> None:
    """Rule wildcards broaden a rule; they never make a wildcard context valid."""

    route = resolve_egress_route(
        (_rule(dataset_key="*", deployment_region="*"),),
        _context(),
    )

    assert route.rule_id == 1
    assert route.egress_id == 9


def test_rule_dimensions_do_not_match_other_concrete_context() -> None:
    """A concrete context cannot be routed by a rule for another dimension."""

    route = resolve_egress_route((_rule(),), _context(dataset_key="equity.quote.snapshot"))

    assert route.rule_id is None
    assert route.strategy is EgressStrategy.DIRECT


def test_route_decision_rejects_raw_strategy_values() -> None:
    """Transport receives only enum-backed route decisions."""

    with pytest.raises(EgressRoutingError) as error:
        EgressRouteDecision(
            rule_id=None,
            strategy="direct",  # type: ignore[arg-type]
            candidates=(None,),
            reason="test",
        )

    assert error.value.code == "EGRESS_INVALID_STRATEGY"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_id", 7.5),
        ("rule_id", 0),
        ("priority", -1),
        ("fixed_egress_id", -2),
        ("strategy", "fixed"),
        ("enabled", 1),
        ("dataset_key", "d" * 121),
        ("deployment_region", "r" * 41),
    ),
)
def test_route_rule_rejects_untyped_or_out_of_bounds_values(field: str, value: object) -> None:
    """Persisted rules receive the same checks as HTTP-created rules."""

    values: dict[str, object] = {
        "rule_id": 1,
        "provider_id": 7,
        "dataset_key": "equity.price.bar",
        "domain_pattern": "data.example.com",
        "deployment_region": "overseas",
        "strategy": EgressStrategy.FIXED,
        "fixed_egress_id": 9,
        "priority": 10,
        "enabled": True,
    }
    values[field] = value

    with pytest.raises(EgressRoutingError):
        EgressRouteRule(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "target_url",
    (
        "https://user:secret@data.example.com/daily",
        "https://data.example.com/daily#fragment",
        "https://data.example.com:invalid/daily",
        "ftp://data.example.com/daily",
    ),
)
def test_request_context_rejects_unsafe_or_invalid_target_url(target_url: str) -> None:
    """Routing never accepts credentials, fragments, invalid ports, or non-HTTP URLs."""

    with pytest.raises(EgressRoutingError) as error:
        EgressRequestContext(
            provider_id=7,
            dataset_key="equity.price.bar",
            target_url=target_url,
            deployment_region="overseas",
        )

    assert error.value.code == "EGRESS_INVALID_URL"
