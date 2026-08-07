"""Composition root for the Data Center-owned R2 market-structure slice."""

from apps.data_center.application.market_structure import (
    MarketStructureGovernanceFacade,
    ReadMarketStructureEvidence,
    RunMarketStructureResearch,
)
from apps.data_center.infrastructure.market_structure_publication import (
    DjangoMarketStructurePublicationGate,
)
from apps.data_center.infrastructure.market_structure_repository import (
    MarketStructureResearchRepository,
)


def make_market_structure_governance_facade() -> MarketStructureGovernanceFacade:
    """Build the governed actor and series registration facade."""

    return MarketStructureGovernanceFacade(MarketStructureResearchRepository())


def make_market_structure_research_runner() -> RunMarketStructureResearch:
    """Build the fail-closed R2 research runner."""

    return RunMarketStructureResearch(
        MarketStructureResearchRepository(),
        DjangoMarketStructurePublicationGate(),
    )


def make_market_structure_evidence_reader() -> ReadMarketStructureEvidence:
    """Build the exact-version evidence reader."""

    return ReadMarketStructureEvidence(MarketStructureResearchRepository())


__all__ = [
    "make_market_structure_evidence_reader",
    "make_market_structure_governance_facade",
    "make_market_structure_research_runner",
]
