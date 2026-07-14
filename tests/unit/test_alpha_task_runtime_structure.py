"""Structural contracts for Alpha Qlib Celery task runtimes."""

from apps.alpha.application import tasks
from apps.alpha.infrastructure import (
    qlib_artifact_runtime,
    qlib_prediction_runtime,
    qlib_runtime_init,
)


def test_qlib_tasks_delegate_runtime_implementation_to_infrastructure() -> None:
    """Keep task registration in Application while moving runtime-heavy helpers."""
    assert tasks._get_qlib_data_latest_date is qlib_runtime_init.get_qlib_data_latest_date
    assert (
        tasks._execute_qlib_prediction.runtime_implementation
        is qlib_prediction_runtime.execute_qlib_prediction
    )
    assert tasks._train_qlib_model is qlib_artifact_runtime.train_qlib_model

    assert tasks.qlib_predict_scores.name == "apps.alpha.application.tasks.qlib_predict_scores"
    assert callable(tasks.qlib_predict_scores.delay)
    assert callable(tasks.qlib_predict_scores.apply)
    assert callable(tasks.qlib_predict_scores.apply_async)
