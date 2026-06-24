# DarkAtlas Asset Management — Track B (AI Applications) Build Plan

> Buguard AI Internship technical assessment. This document is the implementation
> plan for **Track B: AI Applications** — a minimal API plus a LangChain-powered
> analysis layer over Attack Surface Monitoring (ASM) asset data.

---

## 1. What this task is

DarkAtlas is Buguard's **Attack Surface Monitoring** platform. It discovers an
organization's internet-facing assets — domains, subdomains, IP addresses,
exposed services, TLS certificates, and technologies — so security teams can see
and shrink their external attack surface.

The **Asset Management** module is the system of record: it ingests discovered
assets, removes duplicates, tracks each asset's lifecycle and relationships, and
exposes everything for querying, analysis, and reporting.

We are building a **self-contained slice** of that module for the **AI track**:
a small API to load the sample dataset, plus a mandatory LangChain analysis layer
providing four capabilities. No live scanning is required.

---

## 2. Stack & guiding principle

- **Python · FastAPI · PostgreSQL** (SQLAlchemy + Alembic migrations)
- **LangChain + `langchain-google-genai`**, model **`gemini-2.5-flash`** (key from env)
- One-command run via **docker-compose** (API + PostgreSQL)

**Guiding principle (highest-scored rubric item — grounding & guardrails):**
the LLM never invents data and never touches the database directly.

- **NL queries:** the model translates English → a *validated structured filter*
  (Pydantic schema via LangChain structured output); **our code** runs that
  filter against Postgres. the model never writes raw SQL.
- **Risk / report / enrichment:** we fetch the real rows first and pass **only
  those rows** to the model, with a hard "use only provided assets" instruction and
  a **post-check** that every asset ID the model references exists in the input set.
  Anything ungrounded is dropped.

---

## 3. Project layout

```
darkatlas-asm/
├─ docker-compose.yml            # api + postgres, one command
├─ .env.example                  # GOOGLE_API_KEY, DB url, API key (no secrets committed)
├─ README.md                     # setup, design, example prompts + outputs
├─ requirements.txt
├─ alembic/                      # migrations
├─ data/sample_assets.json       # provided dataset (seeded via import endpoint)
└─ app/
   ├─ main.py                    # FastAPI app + router wiring
   ├─ config.py                  # env-driven settings (pydantic-settings)
   ├─ db.py                      # engine / session
   ├─ models.py                  # Asset, Relationship (SQLAlchemy)
   ├─ schemas.py                 # Pydantic request/response + NL→filter schema
   ├─ auth.py                    # API-key dependency on write operations
   ├─ crud.py                    # dedup/merge, lifecycle, filtering, relationships
   ├─ routers/
   │   ├─ assets.py              # POST /import (+ minimal list / get)
   │   └─ analyze.py             # the 4 AI endpoints
   ├─ ai/
   │   ├─ llm.py                 # ChatGoogleGenerativeAI(model="gemini-2.5-flash") factory
   │   ├─ nl_query.py            # capability 1: NL → structured filter → results
   │   ├─ risk.py                # capability 2: risk scoring & summary (grounded)
   │   ├─ enrich.py              # capability 3: classify env / category / criticality
   │   └─ report.py              # capability 4: inventory / risk report
   └─ tests/                     # import+dedup, NL→filter, grounding guard, risk
```

---

## 4. Data model

**asset**
| field | notes |
|---|---|
| `id` | uuid, internal PK |
| `external_id` | the dataset's `"id"` (e.g. `a1`), used to wire relationships |
| `org_id` | multi-tenancy scoping (bonus) |
| `type` | enum: domain, subdomain, ip_address, service, certificate, technology |
| `value` | canonical value (e.g. `api.example.com`, `443/tcp`) |
| `status` | enum: active, stale, archived |
| `first_seen` / `last_seen` | datetimes |
| `source` | import, scan, manual |
| `tags` | jsonb array |
| `metadata` | jsonb (cert issuer/expiry, service banner, tech version…) |

- **Dedup key:** unique `(org_id, type, value)`
- **Indexes:** `type`, `status`, `value`

**relationship**
- `src_asset_id`, `dst_asset_id`, `rel_type`, unique `(src, dst, rel_type)`
- Built from the dataset's `parent` / `covers` fields during import.

---

## 5. The four LangChain capabilities (all mandatory)

1. **Natural-language asset query** — `with_structured_output(AssetFilter)` turns
   English into a structured filter; `crud.filter_assets()` executes it. Ambiguous
   or out-of-scope queries return a clarification, not a guess.
2. **Risk scoring & summarization** — over a real asset/group: flags expired and
   expiring-soon certs (against runtime "today"), sensitive exposed services,
   end-of-life tech; returns a score + concise summary.
3. **Automated enrichment & categorization** — classifies environment
   (prod/staging/dev), category, and criticality from value/tags/metadata; returns
   structured fields we can persist.
4. **Natural-language report generation** — readable inventory/risk report over the
   dataset or a filtered subset.

Each AI endpoint handles model errors and empty data gracefully and stays grounded
in the database.

---

## 6. Minimal API surface

- `POST /import` — bulk import the sample dataset (idempotent, dedup + merge)
- `GET /assets` — minimal list with filtering + pagination (supports the AI layer)
- `GET /assets/{id}` — single asset
- `POST /analyze/query` — capability 1
- `POST /analyze/risk` — capability 2
- `POST /analyze/enrich` — capability 3
- `POST /analyze/report` — capability 4
- Swagger UI auto-generated at `/docs`

Write operations require a lightweight **API key** (`X-API-Key` header).

---

## 7. Edge cases handled (assessment §7)

- **Idempotent imports** — importing twice creates no duplicates
- **Conflicting data** — merge: newest `last_seen` wins per field; tags/metadata unioned
- **Re-appearing assets** — a `stale` asset seen again returns to `active`
- **Malformed records** — skipped per-row; batch continues and returns an error report
- **Large lists** — pagination with sane defaults
- **Certificate dates** — expired vs expiring-soon distinction
- **Hallucination** — answers grounded; ungrounded asset references dropped
- **Multi-tenant isolation** — `org_id` scoping so one org never sees another's assets

---

## 8. Tests, docs, infra

- **pytest:** import+dedup, NL→filter translation, the grounding guard, risk logic
- **Docs:** FastAPI Swagger (free) + README with env vars, run/test commands, design
  decisions, and **example prompts + their outputs** (required for the AI track)
- **Infra:** `docker-compose.yml` brings up API + PostgreSQL with one command;
  `.env.example` documents config; no secrets committed

---

## 9. Scoring target

Targets the full Track B 100 points (4 LangChain features = 40, LLM integration
quality = 20, API & data integration = 10, data modeling = 10, code quality = 10,
README = 10) plus bonus (multi-tenancy, caching).

---

## 10. Assumptions

- This is the **AI track** (the acceptance email is for the AI Internship program).
- LLM provider: **Google Gemini** (`gemini-2.5-flash`); key read from
  `GOOGLE_API_KEY`, never committed.
- "Today" for certificate expiry logic is computed at runtime (not hardcoded).
- Relationships are derived from the sample dataset's `parent` / `covers` fields.
