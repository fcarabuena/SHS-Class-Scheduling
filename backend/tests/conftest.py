"""Test setup: runs against a separate PostgreSQL database (shs_scheduler_test)."""

import os

os.environ["POSTGRES_DB"] = "shs_scheduler_test"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

PASSWORD = "Str0ng-Passw0rd!"


@pytest.fixture(scope="session", autouse=True)
def _database():
    assert settings.postgres_db.endswith("_test"), "refusing to run tests on a non-test database"
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{settings.postgres_db}" ENCODING \'UTF8\' TEMPLATE template0')
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(_database):
    from app import ratelimit

    ratelimit.reset()  # limits are per process; each test starts fresh
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client():
    return TestClient(app)


class Api:
    """A test client bound to one signed-in user."""

    def __init__(self, client: TestClient, token: str, user: dict):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.user = user

    def get(self, url, **kw):
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.headers, **kw)

    def put(self, url, **kw):
        return self.client.put(url, headers=self.headers, **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self.headers, **kw)

    def create(self, url, **json):
        response = self.post(url, json=json)
        assert response.status_code == 201, response.text
        return response.json()


def register(client: TestClient, email: str = "admin@alpha.example", school: str = "Alpha Test School") -> Api:
    response = client.post(
        "/api/auth/register",
        json={"school_name": school, "full_name": "Test Admin", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Api(client, body["access_token"], body["user"])


def add_user(admin: Api, role: str, email: str) -> Api:
    admin.create("/api/users", email=email, full_name=f"Test {role}", password=PASSWORD, role=role)
    response = admin.client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return Api(admin.client, body["access_token"], body["user"])


@pytest.fixture
def admin(client) -> Api:
    return register(client)


@pytest.fixture
def scheduler(admin) -> Api:
    return add_user(admin, "scheduler", "scheduler@alpha.example")


@pytest.fixture
def teacher_user(admin) -> Api:
    return add_user(admin, "teacher", "teacher@alpha.example")


@pytest.fixture
def other_school(client) -> Api:
    return register(client, email="admin@beta.example", school="Beta Test School")


SCHOOL_YEAR = {
    "name": "2026-2027",
    "start_date": "2026-06-15",
    "end_date": "2027-03-31",
    "first_semester": {"start_date": "2026-06-15", "end_date": "2026-10-30"},
    "second_semester": {"start_date": "2026-11-09", "end_date": "2027-03-31"},
}

BELL = [
    {"name": "Period 1", "start_time": "07:00", "end_time": "08:00"},
    {"name": "Period 2", "start_time": "08:00", "end_time": "09:00"},
    {"name": "Recess", "start_time": "09:00", "end_time": "09:20", "is_break": True},
    {"name": "Period 3", "start_time": "09:20", "end_time": "10:20"},
]


@pytest.fixture
def school_setup(admin) -> dict:
    """A school with a year, one shift with a bell schedule, a track and a strand."""
    year = admin.create("/api/school-years", **SCHOOL_YEAR)
    shift = admin.create("/api/shifts", name="Morning", start_time="07:00", end_time="12:00")
    response = admin.put(f"/api/shifts/{shift['id']}/periods", json=BELL)
    assert response.status_code == 200, response.text
    shift = response.json()
    track = admin.create("/api/tracks", code="ACAD", name="Academic Track")
    strand = admin.create("/api/strands", track_id=track["id"], code="STEM", name="STEM")
    return {"year": year, "shift": shift, "track": track, "strand": strand}
