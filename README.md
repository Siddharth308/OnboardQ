# OnboardIQ

AI data onboarding service. Maps messy customer CSV/Excel files to target schemas.

> Status: Phase 1 (foundation). Upload, mapping and review come in later phases.

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
cp .env.example .env
make install
make dev            # API on http://127.0.0.1:8000 with reload
curl localhost:8000/healthz
```

Full stack in containers:

```bash
make up
curl localhost:8000/healthz
make down
```

## Development

```bash
make check          # lint + mypy --strict + tests with coverage gate
make audit          # dependency vulnerability scan
```

## Layout

- `app/main.py`: application factory
- `app/core/`: settings, logging, middleware
- `app/api/v1/`: HTTP routers
- `tests/`: unit and API tests
- `docs/`: design decisions and interview notes (added in Phase 9)
