"""Stage 1 restaurant reservation API."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.errors import ExclusionViolation
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/reservations")
BOOTSTRAP_ADMIN_TOKEN = os.getenv("BOOTSTRAP_ADMIN_TOKEN", "")
DEFAULT_DURATION_MINUTES = 90

app = FastAPI(title="Tablekeeper Service", version="1.0.0")
STATIC_DIR = Path(__file__).resolve().parents[2] / "stage-3" / "static"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_principal(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer API key required", headers={"WWW-Authenticate": "Bearer"})
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer API key required", headers={"WWW-Authenticate": "Bearer"})
    if BOOTSTRAP_ADMIN_TOKEN and secrets.compare_digest(token, BOOTSTRAP_ADMIN_TOKEN):
        return {"id": None, "role": "admin"}
    with connect() as conn:
        principal = conn.execute(
            "SELECT id, role FROM api_keys WHERE token_hash = %s AND revoked_at IS NULL",
            (_digest(token),),
        ).fetchone()
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key", headers={"WWW-Authenticate": "Bearer"})
    return principal


def admin_only(principal: Annotated[dict, Depends(current_principal)]) -> dict:
    if principal["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator key required")
    return principal


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RestaurantCreate(InputModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone name") from None
        return value


class TableCreate(InputModel):
    name: str = Field(min_length=1, max_length=100)
    capacity: int = Field(ge=1, le=100)


class ApiKeyCreate(InputModel):
    role: Literal["customer"] = "customer"


class ReservationCreate(InputModel):
    restaurant_id: int = Field(gt=0)
    party_size: int = Field(ge=1, le=100)
    starts_at: str
    timezone: str
    duration_minutes: int = Field(default=DEFAULT_DURATION_MINUTES, ge=15, le=480)

    @model_validator(mode="after")
    def validate_datetime(self) -> "ReservationCreate":
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone name") from None
        try:
            parsed = datetime.fromisoformat(self.starts_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("starts_at must be an ISO 8601 datetime with a UTC offset") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("starts_at must include a UTC offset")
        wall_time = parsed.replace(tzinfo=None)
        possible_offsets = {
            wall_time.replace(tzinfo=zone, fold=fold).utcoffset() for fold in (0, 1)
        }
        if parsed.utcoffset() not in possible_offsets:
            raise ValueError("starts_at offset does not match the supplied IANA timezone")
        # Round-tripping rejects nonexistent local times in DST spring-forward gaps.
        local = parsed.astimezone(zone)
        if local.replace(tzinfo=None) != wall_time:
            raise ValueError("starts_at is not a valid local time in the supplied timezone")
        self.starts_at = parsed.astimezone(timezone.utc).isoformat()
        return self


def _need_admin(principal: dict = Depends(admin_only)) -> dict:
    return principal


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/admin/api-keys", status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreate,
    _admin: Annotated[dict, Depends(_need_admin)],
) -> dict:
    token = secrets.token_urlsafe(32)
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO api_keys (token_hash, role) VALUES (%s, %s) RETURNING id, role, created_at",
            (_digest(token), body.role),
        ).fetchone()
    return {**row, "api_key": token}


@app.delete("/admin/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(key_id: int, _admin: Annotated[dict, Depends(_need_admin)]) -> None:
    with connect() as conn:
        row = conn.execute(
            "UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING id",
            (key_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")


@app.post("/admin/restaurants", status_code=status.HTTP_201_CREATED)
def create_restaurant(body: RestaurantCreate, _admin: Annotated[dict, Depends(_need_admin)]) -> dict:
    with connect() as conn:
        return conn.execute(
            "INSERT INTO restaurants (name, timezone) VALUES (%s, %s) RETURNING id, name, timezone, created_at",
            (body.name, body.timezone),
        ).fetchone()


@app.get("/restaurants")
def list_restaurants(_principal: Annotated[dict, Depends(current_principal)]) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT id, name, timezone FROM restaurants ORDER BY id"
        ).fetchall()


@app.post("/admin/restaurants/{restaurant_id}/tables", status_code=status.HTTP_201_CREATED)
def create_table(
    restaurant_id: int,
    body: TableCreate,
    _admin: Annotated[dict, Depends(_need_admin)],
) -> dict:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM restaurants WHERE id = %s", (restaurant_id,)).fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
        return conn.execute(
            "INSERT INTO restaurant_tables (restaurant_id, name, capacity) VALUES (%s, %s, %s) "
            "RETURNING id, restaurant_id, name, capacity, active",
            (restaurant_id, body.name, body.capacity),
        ).fetchone()


@app.get("/restaurants/{restaurant_id}/tables")
def list_tables(restaurant_id: int, _principal: Annotated[dict, Depends(current_principal)]) -> list[dict]:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM restaurants WHERE id = %s", (restaurant_id,)).fetchone() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
        return conn.execute(
            "SELECT id, name, capacity FROM restaurant_tables "
            "WHERE restaurant_id = %s AND active ORDER BY capacity, id",
            (restaurant_id,),
        ).fetchall()


@app.post("/reservations", status_code=status.HTTP_201_CREATED)
def create_reservation(
    body: ReservationCreate,
    principal: Annotated[dict, Depends(current_principal)],
) -> dict:
    starts_at = datetime.fromisoformat(body.starts_at)
    ends_at = starts_at + timedelta(minutes=body.duration_minutes)
    try:
        with connect() as conn:
            restaurant = conn.execute(
                "SELECT timezone FROM restaurants WHERE id = %s", (body.restaurant_id,)
            ).fetchone()
            if restaurant is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
            if restaurant["timezone"] != body.timezone:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "timezone must match the restaurant's configured timezone")
            # Lock every eligible table in deterministic order. Conflicting requests
            # serialize here; the exclusion constraint below remains the final guard.
            tables = conn.execute(
                "SELECT id FROM restaurant_tables WHERE restaurant_id = %s AND active AND capacity >= %s "
                "ORDER BY id FOR UPDATE",
                (body.restaurant_id, body.party_size),
            ).fetchall()
            if not tables:
                exists = conn.execute("SELECT 1 FROM restaurants WHERE id = %s", (body.restaurant_id,)).fetchone()
                if exists is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
                raise HTTPException(status.HTTP_409_CONFLICT, "No table can fit this party")
            table_ids = [row["id"] for row in tables]
            available = conn.execute(
                "SELECT t.id FROM restaurant_tables t WHERE t.id = ANY(%s) AND NOT EXISTS ("
                "SELECT 1 FROM reservations r WHERE r.table_id = t.id AND r.status = 'confirmed' "
                "AND tstzrange(r.starts_at, r.ends_at, '[)') && tstzrange(%s, %s, '[)')) "
                "ORDER BY t.capacity, t.id LIMIT 1",
                (table_ids, starts_at, ends_at),
            ).fetchone()
            if available is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "No table is available for that time")
            row = conn.execute(
                "INSERT INTO reservations (restaurant_id, table_id, customer_key_id, party_size, starts_at, ends_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "RETURNING id, restaurant_id, table_id, party_size, starts_at, ends_at, status, created_at",
                (body.restaurant_id, available["id"], principal["id"], body.party_size, starts_at, ends_at),
            ).fetchone()
            return row
    except ExclusionViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "No table is available for that time") from None


@app.post("/availability")
def check_availability(
    body: ReservationCreate,
    _principal: Annotated[dict, Depends(current_principal)],
) -> dict:
    starts_at = datetime.fromisoformat(body.starts_at)
    ends_at = starts_at + timedelta(minutes=body.duration_minutes)
    with connect() as conn:
        restaurant = conn.execute(
            "SELECT timezone FROM restaurants WHERE id = %s", (body.restaurant_id,)
        ).fetchone()
        if restaurant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
        if restaurant["timezone"] != body.timezone:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "timezone must match the restaurant's configured timezone")
        table = conn.execute(
            "SELECT t.id FROM restaurant_tables t WHERE t.restaurant_id = %s AND t.active AND t.capacity >= %s "
            "AND NOT EXISTS (SELECT 1 FROM reservations r WHERE r.table_id = t.id AND r.status = 'confirmed' "
            "AND tstzrange(r.starts_at, r.ends_at, '[)') && tstzrange(%s, %s, '[)')) "
            "ORDER BY t.capacity, t.id LIMIT 1",
            (body.restaurant_id, body.party_size, starts_at, ends_at),
        ).fetchone()
        return {"available": table is not None}


@app.get("/reservations")
def list_reservations(
    principal: Annotated[dict, Depends(current_principal)],
    restaurant_id: int | None = Query(default=None, gt=0),
) -> list[dict]:
    with connect() as conn:
        if principal["role"] == "admin":
            if restaurant_id is None:
                return conn.execute(
                    "SELECT id, restaurant_id, table_id, customer_key_id, party_size, starts_at, ends_at, status "
                    "FROM reservations ORDER BY starts_at"
                ).fetchall()
            return conn.execute(
                "SELECT id, restaurant_id, table_id, customer_key_id, party_size, starts_at, ends_at, status "
                "FROM reservations WHERE restaurant_id = %s ORDER BY starts_at", (restaurant_id,)
            ).fetchall()
        return conn.execute(
            "SELECT id, restaurant_id, table_id, party_size, starts_at, ends_at, status FROM reservations "
            "WHERE customer_key_id = %s AND (%s IS NULL OR restaurant_id = %s) ORDER BY starts_at",
            (principal["id"], restaurant_id, restaurant_id),
        ).fetchall()


@app.delete("/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_reservation(
    reservation_id: int,
    principal: Annotated[dict, Depends(current_principal)],
) -> None:
    with connect() as conn:
        if principal["role"] == "admin":
            row = conn.execute(
                "UPDATE reservations SET status = 'cancelled' WHERE id = %s AND status = 'confirmed' RETURNING id",
                (reservation_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "UPDATE reservations SET status = 'cancelled' WHERE id = %s AND customer_key_id = %s "
                "AND status = 'confirmed' RETURNING id",
                (reservation_id, principal["id"]),
            ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reservation not found")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Keep the asset mount after API routes so it cannot shadow their paths.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
