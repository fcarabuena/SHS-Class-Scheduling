"""Backend for recording the demo video:  python -m tests.video_server

A throwaway database (shs_scheduler_video, wiped on every start) holding the
fictional demo school, reshaped so a complete timetable fits: one regular shift
with seven periods from 07:30, four sections, a qualified teacher for every
subject, and no timetable yet, so the video can build one from scratch.
Runs on port 8002 next to the dev (8000) and test (8001) servers.
"""

import datetime as dt
import os

os.environ.update(
    POSTGRES_DB="shs_scheduler_video",
    DATABASE_URL="",
    CORS_ORIGINS="http://localhost:3002",
    PUBLIC_APP_URL="http://localhost:3002",
    PLATFORM_ADMIN_EMAILS="admin@demo.example",
    RATE_LIMIT_LOGIN="1000/60",
    RATE_LIMIT_REGISTER="1000/60",
)

import psycopg  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app import push  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    CurriculumEntry,
    Period,
    ScheduleEntry,
    School,
    Section,
    Shift,
    Subject,
    Teacher,
    TeachingAssignment,
)
from app.seed import seed  # noqa: E402

KEEP = ("11-STEM-Sampaguita", "11-ABM-Narra", "11-HUMSS-Mabini", "12-STEM-Ilang-Ilang")
BELL = [
    ("Period 1", "07:30", "08:30", False),
    ("Period 2", "08:30", "09:30", False),
    ("Recess", "09:30", "09:50", True),
    ("Period 3", "09:50", "10:50", False),
    ("Period 4", "10:50", "11:50", False),
    ("Lunch", "11:50", "12:50", True),
    ("Period 5", "12:50", "13:50", False),
    ("Period 6", "13:50", "14:50", False),
    ("Period 7", "14:50", "15:50", False),
]


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
    seed()
    with SessionLocal() as db:
        school = db.scalar(select(School))
        db.execute(delete(ScheduleEntry))
        db.execute(delete(TeachingAssignment))
        shifts = {s.name: s for s in db.scalars(select(Shift))}
        regular = shifts["Morning"]
        regular.name, regular.start_time, regular.end_time = "Regular", dt.time(7, 30), dt.time(16, 0)
        sections = []
        for section in db.scalars(select(Section)):
            if section.name in KEEP:
                section.shift_id = regular.id
                sections.append(section)
            else:
                db.delete(section)
        db.flush()
        db.delete(shifts["Afternoon"])
        regular.periods.clear()
        db.flush()
        for order, (name, start, end, is_break) in enumerate(BELL, start=1):
            regular.periods.append(
                Period(
                    school_id=school.id,
                    name=name,
                    sort_order=order,
                    start_time=dt.time.fromisoformat(start),
                    end_time=dt.time.fromisoformat(end),
                    is_break=is_break,
                )
            )

        # Every subject these sections take gets at least two qualified teachers, so auto-assign
        # always finds one with room left.
        groups = {(s.strand_id, s.grade_level) for s in sections}
        rows = [c for c in db.scalars(select(CurriculumEntry)) if c.semester_number == 1 and (c.strand_id, c.grade_level) in groups]
        teachers = list(db.scalars(select(Teacher).order_by(Teacher.id)))
        for subject_id in sorted({c.subject_id for c in rows}):
            while sum(subject_id in t.qualified_subject_ids for t in teachers) < 2:
                spare = [t for t in teachers if subject_id not in t.qualified_subject_ids]
                min(spare, key=lambda t: (len(t.subjects), t.id)).subjects.append(db.get(Subject, subject_id))
                db.flush()
        db.commit()

        hours = {s.id: float(s.hours_per_week) for s in db.scalars(select(Subject))}
        for section in sections:
            mine = [c for c in rows if (c.strand_id, c.grade_level) == (section.strand_id, section.grade_level)]
            total = sum(float(c.hours_per_week) if c.hours_per_week else hours[c.subject_id] for c in mine)
            print(f"{section.name}: {len(mine)} subjects, {total:g} h a week (room for 35 h)")


if __name__ == "__main__":
    build()
    # Set after building, so the reshaping above does not queue any notifications.
    settings.vapid_public_key, settings.vapid_private_key = push.new_keys()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8002, log_level="warning")
