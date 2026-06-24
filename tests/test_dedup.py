"""Deduplication, merge, lifecycle, and malformed-record handling."""

import json
from pathlib import Path

from app import crud
from app.models import AssetStatus, AssetType

SAMPLE = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "sample_assets.json").read_text()
)


def _get(db, value, asset_type):
    _, items = crud.filter_assets(
        db,
        crud.AssetFilter(types=[asset_type], value_contains=value),
        "default",
    )
    return items[0] if items else None


def test_import_is_idempotent(db_session):
    first = crud.import_assets(db_session, SAMPLE, "default")
    # 13 unique valid assets created; the duplicate api.example.com row merges;
    # the record with no value is skipped.
    assert first.created == 13
    assert first.updated == 1
    assert len(first.skipped) == 1

    second = crud.import_assets(db_session, SAMPLE, "default")
    # Re-importing the identical file creates nothing new.
    assert second.created == 0
    assert second.updated == 14
    assert len(second.skipped) == 1


def test_conflicting_sources_are_merged(db_session):
    crud.import_assets(db_session, SAMPLE, "default")
    api = _get(db_session, "api.example.com", AssetType.subdomain)
    assert api is not None
    # Tags from both the scan and the manual record are unioned.
    assert "prod" in api.tags
    assert "external-facing" in api.tags
    # Metadata from the second source is merged in.
    assert api.metadata_.get("note") == "confirmed by analyst"
    # A re-sighting keeps the asset active.
    assert api.status == AssetStatus.active


def test_stale_asset_returns_to_active_when_seen_again(db_session):
    crud.import_assets(db_session, SAMPLE, "default")
    api = _get(db_session, "api.example.com", AssetType.subdomain)
    crud.mark_stale(db_session, api.id, "default")
    assert api.status == AssetStatus.stale

    # Importing again (re-sighting) should flip it back to active.
    crud.import_assets(db_session, SAMPLE, "default")
    db_session.refresh(api)
    assert api.status == AssetStatus.active


def test_malformed_record_is_skipped_not_fatal(db_session):
    result = crud.import_assets(db_session, SAMPLE, "default")
    assert result.created > 0  # the batch still succeeded
    assert any("value" in str(s["error"]) or s["value"] is None for s in result.skipped)


def test_tenants_are_isolated(db_session):
    crud.import_assets(db_session, SAMPLE, "org-a")
    crud.import_assets(db_session, SAMPLE, "org-b")
    total_a, _ = crud.filter_assets(db_session, crud.AssetFilter(limit=500), "org-a")
    total_b, _ = crud.filter_assets(db_session, crud.AssetFilter(limit=500), "org-b")
    total_c, _ = crud.filter_assets(db_session, crud.AssetFilter(limit=500), "org-c")
    assert total_a == 13
    assert total_b == 13
    assert total_c == 0  # an org that never imported sees nothing
