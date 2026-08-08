"""Focused boundary coverage for scenario-research Domain contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.research.domain import scenario_probability_contracts as probability_contracts
from apps.research.domain import scenario_research_evidence as evidence_domain
from apps.research.domain.scenario_probability_contracts import ScenarioResearchScope
from apps.research.domain.scenario_research_evidence import (
    PointInTimeFeatureValue,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_text,
    require_token,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)
SHA = "a" * 64


def test_scenario_research_hashing_rejects_all_malformed_inputs() -> None:
    assert hash_components("a", "bc") != hash_components("ab", "c")
    with pytest.raises(ValueError):
        require_sha256("A" * 64, "digest")
    for value in (1, "", "a b", "x" * 129, "a\x01"):
        with pytest.raises(ValueError):
            require_token(value, "token")  # type: ignore[arg-type]
    for value in (1, "", " ", "x" * 257, "a\x01"):
        with pytest.raises(ValueError):
            require_text(value, "text")  # type: ignore[arg-type]


def test_scenario_research_primitive_guards_cover_every_invalid_branch() -> None:
    with pytest.raises(ValueError):
        evidence_domain._require_evidence_refs(())
    with pytest.raises(ValueError):
        evidence_domain._require_evidence_refs(("",))
    for value in (True, 0):
        with pytest.raises(ValueError):
            evidence_domain._require_positive_count(value, "count")
    for value in (1, Decimal("NaN"), Decimal("-0.1"), Decimal("1.1")):
        with pytest.raises(ValueError):
            evidence_domain._require_probability(value, "probability")  # type: ignore[arg-type]
    for value in (1, Decimal("NaN")):
        with pytest.raises(ValueError):
            evidence_domain._require_finite(value, "value")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        evidence_domain._require_aware(datetime(2026, 1, 1), "time")

    for edges in (
        (Decimal("0"),),
        (Decimal("0.1"), Decimal("1")),
        (Decimal("0"), Decimal("0.5"), Decimal("0.5"), Decimal("1")),
    ):
        with pytest.raises(ValueError):
            probability_contracts._validate_bin_edges(edges)
    for value in (1, Decimal("NaN"), Decimal("-0.1"), Decimal("1.1")):
        with pytest.raises(ValueError):
            probability_contracts._require_probability(value, "probability")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        probability_contracts._require_aware(datetime(2026, 1, 1), "time")


def _feature(**changes: object) -> PointInTimeManifestFeature:
    values = {
        "feature_key": "growth",
        "source_version": "source-v1",
        "available_at": NOW - timedelta(days=2),
        "vintage_at": NOW - timedelta(days=1),
        "content_hash": SHA,
    }
    values.update(changes)
    return PointInTimeManifestFeature(**values)  # type: ignore[arg-type]


def _manifest(**changes: object) -> PointInTimeManifestReference:
    values = {
        "manifest_id": "manifest-1",
        "manifest_version": "manifest-v1",
        "as_of": NOW,
        "manifest_hash": SHA,
        "features": (_feature(),),
    }
    values.update(changes)
    return PointInTimeManifestReference.create(**values)  # type: ignore[arg-type]


def test_point_in_time_manifest_rejects_duplicate_future_and_forged_entries() -> None:
    manifest = _manifest()
    with pytest.raises(ValueError):
        replace(manifest, features=(manifest.features[0], manifest.features[0]))
    with pytest.raises(ValueError):
        _manifest(features=(_feature(available_at=NOW + timedelta(seconds=1)),))
    with pytest.raises(ValueError):
        _manifest(features=(_feature(vintage_at=NOW + timedelta(seconds=1)),))
    with pytest.raises(ValueError):
        replace(manifest, reference_hash="b" * 64)


@pytest.mark.parametrize(
    "changes",
    [
        {"value": 1},
        {"value": Decimal("NaN")},
        {"available_at": datetime(2026, 1, 1)},
        {"vintage_at": datetime(2026, 1, 1)},
    ],
)
def test_point_in_time_feature_value_rejects_invalid_values(
    changes: dict[str, object],
) -> None:
    values = {
        "feature_key": "growth",
        "value": Decimal("1"),
        "unit": "zscore",
        "source_version": "source-v1",
        "available_at": NOW,
        "vintage_at": NOW,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        PointInTimeFeatureValue(**values)  # type: ignore[arg-type]


def test_scenario_scope_rejects_membership_and_horizon_edges() -> None:
    first = UUID("00000000-0000-0000-0000-000000000001")
    second = UUID("00000000-0000-0000-0000-000000000002")
    scope = ScenarioResearchScope.create(
        scope_version="scope-v1",
        scenario_set_revision_id=UUID("00000000-0000-0000-0000-000000000010"),
        scenario_revision_ids=(first, second),
        forecast_horizon=timedelta(days=30),
        censoring_rule_version="censor-v1",
        path_horizon_periods=3,
        path_initial_state_revision_ids=(first,),
    )
    with pytest.raises(ValueError, match="at least one revision"):
        replace(scope, scenario_revision_ids=())
    with pytest.raises(ValueError, match="duplicate revisions"):
        replace(scope, scenario_revision_ids=(first, first))
    with pytest.raises(ValueError, match="canonicalized"):
        replace(scope, scenario_revision_ids=(second, first))
    with pytest.raises(ValueError, match="forecast_horizon must be positive"):
        replace(scope, forecast_horizon=timedelta(0))
    with pytest.raises(ValueError, match="path_horizon_periods"):
        replace(scope, path_horizon_periods=True)
    with pytest.raises(ValueError, match="path initial states"):
        replace(scope, path_initial_state_revision_ids=())
