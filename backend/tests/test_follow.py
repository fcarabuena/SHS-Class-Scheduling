"""Following a section without an account: push notifications, calendar feed, QR code."""

from types import SimpleNamespace

import pytest
from pywebpush import WebPushException

from app import push
from app.config import settings
from app.db import SessionLocal
from app.models import PushSubscription

from .test_schedule_api import MON, TUE, assign, entry_at, generate, ok, place, world  # noqa: F401

FCM = "https://fcm.googleapis.com/fcm/send/device-"
KEYS = {"p256dh": "B" + "x" * 86, "auth": "a" * 22}


@pytest.fixture
def push_on(monkeypatch):
    """Push configured, and timers replaced by a list of the sections that would be notified."""
    public, private = push.new_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    monkeypatch.setattr(settings, "vapid_private_key", private)
    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(push, "_start_timer", lambda semester_id, section_id: queued.append((semester_id, section_id)))
    push._pending.clear()
    yield queued
    push._pending.clear()


def section_link(admin, section) -> dict:
    link = ok(admin.post("/api/share-links", json={"view": "section", "target_id": section["id"]}), 201)
    return {**link, "path": f"/api/public/timetable/{link['token']}"}


def test_following_needs_push_configured_and_a_section_link(admin, world, client):
    link = section_link(admin, world["a"])
    assert ok(client.get(link["path"]))["push_key"] is None
    assert client.post(f"{link['path']}/follow", json={"endpoint": FCM + "1", "keys": KEYS}).status_code == 422


def test_a_device_follows_and_unfollows_a_section(admin, world, client, push_on):
    link = section_link(admin, world["a"])
    assert ok(client.get(link["path"]))["push_key"] == settings.vapid_public_key
    teacher_link = ok(admin.post("/api/share-links", json={"view": "teacher", "target_id": world["ana"]["id"]}), 201)
    assert ok(client.get(f"/api/public/timetable/{teacher_link['token']}"))["push_key"] is None  # sections only

    # Only real push services: the server would otherwise send requests to any address.
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/fcm.googleapis.com", "https://localhost/x"):
        assert client.post(f"{link['path']}/follow", json={"endpoint": bad, "keys": KEYS}).status_code == 422
    assert client.post(f"{link['path']}/follow", json={"endpoint": FCM + "1", "keys": {"p256dh": "x", "auth": "y"}}).status_code == 422

    body = {"endpoint": FCM + "1", "keys": KEYS}
    assert ok(client.post(f"{link['path']}/follow", json=body), 201) == {"following": True}
    ok(client.post(f"{link['path']}/follow", json=body), 201)  # following twice is still one follower
    ok(client.post(f"{link['path']}/follow", json={"endpoint": "https://updates.push.services.mozilla.com/wpush/v2/x", "keys": KEYS}), 201)
    assert ok(admin.get("/api/share-links"))[-1]["followers"] == 2

    ok(client.post(f"{link['path']}/unfollow", json={"endpoint": FCM + "1"}))
    assert ok(admin.get("/api/share-links"))[-1]["followers"] == 1
    assert admin.delete(f"/api/share-links/{link['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.query(PushSubscription).count() == 0  # a turned-off link forgets its followers


def test_visible_timetable_changes_queue_one_notification_per_section(admin, world, push_on):
    semester = world["semester"]["id"]
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    p1, p2 = world["periods"][0], world["periods"][1]
    data = ok(place(admin, data, world["a"], world["math"], MON, p1), 201)
    assert push_on == [(semester, world["a"]["id"])]

    entry = entry_at(data, world["a"], MON, p1)
    ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"day_of_week": TUE}))
    assert len(push_on) == 1  # still waiting to send: the move rides along with the placement

    push._pending.clear()
    ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"pinned": True}))
    assert len(push_on) == 1  # pinning is invisible to students
    ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"remarks": "Bring calculators"}))
    assert push_on[-1] == (semester, world["a"]["id"]) and len(push_on) == 2

    push._pending.clear()
    refused = place(admin, data, world["a"], world["sci"], TUE, p1)  # slot taken: nothing saved
    assert refused.status_code == 409 and len(push_on) == 2
    ok(place(admin, data, world["b"], world["sci"], MON, p2), 201)
    assert push_on[-1] == (semester, world["b"]["id"])


def test_send_reaches_followers_and_forgets_devices_that_left(admin, world, client, push_on, monkeypatch):
    link = section_link(admin, world["a"])
    for n in (1, 2):
        ok(client.post(f"{link['path']}/follow", json={"endpoint": FCM + str(n), "keys": KEYS}), 201)
    other = section_link(admin, world["b"])
    ok(client.post(f"{other['path']}/follow", json={"endpoint": FCM + "3", "keys": KEYS}), 201)

    sent = []

    def fake_webpush(subscription, data, **options):
        if subscription["endpoint"].endswith("2"):
            raise WebPushException("gone", response=SimpleNamespace(status_code=410))
        sent.append((subscription["endpoint"], data, options["vapid_claims"]["sub"]))

    monkeypatch.setattr(push, "webpush", fake_webpush)
    with SessionLocal() as db:
        assert push.send_section(db, world["semester"]["id"], world["a"]["id"]) == 1
        assert {s.endpoint for s in db.query(PushSubscription)} == {FCM + "1", FCM + "3"}  # device 2 is forgotten
    endpoint, message, subject = sent[0]
    assert endpoint == FCM + "1" and subject == settings.vapid_subject
    assert '"title": "11-A: timetable changed"' in message and link["url"] in message


def test_calendar_feed_repeats_each_class_weekly_for_the_semester(admin, world, client):
    data = generate(admin)
    data = assign(admin, data, world["a"], world["math"], world["ana"])
    data = ok(place(admin, data, world["a"], world["math"], MON, world["periods"][0]), 201)
    entry = entry_at(data, world["a"], MON, world["periods"][0])
    ok(admin.put(f"/api/schedule/entries/{entry['id']}", json={"remarks": "Bring calculators, protractor"}))
    link = section_link(admin, world["a"])

    response = client.get(f"{link['path']}/calendar.ics")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/calendar")
    text = response.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n") and text.count("BEGIN:VEVENT") == 1
    # The semester starts on Monday 15 June 2026; period 1 runs 07:00-08:00, Philippine time.
    assert "DTSTART;TZID=Asia/Manila:20260615T070000" in text and "DTEND;TZID=Asia/Manila:20260615T080000" in text
    assert "RRULE:FREQ=WEEKLY;UNTIL=20261030T155959Z" in text  # 30 Oct, 23:59:59 Manila time, in UTC
    assert "SUMMARY:MATH\r\n" in text and "LOCATION:Room 1" in text
    assert "DESCRIPTION:Mathematics\\nTeacher: Ana Cruz\\nBring calculators\\, protractor" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))

    teacher = ok(admin.post("/api/share-links", json={"view": "teacher", "target_id": world["ana"]["id"]}), 201)
    assert "SUMMARY:MATH · 11-A" in client.get(f"/api/public/timetable/{teacher['token']}/calendar.ics").text


def test_qr_code_and_dead_links(admin, world, client):
    link = section_link(admin, world["a"])
    qr = client.get(f"{link['path']}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/svg+xml" and b"<svg" in qr.content
    assert admin.delete(f"/api/share-links/{link['id']}").status_code == 204
    for suffix in ("/qr.svg", "/calendar.ics"):
        assert client.get(link["path"] + suffix).status_code == 404
