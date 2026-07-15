"""Runtime compatibility helpers for the Playwright pytest suite."""

from __future__ import annotations

import asyncio
import sys
from typing import Any


def ensure_subprocess_event_loop_policy(
    *,
    platform: str | None = None,
    asyncio_module: Any = None,
) -> bool:
    """Use the subprocess-capable event-loop policy required by Playwright on Windows.

    Python's selector event loop cannot create subprocess transports on Windows.
    Playwright starts its driver as a subprocess, so the pytest process must use the
    proactor policy before the plugin's session fixtures are created.
    """
    resolved_platform = platform or sys.platform
    if resolved_platform != "win32":
        return False

    runtime = asyncio_module or asyncio
    proactor_policy_type = getattr(runtime, "WindowsProactorEventLoopPolicy", None)
    if proactor_policy_type is None:
        return False

    current_policy = runtime.get_event_loop_policy()
    if isinstance(current_policy, proactor_policy_type):
        return False

    runtime.set_event_loop_policy(proactor_policy_type())
    return True
