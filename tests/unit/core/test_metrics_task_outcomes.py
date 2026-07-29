"""Business-outcome coverage for Celery Prometheus metrics."""

from unittest.mock import patch

from core.metrics import track_celery_task


def test_track_celery_task_records_returned_business_failure() -> None:
    """A normal Python return must not hide a failed task business outcome."""

    @track_celery_task
    def sample_task() -> dict[str, object]:
        return {"success": False, "outcome": "failed", "error": "provider down"}

    with patch("core.metrics.record_celery_task") as record_metric:
        result = sample_task()

    assert result["success"] is False
    assert record_metric.call_args.kwargs["status"] == "failed"


def test_track_celery_task_records_partial_and_unknown_outcomes() -> None:
    """Preserve partial visibility while keeping legacy non-payload tasks compatible."""

    @track_celery_task
    def partial_task() -> dict[str, object]:
        return {"success": True, "outcome": "partial"}

    @track_celery_task
    def legacy_task() -> str:
        return "ok"

    with patch("core.metrics.record_celery_task") as record_metric:
        partial_task()
        legacy_task()

    assert [call.kwargs["status"] for call in record_metric.call_args_list] == [
        "partial",
        "success",
    ]
