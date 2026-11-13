"""Phase 3: public share links, notifications, platform admin, billing hooks, rate limits."""

import datetime as dt
import hashlib
import hmac
import json

import pytest

from app import billing
from app.config import settings
from app.db import SessionLocal
from app.models import ShareLink

from .conftest import PASSWORD, Api
from .test_schedule_api import MON, TUE, assign, entry_at, generate, ok, place, run_solver, world  # noqa: F401


@pytest.fixture
def platform(monkeypatch, admin) -> Api:
    """The Alpha admin is also the platform (all-schools) administrator."""
    monkeypatch.setattr(settings, "platform_admin_emails", admin.user["email"])
    return admin


def login(client, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def linked_teacher_account(admin: Api, teacher: dict, email: str) -> Api:
    admin.create("/api/users", email=email, full_name=teacher["full_name"], password=PASSWORD, role="teacher", teacher_id=teacher["id"])
    body = login(admin.client, email).json()
    return Api(admin.client, body["access_token"], body["user"])


# --- public share links -------------------------------------------------------


def test_share_link_shows_one_timetable_without_signing_in(admin, world, client):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)

    link = ok(admin.post("/api/share-links", json={"view": "section", "target_id": world["a"]["id"]}), 201)
    assert link["status"] == "active" and link["label"] == "11-A" and link["expires_at"] is None
    token = link["url"].rsplit("/share/", 1)[1]
    assert link["url"].startswith(settings.public_app_url) and len(token) >= 40

    public = client.get(f"/api/public/timetable/{token}")  # no Authorization header
    body = ok(public)
    assert (body["school"], body["title"], body["view"]) == ("Alpha Test School", "11-A", "section")
    assert body["days"][0] == "Monday" and body["rows"][0]["cells"][0][:3] == ["MATH", "Ana Cruz", "Room 1"]
    assert "teacher_id" not in json.dumps(body) and "email" not in json.dumps(body)

    listed = ok(admin.get("/api/share-links"))
    assert [x["id"] for x in listed] == [link["id"]] and listed[0]["view_count"] == 1

    assert admin.delete(f"/api/share-links/{link['id']}").status_code == 204
    assert client.get(f"/api/public/timetable/{token}").status_code == 404
    assert ok(admin.get("/api/share-links")) == []  # revoked links drop off the list
    assert client.get("/api/public/timetable/not-a-real-token-at-all-xxxxx").status_code == 404


def test_expired_link_and_access_rules(admin, world, other_school, client):
    link = ok(admin.post("/api/share-links", json={"view": "teacher", "target_id": world["ana"]["id"], "expires_in_days": 7}), 201)
    token = link["url"].rsplit("/", 1)[1]
    assert link["expires_at"] is not None and ok(client.get(f"/api/public/timetable/{token}"))["title"] == "Ana Cruz"

    with SessionLocal() as db:
        db.get(ShareLink, link["id"]).expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        db.commit()
    assert client.get(f"/api/public/timetable/{token}").status_code == 404
    assert ok(admin.get("/api/share-links"))[0]["status"] == "expired"

    viewer = linked_teacher_account(admin, world["ana"], "ana@alpha.example")
    assert viewer.post("/api/share-links", json={"view": "section", "target_id": world["a"]["id"]}).status_code == 403
    assert other_school.delete(f"/api/share-links/{link['id']}").status_code == 404
    assert other_school.post("/api/share-links", json={"view": "room", "target_id": world["room1"]["id"]}).status_code in (404, 422)
    assert admin.post("/api/share-links", json={"view": "students", "target_id": 1}).status_code == 422


# --- notifications --------------------------------------------------------------


