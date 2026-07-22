"""Regression tests for the legacy-compatible alert service facade."""

from shared.infrastructure.alert_service import (
    AlertChannel,
    ConsoleAlertChannel,
    EmailAlertChannel,
    SlackAlertChannel,
    create_default_alert_service,
)


def test_default_service_composes_heterogeneous_channels() -> None:
    service = create_default_alert_service(
        slack_webhook="https://hooks.example.test/alert",
        email_config={
            "smtp_host": "localhost",
            "smtp_port": 25,
            "username": "",
            "password": "",
            "from_email": "alerts@example.test",
            "to_emails": ["ops@example.test"],
        },
        use_console=True,
    )

    assert [type(channel) for channel in service.channels] == [
        SlackAlertChannel,
        EmailAlertChannel,
        ConsoleAlertChannel,
    ]
    assert all(isinstance(channel, AlertChannel) for channel in service.channels)


def test_remove_channel_uses_alert_channel_class_contract() -> None:
    service = create_default_alert_service(use_console=True)

    service.remove_channel(ConsoleAlertChannel)

    assert service.channels == []
