"""The public demo school: fictional data for a link posted online.

Turned on with DEMO_MODE=true. Visitors sign in as the demo scheduler or the
demo teacher, or open the student link (students never have accounts). The
demo admin's password is never published. The demo school is rebuilt when the
API starts and the last rebuild is more than a day old, so visitors' changes do
not pile up. Only the demo school is ever deleted; real schools are untouched.
"""

import datetime as dt
import logging
import secrets
import threading
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import (
    Base,
    CurriculumEntry,
    Period,
    ScheduleEntry,
    School,
    Section,
    Semester,
    ShareLink,
    Shift,
    Subject,
    Teacher,
    TeachingAssignment,
    User,
    teacher_subjects,
)
from .security import hash_password
from .seed import DEMO_PASSWORD, DEMO_USERS, seed, seed_schedule

log = logging.getLogger(__name__)

ADMIN_EMAIL, SCHEDULER_EMAIL, TEACHER_EMAIL = (email for email, _, _ in DEMO_USERS)
# Published on the sign-in page. The admin is deliberately not.
PUBLIC_ACCOUNTS = [("Scheduler", SCHEDULER_EMAIL), ("Teacher", TEACHER_EMAIL)]
# A fixed, public share link: what a student sees after scanning their section's QR code.
STUDENT_TOKEN = "demo-student-view-11-stem-sampaguita"
STUDENT_SECTION = "11-STEM-Sampaguita"
RESET_AFTER = dt.timedelta(hours=24)

# Four sections on one regular shift of seven periods from 07:30, so a complete week fits.
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


def demo_school(db: Session) -> School | None:
    user = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
    return db.get(School, user.school_id) if user else None


def reshape(db: Session, school: School) -> None:
    """Turns the seeded demo school into four sections on one seven-period shift, with an empty week
    and at least two qualified teachers for every subject. Touches only this school's rows."""
    sid = school.id
    db.execute(delete(ScheduleEntry).where(ScheduleEntry.school_id == sid))
    db.execute(delete(TeachingAssignment).where(TeachingAssignment.school_id == sid))
    shifts = {s.name: s for s in db.scalars(select(Shift).where(Shift.school_id == sid))}
    regular = shifts["Morning"]
    regular.name, regular.start_time, regular.end_time = "Regular", dt.time(7, 30), dt.time(16, 0)
    sections = []
    for section in db.scalars(select(Section).where(Section.school_id == sid)):
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
                school_id=sid,
                name=name,
                sort_order=order,
                start_time=dt.time.fromisoformat(start),
                end_time=dt.time.fromisoformat(end),
                is_break=is_break,
            )
        )

    groups = {(s.strand_id, s.grade_level) for s in sections}
    rows = [
        c
        for c in db.scalars(select(CurriculumEntry).where(CurriculumEntry.school_id == sid))
        if c.semester_number == 1 and (c.strand_id, c.grade_level) in groups
    ]
    teachers = list(db.scalars(select(Teacher).where(Teacher.school_id == sid).order_by(Teacher.id)))
    for subject_id in sorted({c.subject_id for c in rows}):
        while sum(subject_id in t.qualified_subject_ids for t in teachers) < 2:
            spare = [t for t in teachers if subject_id not in t.qualified_subject_ids]
            min(spare, key=lambda t: (len(t.subjects), t.id)).subjects.append(db.get(Subject, subject_id))
            db.flush()
    db.commit()


def _delete_school(db: Session, school_id: int) -> None:
    """Removes one school and everything that belongs to it, children first."""
    db.execute(delete(teacher_subjects).where(teacher_subjects.c.teacher_id.in_(select(Teacher.id).where(Teacher.school_id == school_id))))
    for table in reversed(Base.metadata.sorted_tables):
        if "school_id" in table.c:
            db.execute(delete(table).where(table.c.school_id == school_id))
    db.execute(delete(School.__table__).where(School.id == school_id))
    db.commit()


def reset() -> None:
    """Rebuilds the demo school from scratch, with a ready timetable and the public student link."""
    with SessionLocal() as db:
        if old := demo_school(db):
            _delete_school(db, old.id)
    seed(with_schedule=False)
    with SessionLocal() as db:
        school = demo_school(db)
        reshape(db, school)
        seed_schedule(db, school.id)  # teacher loading and a timetable, so the teacher account has classes
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        admin.password_hash = hash_password(settings.demo_admin_password or secrets.token_urlsafe(24))
        semester = db.scalars(select(Semester).where(Semester.school_id == school.id, Semester.is_active)).first()
        section = db.scalar(select(Section).where(Section.school_id == school.id, Section.name == STUDENT_SECTION))
        db.add(
            ShareLink(
                school_id=school.id,
                semester_id=semester.id,
                token=STUDENT_TOKEN,
                view="section",
                target_id=section.id,
                label=section.name,
            )
        )
        school.settings = {**(school.settings or {}), "demo_reset_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        db.commit()


def _reset_safely() -> None:
    try:
        reset()
        log.warning("Demo school rebuilt.")
    except Exception:
        log.exception("Rebuilding the demo school failed")


def start() -> None:
    """At API start: rebuilds the demo school in the background when it is missing or over a day old."""
    if not settings.demo_mode:
        return
    with SessionLocal() as db:
        school = demo_school(db)
        stamp = (school.settings or {}).get("demo_reset_at") if school else None
    due = stamp is None or dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stamp) > RESET_AFTER
    if due:
        threading.Thread(target=_reset_safely, name="demo-reset", daemon=True).start()


def info() -> dict[str, Any]:
    """What the sign-in page shows visitors."""
    if not settings.demo_mode:
        return {"enabled": False}
    return {
        "enabled": True,
        "password": DEMO_PASSWORD,
        "accounts": [{"role": role, "email": email} for role, email in PUBLIC_ACCOUNTS],
        "student_link": f"/share/{STUDENT_TOKEN}",
    }
