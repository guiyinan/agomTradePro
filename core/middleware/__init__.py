"""
Core middleware for AgomSAAF.
"""

from core.middleware.deprecation import DeprecationHeaderMiddleware

__all__ = ['DeprecationHeaderMiddleware']
