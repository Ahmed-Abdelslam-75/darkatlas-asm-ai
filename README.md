# DarkAtlas — Asset Management (AI Track)

[![CI](https://github.com/Ahmed-Abdelslam-75/darkatlas-asm-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Ahmed-Abdelslam-75/darkatlas-asm-ai/actions/workflows/ci.yml)

A self-contained slice of Buguard's **DarkAtlas** Attack Surface Monitoring (ASM)
*Asset Management* module. It ingests and de-duplicates discovered assets, tracks
their lifecycle and relationships, and exposes a **LangChain-powered analysis
layer** (natural-language query, risk scoring, enrichment, and reporting) over
the data.

> **Track:** AI Applications (Track B). Built with the suggested stack —
> **Python · FastAPI · PostgreSQL** — plus **LangChain + Google Gemini**.
> (The task allows any LLM provider; Gemini is used for its free cloud tier.)

---

## Table of contents
1. [Design at a glance](#design-at-a-glance)
2. [Grounding / anti-hallucination strategy](#grounding--anti-hallucination-strategy)
3. [Quick start (Docker)](#quick-start-docker)
4. [Environment variables](#environment-variables)
5. [API reference](#api-reference)
6. [Example prompts & outputs](#example-prompts--outputs)
7. [Running the tests](#running-the-tests)
8. [Edge cases handled](#edge-cases-handled)
9. [Design decisions & assumptions](#design-decisions--assumptions)
10. [What I would do next](#what-i-would-do-next)

---

## Design at a glance

```
            ┌──────────────────────── FastAPI ────────────────────────┐
            │  /import  /assets  /assets/{id}/graph   (data plane)     │
            │  /analyze/query  /risk  /enrich  /report  (AI plane)     │
            └───────────────┬───────────────────────┬─────────────────┘
                            │                       │
                     crud.py (ASM rules)      app/ai/* (LangChain)
                  dedup · merge · lifecycle    NL→filter · risk ·
                  filter · relationships       enrich · report
                            │                       │
                            ▼                       ▼
                      PostgreSQL  ◀── grounded context ──  Gemini (gemini-2.5-flash)
```

* **`app/models.py`** — `Asset` and `Relationship` ORM models. An asset's identity
  for deduplication is the triple `(org_id, type, value)`, enforced by a UNIQUE
  constraint.
* **`app/crud.py`** — all ASM business rules in one testable place (dedup/merge,
  lifecycle, filtering, relationship graph).
* **`app/ai/`** — the four LangChain capabilities. Each one builds its context
  from real database rows and never lets the model touch the database directly.

## Grounding / anti-hallucination strategy

The rubric weights "grounding & guardrails" heavily, so it drove the design:

| Capability | How the model is constrained |
|---|---|
| **NL query** | Gemini only produces a **validated `AssetFilter`** (via `with_structured_output`). It never writes SQL. Our code runs the filter against Postgres, so results are always real rows. Out-of-scope questions return `answerable=false` with a clarification instead of a guess. |
| **Risk scoring** | Gemini is given a compact projection of the **real assets** (with `cert_state`/`sensitive` precomputed in code). Every finding it returns is **filtered against the input id set** — a finding about a non-existent asset is dropped (`ground_findings`). |
| **Enrichment** | Operates on one fetched asset; the `asset_id` is set by our code, never chosen by the model. |
| **Report** | Built from the actual rows plus deterministic stats, with an explicit "use only the provided data" instruction. |

Date math (expired vs. expiring-soon) is computed in Python against the real
"today", not delegated to the model.

---

## Quick start (Docker)

**Prerequisites:** Docker + Docker Compose, and a Google Gemini API key
(free — get one at https://aistudio.google.com/apikey).

```bash
# 1. Configure secrets (never committed)
cp .env.example .env
#    then edit .env and set GOOGLE_API_KEY=AIza...

# 2. Start the API + PostgreSQL
docker compose up --build

# 3. Seed the bundled sample dataset (writes require the API key)
curl -X POST http://localhost:8000/import/sample -H "X-API-Key: dev-secret-key"

# 4. Open the interactive docs
#    http://localhost:8000/docs
```

The data-plane endpoints (import, list, graph) work without a Gemini key.
The `/analyze/*` endpoints need `GOOGLE_API_KEY`; without it they return a
clean `503` rather than crashing.

### Running locally without Docker

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
# Point DATABASE_URL at a local Postgres, then:
uvicorn app.main:app --reload
```

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | *(empty)* | Gemini API key for the analysis layer. **Required for `/analyze/*`.** |
| `LLM_MODEL` | `gemini-2.5-flash` | Gemini model used by LangChain. |
| `API_KEY` | `dev-secret-key` | Shared secret required in `X-API-Key` for write endpoints. |
| `DATABASE_URL` | `postgresql+psycopg2://asm:asm@db:5432/asm` | PostgreSQL connection. |
| `EXPIRING_SOON_DAYS` | `30` | A certificate within this many days of expiry is "expiring soon". |
| `DEFAULT_ORG_ID` | `default` | Tenant used when `X-Org-ID` is not supplied. |

See [`.env.example`](.env.example). Secrets live only in `.env`, which is
git-ignored.

---

## API reference

Interactive OpenAPI/Swagger docs are auto-generated at **`/docs`** (and ReDoc at
`/redoc`). Summary:

### Data plane
| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/import` | API key | Bulk-import an array of asset records (idempotent dedup + merge). |
| `POST` | `/import/sample` | API key | Seed the bundled `data/sample_assets.json`. |
| `GET` | `/assets` | — | List assets with `type`, `status`, `tag`, `value_contains`, `limit`, `offset`. |
| `GET` | `/assets/{id}` | — | Fetch one asset. |
| `GET` | `/assets/{id}/graph` | — | Fetch an asset together with its related assets. |
| `POST` | `/assets/{id}/stale` | API key | Lifecycle: mark an asset stale. |

### AI plane
| Method | Path | Description |
|---|---|---|
| `POST` | `/analyze/query` | Capability 1 — natural-language asset query. |
| `POST` | `/analyze/risk` | Capability 2 — risk scoring & summarization. |
| `POST` | `/analyze/enrich` | Capability 3 — enrichment & categorization. |
| `POST` | `/analyze/report` | Capability 4 — Markdown inventory/risk report. |

**Headers:** `X-API-Key` (writes), optional `X-Org-ID` (tenant scoping).

---

## Example prompts & outputs

> The outputs below are **real responses captured from `gemini-2.5-flash`**
> against the bundled sample dataset. Model wording will vary between runs; the
> **structure and the grounding behaviour are deterministic** (every finding
> references a real asset). Asset ids are shortened here for readability.

### 1. Natural-language query

```bash
curl -X POST http://localhost:8000/analyze/query \
  -H "Content-Type: application/json" \
  -d '{"query": "show me all expired certificates"}'
```

```json
{
  "interpreted_filter": { "types": ["certificate"], "cert_state": "expired", "limit": 50, "offset": 0 },
  "count": 1,
  "assets": [
    { "type": "certificate", "value": "cn=api.example.com",
      "status": "active", "metadata": { "issuer": "Let's Encrypt", "expires": "2025-01-02" } }
  ],
  "note": null
}
```

An out-of-scope question is refused instead of answered:

```bash
curl -X POST http://localhost:8000/analyze/query \
  -H "Content-Type: application/json" -d '{"query": "what is the weather in Cairo?"}'
```
```json
{ "interpreted_filter": {"limit": 50, "offset": 0}, "count": 0, "assets": [],
  "note": "This question is not about the asset inventory." }
```

### 2. Risk scoring & summarization

```bash
curl -X POST http://localhost:8000/analyze/risk \
  -H "Content-Type: application/json" -d '{}'
```

```json
{
  "score": 90,
  "summary": "The organization faces a high overall risk due to several critical and high-severity findings. A certificate for a production API is expired, and a sensitive MySQL database is exposed on a production asset. Furthermore, an SSH service is exposed on a development asset, and an end-of-life Nginx web server is in use, posing significant security vulnerabilities.",
  "findings": [
    { "asset_id": "7f422e06…", "asset_value": "cn=api.example.com", "severity": "critical", "reason": "Certificate for api.example.com is expired." },
    { "asset_id": "dd2f7221…", "asset_value": "cn=staging.example.com", "severity": "high", "reason": "Certificate for staging.example.com is expiring soon." },
    { "asset_id": "b98ac8dc…", "asset_value": "22/tcp", "severity": "high", "reason": "Sensitive SSH service (22/tcp) is exposed on a 'dev' tagged asset." },
    { "asset_id": "db09aa79…", "asset_value": "3306/tcp", "severity": "critical", "reason": "Sensitive MySQL database service (3306/tcp) is exposed on a 'prod' tagged asset." },
    { "asset_id": "2b134991…", "asset_value": "nginx 1.18.0", "severity": "high", "reason": "End-of-life technology 'nginx 1.18.0' is in use." }
  ],
  "assessed_count": 13
}
```

### 3. Enrichment & categorization

```bash
# asset_id comes from GET /assets
curl -X POST http://localhost:8000/analyze/enrich \
  -H "Content-Type: application/json" \
  -d '{"asset_id": "<id-of-api.example.com>", "persist": true}'
```

```json
{
  "asset_id": "59d31446…",
  "environment": "prod",
  "category": "web API",
  "criticality": "critical",
  "rationale": "This is a production, external-facing web API."
}
```

With `"persist": true` the classification is written back into the asset's
`metadata.enrichment`.

### 4. Report generation

```bash
curl -X POST http://localhost:8000/analyze/report \
  -H "Content-Type: application/json" -d '{}'
```

```json
{ "asset_count": 13, "report_markdown": "# Attack Surface Report\n\n..." }
```

Rendered `report_markdown` (real captured output):

> # Attack Surface Report
> This report summarizes the current attack surface, identifying 13 active assets
> across various types. Key risks include an expired SSL/TLS certificate, another
> certificate expiring soon, exposed sensitive services (SSH and MySQL), and the
> presence of an end-of-life technology, all of which warrant immediate attention.
>
> ## Inventory
> - **Total Assets:** 13 — 1 domain, 3 subdomains, 2 IP addresses, 3 services, 3 certificates, 1 technology
>
> ## Key Risks
> - **Expired Certificates:** `cn=api.example.com` is expired.
> - **Expiring Certificates:** `cn=staging.example.com` is expiring soon.
> - **Sensitive Exposed Services:** `22/tcp` (SSH), `3306/tcp` (MySQL).
> - **End-of-Life Technologies:** `nginx 1.18.0`.
>
> ## Recommendations
> 1. Immediately renew the expired certificate for `cn=api.example.com`.
> 2. Plan renewal of `cn=staging.example.com` before expiry.
> 3. Review and restrict access to sensitive services `22/tcp` and `3306/tcp`.
> 4. Upgrade or replace `nginx 1.18.0` with a supported version.

---

## Running the tests

The suite runs against in-memory SQLite — **no Postgres server and no API key
required** (the LLM is replaced by a deterministic fake built on a real
LangChain `Runnable`).

```bash
pip install -r requirements.txt
pytest -q
```

Coverage of the core logic the rubric calls out:

* `test_dedup.py` — idempotent import, conflicting-source merge, stale→active
  re-appearance, malformed-record skip, multi-tenant isolation.
* `test_filter.py` — type/tag/substring filters, pagination, certificate-state.
* `test_relationships.py` — graph edges built from import hints, idempotent.
* `test_ai_grounding.py` — the anti-hallucination guard, and NL→filter
  translation (in-scope and out-of-scope).

---

## Edge cases handled

| Edge case (assessment §7) | Handling |
|---|---|
| Idempotent imports | Identity = `(org_id, type, value)`; re-import updates, never duplicates. |
| Conflicting data | Merge: newest sighting wins per metadata key, tags unioned, `first_seen` preserved. |
| Re-appearing assets | A `stale`/`archived` asset seen again returns to `active`. |
| Malformed records | Validated per-row; bad rows are skipped and reported, batch continues. |
| Large lists | Pagination with sane defaults (`limit=50`, capped at 500). |
| Certificate dates | `expired` vs. `expiring_soon` vs. `valid`, computed against runtime "today". |
| Ambiguous / out-of-scope NL | `answerable=false` + clarification, no fabricated answer. |
| Hallucination | Findings/reports constrained to real rows; ungrounded ids dropped. |
| Multi-tenant isolation | Every query is scoped by `org_id` (`X-Org-ID` header). |

## Design decisions & assumptions

* **AI track.** The acceptance email is for the AI Internship, so this implements
  Track B (minimal API + the four mandatory LangChain capabilities).
* **Gemini via LangChain.** The task allows any provider; Google Gemini
  (`gemini-2.5-flash`) was chosen for its free cloud tier. The key is read from
  `GOOGLE_API_KEY` and never committed, and the LLM is isolated in
  `app/ai/llm.py` so swapping providers is a one-file change. `temperature=0`
  plus structured output and grounding keep results deterministic.
* **`create_all` over Alembic.** For a single self-contained slice, creating
  tables on startup is simpler and fully reproducible via docker-compose. The
  schema is small and explicit; Alembic would be the next step for production.
* **JSON for `tags`/`metadata`.** Assets are heterogeneous (a cert vs. a service
  have different fields), so a JSON column models them faithfully. The column is
  Postgres `JSONB` in production and falls back to generic `JSON` on SQLite so the
  tests run without a database server.
* **Relationships** are derived from the dataset's `parent` / `covers` /
  `resolves_to` hints during import.
* **Multi-tenancy** is modelled end-to-end (`org_id` on every row and query) as a
  bonus, even though the core task is single-tenant.

## Bonus items included

* **Multi-tenancy** — `org_id` scoping across the data model and every query.
* **CI** — GitHub Actions (`.github/workflows/ci.yml`) runs the test suite on every push/PR.
* **Graceful model-failure fallbacks** — every analysis endpoint degrades to a
  deterministic, fully-grounded result if the model returns nothing.

## What I would do next

* Alembic migrations and a seed CLI.
* Response caching for repeated `/analyze` calls (LangChain cache) — a listed bonus.
* Turn the analysis layer into an agent that calls the asset API as tools, plus an
  evaluation harness scoring grounding/quality.
* A small graph visualization of the relationships endpoint.
