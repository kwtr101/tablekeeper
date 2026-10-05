# Factory Operations & Seat Setup — Tablekeeper

## 1. Seat Setup & Environment
- **Environment:** Windows / Docker Container / Python 3.11+
- **Database:** PostgreSQL (with GiST / btree_gist support).
- **Core Stack:** FastAPI, Uvicorn, Psycopg, Pydantic.

## 2. Design Rationale
- **Architecture:** Structured in stages (`stage-1/` to `stage-4/`) separating DB schema, FastAPI backend, UI dashboard, and container configuration.
- **Integrity:** PostgreSQL exclusion constraints prevent double-booking at the database row level.

## 3. Measured Costs & Constraints
- **Container Footprint:** Lightweight container build optimized for rapid deployment and clean container starts.
- **Concurrency Handling:** Stable row-locking order avoids deadlocks during high-traffic availability and reservation checks.

## 4. Error Recovery & Resilience
- **Database Errors:** Automated schema initialization checks on startup.
- **Conflict Management:** Overlapping bookings trigger rejection responses to prevent duplicate reservations.
- **Bad Work Recovery:** If an incorrect migration or invalid transaction disrupts state, the containerized environment can be cleanly restarted via compose down/up to restore a pristine test-service baseline without manual DB state corruption.
