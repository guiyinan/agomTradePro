"""Signal query repository tests."""

import pytest

from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.infrastructure.repositories import DjangoSignalRepository


@pytest.mark.django_db
def test_get_valid_signal_summaries_returns_only_approved_signals():
    repo = DjangoSignalRepository()

    approved = InvestmentSignalModel.objects.create(
        asset_code="000001.SZ",
        asset_class="equity",
        direction="LONG",
        logic_desc="approved signal",
        target_regime="Recovery",
        status="approved",
    )
    InvestmentSignalModel.objects.create(
        asset_code="000001.SZ",
        asset_class="equity",
        direction="LONG",
        logic_desc="invalidated signal",
        target_regime="Recovery",
        status="invalidated",
    )
    InvestmentSignalModel.objects.create(
        asset_code="000001.SZ",
        asset_class="equity",
        direction="LONG",
        logic_desc="rejected signal",
        target_regime="Recovery",
        status="rejected",
    )
    InvestmentSignalModel.objects.create(
        asset_code="000001.SZ",
        asset_class="equity",
        direction="LONG",
        logic_desc="expired signal",
        target_regime="Recovery",
        status="expired",
    )

    summaries = repo.get_valid_signal_summaries(["000001.SZ"])

    assert [summary["id"] for summary in summaries] == [approved.id]
    assert summaries[0]["logic_desc"] == "approved signal"
