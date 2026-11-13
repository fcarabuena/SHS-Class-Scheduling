"""Creates in-app notifications. Rows join the caller's transaction."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Notification, User

# Repeats of the same kind of unread message within this time are folded into one.
FOLD_WINDOW = dt.timedelta(hours=1)


def notify_users(
    db: Session, school_id: int, user_ids: list[int], kind: str, title: str, body: str = "", link: str | None = None
) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    for user_id in dict.fromkeys(user_ids):
        recent = db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.kind == kind,
                Notification.read_at.is_(None),
                Notification.created_at >= now - FOLD_WINDOW,
            )
            .order_by(Notification.id.desc())
        ).first()
        if recent:
            recent.count += 1
            recent.title, recent.body, recent.link, recent.created_at = title[:160], body[:500], link, now
        else:
            db.add(
                Notification(school_id=school_id, user_id=user_id, kind=kind, title=title[:160], body=body[:500], link=link, created_at=now)
            )


def users_of_teacher(db: Session, school_id: int, teacher_id: int | None, exclude: int | None = None) -> list[int]:
    """Active accounts linked to a teacher (usually one)."""
    if teacher_id is None:
        return []
    rows = db.scalars(
        select(User.id).where(User.school_id == school_id, User.teacher_id == teacher_id, User.is_active.is_(True))
    )
    return [user_id for user_id in rows if user_id != exclude]


def notify_teacher(
    db: Session, school_id: int, teacher_id: int | None, kind: str, title: str, body: str = "", link: str | None = "/timetable", exclude: int | None = None
) -> None:
    notify_users(db, school_id, users_of_teacher(db, school_id, teacher_id, exclude), kind, title, body, link)
