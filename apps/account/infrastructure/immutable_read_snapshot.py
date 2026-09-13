"""Compatibility entry point for the shared immutable read mechanism."""

from shared.infrastructure.immutable_read_snapshot import (
    immutable_read_snapshot,
    reuse_immutable_read,
)

__all__ = ["immutable_read_snapshot", "reuse_immutable_read"]
