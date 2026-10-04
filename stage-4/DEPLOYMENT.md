# Container deployment

The Compose deployment builds the FastAPI image, starts PostgreSQL, initializes a new database volume with the Stage 1 schema, and serves the dashboard and API on one origin.

1. Copy `.env.example` to `.env` in this directory.
2. Replace both secret values. Generate a URL-safe database password with `python -c "import secrets; print(secrets.token_hex(32))"` and an administrator token with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. From the repository root, start the stack:

   ```sh
   docker compose --env-file stage-4/.env -f stage-4/compose.yml up --build -d
   ```

4. Open `http://127.0.0.1:8000` and enter the bootstrap administrator token in the dashboard. Check API health at `/health`.
5. Follow startup logs with `docker compose --env-file stage-4/.env -f stage-4/compose.yml logs -f api` and stop the services with `docker compose --env-file stage-4/.env -f stage-4/compose.yml down`.

The database volume persists across restarts. The SQL file in `stage-1/sql` is an initialization script and runs only when PostgreSQL creates an empty volume. Back up the database before changing schema or removing the volume. `down -v` permanently deletes the database volume.

The API port binds to loopback by default. For a public deployment, terminate HTTPS at a trusted reverse proxy, restrict database network access, and store both secrets in the deployment platform's secret manager. Do not commit `.env` or reuse the example values.
