"""Protect serialized and displayed identities while modernizing enum bases."""

import json
import pickle
from enum import Enum

import pytest

from apps.data_center.domain.contracts import FetchOutcome, PublicationState


@pytest.mark.parametrize("enum_type", [FetchOutcome, PublicationState])
def test_publication_enums_preserve_original_string_enum_contract(enum_type) -> None:
    """Compare each member with the original stdlib str/Enum behavior."""

    legacy_type = Enum(
        enum_type.__name__, {member.name: member.value for member in enum_type}, type=str
    )
    for member in enum_type:
        original = legacy_type[member.name]
        assert member == original == member.value
        assert hash(member) == hash(original)
        assert str(member) == str(original)
        assert repr(member) == repr(original)
        for format_spec in ("", ">40", ".5"):
            assert format(member, format_spec) == format(original, format_spec)
        assert enum_type(member.value) is member
        assert pickle.loads(pickle.dumps(member)) is member
    assert json.dumps(list(enum_type)) == json.dumps(list(legacy_type))
