"""QMT bridge use cases with an injected persistence boundary."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, TypedDict

from apps.data_center.domain.qmt_bridge import BridgeBatch


class BatchReceipt(TypedDict):
    """Durable acknowledgement, distinct from transport success."""

    batch_id: str
    outcome: str
    requested: int
    succeeded: int
    failed: int
    stored: int
    reason: str


class BridgeIngestPort(Protocol):
    """Persist an authorized immutable batch and its acknowledgement atomically."""

    def ingest(self, binding_id: str, batch: BridgeBatch) -> BatchReceipt: ...


class IngestQmtBatch:
    """Validate all upload callers before entering the fact repository."""

    def __init__(self, repository: BridgeIngestPort) -> None:
        self.repository = repository

    def execute(self, binding_id: str, batch: BridgeBatch) -> BatchReceipt:
        """Accept only valid source observations; never replace source time."""
        batch.validate(datetime.now(UTC))
        return self.repository.ingest(binding_id, batch)


class BridgeManagementPort(BridgeIngestPort, Protocol):
    """Owner-scoped management and machine authentication boundary."""

    def list_bindings(self, owner_id: int) -> list[dict[str, object]]: ...
    def create(
        self, owner_id: int, agent_id: str, server_url: str, assets: tuple[str, ...]
    ) -> dict[str, object]: ...
    def pair(self, code: str, agent_id: str, server_url: str) -> dict[str, object]: ...
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
    ) -> dict[str, object]: ...
    def authenticate(
        self,
        binding_id: str,
        token: str,
        sent_at: str,
        nonce: str,
        signature: str,
        path: str,
        body: bytes,
    ) -> None: ...
    def plan(self, binding_id: str) -> dict[str, object]: ...


class QmtBridgeService(IngestQmtBatch):
    """Compose owner pairing, collection control and validated ingestion."""

    def __init__(self, repository: BridgeManagementPort) -> None:
        super().__init__(repository)
        self.management = repository

    def list_bindings(self, owner_id: int) -> list[dict[str, object]]:
        """Return only the current user's bridge bindings."""
        return self.management.list_bindings(owner_id)

    def create(
        self, owner_id: int, agent_id: str, server_url: str, assets: tuple[str, ...]
    ) -> dict[str, object]:
        """Create an initially disabled owner binding with a one-time code."""
        if (
            owner_id <= 0
            or re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", agent_id) is None
            or not 1 <= len(assets) <= 200
        ):
            raise ValueError("Owner, Agent and 1–200 catalog assets are required")
        if len(set(assets)) != len(assets):
            raise ValueError("Asset list must be unique")
        return self.management.create(owner_id, agent_id, server_url, assets)

    def pair(self, code: str, agent_id: str, server_url: str) -> dict[str, object]:
        """Consume a one-time code against its exact server and local Agent."""
        return self.management.pair(code, agent_id, server_url)

    def control(
        self,
        binding_id: str,
        actor_id: int,
        staff: bool,
        action: str,
        provider_id: int | None = None,
        quote_multiplier: Decimal | None = None,
        bar_multiplier: Decimal | None = None,
        poll_seconds: int = 10,
        freshness_seconds: int = 60,
    ) -> dict[str, object]:
        """Change collection permission without granting any trading capability."""
        if action not in ("approve", "pause", "resume", "revoke", "repair"):
            raise ValueError("Unsupported bridge action")
        if not 1 <= poll_seconds <= 60 or not 1 <= freshness_seconds <= 3600:
            raise ValueError("Invalid collection/freshness budget")
        if action == "approve" and any(
            v is None or not v.is_finite() or v <= 0 for v in (quote_multiplier, bar_multiplier)
        ):
            raise ValueError("Explicit positive source-volume multipliers are required")
        return self.management.control(
            binding_id,
            actor_id,
            staff,
            action,
            provider_id,
            quote_multiplier,
            bar_multiplier,
            poll_seconds,
            freshness_seconds,
        )

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
        """Authenticate the signed, replay-protected machine request."""
        self.management.authenticate(binding_id, token, sent_at, nonce, signature, path, body)

    def plan(self, binding_id: str) -> dict[str, object]:
        """Return the server-approved collection plan and independent state."""
        return self.management.plan(binding_id)
