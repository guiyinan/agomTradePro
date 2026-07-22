"""Prompt evaluation persistence and activation transaction."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from .eval_models import (
    PromptEvalAssertion,
    PromptEvalCase,
    PromptEvalDataset,
    PromptEvalRun,
    PromptPromotionDecision,
    PromptVersion,
)


class PromptEvaluationRepository:
    @transaction.atomic
    def record_run(self, payload: dict[str, Any]) -> PromptEvalRun:
        version = PromptVersion._default_manager.get(version_id=payload["version_id"])
        if version.status not in {"candidate", "evaluated"}:
            raise ValueError("only candidate/evaluated prompt versions may be evaluated")
        dataset = PromptEvalDataset._default_manager.get(dataset_id=payload["dataset_id"])
        run = PromptEvalRun._default_manager.create(
            run_id=uuid.uuid4().hex,
            prompt_version=version,
            dataset=dataset,
            evaluation_type=payload["evaluation_type"],
            provider=payload.get("provider", ""),
            model=payload.get("model", ""),
            temperature=payload.get("temperature", 0),
            max_cost=payload["max_cost"],
            max_tokens=payload["max_tokens"],
            max_cases=payload["max_cases"],
        )
        failures = []
        total_cost = Decimal("0")
        total_tokens = 0
        executed = 0
        seen_cases: set[str] = set()
        for result in payload.get("assertion_results", []):
            result_cost = Decimal(str(result.get("cost", 0)))
            result_tokens = int(result.get("tokens", 0))
            if (
                executed >= run.max_cases
                or total_cost + result_cost > run.max_cost
                or total_tokens + result_tokens > run.max_tokens
            ):
                failures.append({"code": "budget_exceeded", "case_id": result.get("case_id")})
                run.status = "budget_exceeded"
                break
            case = PromptEvalCase._default_manager.get(case_id=result["case_id"])
            if case.dataset_id != dataset.dataset_id:
                raise ValueError("evaluation case does not belong to the selected dataset")
            seen_cases.add(case.case_id)
            PromptEvalAssertion._default_manager.create(
                run=run,
                case=case,
                assertion_type=result["assertion_type"],
                passed=bool(result["passed"]),
                critical=bool(result.get("critical", True)),
                details=result.get("details", {}),
                latency_ms=int(result.get("latency_ms", 0)),
                tokens=result_tokens,
                cost=result_cost,
            )
            if not result["passed"]:
                failures.append(
                    {
                        "code": result["assertion_type"],
                        "case_id": result["case_id"],
                        "critical": bool(result.get("critical", True)),
                    }
                )
            total_cost += result_cost
            total_tokens += result_tokens
            executed += 1
        expected_case_ids = set(
            dataset.cases.values_list("case_id", flat=True)
        )
        if run.max_cases < len(expected_case_ids) or seen_cases != expected_case_ids:
            failures.append({"code": "incomplete_dataset", "critical": True})
        if run.status == "running":
            run.status = "failed" if any(item.get("critical") for item in failures) else "completed"
        run.actual_cost = total_cost
        run.actual_tokens = total_tokens
        run.executed_cases = executed
        run.failure_summary = failures
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "actual_cost",
                "actual_tokens",
                "executed_cases",
                "failure_summary",
                "completed_at",
            ]
        )
        if run.status == "completed" and version.status == "candidate":
            version.status = "evaluated"
            version.save(update_fields=["status"])
        return run

    @transaction.atomic
    def promote(self, version_id: str) -> PromptPromotionDecision:
        version = PromptVersion._default_manager.select_for_update().get(version_id=version_id)
        existing = PromptPromotionDecision._default_manager.filter(
            prompt_version=version
        ).first()
        if existing:
            return existing
        runs = list(version.eval_runs.all())
        if not runs:
            raise ValueError("prompt version has no evaluation runs")
        passing_types = {run.evaluation_type for run in runs if run.status == "completed"}
        reasons = []
        if version.status != "evaluated":
            reasons.append("version_not_evaluated")
        for required in ("offline", "online"):
            if required not in passing_types:
                reasons.append(f"missing_passing_{required}_run")
        if any(run.status == "budget_exceeded" for run in runs):
            reasons.append("budget_exceeded")
        critical_failures = PromptEvalAssertion._default_manager.filter(
            run__in=runs, critical=True, passed=False
        ).exists()
        if critical_failures:
            reasons.append("critical_assertion_failed")
        decision = "approved" if not reasons else "rejected"
        baseline = next((run for run in reversed(runs) if run.status == "completed"), None)
        promotion = PromptPromotionDecision._default_manager.create(
            decision_id=uuid.uuid5(uuid.NAMESPACE_URL, f"prompt-promotion:{version_id}").hex,
            prompt_version=version,
            eval_run=baseline or runs[-1],
            decision=decision,
            evidence={"reasons": reasons, "passing_types": sorted(passing_types)},
        )
        if decision == "approved":
            PromptVersion._default_manager.filter(
                template=version.template, status="active"
            ).update(status="retired")
            version.status = "active"
            version.save(update_fields=["status"])
            type(version.template)._default_manager.filter(pk=version.template_id).update(
                version=version.version,
                template_content=version.content,
                system_prompt=version.system_prompt,
                is_active=True,
            )
        return promotion
