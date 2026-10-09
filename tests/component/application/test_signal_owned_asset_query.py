"""Cross-app position reads retain the signal ownership boundary."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.account.infrastructure.position_repository import PositionRepository
from apps.signal.application.owned_signal_queries import get_owned_signal_asset_code
from apps.signal.infrastructure.models import InvestmentSignalModel


@pytest.mark.django_db
def test_owned_signal_asset_query_preserves_owner_and_missing_filters():
    owner = get_user_model().objects.create_user(username="signal_asset_owner")
    stranger = get_user_model().objects.create_user(username="signal_asset_stranger")
    signal = InvestmentSignalModel.objects.create(
        user=owner,
        asset_code="000001.SZ",
        asset_class="equity",
        direction="LONG",
        logic_desc="Ownership regression fixture",
        target_regime="test",
    )
    assert get_owned_signal_asset_code(signal_id=signal.pk, user_id=owner.pk) == "000001.SZ"
    assert get_owned_signal_asset_code(signal_id=signal.pk, user_id=stranger.pk) is None
    assert get_owned_signal_asset_code(signal_id=0, user_id=owner.pk) is None
    assert get_owned_signal_asset_code(signal_id=signal.pk + 1, user_id=owner.pk) is None
    with patch("apps.account.infrastructure.position_repository.AccountRepository") as account:
        assert (
            PositionRepository().create_position_from_signal(
                user_id=stranger.pk, signal_id=signal.pk, price=Decimal("10")
            )
            is None
        )
    account.assert_not_called()
