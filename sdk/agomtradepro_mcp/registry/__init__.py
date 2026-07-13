"""Capability registry primitives for AgomTradePro MCP core tools."""

from .dispatcher import CapabilityDispatcher
from .loader import CapabilityRegistryLoader
from .manifest import CapabilityManifest, CapabilityManifestValidationError

__all__ = [
    "CapabilityDispatcher",
    "CapabilityManifest",
    "CapabilityManifestValidationError",
    "CapabilityRegistryLoader",
]
