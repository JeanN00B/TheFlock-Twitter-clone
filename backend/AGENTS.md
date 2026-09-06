# Backend — FastAPI (hexagonal, capability-first)

## Capability modules
- Organize business capabilities under `app/<capability>/` with explicit
  `domain/`, `application/`, and `infrastructure/` modules.
- `app/users/` owns registration, including the public `POST /auth/register`
  route. Do not create an Auth capability for registration-only behavior.
- A later `app/auth/` capability owns login, session, and authentication
  behavior when that work is introduced.

## Dependency direction
- Within each capability, dependencies point inward:
  `infrastructure → application → domain`.
- Domain modules are framework-free and must not import application,
  infrastructure, FastAPI, SQLAlchemy, psycopg, Pydantic, or pwdlib code.
- Cross-capability imports may target only the other capability's domain values
  or application interfaces; never import its infrastructure modules, ORM
  models, routers, repositories, or composition helpers.
- Shared platform exceptions are `app/core/` and
  `app/infrastructure/database.py`; capability behavior remains in its
  capability module.

## Tooling (uv only — no pip)
- `uv sync` / `uv run ...`; locked with `uv.lock` (`--frozen` in Docker).
- DB: sync SQLAlchemy + psycopg (`postgresql+psycopg://...`), single alembic
  env (`alembic upgrade head` in entrypoint when `alembic.ini` exists).
- Tests: `pytest` with `pytest-cov --fail-under=80` (challenge minimum).

## Contracts
- `GET /health` → `{"status": "ok"}` (Docker HEALTHCHECK + compose gating).
- Routers live in capability `infrastructure/`; keep I/O at the edges.
