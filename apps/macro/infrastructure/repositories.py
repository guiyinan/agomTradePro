"""Legacy import shim for macro repositories.

Runtime macro reads and writes are fully backed by ``data_center_compat``.
This module is retained only so older imports continue to resolve without
touching the deprecated ``macro_indicator`` / ``indicator_unit_config``
storage implementation.
"""

from .data_center_compat import DjangoMacroRepository, MacroIndicatorReadRepository

__all__ = ["DjangoMacroRepository", "MacroIndicatorReadRepository"]
