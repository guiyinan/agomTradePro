"""T5 delivery and configuration contracts for shared alert channels."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from shared.infrastructure import alerts
from shared.infrastructure.alerts import (
    AlertChannel,
    AlertMessage,
    AlertService,
    DingTalkAlertChannel,
    EmailAlertChannel,
    SlackAlertChannel,
    WeChatWorkAlertChannel,
)


@pytest.fixture(autouse=True)
def reset_global_alert_service() -> Iterator[None]:
    """Keep the module singleton isolated between contract tests."""
    alerts._alert_service = None
    yield
    alerts._alert_service = None


def _message(level: str = "WARNING") -> AlertMessage:
    """Build a deterministic alert with metadata for payload assertions."""
    return AlertMessage(
        title="provider degraded",
        content="line one\nline two",
        level=level,
        timestamp=datetime(2026, 7, 25, 1, 2, 3, tzinfo=UTC),
        metadata={"provider": "qlib"},
    )


def test_base_channel_requires_a_concrete_delivery_implementation() -> None:
    """The abstract-by-convention channel must reject direct sends."""
    with pytest.raises(NotImplementedError):
        AlertChannel().send(_message())


def test_email_channel_formats_and_delivers_multipart_message() -> None:
    """Email delivery must authenticate, send both formats, and use TLS."""
    smtp = Mock()
    smtp.__enter__ = Mock(return_value=smtp)
    smtp.__exit__ = Mock(return_value=False)
    channel = EmailAlertChannel(
        smtp_host="smtp.example.test",
        smtp_port=587,
        username="operator",
        password="secret",
        from_addr="alerts@example.test",
        to_addrs=["one@example.test", "two@example.test"],
    )

    with patch("shared.infrastructure.alerts.smtplib.SMTP", return_value=smtp) as factory:
        assert channel.send(_message()) is True

    factory.assert_called_once_with("smtp.example.test", 587)
    smtp.starttls.assert_called_once_with()
    smtp.login.assert_called_once_with("operator", "secret")
    sent = smtp.send_message.call_args.args[0]
    assert sent["Subject"] == "[WARNING] provider degraded"
    assert sent["To"] == "one@example.test, two@example.test"
    assert len(sent.get_payload()) == 2

    text = channel._format_text(_message())
    html = channel._format_html(_message())
    assert "详细信息:" in text
    assert "provider: qlib" in text
    assert "#FF9800" in html
    assert "line one<br>line two" in html


def test_email_channel_supports_plain_payload_and_isolates_smtp_failure() -> None:
    """Formatting without metadata and SMTP errors are stable contracts."""
    channel = EmailAlertChannel(
        smtp_host="smtp.example.test",
        smtp_port=25,
        username="",
        password="",
        from_addr="alerts@example.test",
        to_addrs=["ops@example.test"],
        use_tls=False,
    )
    plain = AlertMessage(
        title="health",
        content="ok",
        level="CUSTOM",
        timestamp=datetime(2026, 7, 25, tzinfo=UTC),
    )
    assert "详细信息:" not in channel._format_text(plain)
    assert "#666666" in channel._format_html(plain)

    with patch(
        "shared.infrastructure.alerts.smtplib.SMTP",
        side_effect=OSError("smtp offline"),
    ):
        assert channel.send(plain) is False


@pytest.mark.parametrize(
    ("channel", "payload_keyword"),
    [
        (
            SlackAlertChannel(
                "https://hooks.example.test/slack",
                channel="#operations",
                username="coverage-bot",
            ),
            "json",
        ),
        (DingTalkAlertChannel("https://hooks.example.test/dingtalk"), "data"),
        (WeChatWorkAlertChannel("https://hooks.example.test/wechat"), "data"),
    ],
)
def test_webhook_channels_emit_metadata_payloads(
    channel: AlertChannel,
    payload_keyword: str,
) -> None:
    """Webhook adapters must preserve routing, severity, and metadata."""
    response = Mock()
    with patch("shared.infrastructure.alerts.requests.post", return_value=response) as post:
        assert channel.send(_message("CRITICAL")) is True

    response.raise_for_status.assert_called_once_with()
    raw_payload = post.call_args.kwargs[payload_keyword]
    payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
    if isinstance(channel, SlackAlertChannel):
        assert payload["channel"] == "#operations"
        assert payload["attachments"][0]["color"] == "#D32F2F"
        assert payload["attachments"][0]["fields"][-1]["value"] == "qlib"
    elif isinstance(channel, DingTalkAlertChannel):
        assert payload["msgtype"] == "markdown"
        assert "- provider: qlib" in payload["markdown"]["text"]
    else:
        assert payload["msgtype"] == "markdown"
        assert "provider: qlib" in payload["markdown"]["content"]


@pytest.mark.parametrize(
    "channel",
    [
        SlackAlertChannel("https://hooks.example.test/slack"),
        DingTalkAlertChannel("https://hooks.example.test/dingtalk"),
        WeChatWorkAlertChannel("https://hooks.example.test/wechat"),
    ],
)
def test_webhook_channels_convert_transport_failures_to_false(
    channel: AlertChannel,
) -> None:
    """A failed outbound request must not escape the alert boundary."""
    with patch(
        "shared.infrastructure.alerts.requests.post",
        side_effect=OSError("network offline"),
    ):
        assert channel.send(AlertMessage(title="health", content="down")) is False


class _RecordingChannel(AlertChannel):
    """Capture messages and return a configured outcome."""

    def __init__(self, outcome: bool = True) -> None:
        self.outcome = outcome
        self.messages: list[AlertMessage] = []

    def send(self, message: AlertMessage) -> bool:
        """Record the delivered message."""
        self.messages.append(message)
        return self.outcome


def test_service_convenience_methods_preserve_severity_and_metadata() -> None:
    """Convenience methods must delegate normalized messages to all channels."""
    channel = _RecordingChannel()
    service = AlertService()
    service.add_channel(channel)

    calls = [
        service.send_info("info", "body", metadata={"ordinal": 1}),
        service.send_warning("warning", "body"),
        service.send_error("error", "body"),
        service.send_critical("critical", "body"),
    ]

    assert calls == [{"_RecordingChannel": True}] * 4
    assert [message.level for message in channel.messages] == [
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]
    assert channel.messages[0].metadata == {"ordinal": 1}


def test_environment_factory_builds_all_configured_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment configuration must compose all supported channel types once."""
    configuration = {
        "ALERT_SMTP_HOST": "smtp.example.test",
        "ALERT_SMTP_PORT": "2525",
        "ALERT_SMTP_USERNAME": "operator",
        "ALERT_SMTP_PASSWORD": "secret",
        "ALERT_EMAIL_FROM": "alerts@example.test",
        "ALERT_EMAIL_TO": "one@example.test,two@example.test",
        "ALERT_SLACK_WEBHOOK": "https://hooks.example.test/slack",
        "ALERT_DINGTALK_WEBHOOK": "https://hooks.example.test/dingtalk",
        "ALERT_WECHAT_WEBHOOK": "https://hooks.example.test/wechat",
    }
    for key, value in configuration.items():
        monkeypatch.setenv(key, value)

    service = alerts.get_alert_service()

    assert service is alerts.get_alert_service()
    assert [type(channel) for channel in service.channels] == [
        EmailAlertChannel,
        SlackAlertChannel,
        DingTalkAlertChannel,
        WeChatWorkAlertChannel,
    ]
    email = service.channels[0]
    assert isinstance(email, EmailAlertChannel)
    assert email.smtp_port == 2525
    assert email.to_addrs == ["one@example.test", "two@example.test"]


def test_send_alert_uses_the_singleton_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public helper must construct a message and delegate to the singleton."""
    channel = _RecordingChannel(False)
    service = AlertService([channel])
    monkeypatch.setattr(alerts, "_alert_service", service)

    assert alerts.send_alert(
        "latency",
        "threshold exceeded",
        level="ERROR",
        metadata={"milliseconds": 900},
    ) == {"_RecordingChannel": False}
    assert channel.messages[0].level == "ERROR"
    assert channel.messages[0].metadata == {"milliseconds": 900}
