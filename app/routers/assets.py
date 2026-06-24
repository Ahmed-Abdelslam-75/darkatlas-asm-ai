"""Asset endpoints: bulk import (with dedup), list/filter, fetch, graph, lifecycle."""

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud
from ..auth import get_org_id, require_api_key
from ..db import get_db
from ..models import AssetStatus, AssetType
from ..schemas import (
    AssetFilter,
    AssetGraphOut,
    AssetOut,
    ImportResult,
    PageOut,
    RelatedAssetOut,
)

router = APIRouter(tags=["assets"])

SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sample_assets.json"


@router.post("/import", response_model=ImportResult, dependencies=[Depends(require_api_key)])
def import_assets(
    assets: list[dict] = Body(..., description="Array of raw asset records."),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """Bulk-ingest assets. Idempotent: re-importing updates instead of duplicating."""
    return crud.import_assets(db, assets, org_id)


@router.post(
    "/import/sample", response_model=ImportResult, dependencies=[Depends(require_api_key)]
)
def import_sample(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Convenience seeder that ingests the bundled data/sample_assets.json."""
    if not SAMPLE_PATH.exists():
        raise HTTPException(status_code=404, detail="sample_assets.json not found")
    records = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return crud.import_assets(db, records, org_id)


@router.get("/assets", response_model=PageOut)
def list_assets(
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    type: Optional[AssetType] = Query(default=None),
    status: Optional[AssetStatus] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    value_contains: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List assets with filtering, sorting (by value), and pagination."""
    f = AssetFilter(
        types=[type] if type else None,
        statuses=[status] if status else None,
        tags_any=[tag] if tag else None,
        value_contains=value_contains,
        limit=limit,
        offset=offset,
    )
    total, items = crud.filter_assets(db, f, org_id)
    return PageOut(
        total=total, limit=limit, offset=offset,
        items=[AssetOut.from_orm_asset(a) for a in items],
    )


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    asset = crud.get_asset(db, asset_id, org_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetOut.from_orm_asset(asset)


@router.get("/assets/{asset_id}/graph", response_model=AssetGraphOut)
def get_asset_graph(
    asset_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    """Fetch an asset together with the related assets around it (the graph)."""
    result = crud.get_graph(db, asset_id, org_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset, related = result
    base = AssetOut.from_orm_asset(asset)
    return AssetGraphOut(
        **base.model_dump(),
        related=[
            RelatedAssetOut(rel_type=rt, direction=direction, asset=AssetOut.from_orm_asset(other))
            for (direction, rt, other) in related
        ],
    )


@router.post(
    "/assets/{asset_id}/stale",
    response_model=AssetOut,
    dependencies=[Depends(require_api_key)],
)
def mark_asset_stale(
    asset_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)
):
    """Lifecycle: mark a single asset as stale."""
    asset = crud.mark_stale(db, asset_id, org_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetOut.from_orm_asset(asset)
