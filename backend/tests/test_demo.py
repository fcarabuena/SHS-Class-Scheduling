"""The public demo school: test accounts, student link, daily rebuild, and real schools left alone."""

import datetime as dt

from sqlalchemy import func, select

from app import demo
from app.config import settings
from app.db import SessionLocal
from app.models import ScheduleEntry, School, Section, Teacher
from app.seed import DEMO_PASSWORD


def login(client, email, password=DEMO_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_demo_is_off_unless_turned_on(client, monkeypatch):
    assert client.get("/api/demo").json() == {"enabled": False}
    monkeypatch.setattr(settings, "demo_mode", True)
    info = client.get("/api/demo").json()
    assert info["enabled"] and info["password"] == DEMO_PASSWORD
    assert [a["email"] for a in info["accounts"]] == ["scheduler@demo.example", "teacher@demo.example"]
    assert info["student_link"] == f"/share/{demo.STUDENT_TOKEN}"
    assert "admin@demo.example" not in str(info)  # the admin is never published


def test_reset_builds_a_ready_demo_with_test_accounts_and_a_student_link(client):
    demo.reset()
    assert login(client, "scheduler@demo.example").status_code == 200
    teacher = login(client, "teacher@demo.example")
    assert teacher.status_code == 200 and teacher.json()["user"]["role"] == "teacher"
    assert login(client, "admin@demo.example").status_code == 401  # random password unless one is configured

    headers = {"Authorization": f"Bearer {teacher.json()['access_token']}"}
    overview = client.get("/api/schedule", headers=headers).json()
    mine = [e for e in overview["entries"] if e["teacher_id"] == teacher.json()["user"]["teacher_id"]]
    assert len(overview["entries"]) > 100 and mine  # a timetable, with classes for the test teacher
    assert client.post("/api/schedule/entries", json={}, headers=headers).status_code == 403  # read-only

    student = client.get(f"/api/public/timetable/{demo.STUDENT_TOKEN}")  # no account needed
    assert student.status_code == 200 and student.json()["title"] == "11-STEM-Sampaguita"


def test_reset_replaces_only_the_demo_school(admin, monkeypatch):
    admin.create("/api/teachers", employee_id="T-1", full_name="Real Teacher")
    monkeypatch.setattr(settings, "demo_admin_password", "Private-Admin-Pass-1")
    demo.reset()
    demo.reset()  # twice: the old demo school is removed, not duplicated

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(School)) == 2
        real_id = admin.user["school_id"]
        assert [t.full_name for t in db.scalars(select(Teacher).where(Teacher.school_id == real_id))] == ["Real Teacher"]
        school = demo.demo_school(db)
        assert sorted(s.name for s in db.scalars(select(Section).where(Section.school_id == school.id))) == sorted(demo.KEEP)
        assert db.scalar(select(func.count()).select_from(ScheduleEntry).where(ScheduleEntry.school_id == real_id)) == 0
    assert login(admin.client, "admin@demo.example", "Private-Admin-Pass-1").status_code == 200


def test_rebuild_only_when_missing_or_a_day_old(monkeypatch):
    started = []
    monkeypatch.setattr(demo.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: started.append(kw["name"])})())
    demo.start()
    assert started == []  # demo mode off

    monkeypatch.setattr(settings, "demo_mode", True)
    demo.start()
    assert started == ["demo-reset"]  # no demo school yet

    demo.reset()
    started.clear()
    demo.start()
    assert started == []  # rebuilt moments ago

    with SessionLocal() as db:
        school = demo.demo_school(db)
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=25)).isoformat()
        school.settings = {**school.settings, "demo_reset_at": old}
        db.commit()
    demo.start()
    assert started == ["demo-reset"]
