"""Agent Runtime interface serializer contract tests."""

from types import SimpleNamespace

from apps.agent_runtime.interface.serializers import AgentTaskSerializer


class _RelatedRows:
    """Minimal reverse-relation counter used by serializer tests."""

    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        """Return the configured relation count."""

        return self._count


def test_agent_task_related_counts_use_dynamic_orm_boundary() -> None:
    """Serialize each reverse relation as an explicit integer count."""

    task = SimpleNamespace(
        steps=_RelatedRows(1),
        proposals=_RelatedRows(2),
        artifacts=_RelatedRows(3),
        timeline_events=_RelatedRows(4),
    )
    serializer = AgentTaskSerializer()

    assert serializer.get_steps_count(task) == 1
    assert serializer.get_proposals_count(task) == 2
    assert serializer.get_artifacts_count(task) == 3
    assert serializer.get_timeline_events_count(task) == 4
