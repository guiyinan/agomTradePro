"""Registration, profile, settings, and MCP guide repository operations."""

import json
import logging
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.account.infrastructure.account_profile_repository import AccountRepository
from apps.account.infrastructure.models import (
    AccountProfileModel,
    CapitalFlowModel,
    PortfolioModel,
    SystemSettingsModel,
    TradingCostConfigModel,
    UserAccessTokenModel,
)
from apps.account.infrastructure.portfolio_repository import PortfolioRepository

logger = logging.getLogger(__name__)


class AccountInterfaceRegistrationRepositoryMixin:
    """Persist registration and user-facing account profile workflows."""

    def get_system_settings(self) -> Any:
        """Return the singleton system settings model."""

        return SystemSettingsModel.get_settings()

    def list_global_investment_rule_payloads(self) -> list[dict[str, Any]]:
        """Return active global investment rules for read-only consumers."""

        from apps.account.infrastructure.models import InvestmentRuleModel

        queryset = (
            InvestmentRuleModel._default_manager.filter(
                is_active=True,
                user__isnull=True,
            )
            .order_by("priority", "id")
            .values("rule_type", "conditions", "advice_template")
        )
        return [
            {
                "rule_type": str(row["rule_type"]),
                "conditions": dict(row.get("conditions") or {}),
                "advice_template": str(row.get("advice_template") or ""),
            }
            for row in queryset
        ]

    def has_system_settings_singleton(self) -> bool:
        """Return whether the singleton system settings row already exists."""

        return SystemSettingsModel._default_manager.exists()

    def get_existing_system_settings(self) -> Any:
        """Return the existing singleton settings row without creating one."""

        return SystemSettingsModel._default_manager.first()

    def get_active_access_token(self, key: str) -> UserAccessTokenModel | None:
        """Return one active access token with user/profile preloaded."""

        return (
            UserAccessTokenModel._default_manager.select_related(
                "user",
                "user__account_profile",
            )
            .filter(key=UserAccessTokenModel.hash_key(key), is_active=True)
            .first()
        )

    def touch_access_token(self, token: UserAccessTokenModel) -> None:
        """Persist last-used metadata for one access token."""

        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at", "updated_at"])

    def provision_registered_user(
        self,
        *,
        user: User,
        display_name: str,
        system_settings: Any,
        client_ip: str | None,
        approval_status: str,
        rbac_role: str,
    ) -> None:
        """Create account scaffolding for a newly registered user."""

        AccountProfileModel._default_manager.update_or_create(
            user=user,
            defaults={
                "display_name": display_name,
                "initial_capital": Decimal("1000000.00"),
                "risk_tolerance": "moderate",
                "mcp_enabled": system_settings.default_mcp_enabled,
                "user_agreement_accepted": True,
                "risk_warning_acknowledged": True,
                "agreement_accepted_at": timezone.now(),
                "agreement_ip_address": client_ip,
                "approval_status": approval_status,
                "rbac_role": rbac_role,
            },
        )
        PortfolioModel._default_manager.get_or_create(
            user=user,
            name="默认组合",
            defaults={"is_active": True},
        )

    def username_exists(self, username: str) -> bool:
        """Return whether a username already exists."""

        return User._default_manager.filter(username=username).exists()

    def has_any_administrator(self, *, exclude_user_id: int | None = None) -> bool:
        """Return whether the system already has another admin/staff user."""

        queryset = User._default_manager.filter(Q(is_superuser=True) | Q(is_staff=True))
        if exclude_user_id is not None:
            queryset = queryset.exclude(pk=exclude_user_id)
        return queryset.exists()

    def create_registered_user(self, *, username: str, email: str | None, password: str) -> User:
        """Create the initial Django user row for a registration request."""

        return User._default_manager.create_user(
            username=username,
            email=email,
            password=password,
            is_active=False,
        )

    def register_user_with_account_scaffolding(
        self,
        *,
        username: str,
        email: str | None,
        password: str,
        display_name: str,
        client_ip: str | None,
    ) -> dict[str, Any]:
        """Create the Django user row and all account scaffolding in one transaction."""

        system_settings = SystemSettingsModel.get_settings()
        with transaction.atomic():
            user = self.create_registered_user(
                username=username,
                email=email,
                password=password,
            )

            if not system_settings.require_user_approval:
                approval_status = "auto_approved"
                rbac_role = "owner"
                user.is_active = True
            elif (
                not self.has_any_administrator(exclude_user_id=user.pk)
                and system_settings.auto_approve_first_admin
            ):
                approval_status = "auto_approved"
                rbac_role = "admin"
                user.is_superuser = True
                user.is_staff = True
                user.is_active = True
            else:
                approval_status = "pending"
                rbac_role = "owner"

            user.save(update_fields=["is_active", "is_superuser", "is_staff"])
            self.provision_registered_user(
                user=user,
                display_name=display_name,
                system_settings=system_settings,
                client_ip=client_ip,
                approval_status=approval_status,
                rbac_role=rbac_role,
            )

        return {
            "user": user,
            "approval_status": approval_status,
            "display_name": display_name,
        }

    def get_active_portfolio_for_user(self, user_id: int) -> PortfolioModel | None:
        """Return the user's active portfolio when available."""

        return (
            PortfolioModel._default_manager.filter(user_id=user_id, is_active=True)
            .order_by("-created_at")
            .first()
        )

    def build_profile_context(self, user_id: int) -> dict[str, Any]:
        """Build the profile page context."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        portfolios = PortfolioModel._default_manager.filter(user_id=user_id).order_by("-created_at")
        investment_accounts = AccountRepository().list_investment_accounts(user_id)

        total_assets = 0.0
        if investment_accounts:
            total_assets = sum(float(account["total_value"]) for account in investment_accounts)
        else:
            portfolio_repo = PortfolioRepository()
            for portfolio in portfolios.filter(is_active=True):
                snapshot = portfolio_repo.get_portfolio_snapshot(portfolio.id)
                if snapshot:
                    total_assets += float(snapshot.total_value)

        return {
            "user": user,
            "profile": user.account_profile,
            "portfolios": portfolios,
            "investment_accounts": investment_accounts,
            "total_assets": total_assets,
        }

    def build_settings_context(self, user_id: int) -> dict[str, Any]:
        """Build the settings page context."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile
        portfolio = PortfolioModel._default_manager.filter(user_id=user_id, is_active=True).first()
        system_settings = SystemSettingsModel.get_settings()

        capital_flows: Any
        if portfolio:
            capital_flows = CapitalFlowModel._default_manager.filter(portfolio=portfolio).order_by(
                "-flow_date", "-created_at"
            )
            total_deposit = capital_flows.filter(flow_type="deposit").aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")
            total_withdraw = capital_flows.filter(flow_type="withdraw").aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")
            net_capital = total_deposit - total_withdraw
            trading_cost_config = TradingCostConfigModel._default_manager.filter(
                portfolio=portfolio
            ).first()
        else:
            capital_flows = []
            total_deposit = Decimal("0")
            total_withdraw = Decimal("0")
            net_capital = Decimal("0")
            trading_cost_config = None

        access_tokens = UserAccessTokenModel._default_manager.filter(
            user_id=user_id,
            is_active=True,
        ).order_by("-created_at")

        return {
            "user": user,
            "profile": profile,
            "portfolio": portfolio,
            "capital_flows": capital_flows,
            "total_deposit": total_deposit,
            "total_withdraw": total_withdraw,
            "net_capital": net_capital,
            "trading_cost_config": trading_cost_config,
            "system_settings": system_settings,
            "access_tokens": access_tokens,
        }

    def build_mcp_guide_context(self, *, user_id: int, base_url: str) -> dict[str, Any]:
        """Build the MCP integration guide context for one user."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile
        system_settings = SystemSettingsModel.get_settings()
        token_plaintext_allowed = bool(system_settings.allow_token_plaintext_view)
        investment_accounts = AccountRepository().list_investment_accounts(user_id)
        preferred_account = investment_accounts[0] if investment_accounts else None
        default_account_id = preferred_account["id"] if preferred_account else None
        default_account_name = preferred_account["account_name"] if preferred_account else ""

        access_tokens = list(
            UserAccessTokenModel._default_manager.filter(user_id=user_id, is_active=True).order_by(
                "-last_used_at",
                "-created_at",
            )
        )
        visible_tokens = [
            {
                "id": token.id,
                "name": token.name,
                "preview": token.preview,
                "access_level": token.access_level,
                "access_level_label": token.get_access_level_display(),
                "plaintext": token.reveal_key() if token_plaintext_allowed else "",
                "display_token": (token.reveal_key() if token_plaintext_allowed else token.preview),
                "created_at": token.created_at,
                "last_used_at": token.last_used_at,
            }
            for token in access_tokens
        ]
        recoverable_token_count = sum(
            1 for token in visible_tokens if str(token.get("plaintext") or "").strip()
        )
        token_decryption_failed = bool(
            token_plaintext_allowed
            and access_tokens
            and recoverable_token_count == 0
            and any(bool(token.key_encrypted) for token in access_tokens)
        )
        preferred_token = next(
            (token for token in visible_tokens if token.get("plaintext")),
            visible_tokens[0] if visible_tokens else None,
        )
        preferred_token_value = (
            preferred_token["plaintext"] if preferred_token and preferred_token["plaintext"] else ""
        )
        token_placeholder = preferred_token_value or "your_token_here"
        default_account_placeholder = (
            str(default_account_id) if default_account_id is not None else "your_account_id"
        )
        normalized_base_url = base_url.rstrip("/")
        sdk_cwd = str(Path(settings.BASE_DIR) / "sdk").replace("\\", "/")
        api_profile_endpoint = f"{normalized_base_url}/api/account/profile/"
        dashboard_summary_endpoint = f"{normalized_base_url}/api/dashboard/v1/summary/"
        accounts_endpoint = f"{normalized_base_url}/api/account/accounts/"
        api_root_endpoint = f"{normalized_base_url}/api/"

        powershell_env_block = "\n".join(
            [
                f'$env:AGOMTRADEPRO_BASE_URL="{normalized_base_url}"',
                f'$env:AGOMTRADEPRO_API_TOKEN="{token_placeholder}"',
                f'$env:AGOMTRADEPRO_DEFAULT_ACCOUNT_ID="{default_account_placeholder}"',
                '$env:NO_PROXY="127.0.0.1,localhost"',
                '$env:no_proxy="127.0.0.1,localhost"',
            ]
        )
        bash_env_block = "\n".join(
            [
                f'export AGOMTRADEPRO_BASE_URL="{normalized_base_url}"',
                f'export AGOMTRADEPRO_API_TOKEN="{token_placeholder}"',
                f'export AGOMTRADEPRO_DEFAULT_ACCOUNT_ID="{default_account_placeholder}"',
                'export NO_PROXY="127.0.0.1,localhost"',
                'export no_proxy="127.0.0.1,localhost"',
            ]
        )
        python_sdk_block = "\n".join(
            [
                "from agomtradepro import AgomTradeProClient",
                "",
                "client = AgomTradeProClient(",
                f'    base_url="{normalized_base_url}",',
                f'    api_token="{token_placeholder}",',
                ")",
                "",
                "profile = client.account.get_profile()",
                "summary = client.dashboard.get_summary()",
            ]
        )
        mcp_config_json = json.dumps(
            {
                "mcpServers": {
                    "agomtradepro_local": {
                        "command": "python",
                        "args": ["-m", "agomtradepro_mcp"],
                        "cwd": sdk_cwd,
                        "env": {
                            "AGOMTRADEPRO_BASE_URL": normalized_base_url,
                            "AGOMTRADEPRO_API_TOKEN": token_placeholder,
                            "AGOMTRADEPRO_DEFAULT_ACCOUNT_ID": default_account_placeholder,
                            "NO_PROXY": "127.0.0.1,localhost",
                            "no_proxy": "127.0.0.1,localhost",
                        },
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        curl_example = "\n".join(
            [
                "curl -X GET \\",
                f'  "{dashboard_summary_endpoint}" \\',
                f'  -H "Authorization: Token {token_placeholder}"',
            ]
        )

        return {
            "user": user,
            "profile": profile,
            "system_settings": system_settings,
            "access_tokens": access_tokens,
            "visible_tokens": visible_tokens,
            "preferred_token": preferred_token,
            "token_plaintext_allowed": token_plaintext_allowed,
            "recoverable_token_count": recoverable_token_count,
            "token_decryption_failed": token_decryption_failed,
            "base_url": normalized_base_url,
            "api_root_endpoint": api_root_endpoint,
            "api_profile_endpoint": api_profile_endpoint,
            "dashboard_summary_endpoint": dashboard_summary_endpoint,
            "accounts_endpoint": accounts_endpoint,
            "sdk_cwd": sdk_cwd,
            "mcp_config_json": mcp_config_json,
            "powershell_env_block": powershell_env_block,
            "bash_env_block": bash_env_block,
            "python_sdk_block": python_sdk_block,
            "curl_example": curl_example,
            "default_account_id": default_account_id,
            "default_account_name": default_account_name,
            "account_count": len(investment_accounts),
        }

    def update_account_settings(
        self,
        user_id: int,
        *,
        display_name: str,
        risk_tolerance: str,
        email: str,
        new_password: str,
    ) -> bool:
        """Persist profile and credential changes. Returns whether password changed."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile
        profile.display_name = display_name
        profile.risk_tolerance = risk_tolerance
        profile.save(update_fields=["display_name", "risk_tolerance", "updated_at"])

        user_update_fields: list[str] = []
        if email:
            user.email = email
            user_update_fields.append("email")
        if new_password:
            user.set_password(new_password)
            user_update_fields.append("password")
        if user_update_fields:
            user.save(update_fields=user_update_fields)
        return bool(new_password)

    def get_api_profile(self, user_id: int) -> AccountProfileModel:
        """Return the account profile model for API serialization."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        return user.account_profile

    def update_api_profile(
        self,
        user_id: int,
        *,
        profile_data: Mapping[str, Any],
        email: str | None = None,
    ) -> AccountProfileModel:
        """Persist API profile updates and return the refreshed profile model."""

        user = User._default_manager.select_related("account_profile").get(id=user_id)
        profile = user.account_profile

        update_fields: list[str] = []
        for field_name in ("display_name", "risk_tolerance"):
            if field_name in profile_data:
                setattr(profile, field_name, profile_data[field_name])
                update_fields.append(field_name)

        if update_fields:
            update_fields.append("updated_at")
            profile.save(update_fields=update_fields)

        if email:
            user.email = email
            user.save(update_fields=["email"])

        return profile
