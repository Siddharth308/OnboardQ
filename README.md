# OnboardIQ

AI-assisted data onboarding service. It takes messy customer CSV/Excel files and proposes how their columns map to a target schema.

## Status

| Area | State |
|---|---|
| Upload with size, type and encoding checks | Done |
| CSV/XLSX parsing and column profiling (PII-masked) | Done |
| Background pipeline with explicit job states | Done |
| Rule-based column matching (exact, synonym, fuzzy) | Done |
| Human review API (edit and approve mapping) | Planned |
| LLM structured-output mapping | Planned (Phase 4) |
| RAG over schema docs and past mappings | Planned (Phase 5) |
| Transform execution and row-level validation | Planned (Phase 6) |
| OpenTelemetry tracing, Prometheus metrics, eval suite | Planned (Phase 7) |
| AWS deployment via Terraform | Planned (Phase 8) |

Nothing in the planned rows is implemented yet. No accuracy figures are claimed.

## How it works

1. `POST /v1/jobs` stores the upload (max 10 MB, streamed with a byte counter) and returns `202`.
2. A background task parses and profiles the file, then matches its columns to the target schema:
   `UPLOADED → PROFILING → MAPPING → AWAITING_REVIEW`, or `FAILED` with a reason.
3. Rules run first: exact name, then known synonyms, then fuzzy similarity. Ambiguous fuzzy matches are left unresolved rather than guessed.
4. `GET /v1/jobs/{id}/mapping` returns the proposal with a confidence and reasoning per field.

Target schemas are YAML files in [`schemas/`](schemas/). Each field has a description, synonyms and a default transform.

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Docker is needed only for the container stack.

```bash
cp .env.example .env
make install
make dev                       # API on http://127.0.0.1:8000
```

Needs Postgres for the app. Start one with Docker Compose (`make up`), or point `ONBOARDIQ_DATABASE_URL` at your own instance and run `uv run alembic upgrade head`.

```bash
curl -F "file=@staff.csv" localhost:8000/v1/jobs
curl localhost:8000/v1/jobs/<job_id>/mapping
```

## Development

```bash
make check     # ruff lint and format check, mypy --strict, pytest with coverage gate
make audit     # dependency vulnerability scan
```

Integration tests run against a real Postgres when `ONBOARDIQ_TEST_DATABASE_URL` is set. Otherwise they are skipped.

## Layout

- `app/main.py`: application factory
- `app/core/`: settings, logging, middleware, error format (RFC 7807)
- `app/api/v1/`: HTTP routes
- `app/pipeline/`: parser, profiler, rule matcher, schema registry
- `app/services/`: job orchestration and state transitions
- `app/db/`: models, session, Alembic migrations
- `schemas/`: target schema definitions
- `tests/`: unit, API and Postgres integration tests

## Security notes

- Uploads are size-capped while streaming, and the format is checked from content as well as extension.
- Profiles and mappings mask personal-data columns and never include raw cell values.
- Errors use problem+json and do not echo submitted input.
- Known gap: XLSX files can expand in memory beyond their compressed size. The row limit is checked only after loading.
- Known gap: API-key auth and rate limiting are configured but not enforced yet.
