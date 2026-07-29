"""Always-on guard for critical Celery task behavioral evidence."""

from scripts.check_celery_task_contracts import validate_celery_task_contracts


def test_critical_celery_tasks_have_versioned_contract_evidence() -> None:
    """Block task additions or evidence deletion in governed critical files."""

    violations = validate_celery_task_contracts()
    assert not violations, "\n".join(f"[{item.code}] {item.message}" for item in violations)
