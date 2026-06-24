"""Core data-access logic: ingest/dedup/merge, lifecycle, filtering, graph.

This module deliberately contains *all* the ASM business rules so they are unit
testable without HTTP or the LLM in the loop.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Asset, AssetStatus, AssetType, Relationship
from .schemas import AssetFilter, AssetIn, ImportResult


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_value(asset_type: AssetType, value: str) -> str:
    """Normalize a value so equivalent assets dedupe to the same identity.

    Host-like assets are lowercased and trailing dots/whitespace stripped;
    everything else is just trimmed. Keeping this in one place means ingest and
    lookups always agree on identity.
    """
    v = (value or "").strip()
    if asset_type in (AssetType.domain, AssetType.subdomain, AssetType.certificate):
        v = v.rstrip(".").lower()
    return v


def _parse_expiry(metadata: dict) -> Optional[date]:
    """Best-effort parse of a certificate expiry from common metadata keys."""
    if not metadata:
        return None
    raw = metadata.get("expires") or metadata.get("expiry") or metadata.get("not_after")
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:  # last resort: ISO-8601 with offset
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def cert_state(metadata: dict, today: Optional[date] = None) -> Optional[str]:
    """Classify a certificate as 'expired' | 'expiring_soon' | 'valid'.

    Returns None when there is no parseable expiry date.
    """
    today = today or _utcnow().date()
    expiry = _parse_expiry(metadata)
    if expiry is None:
        return None
    if expiry < today:
        return "expired"
    if expiry <= today + timedelta(days=settings.expiring_soon_days):
        return "expiring_soon"
    return "valid"


# --------------------------------------------------------------------------- #
# Ingest: dedup + merge + lifecycle
# --------------------------------------------------------------------------- #


def upsert_asset(db: Session, item: AssetIn, org_id: str) -> tuple[Asset, bool]:
    """Insert a new asset or merge into an existing one. Returns (asset, created).

    Merge strategy (handles "conflicting data from two sources"):
      * identity = (org_id, type, canonical value)
      * a re-sighting always bumps `last_seen`
      * a stale/archived asset seen again returns to `active` (re-appearing asset)
      * tags are unioned; metadata keys from the incoming record win, but keys
        only the existing record has are preserved
      * `first_seen` is never moved backwards
    """
    value = canonical_value(item.type, item.value)
    existing = db.execute(
        select(Asset).where(
            Asset.org_id == org_id, Asset.type == item.type, Asset.value == value
        )
    ).scalar_one_or_none()

    now = _utcnow()

    if existing is None:
        asset = Asset(
            external_id=item.id,
            org_id=org_id,
            type=item.type,
            value=value,
            status=item.status,
            first_seen=now,
            last_seen=now,
            source=item.source,
            tags=sorted(set(item.tags or [])),
            metadata_=dict(item.metadata or {}),
        )
        db.add(asset)
        db.flush()  # assign PK so relationships can reference it
        return asset, True

    # --- merge into existing ---
    existing.last_seen = now
    if existing.status in (AssetStatus.stale, AssetStatus.archived):
        existing.status = AssetStatus.active  # re-appearing asset returns to active
    if item.source:
        existing.source = item.source
    if item.id and not existing.external_id:
        existing.external_id = item.id

    merged_tags = set(existing.tags or []) | set(item.tags or [])
    existing.tags = sorted(merged_tags)

    merged_meta = dict(existing.metadata_ or {})
    merged_meta.update(item.metadata or {})  # incoming record wins on conflict
    existing.metadata_ = merged_meta

    return existing, False


def _rel_type_for(field: str, child: Asset) -> str:
    if field == "parent":
        return "subdomain_of" if child.type == AssetType.subdomain else "part_of"
    if field == "covers":
        return "covers"
    if field == "resolves_to":
        return "resolves_to"
    return field


def _add_relationship(db: Session, src: Asset, dst: Asset, rel_type: str) -> bool:
    """Create an edge if it does not already exist. Returns True if created."""
    if src.id == dst.id:
        return False
    exists = db.execute(
        select(Relationship.id).where(
            Relationship.src_asset_id == src.id,
            Relationship.dst_asset_id == dst.id,
            Relationship.rel_type == rel_type,
        )
    ).first()
    if exists:
        return False
    db.add(Relationship(src_asset_id=src.id, dst_asset_id=dst.id, rel_type=rel_type))
    return True


def import_assets(db: Session, items: list[dict], org_id: str) -> ImportResult:
    """Bulk import: idempotent dedup, then wire relationships by external id.

    Each raw record is validated individually so a single malformed record is
    skipped and reported, never aborting the whole batch.
    """
    created = updated = 0
    skipped: list[dict] = []
    # external_id -> Asset, so relationship hints (which reference import ids)
    # can be resolved after all rows exist.
    by_external: dict[str, Asset] = {}
    hints: list[tuple[Asset, str, str]] = []  # (child, field, target_external_id)

    for idx, raw in enumerate(items):
        try:
            item = AssetIn(**raw)  # per-row validation -> ValidationError is caught below
            if not item.value or not str(item.value).strip():
                raise ValueError("missing 'value'")
            asset, was_created = upsert_asset(db, item, org_id)
            created += int(was_created)
            updated += int(not was_created)
            if item.id:
                by_external[item.id] = asset
            for field in ("parent", "covers", "resolves_to"):
                target = getattr(item, field)
                if target:
                    hints.append((asset, field, target))
        except Exception as exc:  # noqa: BLE001 - we intentionally never crash the batch
            skipped.append({"index": idx, "value": raw.get("value"), "error": str(exc)})

    rel_count = 0
    for child, field, target_external_id in hints:
        target = by_external.get(target_external_id)
        if target is None:
            continue  # dangling reference; skip silently
        if _add_relationship(db, child, target, _rel_type_for(field, child)):
            rel_count += 1

    db.commit()
    return ImportResult(created=created, updated=updated, relationships=rel_count, skipped=skipped)


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


def mark_stale(db: Session, asset_id: str, org_id: str) -> Optional[Asset]:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.org_id != org_id:
        return None
    asset.status = AssetStatus.stale
    db.commit()
    return asset


def mark_stale_older_than(db: Session, days: int, org_id: str) -> int:
    """Bulk-mark active assets not seen in `days` days as stale. Returns count."""
    cutoff = _utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Asset).where(
            Asset.org_id == org_id,
            Asset.status == AssetStatus.active,
            Asset.last_seen < cutoff,
        )
    ).scalars().all()
    for a in rows:
        a.status = AssetStatus.stale
    db.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Query / filter
# --------------------------------------------------------------------------- #


def filter_assets(db: Session, f: AssetFilter, org_id: str) -> tuple[int, list[Asset]]:
    """Translate an AssetFilter into a safe parameterized query.

    Returns (total_matching, page_of_assets). When `cert_state` is requested we
    must inspect each certificate's metadata, so that part is filtered in Python.
    """
    stmt = select(Asset).where(Asset.org_id == org_id)

    if f.types:
        stmt = stmt.where(Asset.type.in_(f.types))
    if f.statuses:
        stmt = stmt.where(Asset.status.in_(f.statuses))
    if f.value_contains:
        stmt = stmt.where(Asset.value.ilike(f"%{f.value_contains}%"))
    if f.cert_state:
        stmt = stmt.where(Asset.type == AssetType.certificate)

    # Tag membership and certificate-state both require inspecting JSON, which we
    # do in Python so the query stays portable across Postgres and SQLite.
    if f.tags_any or f.cert_state:
        rows = db.execute(stmt.order_by(Asset.value)).scalars().all()
        if f.tags_any:
            wanted = set(f.tags_any)
            rows = [a for a in rows if wanted & set(a.tags or [])]
        if f.cert_state:
            rows = [a for a in rows if cert_state(a.metadata_) == f.cert_state]
        total = len(rows)
        return total, rows[f.offset : f.offset + f.limit]

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    page = db.execute(
        stmt.order_by(Asset.value).offset(f.offset).limit(f.limit)
    ).scalars().all()
    return total, page


def get_asset(db: Session, asset_id: str, org_id: str) -> Optional[Asset]:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.org_id != org_id:
        return None
    return asset


def get_graph(db: Session, asset_id: str, org_id: str):
    """Return an asset plus its neighbours (both edge directions)."""
    asset = get_asset(db, asset_id, org_id)
    if asset is None:
        return None
    related = []
    for edge in asset.out_edges:
        related.append(("out", edge.rel_type, edge.dst))
    for edge in asset.in_edges:
        related.append(("in", edge.rel_type, edge.src))
    return asset, related


def get_assets_by_ids(db: Session, ids: list[str], org_id: str) -> list[Asset]:
    if not ids:
        return []
    rows = db.execute(
        select(Asset).where(Asset.org_id == org_id, Asset.id.in_(ids))
    ).scalars().all()
    return rows
