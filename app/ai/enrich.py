"""Capability 3 — Automated enrichment & categorization.

Given one real asset, the model classifies its environment, category, and
criticality and explains why. We set the asset_id ourselves (the model never
chooses it) and can optionally persist the result into the asset's metadata.
"""

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing import Literal

from ..models import Asset
from ..schemas import EnrichResult
from .context import compact_asset
from .llm import get_llm

SYSTEM = """You enrich a single Attack Surface Monitoring asset. Based only on the \
asset's value, tags, type, and metadata, classify it:

- environment: prod | staging | dev | unknown (infer from hostnames/tags such as
  "api." or "prod" -> prod; "staging." -> staging; "dev."/"test." -> dev).
- category: a short label (e.g. "web API", "database service", "TLS certificate",
  "mail", "infrastructure").
- criticality: critical | high | medium | low (production, internet-facing, or
  sensitive services are higher).
- rationale: one sentence explaining the classification.

Do not invent metadata that is not implied by the asset."""


class _LLMEnrich(BaseModel):
    environment: Literal["prod", "staging", "dev", "unknown"]
    category: str
    criticality: Literal["critical", "high", "medium", "low"]
    rationale: str


def _fallback_enrich(asset: Asset) -> EnrichResult:
    """Heuristic classification used when the model returns nothing."""
    text = f"{asset.value} {' '.join(asset.tags or [])}".lower()
    if "prod" in text or asset.value.startswith("api."):
        env = "prod"
    elif "staging" in text or "stage" in text:
        env = "staging"
    elif "dev" in text or "test" in text:
        env = "dev"
    else:
        env = "unknown"
    criticality = "high" if env == "prod" else "medium" if env == "staging" else "low"
    return EnrichResult(
        asset_id=asset.id,
        environment=env,
        category=asset.type.value,
        criticality=criticality,
        rationale="Heuristic classification from the asset's value and tags (model output unavailable).",
    )


def enrich_asset(asset: Asset) -> EnrichResult:
    llm = get_llm().with_structured_output(_LLMEnrich)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM), ("human", "Asset (JSON):\n{asset}")]
    )
    out: _LLMEnrich | None = (prompt | llm).invoke({"asset": compact_asset(asset)})
    if out is None:
        return _fallback_enrich(asset)
    return EnrichResult(
        asset_id=asset.id,
        environment=out.environment,
        category=out.category,
        criticality=out.criticality,
        rationale=out.rationale,
    )
