"""Pydantic models for request/response bodies and the LLM structured outputs.

These are the public contract of the API (FastAPI uses them to generate the
OpenAPI/Swagger docs) and also the schemas we hand to the model via LangChain's
`with_structured_output`, which is how we keep the model's output constrained
and machine-checkable.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .models import AssetStatus, AssetType

# --------------------------------------------------------------------------- #
# Import / ingest
# --------------------------------------------------------------------------- #


class AssetIn(BaseModel):
    """One record as it appears in the sample dataset. Most fields are optional
    so that partial/messy records can still be ingested rather than rejected."""

    id: Optional[str] = None
    type: AssetType
    value: str
    status: AssetStatus = AssetStatus.active
    source: Optional[str] = "import"
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    # Relationship hints used by the sample dataset.
    parent: Optional[str] = None  # subdomain -> domain
    covers: Optional[str] = None  # certificate -> subdomain/domain
    resolves_to: Optional[str] = None  # ip/subdomain resolution


class ImportResult(BaseModel):
    created: int
    updated: int
    relationships: int
    skipped: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Asset output
# --------------------------------------------------------------------------- #


class AssetOut(BaseModel):
    id: str
    external_id: Optional[str]
    org_id: str
    type: AssetType
    value: str
    status: AssetStatus
    first_seen: datetime
    last_seen: datetime
    source: Optional[str]
    tags: list[str]
    metadata: dict

    @classmethod
    def from_orm_asset(cls, a) -> "AssetOut":
        return cls(
            id=a.id,
            external_id=a.external_id,
            org_id=a.org_id,
            type=a.type,
            value=a.value,
            status=a.status,
            first_seen=a.first_seen,
            last_seen=a.last_seen,
            source=a.source,
            tags=a.tags or [],
            metadata=a.metadata_ or {},
        )


class RelatedAssetOut(BaseModel):
    rel_type: str
    direction: Literal["out", "in"]
    asset: AssetOut


class AssetGraphOut(AssetOut):
    related: list[RelatedAssetOut] = Field(default_factory=list)


class PageOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AssetOut]


# --------------------------------------------------------------------------- #
# Structured filter — the schema the model fills in for natural-language queries.
# the model NEVER writes SQL; it only produces this object, which our own code
# translates into a safe parameterized query.
# --------------------------------------------------------------------------- #


class AssetFilter(BaseModel):
    """A structured representation of an asset query."""

    types: Optional[list[AssetType]] = Field(
        default=None, description="Restrict to these asset types."
    )
    statuses: Optional[list[AssetStatus]] = Field(
        default=None, description="Restrict to these lifecycle statuses."
    )
    tags_any: Optional[list[str]] = Field(
        default=None, description="Match assets having ANY of these tags (e.g. 'prod')."
    )
    value_contains: Optional[str] = Field(
        default=None, description="Substring that must appear in the asset value."
    )
    cert_state: Optional[Literal["expired", "expiring_soon", "valid"]] = Field(
        default=None,
        description="For certificates: filter by expiry state relative to today.",
    )
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# --------------------------------------------------------------------------- #
# Analysis request/response bodies
# --------------------------------------------------------------------------- #


class NLQueryRequest(BaseModel):
    query: str = Field(..., description="Plain-English question about the assets.")
    org_id: Optional[str] = None


class NLQueryResponse(BaseModel):
    interpreted_filter: AssetFilter
    count: int
    assets: list[AssetOut]
    note: Optional[str] = None  # e.g. clarification for ambiguous/out-of-scope queries


class RiskRequest(BaseModel):
    asset_ids: Optional[list[str]] = Field(
        default=None, description="Specific assets to assess. If omitted, uses the filter."
    )
    filter: Optional[AssetFilter] = None
    org_id: Optional[str] = None


class RiskFinding(BaseModel):
    asset_id: str
    asset_value: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    reason: str


class RiskResponse(BaseModel):
    score: int = Field(..., ge=0, le=100, description="0 = clean, 100 = severe.")
    summary: str
    findings: list[RiskFinding]
    assessed_count: int


class EnrichRequest(BaseModel):
    asset_id: str
    org_id: Optional[str] = None
    persist: bool = Field(default=False, description="Write enrichment back into metadata.")


class EnrichResult(BaseModel):
    asset_id: str
    environment: Literal["prod", "staging", "dev", "unknown"]
    category: str
    criticality: Literal["critical", "high", "medium", "low"]
    rationale: str


class ReportRequest(BaseModel):
    filter: Optional[AssetFilter] = None
    org_id: Optional[str] = None


class ReportResponse(BaseModel):
    report_markdown: str
    asset_count: int
