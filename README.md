# Tablekeeper — Stage 1–4

Tablekeeper is a FastAPI restaurant-reservation service backed by PostgreSQL. It includes an administrator and customer API, a same-origin dashboard, and a Docker Compose deployment for local hosting.

## Repository stages

```text
stage-1/
  sql/001_initial.sql       PostgreSQL schema and overlap constraint
  compose.test.yml          Disposable PostgreSQL database for local use/tests
stage-2/
  app/main.py               FastAPI service
  tests/                    PostgreSQL integration tests
  requirements*.txt         Runtime and test dependencies
stage-3/
  static/                   Dashboard HTML, CSS, and JavaScript
stage-4/
  Dockerfile                API image
  compose.yml               Local container deployment
  .env.example              Deployment configuration template
  DEPLOYMENT.md             Container deployment steps
```

This split keeps each delivery stage distinct. `README.md` stays at the repository root as the entry point for setup, API usage, testing, and deployment.

## Requirements

- Python 3.11 or newer
- Docker Engine and the Docker Compose plugin for the disposable database or full container stack
- PostgreSQL 14 or newer when using an external database

## Run locally

Create and activate a virtual environment, then install the backend dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r stage-2\requirements.txt
```

On macOS or Linux, activate with `source .venv/bin/activate` and use the slash-separated requirements path.

Start the disposable PostgreSQL database. On its first start, Compose applies the Stage 1 schema:

```sh
docker compose -f stage-1/compose.test.yml up -d --wait
```

For the host-run path, `DATABASE_URL` must either be unset or point to the Stage 1 `reservations_test` database. Copy `stage-4/.env.example` to `stage-4/.env` if needed and set its `BOOTSTRAP_ADMIN_TOKEN`; if that file contains `DATABASE_URL`, use `postgresql://postgres:postgres@127.0.0.1:5432/reservations_test`. Then launch the app from the repository root:

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
python -m uvicorn app.main:app --app-dir stage-2 --env-file stage-4/.env --reload
```

In macOS or Linux, use `unset DATABASE_URL` and `python -m uvicorn app.main:app --app-dir stage-2 --env-file stage-4/.env --reload`. Uvicorn's `--env-file` loads `BOOTSTRAP_ADMIN_TOKEN` for the host process; `uvicorn[standard]` supplies its dotenv support. Open <http://127.0.0.1:8000> for the dashboard; `/health` is the API health endpoint. The UI and API use the same origin.

For an existing PostgreSQL database, create an empty database and apply the schema once:

```sh
psql "$DATABASE_URL" -f stage-1/sql/001_initial.sql
```

For host execution, leave `DATABASE_URL` unset or set it to the Stage 1 test URL when using the Stage 1 test service; set `BOOTSTRAP_ADMIN_TOKEN` directly or load it from `stage-4/.env` as above. The bootstrap token has administrator access and is checked in constant time. Keep it out of source control. All API routes except `/health` require `Authorization: Bearer <key>`.

Stop the disposable database when finished:

```sh
docker compose -f stage-1/compose.test.yml down
```

Use `down -v` only when you want to permanently discard its test database volume.

## Dashboard

The dark responsive dashboard uses `#9230e1` as its primary accent and calls the documented API routes over the same origin. It supports administrator sign-in, customer API-key creation and revocation, restaurant and table setup, table availability checks, reservation creation/listing, and cancellation. The backend remains the source of truth for authentication, ownership, timezone validation, and booking conflicts.

