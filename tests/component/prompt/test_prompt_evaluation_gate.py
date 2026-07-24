from decimal import Decimal

import pytest

from apps.prompt.infrastructure.eval_models import (
    PromptEvalCase,
    PromptEvalDataset,
    PromptVersion,
)
from apps.prompt.infrastructure.evaluation_repository import PromptEvaluationRepository
from apps.prompt.infrastructure.models import PromptTemplateORM


@pytest.fixture
def prompt_candidate(db):  # type: ignore[no-untyped-def]
    template = PromptTemplateORM.objects.create(
        name="research-eval",
        category="analysis",
        template_content="{{ input }}",
    )
    version = PromptVersion.objects.create(
        version_id="prompt-v2",
        template=template,
        version="2.0",
        content="{{ input }}",
        required_variables=["input"],
        output_schema={"type": "object"},
        allowed_tools=["read_only_market_data"],
        content_hash="d" * 64,
        status="candidate",
    )
    dataset = PromptEvalDataset.objects.create(
        dataset_id="dataset-v1",
        name="research-contracts",
        version="1",
        content_hash="e" * 64,
    )
    PromptEvalCase.objects.create(
        case_id="case-1",
        dataset=dataset,
        input_variables={"input": "test"},
        expected_schema={"type": "object"},
        allowed_tools=["read_only_market_data"],
        assertions=[{"type": "schema"}],
    )
    return version


def _run_payload(evaluation_type: str) -> dict:
    return {
        "version_id": "prompt-v2",
        "dataset_id": "dataset-v1",
        "evaluation_type": evaluation_type,
        "provider": "fixed-provider",
        "model": "fixed-model",
        "temperature": 0,
        "max_cost": Decimal("1.00"),
        "max_tokens": 1000,
        "max_cases": 10,
        "assertion_results": [
            {
                "case_id": "case-1",
                "assertion_type": "schema",
                "passed": True,
                "critical": True,
                "tokens": 10,
                "cost": Decimal("0.01"),
            }
        ],
    }


@pytest.mark.django_db
def test_prompt_activation_requires_passing_offline_and_online_runs(prompt_candidate) -> None:
    repository = PromptEvaluationRepository()
    assert repository.record_run(_run_payload("offline")).status == "completed"
    assert repository.record_run(_run_payload("online")).status == "completed"

    decision = repository.promote(prompt_candidate.version_id)
    prompt_candidate.refresh_from_db()

    assert decision.decision == "approved"
    assert prompt_candidate.status == "active"


@pytest.mark.django_db
def test_prompt_budget_exhaustion_blocks_activation(prompt_candidate) -> None:
    repository = PromptEvaluationRepository()
    payload = _run_payload("offline")
    payload["max_cost"] = Decimal("0.001")
    run = repository.record_run(payload)

    decision = repository.promote(prompt_candidate.version_id)

    assert run.status == "budget_exceeded"
    assert decision.decision == "rejected"
    assert "budget_exceeded" in decision.evidence["reasons"]
