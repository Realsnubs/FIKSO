# FIKSO — home-repair master matching platform (MVP, work in progress)

FIKSO connects a client who needs a home repair job done with the **most suitable available, pre-qualified master**.
It is not a master catalogue: the backend proposes a master, the client confirms, alternatives may be shown.

> Status: unfinished MVP. Core flows work end to end locally; production integrations (maps, SMS, object storage)
> are implemented behind adapters but not yet verified with real provider accounts.

## What it does
- **Ordering** — catalogue (category → specialisation → service with immutable W-IDs), request with photos, city and
  communication language; ordering is possible without registering (password-less client account, SMS-code sign-in).
- **Deterministic matching** — competence, admin-verified qualifications, availability mode, work city, language,
  ETA and reputation; proposal and offer timers, up to 3 rounds; no AI in the decision.
- **Order lifecycle** — one state machine (offered → accepted → en route → started → completed → reviewed) with
  status history and append-only domain events written in the same transaction.
- **Masters** — availability modes incl. automatic Busy, work sheets, commission limit and blocking.
- **Admin** — master approval, qualification review, catalogue management with impact preview, signed catalogue
  export/import between environments, public content and media, audit log.
- **Privacy & security** — role + ownership checks on every endpoint, exact address/phone revealed only after
  assignment, private file storage through an authorised API, rate limits, no secrets in the repo.
- **UI** — Latvian, English and Russian; mobile-first PWA; light and dark themes.

## Stack
| Layer | Technology |
|---|---|
| Backend | Python 3, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL (btree_gist), background worker |
| Frontend | React 19, TypeScript (strict), Vite, React Router 7 |
| Tests | pytest (≈870 tests), Vitest + Testing Library (≈390 tests), Playwright browser checks |
| Quality | ruff, mypy, ESLint, GitHub Actions CI |
| Deploy | Docker Compose (nginx + API replicas + worker + PostgreSQL), S3-compatible storage |

## Run locally
```bash
# Backend (PostgreSQL running locally, database fikso_dev)
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload          # http://localhost:8000/docs
.venv/bin/python -m app.cli run-jobs             # background worker (timers, notifications)

# Frontend
cd frontend
npm ci
npm run dev                                       # http://localhost:5173
```

Checks: `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy app`,
`cd frontend && npm run lint && npm test && npm run build`.

Documentation: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DATABASE.md`](docs/DATABASE.md),
[`docs/CATALOGUE_SEED.md`](docs/CATALOGUE_SEED.md).
