"""Compatibility alias for the operational-readiness owner."""

import sys
from importlib import import_module

_module = import_module(
    "apps.operational_readiness.management.commands.simulate_personal_readiness_checkpoints"
)
sys.modules[__name__] = _module
