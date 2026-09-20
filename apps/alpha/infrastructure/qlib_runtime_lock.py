"""Cross-process exclusion for shared Qlib feature builds and predictions."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from core.exceptions import DataFetchError


@contextmanager
def qlib_runtime_lock(provider_uri: str | Path, *, read_only: bool = False) -> Iterator[None]:
    """Fail closed when another process is using this shared feature directory."""
    root = Path(provider_uri).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".qlib-runtime.lock").open("a+b") as handle:
        try:
            if sys.platform == "win32":
                import msvcrt

                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(
                    handle.fileno(), msvcrt.LK_NBRLCK if read_only else msvcrt.LK_NBLCK, 1
                )
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(), (fcntl.LOCK_SH if read_only else fcntl.LOCK_EX) | fcntl.LOCK_NB
                )
        except OSError as exc:
            raise DataFetchError(
                "Qlib shared data is being refreshed or read",
                code="MODEL_MARKET_REFRESH_BUSY",
            ) from exc
        yield
