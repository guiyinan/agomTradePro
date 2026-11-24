"""Use the normal authenticated Portfolio selectors in a full, source-backed rehearsal."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from django.test import Client

from tests.support.portfolio_benchmark_ledger_cleanup import (
    isolated_benchmark_ledger as isolated_benchmark_ledger,
)


@dataclass(frozen=True)
class PublishedBenchmarkApproval:
    approval_id: UUID
    version: int
    content_hash: str
    submission_hash: str


def issue_benchmark_through_sessions(
    *,
    owner_session: Client,
    approver_session: Client,
    valuation_id: UUID,
    valuation_version: int,
    request_id: UUID | None = None,
) -> PublishedBenchmarkApproval:
    """Submit and approve a real current valuation through two pre-authenticated sessions."""
    selected = request_id or uuid4()
    root = "/api/portfolio/benchmark-approvals/"
    submitted = owner_session.post(
        root,
        {
            "request_id": str(selected),
            "valuation_id": str(valuation_id),
            "valuation_version": valuation_version,
        },
        content_type="application/json",
    )
    assert submitted.status_code == 200, submitted.content[:500]
    assert submitted.headers["Content-Type"].startswith("application/json")
    submission = submitted.json()
    assert submission["action"] == "submitted"
    reviewed = approver_session.get(f"{root}{selected}/")
    assert reviewed.status_code == 200, reviewed.content[:500]
    assert reviewed.headers["Content-Type"].startswith("application/json")
    facts = reviewed.json()
    assert facts["state"] == "pending" and facts["submission_hash"] == submission["content_hash"]
    assert facts["source"]["valuation"]["valuation_id"] == str(valuation_id)
    assert facts["source"]["valuation"]["valuation_version"] == valuation_version
    granted = approver_session.post(
        f"{root}{selected}/approve/",
        {
            "expected_content_hash": submission["content_hash"],
        },
        content_type="application/json",
    )
    assert granted.status_code == 200, granted.content[:500]
    assert granted.headers["Content-Type"].startswith("application/json")
    approval = granted.json()
    assert approval["action"] == "approved" and approval["request_id"] == str(selected)
    return PublishedBenchmarkApproval(
        selected, approval["version"], approval["content_hash"], submission["content_hash"]
    )


def revoke_benchmark_through_session(
    *, session: Client, receipt: PublishedBenchmarkApproval
) -> None:
    """Revoke precisely the selected approval through the normal operator endpoint."""
    result = session.post(
        f"/api/portfolio/benchmark-approvals/{receipt.approval_id}/revoke/",
        {
            "expected_content_hash": receipt.content_hash,
        },
        content_type="application/json",
    )
    assert result.status_code == 200, result.content[:500]
    assert result.json()["action"] == "revoked"
