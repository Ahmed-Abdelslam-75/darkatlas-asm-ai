"""Grounding helpers: turn real DB rows into compact, model-friendly context.

Everything the LLM reasons about is built here from actual `Asset` rows, so the
model can only talk about assets that exist. We also precompute derived signals
(certificate state, sensitive services) in code rather than asking the model to
do date math or pattern-matching it might get wrong.
"""

from ..crud import cert_state
from ..models import Asset

# Protocols that are risky to expose directly to the internet.
SENSITIVE_PROTOCOLS = {
    "ssh", "telnet", "ftp", "rdp", "vnc", "smb",
    "mysql", "postgres", "postgresql", "mongodb", "redis", "mssql", "elasticsearch",
}


def compact_asset(a: Asset) -> dict:
    """A small, faithful projection of an asset for prompting."""
    d = {
        "id": a.id,
        "type": a.type.value,
        "value": a.value,
        "status": a.status.value,
        "tags": a.tags or [],
        "metadata": a.metadata_ or {},
    }
    if a.type.value == "certificate":
        d["cert_state"] = cert_state(a.metadata_)  # expired | expiring_soon | valid | None
    if a.type.value == "service":
        proto = str((a.metadata_ or {}).get("protocol", "")).lower()
        d["sensitive"] = proto in SENSITIVE_PROTOCOLS
    return d


def dataset_stats(assets: list[Asset]) -> dict:
    """Deterministic summary stats used to ground the risk/report prompts."""
    by_type: dict[str, int] = {}
    cert_states: dict[str, int] = {}
    sensitive_services: list[str] = []
    eol_tech: list[str] = []

    for a in assets:
        by_type[a.type.value] = by_type.get(a.type.value, 0) + 1
        if a.type.value == "certificate":
            state = cert_state(a.metadata_) or "unknown"
            cert_states[state] = cert_states.get(state, 0) + 1
        if a.type.value == "service":
            proto = str((a.metadata_ or {}).get("protocol", "")).lower()
            if proto in SENSITIVE_PROTOCOLS:
                sensitive_services.append(a.value)
        if a.type.value == "technology" and (a.metadata_ or {}).get("eol"):
            eol_tech.append(a.value)

    return {
        "total": len(assets),
        "by_type": by_type,
        "certificate_states": cert_states,
        "sensitive_services": sensitive_services,
        "end_of_life_technologies": eol_tech,
    }
