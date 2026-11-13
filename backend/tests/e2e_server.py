"""Backend for the browser end-to-end tests.

Runs the API on port 8001 against a throwaway database (shs_scheduler_e2e)
that is wiped on every start, so e2e runs never touch development data.

    python -m tests.e2e_server
"""

import os

os.environ["POSTGRES_DB"] = "shs_scheduler_e2e"
os.environ["DATABASE_URL"] = ""  # the throwaway local database, never a hosted one
os.environ["CORS_ORIGINS"] = "http://localhost:3001"
os.environ["PUBLIC_APP_URL"] = "http://localhost:3001"
os.environ["PLATFORM_ADMIN_EMAILS"] = "owner@platform.example"
# The browser tests sign in and register many times from one address.
os.environ["RATE_LIMIT_LOGIN"] = "1000/60"
os.environ["RATE_LIMIT_REGISTER"] = "1000/60"

import psycopg  # noqa: E402
import uvicorn  # noqa: E402

from app import push  # noqa: E402
from app.config import settings  # noqa: E402

# Throwaway keys so the public page offers "Follow" (nothing is actually sent in the tests).
settings.vapid_public_key, settings.vapid_private_key = push.new_keys()
from app.db import engine  # noqa: E402
from app.models import Base  # noqa: E402


def reset_database() -> None:
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


if __name__ == "__main__":
    reset_database()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, log_level="warning")
