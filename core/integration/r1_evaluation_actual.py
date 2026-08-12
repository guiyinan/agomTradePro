"""App-neutral factory for the Data Center-owned R1 actual read repository."""

from __future__ import annotations

from collections.abc import Callable

_factory: Callable[[str], object] | None = None


def configure_r1_evaluation_actual_repository_factory(
    factory: Callable[[str], object],
) -> None:
    """Register the Data Center-owned strict read repository factory."""

    global _factory
    _factory = factory


def build_r1_evaluation_actual_repository(*, using: str) -> object:
    """Build the repository or fail closed before owner registration."""

    if _factory is None:
        raise RuntimeError("r1_evaluation_actual_repository_factory_unconfigured")
    return _factory(using)


__all__ = [
    "build_r1_evaluation_actual_repository",
    "configure_r1_evaluation_actual_repository_factory",
]
