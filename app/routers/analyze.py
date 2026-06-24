"""The LangChain-powered analysis endpoints (Track B's four capabilities).

Every endpoint resolves REAL assets from the database first, then hands them to
the AI layer. Model/configuration failures are turned into clean HTTP errors
rather than 500s, so the API degrades gracefully.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud
from ..ai import enrich as ai_enrich
from ..ai import nl_query as ai_query
from ..ai import report as ai_report
from ..ai import risk as ai_risk
from ..ai.llm import LLMNotConfigured
from ..auth import get_org_id
from ..db import get_db
from ..models import AssetStatus
from ..schemas import (
    AssetFilter,
    AssetOut,
    EnrichRequest,
    EnrichResult,
    NLQueryRequest,
    NLQueryResponse,
    ReportRequest,
    ReportResponse,
    RiskRequest,
    RiskResponse,
)

router = APIRouter(prefix="/analyze", tags=["analysis"])


def _guard(callable_, *args, **kwargs):
    """Run an LLM-backed call, mapping its failure modes to HTTP errors."""
    try:
        return callable_(*args, **kwargs)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface model/transport errors cleanly
        raise HTTPException(status_code=502, detail=f"LLM analysis failed: {exc}") from exc


@router.post("/query", response_model=NLQueryResponse)
def nl_query(
    body: NLQueryRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Capability 1: plain-English question -> structured query -> real matches."""
    org = body.org_id or org_id
    interpretation = _guard(ai_query.interpret_query, body.query)

    if not interpretation.answerable:
        return NLQueryResponse(
            interpreted_filter=interpretation.filter,
            count=0,
            assets=[],
            note=interpretation.clarification or "This question is out of scope for the asset inventory.",
        )

    total, items = crud.filter_assets(db, interpretation.filter, org)
    return NLQueryResponse(
        interpreted_filter=interpretation.filter,
        count=total,
        assets=[AssetOut.from_orm_asset(a) for a in items],
        note=interpretation.clarification,
    )


@router.post("/risk", response_model=RiskResponse)
def risk(
    body: RiskRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Capability 2: risk score + summary over selected/filtered assets."""
    org = body.org_id or org_id
    if body.asset_ids:
        assets = crud.get_assets_by_ids(db, body.asset_ids, org)
    else:
        f = body.filter or AssetFilter(statuses=[AssetStatus.active], limit=500)
        _, assets = crud.filter_assets(db, f, org)
    return _guard(ai_risk.assess_risk, assets)


@router.post("/enrich", response_model=EnrichResult)
def enrich(
    body: EnrichRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Capability 3: classify an asset's environment/category/criticality."""
    org = body.org_id or org_id
    asset = crud.get_asset(db, body.asset_id, org)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    result = _guard(ai_enrich.enrich_asset, asset)

    if body.persist:
        meta = dict(asset.metadata_ or {})
        meta["enrichment"] = result.model_dump(exclude={"asset_id"})
        asset.metadata_ = meta
        db.commit()

    return result


@router.post("/report", response_model=ReportResponse)
def report(
    body: ReportRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Capability 4: readable Markdown inventory/risk report."""
    org = body.org_id or org_id
    f = body.filter or AssetFilter(limit=500)
    _, assets = crud.filter_assets(db, f, org)
    markdown = _guard(ai_report.generate_report, assets)
    return ReportResponse(report_markdown=markdown, asset_count=len(assets))
