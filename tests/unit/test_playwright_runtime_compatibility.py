"""Tests for the Playwright pytest runtime compatibility guard."""

from tests.playwright.runtime_compatibility import (
    ensure_subprocess_event_loop_policy,
)


class _SelectorPolicy:
    """Stand-in for the Windows selector event-loop policy."""


class _ProactorPolicy:
    """Stand-in for the Windows proactor event-loop policy."""


class _FakeAsyncio:
    WindowsProactorEventLoopPolicy = _ProactorPolicy

    def __init__(self, policy: object) -> None:
        self.policy = policy
        self.set_calls = 0

    def get_event_loop_policy(self) -> object:
        return self.policy

    def set_event_loop_policy(self, policy: object) -> None:
        self.policy = policy
        self.set_calls += 1


def test_windows_selector_policy_is_replaced() -> None:
    """Windows Playwright needs the subprocess-capable proactor policy."""
    asyncio_module = _FakeAsyncio(_SelectorPolicy())

    changed = ensure_subprocess_event_loop_policy(
        platform="win32",
        asyncio_module=asyncio_module,
    )

    assert changed is True
    assert isinstance(asyncio_module.policy, _ProactorPolicy)
    assert asyncio_module.set_calls == 1


def test_existing_proactor_policy_is_preserved() -> None:
    """Do not replace a policy that already supports subprocesses."""
    asyncio_module = _FakeAsyncio(_ProactorPolicy())

    changed = ensure_subprocess_event_loop_policy(
        platform="win32",
        asyncio_module=asyncio_module,
    )

    assert changed is False
    assert asyncio_module.set_calls == 0


def test_non_windows_platform_is_unchanged() -> None:
    """Other platforms must retain their native event-loop policy."""
    asyncio_module = _FakeAsyncio(_SelectorPolicy())

    changed = ensure_subprocess_event_loop_policy(
        platform="linux",
        asyncio_module=asyncio_module,
    )

    assert changed is False
    assert asyncio_module.set_calls == 0
