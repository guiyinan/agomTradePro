"""Safety contract for bounded no-follow S6 evidence reads."""

import os
from pathlib import Path

import pytest

from shared.release_rehearsal_file_io import RehearsalFileReadError, read_regular_file


def test_reads_regular_file_beneath_root(tmp_path: Path) -> None:
    (tmp_path / "evidence.json").write_bytes(b"{}")

    assert read_regular_file(tmp_path, "evidence.json", 16) == b"{}"


def test_rejects_file_larger_than_bound(tmp_path: Path) -> None:
    (tmp_path / "large.bin").write_bytes(b"12345")

    with pytest.raises(RehearsalFileReadError, match="file_too_large"):
        read_regular_file(tmp_path, "large.bin", 4)


@pytest.mark.linux_symlink
def test_rejects_symlink_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    link = tmp_path / "evidence.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(RehearsalFileReadError):
        read_regular_file(tmp_path, "evidence.json", 16)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO files are not supported")
def test_rejects_fifo_without_blocking_on_open(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "capture.frb")

    with pytest.raises(RehearsalFileReadError):
        read_regular_file(tmp_path, "capture.frb", 1024)


@pytest.mark.linux_symlink
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO files are not supported")
def test_rejects_fifo_swapped_between_stat_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "capture.frb"
    artifact.write_bytes(b"regular evidence")
    real_open = os.open

    def swap_to_fifo(path: str, flags: int, *, dir_fd: int | None = None) -> int:
        if path == artifact.name and dir_fd is not None:
            artifact.unlink()
            os.mkfifo(artifact)
            assert flags & getattr(os, "O_NONBLOCK", 0)
        return real_open(path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_to_fifo)
    with pytest.raises(RehearsalFileReadError):
        read_regular_file(tmp_path, artifact.name, 1024)
