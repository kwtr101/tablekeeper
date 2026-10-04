# Restaurant Reservation Service — Stage 1

A small FastAPI service backed by PostgreSQL. Stage 1 includes administrator-managed restaurant and table setup, API-key authentication, customer reservations, reservation listing, and cancellation.

## Requirements and setup

- Python 3.11 or newer (for `zoneinfo`)
- PostgreSQL 14 or newer

Create a database, then apply the schema once:

```sh
psql "$DATABASE_URL" -f sql/001_initial.sql
```

Install and start the service:

```sh
python -m venv .venv
. .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/reservations'
export BOOTSTRAP_ADMIN_TOKEN='replace-with-a-long-random-secret'
uvicorn app.main:app --reload
```

Set `DATABASE_URL` and `BOOTSTRAP_ADMIN_TOKEN` in the process environment before launch. The bootstrap token grants administrator access and is compared in constant time; keep it out of source control. All API routes except `/health` require `Authorization: Bearer <key>`. The bootstrap token is an administrator key. Use it to create customer keys; the returned plaintext key is shown once, while only its SHA-256 hash is stored.

## API defaults

- `GET /health` reports process health.
- `POST /admin/api-keys` creates a customer API key. Body: `{ "role": "customer" }`.
- `DELETE /admin/api-keys/{key_id}` revokes a customer key.
- `POST /admin/restaurants` creates a restaurant. Body: `{ "name": "North Room", "timezone": "America/New_York" }`.
- `GET /restaurants` lists restaurants.
- `POST /admin/restaurants/{restaurant_id}/tables` adds a table. Body: `{ "name": "T1", "capacity": 4 }`.
- `GET /restaurants/{restaurant_id}/tables` lists active tables.
- `POST /reservations` books the smallest available table that fits the party. Body:
  `{ "restaurant_id": 1, "party_size": 2, "starts_at": "2026-10-12T19:00:00-04:00", "timezone": "America/New_York", "duration_minutes": 90 }`.
  `duration_minutes` defaults to 90 and must be from 15 through 480.
- `POST /availability` checks current availability using the same body as reservation creation. Availability can change before a subsequent booking.
- `GET /reservations` lists the caller's reservations. Administrators can see all reservations and can optionally filter by `restaurant_id`.
- `DELETE /reservations/{reservation_id}` cancels an owned reservation; administrators can cancel any reservation. Repeated cancellation returns 404.

`starts_at` must be ISO 8601 and include a numeric UTC offset (a trailing `Z` is accepted). `timezone` must be an IANA timezone name, and the provided offset must be valid for that zone at the given local wall time. This makes DST fall-back times unambiguous and rejects nonexistent spring-forward times. Instants are stored as `TIMESTAMPTZ` in UTC. Reservation intervals are half-open: a party may book a table at the exact instant the previous reservation ends.

## Concurrency and errors

Reservation creation locks eligible table rows in stable ID order in the same transaction that selects and inserts the reservation. Concurrent requests therefore serialize around those tables. PostgreSQL also enforces a GiST exclusion constraint against overlapping confirmed intervals per table, so a conflicting insert cannot succeed even if another writer bypasses the API's lock protocol. A conflict or lack of a fitting/available table returns HTTP 409. Invalid payloads return 422, missing resources return 404, invalid/missing credentials return 401, and customer attempts to use administrator routes return 403.

API keys do not expire automatically. Administrators can revoke customer keys through the API. Availability is determined at reservation-write time; this stage does not promise a hold between a separate availability lookup and booking.

## PostgreSQL integration tests

The test suite needs a disposable PostgreSQL database with `btree_gist` and a user that can create and drop schemas. The Compose setup installs the baseline SQL migration on first initialization and waits until PostgreSQL is ready:

```powershell
python -m pip install -r requirements.txt -r requirements-test.txt
docker compose -f compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:5432/reservations_test'
python -m unittest discover -s tests -v
docker compose -f compose.test.yml down -v
```

`TEST_DATABASE_URL` is exactly `postgresql://postgres:postgres@127.0.0.1:5432/reservations_test`. The service binds to loopback and uses the fixed local test credentials shown above; do not reuse them for a reachable or production database. The test suite creates an isolated schema for its run and drops it during teardown. `docker compose ... down -v` removes its anonymous data volume so the next `up` starts from a clean database and reruns the migration. If port 5432 is already occupied, change the host side of the port mapping and use that host port in `TEST_DATABASE_URL`. The suite sends 32 synchronized overlapping reservation requests, checks HTTP conflicts and the stored reservations, verifies PostgreSQL's exclusion constraint directly, and confirms that adjacent half-open reservations are accepted.
