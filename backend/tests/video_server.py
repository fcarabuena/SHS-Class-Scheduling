"""Backend for recording the demo video:  python -m tests.video_server

A throwaway database (shs_scheduler_video, wiped on every start) holding the
fictional demo school, reshaped like the public demo (app/demo.py) but with no
teacher loading and no timetable yet, so the video can build them from scratch.
Runs on port 8002 next to the dev (8000) and test (8001) servers.
"""

import os

os.environ.update(
    POSTGRES_DB="shs_scheduler_video",
    DATABASE_URL="",
    DEMO_MODE="false",
    CORS_ORIGINS="http://localhost:3002",
    PUBLIC_APP_URL="http://localhost:3002",
    PLATFORM_ADMIN_EMAILS="admin@demo.example",
    RATE_LIMIT_LOGIN="1000/60",
    RATE_LIMIT_REGISTER="1000/60",
)

import psycopg  # noqa: E402
import uvicorn  # noqa: E402

from app import demo, push  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.seed import seed  # noqa: E402


def reset_database() -> None:
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,)).fetchone():
            conn.execute(f'CREATE DATABASE "{settings.postgres_db}" ENCODING \'UTF8\' TEMPLATE template0')
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def build() -> None:
    assert settings.database_url.database == "shs_scheduler_video", "refusing to touch any other database"
    reset_database()
    seed(with_schedule=False)
    with SessionLocal() as db:
        demo.reshape(db, demo.demo_school(db))


if __name__ == "__main__":
    build()
    # Set after building, so the reshaping above does not queue any notifications.
    settings.vapid_public_key, settings.vapid_private_key = push.new_keys()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8002, log_level="warning")
