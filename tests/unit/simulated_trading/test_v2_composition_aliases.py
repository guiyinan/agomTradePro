from __future__ import annotations

from typing import cast

import pytest

from apps.simulated_trading import account_physical_row_v2_composition, source_v2_composition


class _RepositorySpy:
    """Capture the alias used by a composition root without touching a database."""

    def __init__(self, *, using: str = "default") -> None:
        self.using = using


def test_raw_source_builder_passes_explicit_and_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raw provider receives the requested repository alias, including legacy default."""

    created: list[_RepositorySpy] = []

    def build_spy(*, using: str = "default") -> _RepositorySpy:
        repository = _RepositorySpy(using=using)
        created.append(repository)
        return repository

    monkeypatch.setattr(
        source_v2_composition,
        "DjangoSimulatedAccountRawObservationRepository",
        build_spy,
    )

    explicit = source_v2_composition.build_exact_raw_simulated_account_observation_v2_provider(
        using="staging"
    )
    default = source_v2_composition.build_exact_raw_simulated_account_observation_v2_provider()

    assert [repository.using for repository in created] == ["staging", "default"]
    assert explicit._repository is created[0]  # type: ignore[attr-defined]
    assert default._repository is created[1]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "invalid_alias",
    [None, True, 0, "", " ", " staging", "staging ", "staging alias"],
)
def test_raw_source_builder_rejects_invalid_alias_without_constructing_repository(
    monkeypatch: pytest.MonkeyPatch,
    invalid_alias: object,
) -> None:
    """Invalid aliases fail before the raw repository dependency is created."""

    created: list[object] = []

    def fail_if_constructed(*, using: str = "default") -> object:
        created.append(using)
        raise AssertionError("repository must not be constructed")

    monkeypatch.setattr(
        source_v2_composition,
        "DjangoSimulatedAccountRawObservationRepository",
        fail_if_constructed,
    )

    with pytest.raises(ValueError, match="database alias"):
        source_v2_composition.build_exact_raw_simulated_account_observation_v2_provider(
            using=cast(str, invalid_alias)
        )

    assert created == []


def test_physical_row_builder_passes_explicit_and_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The physical-row provider receives the requested repository alias."""

    created: list[_RepositorySpy] = []

    def build_spy(*, using: str = "default") -> _RepositorySpy:
        repository = _RepositorySpy(using=using)
        created.append(repository)
        return repository

    monkeypatch.setattr(
        account_physical_row_v2_composition,
        "DjangoSimulatedAccountRowSourceV2Repository",
        build_spy,
    )

    explicit = account_physical_row_v2_composition.build_account_physical_row_v2_provider(
        using="staging"
    )
    default = account_physical_row_v2_composition.build_account_physical_row_v2_provider()

    assert [repository.using for repository in created] == ["staging", "default"]
    assert explicit._repository is created[0]  # type: ignore[attr-defined]
    assert default._repository is created[1]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "invalid_alias",
    [None, True, 0, "", " ", " staging", "staging ", "staging alias"],
)
def test_physical_row_builder_rejects_invalid_alias_without_constructing_repository(
    monkeypatch: pytest.MonkeyPatch,
    invalid_alias: object,
) -> None:
    """Invalid aliases fail before the source-v2 repository dependency is created."""

    created: list[object] = []

    def fail_if_constructed(*, using: str = "default") -> object:
        created.append(using)
        raise AssertionError("repository must not be constructed")

    monkeypatch.setattr(
        account_physical_row_v2_composition,
        "DjangoSimulatedAccountRowSourceV2Repository",
        fail_if_constructed,
    )

    with pytest.raises(ValueError, match="database alias"):
        account_physical_row_v2_composition.build_account_physical_row_v2_provider(
            using=cast(str, invalid_alias)
        )

    assert created == []
