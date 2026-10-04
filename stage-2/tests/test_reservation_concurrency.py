"""PostgreSQL integration tests for reservation concurrency and half-open intervals.

Run with TEST_DATABASE_URL pointing to a disposable PostgreSQL database where the
user can create/drop schemas and install btree_gist:
    python -m unittest discover -s stage-2/tests -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.errors import ExclusionViolation


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
ADMIN_TOKEN = "stage1-test-bootstrap-token"
START = datetime(2030, 1, 15, 19, 0, tzinfo=timezone.utc)


class ReservationConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base_url = os.getenv("TEST_DATABASE_URL")
        if not base_url:
            raise RuntimeError(
                "TEST_DATABASE_URL must point to a disposable PostgreSQL database "
                "for Stage 1 integration tests"
            )

        base_url = make_conninfo(base_url, connect_timeout=5)
        cls.schema = "stage1_test_" + uuid.uuid4().hex
        with psycopg.connect(base_url, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA "{cls.schema}"')
        cls.database_url = make_conninfo(
            base_url, options=f"-c search_path={cls.schema},public"
        )
        with psycopg.connect(cls.database_url) as conn:
            conn.execute(
                (REPO_ROOT / "stage-1" / "sql" / "001_initial.sql").read_text(
                    encoding="utf-8"
                )
            )

        os.environ["DATABASE_URL"] = cls.database_url
        os.environ["BOOTSTRAP_ADMIN_TOKEN"] = ADMIN_TOKEN
        from app import main

        main.DATABASE_URL = cls.database_url
        main.BOOTSTRAP_ADMIN_TOKEN = ADMIN_TOKEN
        cls.app = main.app

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "schema"):
            base_url = make_conninfo(os.environ["TEST_DATABASE_URL"], connect_timeout=5)
            with psycopg.connect(base_url, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE')

    def setUp(self) -> None:
        self.headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        restaurant = self.request(
            "POST",
            "/admin/restaurants",
            json={"name": "Concurrency Test", "timezone": "UTC"},
        )
        self.assertEqual(restaurant.status_code, 201, restaurant.text)
        self.restaurant_id = restaurant.json()["id"]
        table = self.request(
            "POST",
            f"/admin/restaurants/{self.restaurant_id}/tables",
            json={"name": "Only Table", "capacity": 8},
        )
        self.assertEqual(table.status_code, 201, table.text)
        self.table_id = table.json()["id"]

    def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, url, headers=self.headers, **kwargs)

        return asyncio.run(send())

    def payload(self, starts_at: datetime = START) -> dict:
        return {
            "restaurant_id": self.restaurant_id,
            "party_size": 2,
            "starts_at": starts_at.isoformat(),
            "timezone": "UTC",
        }

    def test_simultaneous_overlapping_bookings_under_load_never_double_book(self) -> None:
        request_count = 32
        payload = self.payload()

        async def run_load() -> list[int]:
            barrier = asyncio.Barrier(request_count)
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                async def book() -> tuple[int, dict]:
                    await barrier.wait()
                    response = await client.post(
                        "/reservations", headers=self.headers, json=payload
                    )
                    return response.status_code, response.json()

                return await asyncio.gather(*(book() for _ in range(request_count)))

        statuses = asyncio.run(run_load())
        codes = [code for code, _ in statuses]
        self.assertEqual(codes.count(201), 1, statuses)
        self.assertEqual(codes.count(409), request_count - 1, statuses)
        self.assertEqual(set(codes), {201, 409})
        self.assertTrue(
            all(body == {"detail": "No table is available for that time"} for code, body in statuses if code == 409),
            statuses,
        )

        with psycopg.connect(self.database_url) as conn:
            confirmed = conn.execute(
                "SELECT count(*) AS n FROM reservations "
                "WHERE restaurant_id = %s AND status = 'confirmed'",
                (self.restaurant_id,),
            ).fetchone()[0]
            overlaps = conn.execute(
                "SELECT count(*) AS n FROM reservations a "
                "JOIN reservations b ON a.table_id = b.table_id AND a.id < b.id "
                "AND tstzrange(a.starts_at, a.ends_at, '[)') && tstzrange(b.starts_at, b.ends_at, '[)') "
                "WHERE a.restaurant_id = %s AND a.status = 'confirmed' AND b.status = 'confirmed'",
                (self.restaurant_id,),
            ).fetchone()[0]
        self.assertEqual(confirmed, 1)
        self.assertEqual(overlaps, 0)

    def test_exclusion_constraint_rejects_overlapping_database_insert(self) -> None:
        existing = self.request("POST", "/reservations", json=self.payload())
        self.assertEqual(existing.status_code, 201, existing.text)

        with self.assertRaises(ExclusionViolation):
            with psycopg.connect(self.database_url) as conn:
                conn.execute(
                    "INSERT INTO reservations (restaurant_id, table_id, party_size, starts_at, ends_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        self.restaurant_id,
                        self.table_id,
                        2,
                        START,
                        START + timedelta(minutes=90),
                    ),
                )

    def test_adjacent_default_duration_reservations_are_allowed(self) -> None:
        first = self.request("POST", "/reservations", json=self.payload())
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(
            datetime.fromisoformat(first.json()["ends_at"]),
            START + timedelta(minutes=90),
        )

        adjacent_start = START + timedelta(minutes=90)
        second = self.request(
            "POST", "/reservations", json=self.payload(adjacent_start)
        )
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(first.json()["table_id"], second.json()["table_id"])


if __name__ == "__main__":
    unittest.main()





