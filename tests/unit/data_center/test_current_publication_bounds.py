"""A current publication must retain its own explicit source-time boundary."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.data_center.test_current_publication_evidence import (
    OBSERVED,
    _fact_hashes,
    _member,
    _policy,
    _publication,
    _reason,
)


@pytest.mark.parametrize("as_of", [None, OBSERVED - timedelta(seconds=1)])
def test_current_requires_explicit_as_of_covering_every_member(as_of) -> None:
    policy = _policy()
    members = (_member(),)
    publication = replace(_publication(policy, members), as_of=as_of)
    assert (
        _reason(publication, policy, members, _fact_hashes(members))
        == "publication_knowledge_unavailable"
    )
