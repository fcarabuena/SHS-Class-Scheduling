"""Phone and browser notifications for people who follow a section's timetable.

Followers have no account: a device subscribes through a public share link.
Whenever a section's classes change, one notification goes to its followers
after a quiet minute, so a burst of edits becomes one message.

    python -m app.push      prints a new key pair for .env
"""

import base64
import datetime as dt
import json
import logging
import threading
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import PushSubscription, ScheduleEntry, School, ShareLink

log = logging.getLogger(__name__)

# The server POSTs to whatever address a browser gives, so only real push services are accepted.
PUSH_HOSTS = ("fcm.googleapis.com", ".push.services.mozilla.com", ".notify.windows.com", ".push.apple.com")
# Edits within this time become one notification.
DELAY_SECONDS = 60.0
# A change to any of these is visible on the timetable (pinning is not).
VISIBLE = ("day_of_week", "period_id", "subject_id", "teacher_id", "room_id", "remarks")


def enabled() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def allowed_endpoint(url: str) -> bool:
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS)


# --- noticing changes ---------------------------------------------------------


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _context) -> None:
    changed = session.info.setdefault("timetable_changes", set())
    for obj in (*session.new, *session.deleted):
        if isinstance(obj, ScheduleEntry):
            changed.add((obj.semester_id, obj.section_id))
    for obj in session.dirty:
        if isinstance(obj, ScheduleEntry) and any(inspect(obj).attrs[name].history.has_changes() for name in VISIBLE):
            changed.add((obj.semester_id, obj.section_id))


@event.listens_for(Session, "after_commit")
def _committed(session: Session) -> None:
    for key in session.info.pop("timetable_changes", ()):
        section_changed(*key)


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: Session) -> None:
    session.info.pop("timetable_changes", None)


# --- sending -----------------------------------------------------------------

_pending: set[tuple[int, int]] = set()
_lock = threading.Lock()


def section_changed(semester_id: int, section_id: int) -> None:
    if not enabled():
        return
    with _lock:
        if (semester_id, section_id) in _pending:
            return  # already waiting: this change rides along
        _pending.add((semester_id, section_id))
    _start_timer(semester_id, section_id)


def _start_timer(semester_id: int, section_id: int) -> None:
    # shortcut: waiting messages live in memory and are lost if the API restarts within the minute; use a job queue if that matters.
    timer = threading.Timer(DELAY_SECONDS, _send_later, (semester_id, section_id))
    timer.daemon = True
    timer.start()


def _send_later(semester_id: int, section_id: int) -> None:
    with _lock:
        _pending.discard((semester_id, section_id))
    try:
        with SessionLocal() as db:
            send_section(db, semester_id, section_id)
    except Exception:  # a failed send must never take anything else down
        log.exception("push to followers of section %s failed", section_id)


def send_section(db: Session, semester_id: int, section_id: int) -> int:
    """Notifies every device following this section. Returns how many were reached."""
    now = dt.datetime.now(dt.timezone.utc)
    rows = db.execute(
        select(PushSubscription, ShareLink)
        .join(ShareLink, PushSubscription.share_link_id == ShareLink.id)
        .join(School, School.id == ShareLink.school_id)
        .where(
            ShareLink.view == "section",
            ShareLink.target_id == section_id,
            ShareLink.semester_id == semester_id,
            ShareLink.revoked_at.is_(None),
            School.status == "active",
        )
    ).all()
    reached = 0
    for subscription, link in rows:
        if link.expires_at is not None and link.expires_at <= now:
            continue
        message = {"title": f"{link.label}: timetable changed", "body": "Tap to see the latest timetable.", "url": link.url}
        try:
            webpush(
                {"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
                json.dumps(message),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=24 * 3600,
                timeout=10,
            )
            reached += 1
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                db.delete(subscription)  # the device stopped following (app removed, permission withdrawn)
            else:
                log.warning("push to a follower of section %s failed: %s", section_id, exc)
    db.commit()
    return reached


def new_keys() -> tuple[str, str]:
    """A VAPID key pair as (public, private), both base64url."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    vapid = Vapid02()
    vapid.generate_keys()
    raw_public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    raw_private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")

    def encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return encode(raw_public), encode(raw_private)


if __name__ == "__main__":
    public, private = new_keys()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
