"""SQLAlchemy ORM models: the asset system-of-record and its relationship graph.

Design notes
------------
* `Asset` carries the canonical fields from the task's core domain model plus an
  `org_id` for multi-tenant isolation (a bonus item) and an `external_id` that
  preserves the id from the import file so we can wire up relationships.
* The natural identity of an asset for **deduplication** is the triple
  ``(org_id, type, value)`` — enforced by a UNIQUE constraint. Re-importing the
  same asset therefore updates the existing row instead of creating a duplicate.
* `tags` and `metadata_` are JSON columns: assets are heterogeneous (a cert has
  an issuer/expiry, a service has a banner) so a rigid column-per-field schema
  would be wrong here.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Use Postgres JSONB in production but fall back to generic JSON on SQLite, so
# the test suite can run in-memory without a Postgres server.
JSONType = JSONB().with_variant(JSON(), "sqlite")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class AssetType(str, enum.Enum):
    domain = "domain"
    subdomain = "subdomain"
    ip_address = "ip_address"
    service = "service"
    certificate = "certificate"
    technology = "technology"


class AssetStatus(str, enum.Enum):
    active = "active"
    stale = "stale"
    archived = "archived"


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        # Deduplication identity: one row per (tenant, type, canonical value).
        UniqueConstraint("org_id", "type", "value", name="uq_asset_identity"),
        # Indexes backing the list/filter endpoints.
        Index("ix_assets_type", "type"),
        Index("ix_assets_status", "status"),
        Index("ix_assets_value", "value"),
        Index("ix_assets_org", "org_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False, default="default")

    type: Mapped[AssetType] = mapped_column(Enum(AssetType, name="asset_type"), nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"), nullable=False, default=AssetStatus.active
    )

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    source: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    # `metadata` is reserved by SQLAlchemy's Declarative API, so the attribute is
    # `metadata_` while the DB column stays "metadata".
    metadata_: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)

    # Relationships where this asset is the source / destination node.
    out_edges: Mapped[list["Relationship"]] = relationship(
        back_populates="src", foreign_keys="Relationship.src_asset_id",
        cascade="all, delete-orphan",
    )
    in_edges: Mapped[list["Relationship"]] = relationship(
        back_populates="dst", foreign_keys="Relationship.dst_asset_id",
        cascade="all, delete-orphan",
    )


class Relationship(Base):
    """A directed edge between two assets (the relationships graph).

    Examples: subdomain --subdomain_of--> domain, service --runs_on--> ip_address,
    certificate --covers--> subdomain.
    """

    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint(
            "src_asset_id", "dst_asset_id", "rel_type", name="uq_relationship_identity"
        ),
        Index("ix_rel_src", "src_asset_id"),
        Index("ix_rel_dst", "dst_asset_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    src_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    dst_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    rel_type: Mapped[str] = mapped_column(String, nullable=False)

    src: Mapped["Asset"] = relationship(back_populates="out_edges", foreign_keys=[src_asset_id])
    dst: Mapped["Asset"] = relationship(back_populates="in_edges", foreign_keys=[dst_asset_id])