def test_teacher_is_notified_when_their_load_and_timetable_change(admin, world):
    ana = linked_teacher_account(admin, world["ana"], "ana@alpha.example")
    assert ok(ana.get("/api/notifications")) == {"unread": 0, "items": []}

    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    entry = entry_at(data, world["a"], MON, p1)
    ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"day_of_week": TUE, "period_id": p2["id"]}))

    inbox = ok(ana.get("/api/notifications"))
    by_kind = {item["kind"]: item for item in inbox["items"]}
    assert inbox["unread"] == 2
    assert by_kind["loading"]["body"] == "11-A · MATH is now yours."
    # The placement and the move are folded into one message.
    assert by_kind["timetable"]["count"] == 2 and by_kind["timetable"]["body"] == "11-A · MATH: Mon Period 1 → Tue Period 2"
    assert ok(admin.get("/api/notifications"))["unread"] == 0  # nobody is told about their own changes

    ok(ana.post("/api/notifications/read", json={"ids": [by_kind["loading"]["id"]]}))
    assert ok(ana.get("/api/notifications"))["unread"] == 1
    assert ok(ana.post("/api/notifications/read", json={}))["marked"] == 1
    assert ok(ana.get("/api/notifications"))["unread"] == 0
    # Another user's notification ids are ignored.
    assert ok(admin.post("/api/notifications/read", json={"ids": [by_kind["loading"]["id"]]}))["marked"] == 0

    data = assign(admin, data, world["a"], world["math"], world["ben"])
    assert ok(ana.get("/api/notifications"))["items"][0]["title"] == "A class was taken off your load"


def test_auto_schedule_tells_the_person_who_started_it(admin, world):
    data = generate(admin)
    for section in (world["a"], world["b"]):
        data = assign(admin, data, section, world["math"], world["ben"])
    run_solver(admin)
    item = ok(admin.get("/api/notifications"))["items"][0]
    assert item["kind"] == "solver" and item["title"] == "Auto-schedule finished" and item["link"] == "/timetable"


# --- platform admin: all schools -----------------------------------------------------


def test_only_platform_admins_see_all_schools(admin, other_school):
    assert admin.get("/api/platform/schools").status_code == 403
    assert login(admin.client, admin.user["email"]).json()["user"]["is_platform_admin"] is False


def test_platform_admin_lists_and_suspends_schools(platform, other_school, client):
    assert login(client, platform.user["email"]).json()["user"]["is_platform_admin"] is True
    listing = ok(platform.get("/api/platform/schools"))
    assert {p["code"] for p in listing["plans"]} >= {"standard", "starter"}
    beta = next(s for s in listing["schools"] if s["name"] == "Beta Test School")
    assert (beta["status"], beta["plan"], beta["users"], beta["teachers"]) == ("active", "standard", 1, 0)

    changed = ok(platform.put(f"/api/platform/schools/{beta['id']}", json={"status": "suspended"}))
    assert changed["status"] == "suspended"
    assert other_school.get("/api/school").status_code == 403  # an open session stops working at once
    blocked = login(client, "admin@beta.example")
    assert blocked.status_code == 403 and "suspended" in blocked.json()["detail"]

    ok(platform.put(f"/api/platform/schools/{beta['id']}", json={"status": "active", "plan": "starter"}))
    assert login(client, "admin@beta.example").status_code == 200
    history = ok(other_school.get("/api/audit-logs?entity_type=school_account"))
    assert "plan standard → starter" in history[0]["changes"]["summary"]

    own = platform.put(f"/api/platform/schools/{platform.user['school_id']}", json={"status": "suspended"})
    assert own.status_code == 422
    assert platform.put(f"/api/platform/schools/{beta['id']}", json={"plan": "gold"}).status_code == 422
    assert platform.put("/api/platform/schools/999999", json={"status": "active"}).status_code == 404


def test_public_link_of_a_suspended_school_stops_working(platform, other_school, client):
    room = other_school.create("/api/rooms", code="R1", name="Room 1", capacity=40)
    other_school.create(
        "/api/school-years",
        name="2026-2027",
        start_date="2026-06-15",
        end_date="2027-03-31",
        first_semester={"start_date": "2026-06-15", "end_date": "2026-10-30"},
        second_semester={"start_date": "2026-11-09", "end_date": "2027-03-31"},
    )
    link = ok(other_school.post("/api/share-links", json={"view": "room", "target_id": room["id"]}), 201)
    token = link["url"].rsplit("/", 1)[1]
    assert client.get(f"/api/public/timetable/{token}").status_code == 200
    beta_id = other_school.user["school_id"]
    ok(platform.put(f"/api/platform/schools/{beta_id}", json={"status": "suspended"}))
    assert client.get(f"/api/public/timetable/{token}").status_code == 404


