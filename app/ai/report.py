"""Capability 4 — Natural-language report generation.

Produces a readable Markdown inventory/risk report over a set of REAL assets.
The model is given the actual rows plus deterministic stats and is instructed to
use only that data — so the report cannot reference assets that don't exist.
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..models import Asset
from .context import compact_asset, dataset_stats
from .llm import get_llm

SYSTEM = """You write a concise Attack Surface Monitoring inventory & risk report \
in GitHub-flavored Markdown, using ONLY the provided assets and statistics.

Structure:
# Attack Surface Report
- a one-paragraph executive summary
- a "## Inventory" section summarizing counts by type
- a "## Key Risks" section (expired/expiring certificates, sensitive exposed
  services, end-of-life technologies) referencing concrete asset values
- a short "## Recommendations" list

Do not invent assets, counts, hostnames, or values. If a category has no items,
say so briefly rather than fabricating entries."""


def _fallback_report(stats: dict) -> str:
    """Deterministic Markdown report from precomputed stats (model unavailable)."""
    inv = ", ".join(f"{n} {t}" for t, n in sorted(stats["by_type"].items())) or "none"
    lines = ["# Attack Surface Report", "",
             f"Inventory of {stats['total']} assets.", "",
             "## Inventory", f"- {inv}", "", "## Key Risks"]
    cert = stats["certificate_states"]
    if cert.get("expired"):
        lines.append(f"- {cert['expired']} expired certificate(s)")
    if cert.get("expiring_soon"):
        lines.append(f"- {cert['expiring_soon']} certificate(s) expiring soon")
    if stats["sensitive_services"]:
        lines.append(f"- Sensitive exposed services: {', '.join(stats['sensitive_services'])}")
    if stats["end_of_life_technologies"]:
        lines.append(f"- End-of-life technology: {', '.join(stats['end_of_life_technologies'])}")
    if len(lines) == 8:  # nothing appended under Key Risks
        lines.append("- No major risks detected.")
    return "\n".join(lines)


def generate_report(assets: list[Asset]) -> str:
    if not assets:
        return "# Attack Surface Report\n\nNo assets matched the requested filter."

    stats = dataset_stats(assets)
    context = {"stats": stats, "assets": [compact_asset(a) for a in assets]}
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM), ("human", "Assets and stats (JSON):\n{ctx}")]
    )
    chain = prompt | llm | StrOutputParser()
    markdown = chain.invoke({"ctx": context})
    return markdown if markdown and markdown.strip() else _fallback_report(stats)
