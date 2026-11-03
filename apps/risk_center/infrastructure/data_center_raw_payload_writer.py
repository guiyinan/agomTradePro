"""Adapter to the public Data Center application RawPayload write boundary."""

from __future__ import annotations

from apps.data_center.application.raw_landing_public import land_raw_payload
from apps.data_center.domain.raw_landing import RawPayload


class DataCenterRawPayloadWriter:
    """Delegate an already validated payload to Data Center's ready-registered port."""

    def land(self, payload: RawPayload) -> RawPayload:
        """Persist one immutable payload without importing Data Center infrastructure."""

        return land_raw_payload(payload)


__all__ = ("DataCenterRawPayloadWriter",)
