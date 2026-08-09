"""Non-persistent compatibility shape for account and backup user interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SystemSettingsProjection:
    """Typed view projection backed only by canonical Config Center owners."""

    MARKET_COLOR_CONVENTION_CHOICES = [
        ("cn_a_share", "A股红涨绿跌"),
        ("us_market", "美股绿涨红跌"),
    ]
    ALPHA_POOL_MODE_STRICT_VALUATION = "strict_valuation"
    ALPHA_POOL_MODE_CHOICES = [
        ("strict_valuation", "严格估值股票池"),
        ("market", "市场股票池"),
    ]

    pk: int = 1
    require_user_approval: bool = True
    auto_approve_first_admin: bool = False
    default_mcp_enabled: bool = False
    allow_token_plaintext_view: bool = False
    user_agreement_content: str = ""
    risk_warning_content: str = ""
    notes: str = ""
    market_color_convention: str = "cn_a_share"
    alpha_pool_mode: str = ""
    benchmark_code_map: dict[str, str] = field(default_factory=dict)
    asset_proxy_code_map: dict[str, str] = field(default_factory=dict)
    backup_enabled: bool = False
    backup_email: str = ""
    backup_app_base_url: str = ""
    backup_mail_from_email: str = ""
    backup_smtp_host: str = ""
    backup_smtp_port: int = 0
    backup_smtp_username: str = ""
    backup_smtp_use_tls: bool = False
    backup_smtp_use_ssl: bool = False
    backup_interval_days: int = 0
    backup_link_ttl_days: int = 0
    backup_password_hint: str = ""
    backup_last_sent_at: datetime | None = None
    backup_download_token_digest: str = ""
    backup_download_token_expires_at: datetime | None = None
    backup_download_consumed_at: datetime | None = None
    updated_at: datetime | None = None
    _backup_password: str = field(default="", repr=False)
    _backup_smtp_password: str = field(default="", repr=False)

    def attach_backup_password(self, raw_password: str) -> None:
        """Attach a resolved canonical archive password to this ephemeral view."""

        self._backup_password = str(raw_password or "")

    def get_backup_password(self) -> str:
        """Return the resolved canonical archive password for internal delivery code."""

        return self._backup_password

    def attach_backup_smtp_password(self, raw_password: str) -> None:
        """Attach a resolved canonical SMTP password to this ephemeral view."""

        self._backup_smtp_password = str(raw_password or "")

    def get_backup_smtp_password(self) -> str:
        """Return the resolved canonical SMTP password for internal delivery code."""

        return self._backup_smtp_password

    def is_backup_due(self, now: datetime | None = None) -> bool:
        """Return whether the canonical policy permits a delivery now."""

        if (
            not self.backup_enabled
            or not self.backup_email
            or not self.get_backup_password()
            or self.backup_interval_days < 1
        ):
            return False
        current = now or datetime.now(UTC)
        if self.backup_last_sent_at is None:
            return True
        return bool((current - self.backup_last_sent_at).days >= self.backup_interval_days)

    def save(self, *, update_fields: list[str] | None = None) -> None:
        """Keep legacy-shaped test doubles callable without persisting this projection."""

        del update_fields


__all__ = ["SystemSettingsProjection"]
