from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_record_codec import (
    CanonicalAccountOwnershipReobservationV1RecordCodecError,
    decode_canonical_account_ownership_reobservation_v1_record,
    encode_canonical_account_ownership_reobservation_v1_record,
)
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import (
    _reobservation,
)


def test_record_codec_round_trips_the_complete_nested_evidence() -> None:
    value = PersistedCanonicalAccountOwnershipReobservationV1(_reobservation())
    payload = encode_canonical_account_ownership_reobservation_v1_record(value)

    assert set(payload) == {
        "reobservation",
        "identity_hash",
        "content_hash",
        "record_seal",
        "ledger_seal",
    }
    assert all(len(cast(str, payload[name])) == 64 for name in set(payload) - {"reobservation"})
    assert decode_canonical_account_ownership_reobservation_v1_record(payload) == value


def test_record_codec_rejects_shape_and_nested_seal_tampering() -> None:
    value = PersistedCanonicalAccountOwnershipReobservationV1(_reobservation())
    payload = encode_canonical_account_ownership_reobservation_v1_record(value)

    with pytest.raises(CanonicalAccountOwnershipReobservationV1RecordCodecError, match="shape"):
        decode_canonical_account_ownership_reobservation_v1_record({**payload, "recorded_by": {}})

    tampered = deepcopy(payload)
    observation = cast(dict[str, object], tampered["reobservation"])
    observation["content_hash"] = "0" * 64
    with pytest.raises(CanonicalAccountOwnershipReobservationV1RecordCodecError):
        decode_canonical_account_ownership_reobservation_v1_record(tampered)

    for field_name in ("identity_hash", "content_hash", "record_seal", "ledger_seal"):
        altered = deepcopy(payload)
        altered[field_name] = "0" * 64
        with pytest.raises(CanonicalAccountOwnershipReobservationV1RecordCodecError):
            decode_canonical_account_ownership_reobservation_v1_record(altered)
