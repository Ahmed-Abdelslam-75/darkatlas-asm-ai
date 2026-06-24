# Submission email (draft)

> Reply to Ahmed Abdeltawab's email. **Put Khaled Elborai in CC.** Replace the
> `<...>` placeholders before sending.

---

**To:** a.abdeltawab@buguard.io
**Cc:** k.elborai@buguard.io
**Subject:** AI Internship Technical Assessment — Submission — <Your Full Name>

---

Dear Mr. Ahmed, Mr. Khaled,

Thank you for the opportunity. Please find my completed technical assessment for
the AI Internship Program below.

I implemented **Track B (AI Applications)** — a slice of the DarkAtlas Asset
Management module: a FastAPI + PostgreSQL service that ingests and de-duplicates
assets, tracks their lifecycle and relationships, and exposes a LangChain-powered
analysis layer over the data.

**GitHub repository:** <https://github.com/your-username/your-repo>

Highlights:
- **All four LangChain capabilities** working over the data: natural-language
  asset query, risk scoring & summarization, enrichment & categorization, and
  report generation.
- **Grounding / anti-hallucination by design:** the model only ever produces a
  validated structured filter (never raw SQL), and every risk finding is checked
  against the real assets so the model cannot invent assets. Each endpoint also
  falls back to a deterministic, fully-grounded result if the model returns
  nothing.
- **ASM edge cases handled:** idempotent imports, conflicting-source merge,
  stale→active re-appearance, malformed-record skipping, certificate
  expired-vs-expiring logic, and pagination.
- **Infra & docs:** one-command `docker-compose` (API + PostgreSQL), auto-generated
  Swagger at `/docs`, a full README with example prompts and real outputs, an
  automated test suite (20 tests), and a GitHub Actions CI pipeline.
- **Bonus:** multi-tenant isolation (`org_id`) across the data model and API.

LLM provider: Google Gemini via LangChain (the task allows any provider; I chose
Gemini for its free tier). The model is isolated in one module, so switching
providers is a one-file change. Setup, environment variables, design decisions,
and assumptions are documented in the README.

I'm happy to walk through any part of the implementation. Thank you for your time.

Best regards,
<Your Full Name>
<Your phone number>
<Your LinkedIn / GitHub, optional>
