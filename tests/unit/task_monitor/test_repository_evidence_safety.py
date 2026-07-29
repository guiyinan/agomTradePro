"""Task-monitor persisted evidence safety boundaries."""

from apps.task_monitor.infrastructure.repositories import _to_json_compatible


def test_task_evidence_redacts_nested_credentials_and_non_finite_values() -> None:
    secret = "postgresql://operator:secret@db.internal/tasks"

    payload = _to_json_compatible(
        {
            "authorization": "Bearer top-secret",
            "nested": {
                "endpoint": secret,
                "score": float("nan"),
            },
        }
    )

    rendered = repr(payload)
    assert "top-secret" not in rendered
    assert "operator:secret" not in rendered
    assert "[REDACTED]" in rendered
    assert payload["nested"]["score"] is None


def test_task_evidence_replaces_unknown_dynamic_objects() -> None:
    class ProviderObject:
        def __str__(self) -> str:
            return "token=should-not-be-persisted"

    payload = _to_json_compatible({"provider": ProviderObject()})

    assert payload == {"provider": "<ProviderObject>"}