# --- billing ------------------------------------------------------------------------


TINY = {"default_plan": "free", "plans": {"free": {"name": "Free", "max_sections": None, "max_teachers": 1}, "pro": {"name": "Pro"}}}


def test_plan_limits_are_enforced_and_shown(admin, monkeypatch):
    monkeypatch.setattr(billing, "load_plans", lambda: TINY)
    admin.create("/api/teachers", employee_id="T-1", full_name="Ana Cruz")
    refused = admin.post("/api/teachers", json={"employee_id": "T-2", "full_name": "Ben Reyes"})
    assert refused.status_code == 402 and "Free plan allows up to 1 teachers" in refused.json()["detail"]
    plan = ok(admin.get("/api/billing"))
    assert plan["plan"] == "free" and plan["plan_name"] == "Free"  # "standard" is unknown here, so the default applies
    assert {"what": "teachers", "used": 1, "limit": 1} in plan["limits"]
    # Editing an existing record is never blocked by the limit.
    teacher = ok(admin.get("/api/teachers"))[0]
    assert admin.put(f"/api/teachers/{teacher['id']}", json={**teacher, "full_name": "Ana Dela Cruz"}).status_code == 200


def test_billing_page_is_for_admins(admin):
    viewer_body = admin.create("/api/users", email="v@alpha.example", full_name="Viewer", password=PASSWORD, role="scheduler")
    token = login(admin.client, viewer_body["email"]).json()["access_token"]
    assert admin.client.get("/api/billing", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def signed(body: dict, secret: str = "test-secret") -> dict:
    raw = json.dumps(body).encode()
    return {"content": raw, "headers": {"Content-Type": "application/json", "X-Signature": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}}


def test_billing_webhook_updates_the_plan(admin, client, monkeypatch):
    school_id = admin.user["school_id"]
    event = {"event": "subscription.updated", "school_id": school_id, "billing_ref": "cus_123", "plan": "starter", "renews_at": "2027-06-30"}
    assert client.post("/api/billing/webhook", **signed(event)).status_code == 503  # off until a secret is set

    monkeypatch.setattr(settings, "billing_webhook_secret", "test-secret")
    assert client.post("/api/billing/webhook", **signed(event, secret="wrong")).status_code == 401
    assert client.post("/api/billing/webhook", content=json.dumps(event).encode()).status_code == 401

    result = ok(client.post("/api/billing/webhook", **signed(event)))
    assert (result["school_id"], result["plan"], result["status"]) == (school_id, "starter", "active")
    plan = ok(admin.get("/api/billing"))
    assert plan["plan"] == "starter" and plan["renews_at"] == "2027-06-30"

    # Later events can find the school by the provider's customer id alone.
    cancelled = ok(client.post("/api/billing/webhook", **signed({"event": "subscription.cancelled", "billing_ref": "cus_123"})))
    assert cancelled["plan"] == "standard"
    log = ok(admin.get("/api/audit-logs?entity_type=school_account"))[0]
    assert log["action"] == "billing" and log["user_id"] is None and "subscription.cancelled" in log["changes"]["summary"]

    assert client.post("/api/billing/webhook", **signed({"event": "subscription.updated", "billing_ref": "nobody"})).status_code == 404
    assert client.post("/api/billing/webhook", **signed({**event, "plan": "gold"})).status_code == 422
    assert client.post("/api/billing/webhook", **signed({"event": "refund.created"})).status_code == 422


# --- rate limits ------------------------------------------------------------------------


def test_login_attempts_are_rate_limited(admin, client):
    for _ in range(10):
        assert login(client, "admin@alpha.example", "wrong-password").status_code == 401
    blocked = login(client, "admin@alpha.example", PASSWORD)
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    assert login(client, "other@alpha.example", "wrong-password").status_code == 401  # counted per account
