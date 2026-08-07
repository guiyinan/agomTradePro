"""Qlib model evaluation orchestration shared by Celery entrypoints."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any


def evaluate_model_artifact(
    *,
    model_artifact_hash: str,
    as_of_date: date,
    registry_repository: Any,
    evaluator: Callable[..., Any],
) -> dict[str, Any]:
    """Evaluate one registered artifact and persist its latest metrics."""

    model = registry_repository.get_by_artifact_hash(model_artifact_hash)
    metrics = evaluator(
        model_artifact_hash=model_artifact_hash,
        universe_id=model.universe,
        start_date=as_of_date - timedelta(days=60),
        end_date=as_of_date,
    )
    model = registry_repository.update_metrics(
        artifact_hash=model_artifact_hash,
        ic=metrics.ic,
        icir=metrics.icir,
        rank_ic=metrics.rank_ic,
    )
    return {
        "status": "success",
        "model_artifact_hash": model_artifact_hash,
        "ic": float(model.ic) if model.ic else None,
        "icir": float(model.icir) if model.icir else None,
    }


__all__ = ["evaluate_model_artifact"]
