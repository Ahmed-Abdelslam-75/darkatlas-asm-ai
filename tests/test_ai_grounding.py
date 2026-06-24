"""AI layer: the grounding guard and the NL->filter translation.

No network or API key is used — the grounding guard is a pure function, and the
LLM is replaced with a deterministic fake built on a real LangChain Runnable.
"""

from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from app.ai import enrich, nl_query, report, risk
from app.ai.nl_query import QueryInterpretation
from app.models import Asset, AssetStatus, AssetType
from app.schemas import AssetFilter


def _asset(asset_id: str, value: str) -> Asset:
    return Asset(
        id=asset_id,
        org_id="default",
        type=AssetType.service,
        value=value,
        status=AssetStatus.active,
        tags=[],
        metadata_={},
    )


def test_grounding_drops_hallucinated_assets():
    assets = [_asset("real-1", "22/tcp"), _asset("real-2", "3306/tcp")]
    findings = [
        SimpleNamespace(asset_id="real-1", severity="high", reason="exposed ssh"),
        SimpleNamespace(asset_id="ghost-99", severity="critical", reason="invented"),
    ]
    grounded = risk.ground_findings(findings, assets)

    # The invented asset is dropped; only the real one survives.
    assert len(grounded) == 1
    assert grounded[0].asset_id == "real-1"
    assert grounded[0].asset_value == "22/tcp"


def test_assess_risk_with_no_assets_does_not_call_llm():
    result = risk.assess_risk([])  # would raise if it tried to reach the LLM
    assert result.score == 0
    assert result.assessed_count == 0


class _FakeStructuredLLM:
    """Stands in for ChatGoogleGenerativeAI; returns a canned structured object."""

    def __init__(self, value):
        self._value = value

    def with_structured_output(self, _schema):
        # RunnableLambda is a real Runnable, so `prompt | this` composes correctly.
        return RunnableLambda(lambda _prompt_value: self._value)


def test_nl_query_translation(monkeypatch):
    canned = QueryInterpretation(
        filter=AssetFilter(types=[AssetType.certificate], cert_state="expired"),
        answerable=True,
    )
    monkeypatch.setattr(nl_query, "get_llm", lambda: _FakeStructuredLLM(canned))

    out = nl_query.interpret_query("show me all expired certificates")
    assert out.answerable is True
    assert out.filter.types == [AssetType.certificate]
    assert out.filter.cert_state == "expired"


def test_nl_query_out_of_scope(monkeypatch):
    canned = QueryInterpretation(
        filter=AssetFilter(),
        answerable=False,
        clarification="That question is not about the asset inventory.",
    )
    monkeypatch.setattr(nl_query, "get_llm", lambda: _FakeStructuredLLM(canned))

    out = nl_query.interpret_query("what's the weather today?")
    assert out.answerable is False
    assert out.clarification


# --- graceful fallbacks when the model returns nothing (deterministic, grounded) ---


def test_fallback_risk_is_deterministic_and_grounded():
    assets = [
        Asset(id="cert-1", org_id="default", type=AssetType.certificate,
              value="cn=old.test", status=AssetStatus.active, tags=[],
              metadata_={"expires": "2000-01-01"}),
        Asset(id="svc-1", org_id="default", type=AssetType.service, value="22/tcp",
              status=AssetStatus.active, tags=[], metadata_={"protocol": "ssh"}),
        Asset(id="tech-1", org_id="default", type=AssetType.technology,
              value="nginx 1.18.0", status=AssetStatus.active, tags=[],
              metadata_={"eol": True}),
    ]
    result = risk._fallback_risk(assets)
    real_ids = {a.id for a in assets}
    assert result.score > 0
    assert result.findings  # something flagged
    assert all(f.asset_id in real_ids for f in result.findings)  # all grounded


def test_fallback_enrich_uses_heuristics():
    asset = Asset(id="a-1", org_id="default", type=AssetType.subdomain,
                  value="api.example.com", status=AssetStatus.active, tags=["prod"],
                  metadata_={})
    result = enrich._fallback_enrich(asset)
    assert result.environment == "prod"
    assert result.criticality == "high"


def test_fallback_report_from_stats():
    stats = {
        "total": 2,
        "by_type": {"certificate": 1, "service": 1},
        "certificate_states": {"expired": 1},
        "sensitive_services": ["22/tcp"],
        "end_of_life_technologies": [],
    }
    md = report._fallback_report(stats)
    assert "# Attack Surface Report" in md
    assert "expired" in md.lower()
    assert "22/tcp" in md
