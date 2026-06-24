"""Capability 1 — Natural-language asset query.

The model's ONLY job is to translate the analyst's question into a structured
`AssetFilter`. It never sees the data and never writes SQL. Our own code then
runs that filter against Postgres, so results are always grounded in real rows.
"""

from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ..schemas import AssetFilter
from .llm import get_llm

SYSTEM = """You translate a security analyst's natural-language question into a \
structured filter over an Attack Surface Monitoring (ASM) asset inventory.

Asset types: domain, subdomain, ip_address, service, certificate, technology.
Lifecycle statuses: active, stale, archived.

Rules:
- Only populate fields that the question clearly implies; leave the rest null.
- Environment words map to tags: "production"/"prod" -> tags_any ["prod"];
  "staging" -> ["staging"]; "dev"/"development" -> ["dev"].
- "expired certificate(s)" -> types ["certificate"], cert_state "expired".
  "expiring soon" / "about to expire" -> cert_state "expiring_soon".
- A bare hostname or keyword the analyst wants to find -> value_contains.
- If the question is NOT about this asset inventory (out of scope), set
  answerable=false and put a short clarification message; leave the filter empty.
- Never invent assets, counts, or values. You only build a filter."""


class QueryInterpretation(BaseModel):
    """What the LLM returns: a filter plus a flag/clarification for guardrails."""

    filter: AssetFilter = Field(default_factory=AssetFilter)
    answerable: bool = Field(
        default=True, description="False when the question is not about the asset inventory."
    )
    clarification: Optional[str] = Field(
        default=None, description="A short note shown to the user when not answerable or ambiguous."
    )


def interpret_query(query: str) -> QueryInterpretation:
    """Use the model (structured output) to turn the question into a filter."""
    llm = get_llm().with_structured_output(QueryInterpretation)
    prompt = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", "{question}")])
    chain = prompt | llm
    result: QueryInterpretation | None = chain.invoke({"question": query})
    if result is None:  # model returned nothing parseable
        return QueryInterpretation(
            filter=AssetFilter(),
            answerable=False,
            clarification="Could not interpret the question; please rephrase it.",
        )
    return result
