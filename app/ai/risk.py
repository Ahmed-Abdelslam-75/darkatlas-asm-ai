"""Capability 2 — Risk scoring & summarization.

We pass the model a compact projection of the REAL assets (with derived signals
like cert_state and `sensitive` precomputed in code). the model returns a score, a
summary, and findings keyed by asset id. We then drop any finding whose id is
not in the input set — the model literally cannot report on a non-existent asset.
"""

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ..models import Asset
from ..schemas import RiskFinding, RiskResponse
from .context import compact_asset, dataset_stats
from .llm import get_llm

SYSTEM = """You are a security analyst assessing an organization's external attack \
surface. You are given a list of REAL assets (each with an `id`) and precomputed \
signals. Assess only these assets.

Consider: expired or expiring-soon certificates, sensitive exposed services
(ssh, rdp, databases, etc.), end-of-life technologies, and risky tags.

Output:
- score: integer 0-100 overall risk (0 = clean, 100 = severe).
- summary: 2-4 sentence plain-English summary of the most important risks.
- findings: one entry per genuinely notable asset, each referencing an `id`
  from the provided list ONLY. Do not invent assets, ids, or values."""


class _LLMFinding(BaseModel):
    asset_id: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    reason: str


class _LLMRisk(BaseModel):
    score: int = Field(ge=0, le=100)
    summary: str
    findings: list[_LLMFinding] = Field(default_factory=list)


def ground_findings(findings, assets: list[Asset]) -> list[RiskFinding]:
    """Keep only findings that reference an asset we actually sent to the model.

    This is the anti-hallucination guard: any finding whose `asset_id` is not in
    the input set is dropped, so the model cannot report on invented assets.
    """
    by_id = {a.id: a for a in assets}
    grounded: list[RiskFinding] = []
    for f in findings:
        asset = by_id.get(f.asset_id)
        if asset is None:
            continue
        grounded.append(
            RiskFinding(
                asset_id=asset.id,
                asset_value=asset.value,
                severity=f.severity,
                reason=f.reason,
            )
        )
    return grounded


_SEVERITY_WEIGHT = {"critical": 35, "high": 20, "medium": 10, "low": 4, "info": 1}


def _fallback_risk(assets: list[Asset]) -> RiskResponse:
    """Deterministic, fully-grounded assessment used when the model returns no
    usable output. Built entirely from precomputed signals — never hallucinates."""
    from ..crud import cert_state
    from .context import SENSITIVE_PROTOCOLS

    findings: list[RiskFinding] = []
    for a in assets:
        if a.type.value == "certificate":
            state = cert_state(a.metadata_)
            if state == "expired":
                findings.append(RiskFinding(asset_id=a.id, asset_value=a.value,
                                            severity="high", reason="TLS certificate has expired."))
            elif state == "expiring_soon":
                findings.append(RiskFinding(asset_id=a.id, asset_value=a.value,
                                            severity="medium", reason="TLS certificate expires soon."))
        elif a.type.value == "service":
            proto = str((a.metadata_ or {}).get("protocol", "")).lower()
            if proto in SENSITIVE_PROTOCOLS:
                findings.append(RiskFinding(asset_id=a.id, asset_value=a.value,
                                            severity="high",
                                            reason=f"Sensitive service ({proto}) exposed to the internet."))
        elif a.type.value == "technology" and (a.metadata_ or {}).get("eol"):
            findings.append(RiskFinding(asset_id=a.id, asset_value=a.value,
                                        severity="medium", reason="End-of-life technology in use."))

    score = min(100, sum(_SEVERITY_WEIGHT[f.severity] for f in findings))
    summary = (
        f"Deterministic assessment of {len(assets)} assets: {len(findings)} notable risk(s) "
        "from expired/expiring certificates, sensitive exposed services, and end-of-life technologies."
        if findings else f"No notable risks detected across {len(assets)} assets."
    )
    return RiskResponse(score=score, summary=summary, findings=findings, assessed_count=len(assets))


def assess_risk(assets: list[Asset]) -> RiskResponse:
    if not assets:
        return RiskResponse(score=0, summary="No assets matched; nothing to assess.",
                            findings=[], assessed_count=0)

    context = {
        "stats": dataset_stats(assets),
        "assets": [compact_asset(a) for a in assets],
    }

    llm = get_llm().with_structured_output(_LLMRisk)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM), ("human", "Assets and signals (JSON):\n{ctx}")]
    )
    result: _LLMRisk | None = (prompt | llm).invoke({"ctx": context})

    if result is None:  # model returned nothing parseable -> safe deterministic fallback
        return _fallback_risk(assets)

    grounded = ground_findings(result.findings, assets)  # drop hallucinated ids
    return RiskResponse(
        score=max(0, min(100, result.score)),
        summary=result.summary,
        findings=grounded,
        assessed_count=len(assets),
    )
