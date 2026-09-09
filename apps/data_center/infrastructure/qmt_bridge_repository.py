"""Atomic pairing, authentication and canonical fact ingestion for QMT."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.qmt_bridge import BatchReceipt
from apps.data_center.domain.qmt_bridge import BridgeBatch
from core.exceptions import AuthorizationError, DuplicateResourceError, ResourceNotFoundError

from .models import AssetMasterModel, PriceBarModel, ProviderConfigModel, QuoteSnapshotModel
from .qmt_bridge_models import (
    QmtBridgeAuditModel,
    QmtBridgeBatchModel,
    QmtBridgeBindingModel,
    QmtBridgeNonceModel,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _pairing(binding: QmtBridgeBindingModel, *, repair: bool = False) -> dict[str, object]:
    code = secrets.token_urlsafe(32)
    binding.pairing_hash = _hash(code)
    binding.pairing_expires_at = timezone.now() + timedelta(minutes=10)
    binding.save()
    return {
        "binding_id": str(binding.pk),
        "pairing_code": code,
        "server_url": binding.server_url,
        "agent_id": binding.agent_id,
        "expires_at": binding.pairing_expires_at.isoformat(),
        "next_step": "在安装目录运行配对命令，按提示输入配对码；随后由管理员批准行情数据源。",
        "pair_command": (
            ".\\runtime\\Scripts\\python.exe -m qmt_agent.main --bridge --state-dir .\\market-state "
            f'{"--repair" if repair else "--pair"} '
            f'--server "{binding.server_url}" --agent-id "{binding.agent_id}"'
        ),
    }


class QmtBridgeRepository:
    """Persist only authorized sources; never activate a current Publication here."""

    def list_bindings(self, owner_id: int) -> list[dict[str, object]]:
        """List only the owner's bindings, without exposing credentials."""
        return [
            self._status(row) for row in QmtBridgeBindingModel.objects.filter(owner_id=owner_id)
        ]

    @staticmethod
    def _status(row: QmtBridgeBindingModel) -> dict[str, object]:
        now = timezone.now()
        receipt = QmtBridgeBatchModel.objects.filter(binding=row).order_by("-created_at").first()
        fresh = row.last_observed_at is not None and timedelta(
            0
        ) <= now - row.last_observed_at <= timedelta(seconds=row.freshness_seconds)
        return {
            "binding_id": str(row.pk),
            "agent_id": row.agent_id,
            "server_url": row.server_url,
            "paired": row.paired_at is not None,
            "enabled": row.enabled,
            "revoked": row.revoked,
            "provider_id": row.provider_id,
            "assets": row.assets,
            "last_seen_at": row.last_seen_at,
            "observed_at": row.last_observed_at,
            "freshness": "fresh" if fresh else "stale_or_missing",
            "reliability": "unverified",
            "must_not_use_for_decision": True,
            "blocked_reason": "qmt_bridge_requires_publication_validation",
            "last_batch": receipt.receipt if receipt is not None else None,
        }

    @transaction.atomic
    def create(
        self, owner_id: int, agent_id: str, server_url: str, assets: tuple[str, ...]
    ) -> dict[str, object]:
        """Bind the authenticated owner; only catalog assets are accepted."""
        if set(
            AssetMasterModel.objects.filter(
                code__in=assets, is_active=True, currency="CNY"
            ).values_list("code", flat=True)
        ) != set(assets):
            raise ValueError("Select active CNY assets from the asset catalog")
        try:
            with transaction.atomic():
                row = QmtBridgeBindingModel.objects.create(
                    owner_id=owner_id, agent_id=agent_id, server_url=server_url, assets=list(assets)
                )
        except IntegrityError as exc:
            raise DuplicateResourceError("This Agent is already bound; use repair pairing") from exc
        QmtBridgeAuditModel.objects.create(binding=row, actor_id=owner_id, action="created")
        return _pairing(row)

    @transaction.atomic
    def pair(self, code: str, agent_id: str, server_url: str) -> dict[str, object]:
        """Consume a single-use, short-lived pairing code and issue a scoped token."""
        row = (
            QmtBridgeBindingModel.objects.select_for_update()
            .filter(pairing_hash=_hash(code))
            .first()
        )
        now = timezone.now()
        if (
            row is None
            or row.revoked
            or row.pairing_expires_at is None
            or row.pairing_expires_at <= now
            or row.agent_id != agent_id
            or row.server_url != server_url
        ):
            raise AuthorizationError("Pairing code expired or does not match this Agent/server")
        token = secrets.token_urlsafe(48)
        row.token_hash = _hash(token)
        row.token_expires_at = now + timedelta(days=90)
        row.pairing_hash = ""
        row.pairing_expires_at = None
        row.paired_at = now
        row.save()
        QmtBridgeAuditModel.objects.create(binding=row, action="paired")
        return {
            "binding_id": str(row.pk),
            "token": token,
            "agent_id": row.agent_id,
            "server_url": row.server_url,
            "expires_at": row.token_expires_at.isoformat(),
            "scope": "market_data",
            "trading_enabled": False,
        }

    @transaction.atomic
    def control(
        self,
        binding_id: str,
        actor_id: int,
        staff: bool,
        action: str,
        provider_id: int | None,
        quote_multiplier: Decimal | None,
        bar_multiplier: Decimal | None,
        poll_seconds: int,
        freshness_seconds: int,
    ) -> dict[str, object]:
        """Serialize permission changes with ingestion and append lifecycle audit."""
        row = QmtBridgeBindingModel.objects.select_for_update().filter(pk=binding_id).first()
        if row is None or (row.owner_id != actor_id and not staff):
            raise ResourceNotFoundError("Bridge binding not found")
        if action == "approve":
            if not staff:
                raise AuthorizationError(
                    "Administrator approval is required for shared market data"
                )
            if provider_id is None:
                raise ValueError("An active QMT provider is required")
            provider = (
                ProviderConfigModel.objects.select_for_update()
                .filter(pk=provider_id, source_type="qmt", is_active=True)
                .first()
            )
            if provider is None:
                raise ValueError("An active QMT provider is required")
            if QmtBridgeBindingModel.objects.filter(provider=provider).exclude(pk=row.pk).exists():
                raise ValueError("Provider is already assigned to another bridge")
            if row.provider_id is not None and row.provider_id != provider.pk:
                raise ValueError("Provider identity is immutable; create a new binding")
            if QmtBridgeBatchModel.objects.filter(binding=row).exists() and (
                row.quote_volume_multiplier != quote_multiplier
                or row.bar_volume_multiplier != bar_multiplier
            ):
                raise ValueError(
                    "Uploaded source unit contracts are immutable; create a new binding"
                )
            row.provider = provider
            row.quote_volume_multiplier = quote_multiplier
            row.bar_volume_multiplier = bar_multiplier
            row.poll_seconds = poll_seconds
            row.freshness_seconds = freshness_seconds
            row.enabled = True
            provider.extra_config = {**provider.extra_config, "qmt_bridge_id": str(row.pk)}
            provider.save(update_fields=["extra_config"])
        elif action == "resume":
            if row.provider_id is None:
                raise AuthorizationError("Approve the provider and unit contract first")
            row.enabled = True
        elif action == "pause":
            row.enabled = False
        elif action == "revoke":
            row.enabled = False
            row.revoked = True
            row.token_hash = ""
            row.pairing_hash = ""
        elif action == "repair":
            row.enabled = False
            row.token_hash = ""
            row.paired_at = None
        if row.revoked and action != "revoke":
            raise AuthorizationError("Revoked bindings cannot be reactivated")
        row.save()
        QmtBridgeAuditModel.objects.create(binding=row, actor_id=actor_id, action=action)
        return _pairing(row, repair=True) if action == "repair" else self._status(row)

    @transaction.atomic
    def authenticate(
        self,
        binding_id: str,
        token: str,
        sent_at: str,
        nonce: str,
        signature: str,
        path: str,
        body: bytes,
    ) -> None:
        """Verify token, signed destination/body, clock window and nonce atomically."""
        try:
            UUID(binding_id)
            sent = datetime.fromisoformat(sent_at)
        except ValueError as exc:
            raise AuthorizationError("Invalid bridge authentication") from exc
        now = timezone.now()
        if (
            sent.utcoffset() is None
            or abs(now - sent) > timedelta(minutes=5)
            or not 16 <= len(nonce) <= 128
        ):
            raise AuthorizationError("Invalid bridge request time or nonce")
        row = (
            QmtBridgeBindingModel.objects.select_for_update()
            .filter(pk=binding_id, owner__is_active=True)
            .first()
        )
        if (
            row is None
            or row.revoked
            or not token
            or not row.token_hash
            or row.token_expires_at is None
            or row.token_expires_at <= now
            or not hmac.compare_digest(row.token_hash, _hash(token))
        ):
            raise AuthorizationError("Bridge credential is invalid or expired")
        canonical = (
            f"POST\n{path}\n{binding_id}\n{sent_at}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
        )
        expected = hmac.new(token.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AuthorizationError("Invalid bridge signature")
        QmtBridgeNonceModel.objects.filter(
            binding=row, created_at__lt=now - timedelta(minutes=10)
        ).delete()
        try:
            with transaction.atomic():
                QmtBridgeNonceModel.objects.create(binding=row, nonce=nonce)
        except IntegrityError as exc:
            raise AuthorizationError("Bridge request was already used") from exc
        row.last_seen_at = now
        row.save(update_fields=["last_seen_at"])

    def plan(self, binding_id: str) -> dict[str, object]:
        """Return bounded server-owned collection configuration."""
        row = QmtBridgeBindingModel.objects.select_related("provider").get(pk=binding_id)
        return {
            "binding_id": str(row.pk),
            "agent_id": row.agent_id,
            "server_url": row.server_url,
            "enabled": row.enabled
            and not row.revoked
            and row.provider is not None
            and row.provider.is_active,
            "assets": row.assets,
            "poll_seconds": row.poll_seconds,
            "kinds": ["quote", "bar"],
            "adjustment": "none",
            "trading_enabled": False,
        }

    @transaction.atomic
    def ingest(self, binding_id: str, batch: BridgeBatch) -> BatchReceipt:
        """Atomically persist facts and receipt; retry never mutates earlier facts."""
        row = (
            QmtBridgeBindingModel.objects.select_for_update()
            .select_related("provider")
            .get(pk=binding_id)
        )
        if not row.enabled or row.revoked or row.provider is None or not row.provider.is_active:
            raise AuthorizationError("Market collection is disabled or not approved")
        if not {s.asset_code for s in batch.samples}.issubset(set(row.assets)):
            raise AuthorizationError("Upload contains assets outside the binding")
        digest = _hash(json.dumps(asdict(batch), sort_keys=True, default=str))
        previous = QmtBridgeBatchModel.objects.filter(binding=row, batch_id=batch.batch_id).first()
        if previous is not None:
            if previous.digest != digest:
                raise DuplicateResourceError("Batch identity already has different content")
            return cast(BatchReceipt, previous.receipt)
        source = f"qmt-bridge:{row.pk.hex}"
        stored = 0
        for sample in batch.samples:
            multiplier = (
                row.quote_volume_multiplier if batch.kind == "quote" else row.bar_volume_multiplier
            )
            if multiplier is None:
                raise ValueError("Source volume contract is not configured")
            volume = sample.volume * multiplier if sample.volume is not None else None
            if volume is not None and volume >= Decimal("1e22"):
                raise ValueError("Normalized volume exceeds the canonical storage bound")
            common = {
                "open": sample.open,
                "high": sample.high,
                "low": sample.low,
                "volume": volume,
                "amount": sample.amount,
                "raw_payload_hash": digest,
                "contract_version": "qmt-bridge-v1",
            }
            if batch.kind == "quote":
                quote, created = QuoteSnapshotModel.objects.get_or_create(
                    asset_code=sample.asset_code,
                    snapshot_at=sample.observed_at,
                    source=source,
                    defaults={
                        **common,
                        "current_price": sample.price,
                        "prev_close": sample.prev_close,
                        "fetched_at": batch.collected_at,
                        "quality_status": "unverified",
                        "extra": {
                            "binding_id": str(row.pk),
                            "batch_id": batch.batch_id,
                            "raw_volume": str(sample.volume),
                            "volume_multiplier": str(multiplier),
                            "received_at": timezone.now().isoformat(),
                            "must_not_use_for_decision": True,
                            "blocked_reason": "qmt_bridge_requires_publication_validation",
                        },
                    },
                )
                if not created and (
                    quote.current_price != sample.price
                    or quote.volume != volume
                    or quote.amount != sample.amount
                    or quote.open != sample.open
                    or quote.high != sample.high
                    or quote.low != sample.low
                    or quote.prev_close != sample.prev_close
                ):
                    raise DuplicateResourceError(
                        "Source quote identity conflicts with an earlier observation"
                    )
            else:
                if sample.bar_date is None or sample.bar_date >= timezone.localdate():
                    raise ValueError(
                        "Only completed historical dates can be uploaded as daily bars"
                    )
                bar, created = PriceBarModel.objects.get_or_create(
                    asset_code=sample.asset_code,
                    bar_date=sample.bar_date,
                    source=source,
                    freq="1d",
                    adjustment="none",
                    defaults={**common, "close": sample.price, "quality_status": "unverified"},
                )
                if not created and (
                    bar.close != sample.price
                    or bar.volume != volume
                    or bar.amount != sample.amount
                    or bar.open != sample.open
                    or bar.high != sample.high
                    or bar.low != sample.low
                ):
                    raise DuplicateResourceError(
                        "Daily source correction requires an explicit audited repair"
                    )
            stored += int(created)
        newest = max(s.observed_at for s in batch.samples) if batch.kind == "quote" else None
        if newest is not None and (row.last_observed_at is None or newest > row.last_observed_at):
            row.last_observed_at = newest
            row.save(update_fields=["last_observed_at"])
        receipt: BatchReceipt = {
            "batch_id": batch.batch_id,
            "outcome": "success" if stored else "noop",
            "requested": len(batch.samples),
            "succeeded": len(batch.samples),
            "failed": 0,
            "stored": stored,
            "reason": "facts_stored_publication_pending" if stored else "already_stored",
        }
        QmtBridgeBatchModel.objects.create(
            binding=row,
            batch_id=batch.batch_id,
            digest=digest,
            receipt=receipt,
            payload=json.loads(json.dumps(asdict(batch), default=str)),
        )
        return receipt
