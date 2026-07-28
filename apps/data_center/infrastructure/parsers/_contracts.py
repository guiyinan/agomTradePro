"""Minimal dataframe contracts used by external market payload parsers."""

from collections.abc import Iterator
from typing import Protocol


class ExternalRowProtocol(Protocol):
    """Mapping-like row surface exposed by pandas Series and test fakes."""

    def get(self, key: str, default: object = None) -> object:
        """Return one external field without assuming a concrete dataframe type."""
        ...


class ExternalDataFrameProtocol(Protocol):
    """Minimal dataframe iteration surface used by batch parsers."""

    @property
    def empty(self) -> bool:
        """Return whether the frame has no rows."""
        ...

    def iterrows(self) -> Iterator[tuple[object, ExternalRowProtocol]]:
        """Yield external row objects."""
        ...
