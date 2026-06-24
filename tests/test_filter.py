"""Filtering, pagination, and certificate-state logic."""

import json
from datetime import date, timedelta
from pathlib import Path

from app import crud
from app.crud import cert_state
from app.models import AssetType
from app.schemas import AssetFilter

SAMPLE = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "sample_assets.json").read_text()
)


def test_cert_state_classification():
    today = date(2026, 6, 23)
    assert cert_state({"expires": "2025-01-02"}, today) == "expired"
    assert cert_state({"expires": "2026-07-05"}, today) == "expiring_soon"
    assert cert_state({"expires": "2027-12-31"}, today) == "valid"
    assert cert_state({}, today) is None


def test_filter_by_type_and_tag(db_session):
    crud.import_assets(db_session, SAMPLE, "default")

    total_certs, _ = crud.filter_assets(
        db_session, AssetFilter(types=[AssetType.certificate]), "default"
    )
    assert total_certs == 3

    total_prod, prod = crud.filter_assets(
        db_session, AssetFilter(tags_any=["prod"]), "default"
    )
    assert total_prod >= 1
    assert all("prod" in a.tags for a in prod)


def test_value_contains_filter(db_session):
    crud.import_assets(db_session, SAMPLE, "default")
    total, items = crud.filter_assets(
        db_session, AssetFilter(value_contains="staging"), "default"
    )
    assert total >= 1
    assert all("staging" in a.value for a in items)


def test_pagination(db_session):
    crud.import_assets(db_session, SAMPLE, "default")
    total, page1 = crud.filter_assets(db_session, AssetFilter(limit=5, offset=0), "default")
    _, page2 = crud.filter_assets(db_session, AssetFilter(limit=5, offset=5), "default")
    assert total == 13
    assert len(page1) == 5
    # Pages don't overlap.
    assert {a.id for a in page1}.isdisjoint({a.id for a in page2})


def test_cert_state_filter_is_deterministic(db_session):
    """Use dates relative to today so the test never depends on the wall clock."""
    today = date.today()
    records = [
        {"id": "c_exp", "type": "certificate", "value": "CN=expired.test",
         "metadata": {"expires": str(today - timedelta(days=10))}},
        {"id": "c_soon", "type": "certificate", "value": "CN=soon.test",
         "metadata": {"expires": str(today + timedelta(days=10))}},
        {"id": "c_ok", "type": "certificate", "value": "CN=ok.test",
         "metadata": {"expires": str(today + timedelta(days=400))}},
    ]
    crud.import_assets(db_session, records, "default")

    _, expired = crud.filter_assets(
        db_session, AssetFilter(cert_state="expired"), "default"
    )
    _, soon = crud.filter_assets(
        db_session, AssetFilter(cert_state="expiring_soon"), "default"
    )
    # Certificate values are canonicalized to lowercase on ingest (dedup rule).
    assert [a.value for a in expired] == ["cn=expired.test"]
    assert [a.value for a in soon] == ["cn=soon.test"]
