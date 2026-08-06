"""Composite R5 exact-reread, shared-liquidity, and fail-closed coverage."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Generic, TypeVar

import pytest

from apps.fixed_income.application.relative_value import (
    RunR5RelativeValueResearch,
    RunR5RelativeValueResearchCommand,
)
from apps.fixed_income.domain.evidence import (
    EvidenceLocator,
    EvidenceRole,
    ExactEvidence,
    canonical_hash,
)
from apps.fixed_income.domain.rating_migration import RatingTerminalKind
from apps.fixed_income.domain.relative_value_assessment import (
    R5Component,
    R5ComponentStatus,
    R5RelativeValueAssessment,
    R5RelativeValueBlockerCode,
    R5RelativeValueInputSet,
    R5RelativeValuePolicySet,
    R5RelativeValueStatus,
    collect_r5_publication_evidence,
)
from tests.unit.fixed_income import test_curve_relative_value as curve_fixtures
from tests.unit.fixed_income import test_rating_migration as rating_fixtures
from tests.unit.fixed_income import test_spread_history as spread_fixtures

_EVALUATED_AT = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)

T = TypeVar("T")


@dataclass
class _Provider(Generic[T]):
    values: dict[EvidenceLocator, T]
    calls: list[tuple[EvidenceLocator, datetime]]

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> T | None:
        self.calls.append((locator, evaluated_at))
        return self.values.get(locator)


@dataclass(frozen=True)
class _FixtureGraph:
    input_set: R5RelativeValueInputSet
    policy_set: R5RelativeValuePolicySet


@dataclass
class _RunnerGraph:
    runner: RunR5RelativeValueResearch
    input_provider: _Provider[R5RelativeValueInputSet]
    policy_provider: _Provider[R5RelativeValuePolicySet]
    publication_provider: _Provider[ExactEvidence]
    bond_master_provider: _Provider[curve_fixtures.BondMasterEvidence]
    cash_flow_provider: _Provider[curve_fixtures.CashFlowEvidence]
    calendar_provider: _Provider[ExactEvidence]
    exact_owner_provider: _Provider[ExactEvidence]

    @property
    def providers(self) -> tuple[_Provider[object], ...]:
        return (
            self.input_provider,
            self.policy_provider,
            self.publication_provider,
            self.bond_master_provider,
            self.cash_flow_provider,
            self.calendar_provider,
            self.exact_owner_provider,
        )


def _canonical_evidence(
    items: tuple[ExactEvidence, ...],
) -> tuple[ExactEvidence, ...]:
    by_locator = {(item.evidence_id, item.version): item for item in items}
    return tuple(
        sorted(
            by_locator.values(),
            key=lambda item: (item.evidence_id, item.version, item.seal_hash),
        )
    )


def _fixture_graph(
    monkeypatch: pytest.MonkeyPatch,
    *,
    omit_short_capacity: bool = False,
) -> _FixtureGraph:
    exact_defaults = dict(curve_fixtures._exact.__kwdefaults__ or {})
    exact_defaults["observed_at"] = _EVALUATED_AT - timedelta(seconds=60)
    exact_defaults["available_at"] = _EVALUATED_AT - timedelta(seconds=50)
    monkeypatch.setattr(
        curve_fixtures._exact,
        "__kwdefaults__",
        exact_defaults,
    )
    leg_defaults = dict(curve_fixtures._leg.__kwdefaults__ or {})
    leg_defaults["settlement_at"] = _EVALUATED_AT + timedelta(days=1)
    monkeypatch.setattr(curve_fixtures._leg, "__kwdefaults__", leg_defaults)
    monkeypatch.setattr(curve_fixtures, "_EVALUATED_AT", _EVALUATED_AT)
    monkeypatch.setattr(
        curve_fixtures,
        "_OBSERVED_AT",
        _EVALUATED_AT - timedelta(seconds=60),
    )
    monkeypatch.setattr(
        curve_fixtures,
        "_AVAILABLE_AT",
        _EVALUATED_AT - timedelta(seconds=50),
    )
    monkeypatch.setattr(
        curve_fixtures,
        "_VALID_UNTIL",
        _EVALUATED_AT + timedelta(days=60),
    )
    monkeypatch.setattr(
        curve_fixtures,
        "_SETTLEMENT_AT",
        _EVALUATED_AT + timedelta(days=1),
    )
    spread_calendar = spread_fixtures._calendar()
    spread_evidence = spread_fixtures._evidence(
        (
            spread_fixtures._observation("2026-01-31", "10"),
            spread_fixtures._observation("2026-02-28", "20"),
        )
    )
    rating_policy = rating_fixtures._policy()
    rating_evidence = rating_fixtures._evidence(
        (
            rating_fixtures._transition(
                "bond-a",
                "AAA",
                RatingTerminalKind.LIVE_GRADE,
                "AA",
                rating_policy,
            ),
            rating_fixtures._transition(
                "bond-b",
                "AA",
                RatingTerminalKind.DEFAULT,
                "DEFAULT",
                rating_policy,
            ),
        )
    )
    curve_evidence = curve_fixtures._evidence(omit_short_capacity=omit_short_capacity)
    liquidity_evidences = curve_evidence.liquidity_inputs
    child_sources = (
        spread_evidence.source,
        rating_evidence.source,
        *(item.source for item in liquidity_evidences),
        curve_evidence.source,
    )
    publications = collect_r5_publication_evidence(
        spread=spread_evidence,
        rating=rating_evidence,
        liquidities=liquidity_evidences,
        curve=curve_evidence,
    )
    calendars = _canonical_evidence(
        (spread_calendar.evidence, curve_evidence.trading_calendar.evidence)
    )
    owner_sources = _canonical_evidence(
        (
            spread_evidence.source,
            rating_evidence.source,
            rating_evidence.cohort.evidence,
            *(item.source for item in liquidity_evidences),
            curve_evidence.source,
            curve_evidence.cash_funding.evidence,
            *(item.source for item in curve_evidence.legs),
        )
    )
    child_input_hashes = tuple(
        sorted(
            (
                spread_evidence.evidence_hash,
                spread_calendar.calendar_hash,
                rating_evidence.evidence_hash,
                *(item.evidence_hash for item in liquidity_evidences),
                curve_evidence.evidence_hash,
            )
        )
    )
    input_manifest_hash = canonical_hash(
        {
            "input_set_id": "r5-input-set",
            "input_set_version": "v1",
            "currency": "CNY",
            "spread_evidence_hash": spread_evidence.evidence_hash,
            "spread_calendar_hash": spread_calendar.calendar_hash,
            "rating_evidence_hash": rating_evidence.evidence_hash,
            "liquidity_evidence_hashes": tuple(
                (item.subject_id, item.evidence_hash) for item in liquidity_evidences
            ),
            "curve_evidence_hash": curve_evidence.evidence_hash,
            "publication_seals": tuple(item.seal_hash for item in publications),
            "bond_master_hashes": tuple(item.master_hash for item in curve_evidence.bond_masters),
            "cash_flow_hashes": tuple(item.schedule_hash for item in curve_evidence.cash_flows),
            "calendar_seals": tuple(item.seal_hash for item in calendars),
            "owner_exact_source_seals": tuple(item.seal_hash for item in owner_sources),
        }
    )
    input_set = R5RelativeValueInputSet(
        input_set_id="r5-input-set",
        input_set_version="v1",
        currency="CNY",
        spread_evidence=spread_evidence,
        spread_calendar=spread_calendar,
        rating_evidence=rating_evidence,
        liquidity_evidences=liquidity_evidences,
        curve_evidence=curve_evidence,
        source=ExactEvidence(
            role=EvidenceRole.FIXED_INCOME_INPUT_SET,
            owner="fixed_income",
            evidence_id="r5-input-set",
            version="v1",
            subject_id="r5-input-set",
            content_hash=input_manifest_hash,
            observed_at=max(item.observed_at for item in child_sources),
            available_at=max(item.available_at for item in child_sources),
            valid_until=min(item.valid_until for item in child_sources),
            currency="CNY",
            curve_role="r5_relative_value_input_set",
            upstream_hashes=child_input_hashes,
        ),
    )
    spread_policy = spread_fixtures._policy()
    liquidity_policy = curve_fixtures._liquidity_policy()
    curve_policy = curve_fixtures._curve_policy()
    child_policy_hashes = tuple(
        sorted(
            (
                spread_policy.policy_hash,
                rating_policy.policy_hash,
                liquidity_policy.policy_hash,
                curve_policy.policy_hash,
            )
        )
    )
    policy_manifest_hash = canonical_hash(
        {
            "policy_set_id": "r5-policy-set",
            "policy_set_version": "v1",
            "spread_policy_hash": spread_policy.policy_hash,
            "rating_policy_hash": rating_policy.policy_hash,
            "liquidity_policy_hash": liquidity_policy.policy_hash,
            "curve_policy_hash": curve_policy.policy_hash,
        }
    )
    policy_sources = (
        spread_policy.evidence,
        rating_policy.evidence,
        liquidity_policy.evidence,
        curve_policy.evidence,
    )
    policy_set = R5RelativeValuePolicySet(
        policy_set_id="r5-policy-set",
        policy_set_version="v1",
        spread_policy=spread_policy,
        rating_policy=rating_policy,
        liquidity_policy=liquidity_policy,
        curve_policy=curve_policy,
        source=ExactEvidence(
            role=EvidenceRole.POLICY,
            owner="research",
            evidence_id="r5-policy-set",
            version="v1",
            subject_id="r5-policy-set",
            content_hash=policy_manifest_hash,
            observed_at=max(item.observed_at for item in policy_sources),
            available_at=max(item.available_at for item in policy_sources),
            valid_until=min(item.valid_until for item in policy_sources),
            currency=None,
            curve_role="r5_relative_value_policy_set",
            upstream_hashes=child_policy_hashes,
        ),
    )
    return _FixtureGraph(input_set=input_set, policy_set=policy_set)


def _runner_graph(graph: _FixtureGraph) -> _RunnerGraph:
    input_provider = _Provider({graph.input_set.source.locator: graph.input_set}, [])
    policy_provider = _Provider({graph.policy_set.source.locator: graph.policy_set}, [])
    publication_provider = _Provider(
        {item.locator: item for item in graph.input_set.publications}, []
    )
    bond_master_provider = _Provider(
        {item.evidence.locator: item for item in graph.input_set.bond_masters},
        [],
    )
    cash_flow_provider = _Provider(
        {item.evidence.locator: item for item in graph.input_set.cash_flows},
        [],
    )
    calendar_provider = _Provider({item.locator: item for item in graph.input_set.calendars}, [])
    exact_owner_provider = _Provider(
        {item.locator: item for item in graph.input_set.owner_exact_sources}, []
    )
    runner = RunR5RelativeValueResearch(
        input_provider=input_provider,
        policy_provider=policy_provider,
        publication_provider=publication_provider,
        bond_master_provider=bond_master_provider,
        cash_flow_provider=cash_flow_provider,
        calendar_provider=calendar_provider,
        exact_owner_provider=exact_owner_provider,
    )
    return _RunnerGraph(
        runner=runner,
        input_provider=input_provider,
        policy_provider=policy_provider,
        publication_provider=publication_provider,
        bond_master_provider=bond_master_provider,
        cash_flow_provider=cash_flow_provider,
        calendar_provider=calendar_provider,
        exact_owner_provider=exact_owner_provider,
    )


def _command(graph: _FixtureGraph) -> RunR5RelativeValueResearchCommand:
    return RunR5RelativeValueResearchCommand(
        assessment_id="r5-assessment",
        input_set=graph.input_set.source.locator,
        policy_set=graph.policy_set.source.locator,
        evaluated_at=_EVALUATED_AT,
    )


def _codes(
    result: R5RelativeValueAssessment,
) -> set[R5RelativeValueBlockerCode]:
    return {item.code for item in result.blockers}


def test_application_rereads_full_graph_at_one_cutoff_and_seals_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runner_graph = _runner_graph(graph)

    result = runner_graph.runner.execute(_command(graph))

    assert result.status is R5RelativeValueStatus.AVAILABLE
    assert tuple(item.subject_id for item in result.liquidity_results) == (
        "bond-back",
        "bond-front",
    )
    assert result.curve_result is not None
    assert result.curve_result.liquidity_result_seals
    assert all(
        seal.status is R5ComponentStatus.AVAILABLE and seal.policy_hash is not None
        for seal in result.component_seals
    )
    assert {seal.component for seal in result.component_seals} == set(R5Component)
    assert all(
        evaluated_at == _EVALUATED_AT
        for provider in runner_graph.providers
        for _, evaluated_at in provider.calls
    )
    assert len(runner_graph.exact_owner_provider.calls) == len(graph.input_set.owner_exact_sources)


def test_missing_nested_exact_owner_source_blocks_without_placeholder_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runner_graph = _runner_graph(graph)
    missing = graph.input_set.owner_exact_sources[0]
    runner_graph.exact_owner_provider.values.pop(missing.locator)

    result = runner_graph.runner.execute(_command(graph))

    assert result.status is R5RelativeValueStatus.BLOCKED
    assert R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISSING in _codes(result)
    assert all(
        seal.status is R5ComponentStatus.MISSING
        and seal.input_hash is None
        and seal.output_hash is None
        and seal.policy_hash is None
        for seal in result.component_seals
    )


def test_mismatched_nested_exact_owner_seal_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runner_graph = _runner_graph(graph)
    expected = graph.input_set.owner_exact_sources[0]
    runner_graph.exact_owner_provider.values[expected.locator] = replace(
        expected,
        content_hash=canonical_hash({"tampered": expected.content_hash}),
    )

    result = runner_graph.runner.execute(_command(graph))

    assert result.status is R5RelativeValueStatus.BLOCKED
    assert R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH in _codes(result)


@pytest.mark.parametrize(
    "boundary",
    ("publication", "bond_master", "cash_flow", "calendar"),
)
def test_authoritative_provider_tamper_blocks_at_each_typed_boundary(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    graph = _fixture_graph(monkeypatch)
    runner_graph = _runner_graph(graph)
    if boundary == "publication":
        expected = graph.input_set.publications[0]
        runner_graph.publication_provider.values[expected.locator] = replace(
            expected,
            content_hash=canonical_hash({"tampered": expected.content_hash}),
        )
    elif boundary == "bond_master":
        expected_master = graph.input_set.bond_masters[0]
        runner_graph.bond_master_provider.values[expected_master.evidence.locator] = replace(
            expected_master,
            issue_size=expected_master.issue_size + Decimal("1"),
        )
    elif boundary == "cash_flow":
        expected_cash_flow = graph.input_set.cash_flows[0]
        runner_graph.cash_flow_provider.values[expected_cash_flow.evidence.locator] = replace(
            expected_cash_flow,
            face_value=expected_cash_flow.face_value + Decimal("1"),
        )
    else:
        expected_calendar = graph.input_set.calendars[0]
        runner_graph.calendar_provider.values[expected_calendar.locator] = replace(
            expected_calendar,
            content_hash=canonical_hash({"tampered": expected_calendar.content_hash}),
        )

    result = runner_graph.runner.execute(_command(graph))

    assert result.status is R5RelativeValueStatus.BLOCKED
    assert R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH in _codes(result)


def test_blocked_child_blocks_composite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _fixture_graph(monkeypatch, omit_short_capacity=True)

    result = _runner_graph(graph).runner.execute(_command(graph))

    assert result.status is R5RelativeValueStatus.BLOCKED
    assert R5RelativeValueBlockerCode.CHILD_BLOCKED in _codes(result)
    curve_seal = next(
        seal
        for seal in result.component_seals
        if seal.component is R5Component.CURVE_RELATIVE_VALUE
    )
    assert curve_seal.status is R5ComponentStatus.BLOCKED


def test_command_boundary_contains_only_ids_versions_and_cutoff() -> None:
    assert tuple(item.name for item in fields(RunR5RelativeValueResearchCommand)) == (
        "assessment_id",
        "input_set",
        "policy_set",
        "evaluated_at",
    )
