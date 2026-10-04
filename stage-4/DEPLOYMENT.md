# Container deployment

The Compose deployment builds the FastAPI image, starts PostgreSQL, initializes a new database volume with the Stage 1 schema, and serves the dashboard and API on one origin.

1. Copy `.env.example` to `.env` in this directory.
2. Set `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD`, and `BOOTSTRAP_ADMIN_TOKEN`. Generate a URL-safe database password with `python -c "import secrets; print(secrets.token_hex(32))"` and an administrator token with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The UI must be given this Tablekeeper `BOOTSTRAP_ADMIN_TOKEN` (or a customer key issued by this Tablekeeper instance); unrelated workspace/provider API keys are not accepted.
3. From the repository root, start the stack:

   ```sh
   docker compose --env-file stage-4/.env -f stage-4/compose.yml up --build -d
   ```

4. Open `http://127.0.0.1:8000` and enter the bootstrap administrator token in the dashboard. Check API health at `/health`.
5. Follow startup logs with `docker compose --env-file stage-4/.env -f stage-4/compose.yml logs -f api` and stop the services with `docker compose --env-file stage-4/.env -f stage-4/compose.yml down`.

Compose constructs the API's internal `DATABASE_URL` using the configured `POSTGRES_*` values and hostname `db`; it does not use a host-local `DATABASE_URL`.

For **host-run Uvicorn** instead of the Stage 4 Compose stack, start the Stage 1 test database with `docker compose -f stage-1/compose.test.yml up -d --wait`, ensure `DATABASE_URL` is unset, and run from the repository root:

```sh
python -m uvicorn app.main:app --app-dir stage-2 --env-file stage-4/.env --reload
```

The host process reads `BOOTSTRAP_ADMIN_TOKEN` from `stage-4/.env`. Leave `DATABASE_URL` out of that file to use the app default, or set it to `postgresql://postgres:postgres@127.0.0.1:5432/reservations_test`. Do not point the host process at the Compose-only `db` hostname. The Stage 4 `POSTGRES_*` settings are for the container stack and do not configure the host-run Stage 1 database.

The database volume persists across restarts. The SQL file in `stage-1/sql` is an initialization script and runs only when PostgreSQL creates an empty volume. Changing `POSTGRES_PASSWORD` in `.env` does not change the password of a role already stored in that existing volume; keep the configured password consistent with the initialized database, or perform a planned credential rotation against PostgreSQL. Back up the database before changing schema or removing the volume. `down -v` permanently deletes the database volume.

The API port binds to loopback by default. For a public deployment, terminate HTTPS at a trusted reverse proxy, restrict database network access, and store both secrets in the deployment platform's secret manager. Do not commit `.env` or reuse the example values.
