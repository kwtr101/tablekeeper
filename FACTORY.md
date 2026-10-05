# Factory Operations & Seat Setup — Tablekeeper

## 1. Seat Setup & Environment
- **Environment:** Windows / Docker Container / Python 3.11+
- **Database:** PostgreSQL (with GiST / btree_gist support).
- **Core Stack:** FastAPI, Uvicorn, Psycopg, Pydantic.

## 2. Design Rationale
- **Architecture:** Structured in stages (`stage-1/` to `stage-4/`) separating DB schema, FastAPI backend, UI dashboard, and container configuration.
- **Integrity:** PostgreSQL exclusion constraints prevent double-booking at the database row level.

## 3. Error Recovery & Resilience
- **Database Errors:** Automated schema initialization checks on startup.
- **Conflict Management:** Overlapping bookings return explicit `409 Conflict` responses.
