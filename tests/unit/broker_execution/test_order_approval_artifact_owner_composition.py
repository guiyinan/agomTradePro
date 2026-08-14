"""App-root factory tests for the Broker order artifact owner reader."""

from inspect import signature

from apps.broker_execution.application.order_approval_artifact_owner_reader import (
    BrokerOrderApprovalArtifactOwnerReader,
)
from apps.broker_execution.infrastructure.order_approval_artifact_owner_reader_repository import (
    DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository,
)
from apps.broker_execution.order_approval_artifact_owner_composition import (
    build_django_broker_order_approval_artifact_owner_reader,
)


def test_factory_is_using_only_and_builds_read_only_owner_graph() -> None:
    assert tuple(
        signature(build_django_broker_order_approval_artifact_owner_reader).parameters
    ) == ("using",)

    reader = build_django_broker_order_approval_artifact_owner_reader(using="default")

    assert isinstance(reader, BrokerOrderApprovalArtifactOwnerReader)
    repository = object.__getattribute__(reader, "_repository")
    assert isinstance(repository, DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository)
    assert not hasattr(repository, "append")
    assert not hasattr(repository, "atomic")
    assert not hasattr(repository, "get_exact")


def test_factory_module_exports_only_the_read_factory() -> None:
    from apps.broker_execution import order_approval_artifact_owner_composition as composition

    assert composition.__all__ == ["build_django_broker_order_approval_artifact_owner_reader"]
