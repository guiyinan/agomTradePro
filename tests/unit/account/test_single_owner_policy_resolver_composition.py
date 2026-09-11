"""The public policy resolver factory binds an explicit alias without opening it."""

import pytest
from django.db import connections

from apps.account.application.single_owner_policy_resolution import (
    ResolveCurrentSingleOwnerPolicyBinding,
)
from apps.account.single_owner_authority_policy_composition import (
    build_current_single_owner_policy_resolver,
)


def test_unregistered_alias_can_be_composed_without_opening_database():
    alias = "policy-resolver-composition-only"
    assert alias not in connections.databases
    assert (
        type(build_current_single_owner_policy_resolver(using=alias))
        is ResolveCurrentSingleOwnerPolicyBinding
    )
    assert alias not in connections.databases


@pytest.mark.parametrize("alias", [None, True, "", " default", "two aliases"])
def test_invalid_alias_is_rejected_before_database_access(alias):
    with pytest.raises(ValueError, match="database alias"):
        build_current_single_owner_policy_resolver(using=alias)
