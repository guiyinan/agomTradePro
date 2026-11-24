"""A real Risk approval is valid only alongside its exact current policy and DB fences."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, OperationalError, connection

from apps.broker_execution.ash09_checkpoint_composition import bounded_checkpoint_diagnostic
from apps.risk_center.application.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationUnavailable,
)
from apps.risk_center.broker_checkpoint_composition import read_current_broker_order_risk
from apps.risk_center.infrastructure.broker_order_execution_policy_repository import (
    DjangoBrokerOrderExecutionPolicyRepository,
)
from apps.risk_center.infrastructure.broker_order_risk_authorization_repository import (
    DjangoBrokerOrderRiskAuthorizationRepository,
)
from tests.component.risk_center import test_broker_order_execution_policy_repository as policies
from tests.component.risk_center import test_broker_order_risk_authorization_repository as approvals


@pytest.mark.django_db
def test_sqlite_cannot_supply_a_transaction_fenced_risk_approval():
    if connection.vendor != "sqlite":
        pytest.skip("SQLite denial contract")
    with pytest.raises(BrokerOrderRiskAuthorizationUnavailable, match="PostgreSQL transaction"):
        read_current_broker_order_risk(account_id=41, client_order_id=uuid4(), using="default")


@pytest.mark.django_db
def test_risk_approval_requires_exact_current_policy_activation():
    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL transaction fences required")
    policy_clock = policies.FixedClock(policies.ACTIVATED_AT)
    policy_ledger = DjangoBrokerOrderExecutionPolicyRepository(clock=policy_clock)
    activation = policies._activate(policy_ledger, policies._source())
    policy = activation.policy
    now = policies.ACTIVATED_AT + timedelta(seconds=1)
    end = policy.valid_until - timedelta(minutes=1)
    scope = replace(
        approvals._scope(),
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.content_hash,
        policy_activation_hash=activation.content_hash,
        policy_valid_until=policy.valid_until,
        plan_valid_until=end,
        order_valid_until=end,
        execution_scope_valid_until=end,
        content_hash="",
    )
    subject = replace(
        approvals._subject(), scope=scope, requested_at=now, valid_until=end, content_hash=""
    )
    record = replace(
        approvals._record(approvals._subject()),
        subject=subject,
        issued_at=now,
        valid_until=end,
        content_hash="",
    )
    approval_ledger = DjangoBrokerOrderRiskAuthorizationRepository(clock=approvals.FixedClock(now))
    with approval_ledger.atomic():
        approval_ledger.append_subject(subject, recorded_at=now)
        approval_ledger.append(record, expected_predecessor_hash=None, recorded_at=now)
    order_id = UUID(scope.order_id)
    current = read_current_broker_order_risk(
        account_id=41, client_order_id=order_id, using="default"
    )
    assert current is not None
    assert current.authorization == record
    assert current.policy.policy_activation_hash == activation.content_hash
    policy_clock.value = policies.SECOND_AT
    source = policies._source(
        source_id="new-source", source_version="v2", recorded_at=policy_clock.value
    )
    command = policies._command(
        policy_id="new-policy", policy_version="v2", source_id="new-source", source_version="v2"
    )
    policies._activate(policy_ledger, source, command)
    assert (
        read_current_broker_order_risk(account_id=41, client_order_id=order_id, using="default")
        is None
    )


@pytest.mark.django_db
def test_empty_scope_blocks_new_raw_writes_on_every_risk_ledger_only_for_this_scope():
    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL transaction fences required")
    order_id = uuid4()
    assert (
        read_current_broker_order_risk(account_id=41, client_order_id=order_id, using="default")
        is None
    )
    writer = connection.copy()
    try:
        with writer.cursor() as cursor:
            cursor.execute("SET lock_timeout = '300ms'")
            for table, policy in (
                ("risk_center_broker_execution_policy_source", True),
                ("risk_center_broker_execution_policy_activation", True),
                ("risk_center_broker_order_risk_subject", False),
                ("risk_center_broker_order_risk_authorization", False),
            ):
                columns = "account_id" if policy else "account_id, order_id"
                placeholders = "%s" if policy else "%s, %s"
                statement = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
                with pytest.raises(OperationalError) as held:
                    cursor.execute(statement, (41,) if policy else (41, str(order_id)))
                assert held.value.__cause__.sqlstate == "55P03"
                # The unrelated insertion passes the trigger and reaches NOT NULL validation.
                with pytest.raises(IntegrityError) as unrelated:
                    cursor.execute(statement, (42,) if policy else (41, str(uuid4())))
                assert unrelated.value.__cause__.sqlstate == "23502"
    finally:
        writer.close()


@pytest.mark.django_db
def test_busy_pg_scope_honors_stricter_timeout_and_restores_the_outer_transaction():
    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL lock timeout required")
    order_id = uuid4()
    writer = connection.copy()
    try:
        writer.set_autocommit(False)
        with writer.cursor() as other:
            other.execute(
                "SELECT pg_advisory_xact_lock(risk_broker_checkpoint_scope(%s, %s, %s))",
                ("authorization", 41, str(order_id)),
            )
        with connection.cursor() as cursor:
            for original, expected in (("0", "250ms"), ("50ms", "50ms")):
                cursor.execute("SELECT set_config('lock_timeout', %s, true)", (original,))
                with pytest.raises(OperationalError) as held:
                    with bounded_checkpoint_diagnostic(using="default"):
                        cursor.execute("SHOW lock_timeout")
                        assert cursor.fetchone() == (expected,)
                        read_current_broker_order_risk(
                            account_id=41,
                            client_order_id=order_id,
                            using="default",
                        )
                assert held.value.__cause__.sqlstate == "55P03"
                cursor.execute("SHOW lock_timeout")
                assert cursor.fetchone() == (original,)
                with bounded_checkpoint_diagnostic(using="default"):
                    assert (
                        read_current_broker_order_risk(
                            account_id=41,
                            client_order_id=uuid4(),
                            using="default",
                        )
                        is None
                    )
                cursor.execute("SHOW lock_timeout")
                assert cursor.fetchone() == (original,)
    finally:
        writer.rollback()
        writer.close()
