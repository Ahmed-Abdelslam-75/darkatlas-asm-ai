"""Lightweight authentication and tenant scoping.

* Write operations require a shared secret in the `X-API-Key` header.
* Every request resolves an `org_id` (from the optional `X-Org-ID` header),
  which is threaded through the data layer so one tenant never sees another's
  assets — the multi-tenancy guardrail.
"""

from fastapi import Header, HTTPException, status

from .config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Dependency for write endpoints. Rejects requests without the right key."""
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key (set the X-API-Key header).",
        )
    return x_api_key


async def get_org_id(x_org_id: str | None = Header(default=None)) -> str:
    """Resolve the tenant for this request, defaulting to the configured org."""
    return x_org_id or settings.default_org_id