## API overview

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | Public | Health status |
| `POST` | `/admin/api-keys` | Admin | Create a customer API key; plaintext is returned once |
| `DELETE` | `/admin/api-keys/{key_id}` | Admin | Revoke a customer API key |
| `POST` | `/admin/restaurants` | Admin | Create a restaurant with an IANA timezone |
| `GET` | `/restaurants` | Authenticated | List restaurants |
| `POST` | `/admin/restaurants/{restaurant_id}/tables` | Admin | Add a table and capacity |
| `GET` | `/restaurants/{restaurant_id}/tables` | Authenticated | List active tables |
| `POST` | `/availability` | Authenticated | Check current table availability |
| `POST` | `/reservations` | Authenticated | Book the smallest available table that fits |
| `GET` | `/reservations` | Authenticated | Customers see their own reservations; admins can list all and filter by restaurant |
| `DELETE` | `/reservations/{reservation_id}` | Owner or admin | Cancel a confirmed reservation |

All API routes except `/health` require a Tablekeeper bearer credential. For administrator access, enter the same `BOOTSTRAP_ADMIN_TOKEN` value configured in the API process. A key issued by another workspace, provider, or unrelated service will return `401`; customer keys created by Tablekeeper work for customer routes. Admin routes return `403` to customer keys. Missing or invalid credentials return `401`.

Create a customer key with the bootstrap administrator credential:

```sh
curl -X POST http://127.0.0.1:8000/admin/api-keys \
  -H "Authorization: Bearer $BOOTSTRAP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role":"customer"}'
```

The customer key is returned in the response and stored only as a SHA-256 hash by the API. Use the plaintext key as the bearer credential for customer operations.

### Reservation rules

Reservation requests include `restaurant_id`, `party_size`, `starts_at`, `timezone`, and optional `duration_minutes` (default 90; range 15–480). Example:

```json
{
  "restaurant_id": 1,
  "party_size": 2,
  "starts_at": "2026-10-12T19:00:00-04:00",
  "timezone": "America/New_York",
  "duration_minutes": 90
}
```

`starts_at` must be ISO 8601 with a UTC offset (`Z` is accepted). The offset must match the supplied IANA timezone at that wall time. This distinguishes daylight-saving fall-back times and rejects nonexistent spring-forward times. The supplied timezone must match the restaurant configuration. Stored instants use `TIMESTAMPTZ` in UTC.

Reservation intervals are half-open, so a booking can begin exactly when the previous one ends. Reservation creation locks eligible table rows in stable ID order, and PostgreSQL enforces a GiST exclusion constraint on overlapping confirmed intervals per table. Conflicts and requests without a fitting/available table return `409`. Availability is a point-in-time check and does not hold a table for a later booking.

Customer reservation listing and cancellation are scoped to the authenticated customer key. Administrators can list all reservations, optionally filter by `restaurant_id`, and cancel any confirmed reservation. Repeated cancellation returns `404`.

## Integration tests

Install test dependencies and start the disposable PostgreSQL service:

```sh
python -m pip install -r stage-2/requirements.txt -r stage-2/requirements-test.txt
docker compose -f stage-1/compose.test.yml up -d --wait
```

Set `TEST_DATABASE_URL` to `postgresql://postgres:postgres@127.0.0.1:5432/reservations_test`, then run the suite:

```powershell
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:5432/reservations_test'
python -m unittest discover -s stage-2/tests -v
```

On macOS or Linux, use `export TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/reservations_test'` before the same `python -m unittest` command.

The suite creates and drops a unique schema for each run. It sends 32 synchronized overlapping reservation requests, verifies one success and 31 conflicts, checks stored rows and the database exclusion constraint, and confirms adjacent half-open reservations can both succeed. The test database user must be able to create/drop schemas and use `btree_gist`. If host port 5432 is occupied, change the host side in `stage-1/compose.test.yml` and set `TEST_DATABASE_URL` to that port.

## Container deployment

For a self-contained local deployment with persistent PostgreSQL storage, follow [Stage 4 deployment instructions](stage-4/DEPLOYMENT.md). That Compose stack builds its internal database URL from `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`, and reaches PostgreSQL at hostname `db`. Do not use the host-local Stage 1 test URL inside that stack. The stack binds the web port to loopback by default. For public hosting, configure HTTPS and secret management at the deployment boundary.
