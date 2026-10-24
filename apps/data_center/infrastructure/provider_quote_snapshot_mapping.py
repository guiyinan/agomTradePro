"""Optional quote-field adaptation at the gateway boundary."""

from apps.data_center.domain.quote_change_pct import QuoteChangePctCandidate


def optional_quote_change_pct_candidate(
    quote: object, *, provider_source: str
) -> QuoteChangePctCandidate | None:
    """Keep legacy quote prices readable when no witnessed metric API exists.

    Only the existing gateway candidate method can supply a metric. Missing,
    malformed, or untyped optional output stays unknown; no price arithmetic or
    legacy percentage attribute is used to manufacture a candidate.
    """

    if not isinstance(provider_source, str) or not provider_source.strip():
        return None
    builder = getattr(quote, "to_change_pct_candidate", None)
    if not callable(builder):
        return None
    try:
        candidate = builder(provider_source=provider_source)
    except (TypeError, ValueError):
        return None
    return candidate if isinstance(candidate, QuoteChangePctCandidate) else None


def quote_source(quote: object, fallback_source: str) -> str:
    """Narrow an optional gateway source, retaining the configured fallback."""

    source = getattr(quote, "source", None)
    return source.strip() if isinstance(source, str) and source.strip() else fallback_source.strip()


def optional_quote_source_extra(quote: object) -> dict[str, str]:
    """Publish an actual source only when the gateway supplied its identity."""

    source = getattr(quote, "source", None)
    return {"actual_source": source.strip()} if isinstance(source, str) and source.strip() else {}
