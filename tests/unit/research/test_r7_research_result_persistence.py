"""Unit contracts for the complete R7 research evidence/result seal."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from apps.research.infrastructure.r7_research_result_codec import (
    R7ResearchResultCodecError,
    decode_persisted_r7_research_result,
    encode_persisted_r7_research_result,
)
from tests.unit.research.r7_research_result_factories import make_result


def test_complete_packet_seals_calibration_analogy_pit_and_typed_path_evidence() -> None:
    result = make_result()

    assert result.evidence_graph.historical_analogy is not None
    assert result.evidence_graph.historical_analogy.query_manifest.manifest_id
    assert result.evidence_graph.path_study is not None
    assert result.evidence_graph.path_study.conditional_probabilities
    assert result.evidence_graph.path_study.transition_probabilities
    assert result.input_receipt.evidence_graph_hash == result.evidence_graph.content_hash
    assert result.calibration.content_hash
    assert result.trains_probability_model is False
    assert result.publishes_model_probability is False
    assert result.produces_decision is False
    assert result.executes_orders is False
    assert result.research_only is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True


def test_strict_codec_round_trips_the_complete_typed_graph() -> None:
    result = make_result()

    assert (
        decode_persisted_r7_research_result(encode_persisted_r7_research_result(result)) == result
    )


def test_nested_path_tamper_and_noncanonical_uuid_are_rejected() -> None:
    payload = encode_persisted_r7_research_result(make_result())
    tampered = deepcopy(payload)
    body = tampered["body"]
    assert isinstance(body, dict)
    graph = body["evidence_graph"]
    assert isinstance(graph, dict)
    path = graph["path_study"]
    assert isinstance(path, dict)
    transitions = path["transition_probabilities"]
    assert isinstance(transitions, list)
    transition = transitions[0]
    assert isinstance(transition, dict)
    transition["probability"] = "0.99"
    with pytest.raises(R7ResearchResultCodecError):
        decode_persisted_r7_research_result(tampered)

    noncanonical = deepcopy(payload)
    body = noncanonical["body"]
    assert isinstance(body, dict)
    graph = body["evidence_graph"]
    assert isinstance(graph, dict)
    path = graph["path_study"]
    assert isinstance(path, dict)
    transitions = path["transition_probabilities"]
    assert isinstance(transitions, list)
    transition = transitions[0]
    assert isinstance(transition, dict)
    value = transition["to_scenario_revision_id"]
    assert isinstance(value, str)
    transition["to_scenario_revision_id"] = "{" + value + "}"
    with pytest.raises(R7ResearchResultCodecError, match="UUID is non-canonical"):
        decode_persisted_r7_research_result(noncanonical)


def test_unknown_fields_and_relaxed_safety_flags_are_rejected() -> None:
    result = make_result()
    payload = encode_persisted_r7_research_result(result)
    tampered = deepcopy(payload)
    body = tampered["body"]
    assert isinstance(body, dict)
    body["decision"] = "approve"
    with pytest.raises(R7ResearchResultCodecError, match="keys mismatch"):
        decode_persisted_r7_research_result(tampered)

    with pytest.raises(ValueError, match="research-only"):
        replace(result, produces_decision=True)
