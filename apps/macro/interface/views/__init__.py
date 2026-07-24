"""
Views package for Macro app.

This package contains all view functions organized by functionality.
"""

from .page_views import (
    data_controller_view,
    macro_data_view,
)

__all__ = [
    "macro_data_view",
    "data_controller_view",
]
