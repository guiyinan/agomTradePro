"""Django Admin autodiscovery entry point for Sector registrations."""

from apps.sector.interface.admin import (
    SectorIndexAdmin,
    SectorInfoAdmin,
    SectorPreferenceConfigAdmin,
    SectorRelativeStrengthAdmin,
)

__all__ = [
    "SectorIndexAdmin",
    "SectorInfoAdmin",
    "SectorPreferenceConfigAdmin",
    "SectorRelativeStrengthAdmin",
]
