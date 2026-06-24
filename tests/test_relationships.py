"""Relationship graph: edges are built from import hints and fetched together."""

import json
from pathlib import Path

from app import crud
from app.models import AssetType
from app.schemas import AssetFilter

SAMPLE = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "sample_assets.json").read_text()
)


def _find(db, value, asset_type):
    _, items = crud.filter_assets(
        db, AssetFilter(types=[asset_type], value_contains=value), "default"
    )
    return items[0]


def test_relationships_are_created(db_session):
    result = crud.import_assets(db_session, SAMPLE, "default")
    assert result.relationships > 0


def test_graph_returns_neighbours(db_session):
    crud.import_assets(db_session, SAMPLE, "default")
    api = _find(db_session, "api.example.com", AssetType.subdomain)

    asset, related = crud.get_graph(db_session, api.id, "default")
    rel_types = {rt for (_direction, rt, _other) in related}

    # api.example.com is a subdomain_of example.com, resolves_to an IP, and is
    # covered by a certificate (incoming edge).
    assert "subdomain_of" in rel_types
    assert "resolves_to" in rel_types
    assert "covers" in rel_types


def test_relationships_are_idempotent(db_session):
    first = crud.import_assets(db_session, SAMPLE, "default")
    second = crud.import_assets(db_session, SAMPLE, "default")
    # Re-importing must not create duplicate edges.
    assert second.relationships == 0
    assert first.relationships > 0
