"""Behavioral regression tests for the shared multi-channel alert service."""

from __future__ import annotations

from unittest.mock import Mock, patch

from shared.infrastructure.alerts import (
    AlertChannel,
    AlertMessage,
    AlertService,
    EmailAlertChannel,
    SlackAlertChannel,
)


class SuccessfulChannel(AlertChannel):
    def send(self, message: AlertMessage) -> bool:
        return True


class FailingChannel(AlertChannel):
    def send(self, message: AlertMessage) -> bool:
        raise RuntimeError("offline")


def test_alert_message_defaults_are_complete_and_isolated() -> None:
    first = AlertMessage(title="one", content="body")
    second = AlertMessage(title="two", content="body")

    first.metadata["source"] = "test"

    assert first.timestamp.tzinfo is not None
    assert second.metadata == {}


def test_alert_service_isolates_channel_failure() -> None:
    service = AlertService([SuccessfulChannel(), FailingChannel()])

    results = service.send(AlertMessage(title="health", content="check"))

    assert results == {"SuccessfulChannel": True, "FailingChannel": False}


def test_slack_channel_sends_structured_timestamp_and_metadata() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    message = AlertMessage(
        title="provider down",
        content="qlib is unavailable",
        level="CRITICAL",
        metadata={"provider": "qlib"},
    )

    with patch("shared.infrastructure.alerts.requests.post", return_value=response) as post:
        success = SlackAlertChannel("https://hooks.example.test/alert").send(message)

    assert success is True
    payload = post.call_args.kwargs["json"]
    assert payload["attachments"][0]["ts"] == int(message.timestamp.timestamp())
    assert payload["attachments"][0]["fields"][-1]["title"] == "provider"
    response.raise_for_status.assert_called_once_with()


def test_email_formatter_uses_initialized_timestamp() -> None:
    channel = EmailAlertChannel(
        smtp_host="localhost",
        smtp_port=25,
        username="",
        password="",
        from_addr="alerts@example.test",
        to_addrs=["ops@example.test"],
    )
    message = AlertMessage(title="health", content="all good")

    output = channel._format_text(message)

    assert f"时间: {message.timestamp:%Y-%m-%d %H:%M:%S}" in output
