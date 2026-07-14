"""Migration coverage for realtime alert persistence."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_realtime_alert_subscription_migration_is_reversible() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("realtime", "0001_alerts_subscriptions")])
        apps = executor.loader.project_state(
            [("realtime", "0001_alerts_subscriptions")]
        ).apps
        alert_model = apps.get_model("realtime", "PriceAlertModel")
        subscription_model = apps.get_model("realtime", "PriceSubscriptionModel")
        assert alert_model._meta.db_table == "realtime_price_alert"
        assert subscription_model._meta.db_table == "realtime_price_subscription"

        executor = MigrationExecutor(connection)
        executor.migrate([("realtime", None)])
        table_names = connection.introspection.table_names()
        assert "realtime_price_alert" not in table_names
        assert "realtime_price_subscription" not in table_names
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
