"""Node-region context shared by the native Data Center adapters."""

import os


def _deployment_region() -> str:
    """Read the explicit node-region label used by egress rules."""

    return (
        str(
            os.environ.get("DATA_CENTER_DEPLOYMENT_REGION")
            or os.environ.get("AGOMTRADEPRO_DEPLOYMENT_REGION")
            or "unknown"
        )
        .strip()
        .lower()
        or "unknown"
    )
