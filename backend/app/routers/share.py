"""Public share links: a read-only timetable anyone with the link can open, follow and add to a calendar."""

import datetime as dt
import io
import secrets
from typing import Any

import segno
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import push, ratelimit
from ..config import settings
from ..deps import DbSession, EditorUser
from ..models import PushSubscription, Room, School, Section, Semester, ShareLink, Teacher
from ..scheduling import engine as eng
from ..scheduling import export
from ..scheduling.state import load_state
from ..services import audit, commit, get_owned
from .schedule import get_semester

router = APIRouter(prefix="/api", tags=["share"])

TARGETS = {"section": (Section, "name"), "teacher": (Teacher, "full_name"), "room": (Room, "name")}
NOT_FOUND = "This link does not exist or is no longer active."
MAX_FOLLOWERS = 5000  # per link; a whole school is far below this


class ShareLinkIn(BaseModel):
    view: str = Field(pattern="^(section|teacher|room)$")
    target_id: int
    semester_id: int | None = None
    # Leave empty for a link that works until it is revoked.
    expires_in_days: int | None = Field(default=None, ge=1, le=366)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _json(link: ShareLink, followers: int = 0) -> dict[str, Any]:
    expired = link.expires_at is not None and link.expires_at <= _now()
    return {
        "id": link.id,
        "semester_id": link.semester_id,
        "view": link.view,
        "target_id": link.target_id,
        "label": link.label,
        "url": link.url,
        "token": link.token,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
        "status": "revoked" if link.revoked_at else "expired" if expired else "active",
        "view_count": link.view_count,
        "last_viewed_at": link.last_viewed_at,
        "followers": followers,
    }


@router.get("/share-links")
def list_share_links(db: DbSession, user: EditorUser, semester_id: int | None = None):
    semester = get_semester(db, user.school_id, semester_id)
    links = db.scalars(
        select(ShareLink)
        .where(ShareLink.school_id == user.school_id, ShareLink.semester_id == semester.id, ShareLink.revoked_at.is_(None))
        .order_by(ShareLink.id.desc())
    ).all()
    followers = dict(
        db.execute(
            select(PushSubscription.share_link_id, func.count())
            .where(PushSubscription.share_link_id.in_([link.id for link in links]))
            .group_by(PushSubscription.share_link_id)
        ).all()
    )
    return [_json(link, followers.get(link.id, 0)) for link in links]


@router.post("/share-links", status_code=201)
def create_share_link(data: ShareLinkIn, db: DbSession, user: EditorUser):
    """Creates a link to one section's, teacher's or room's timetable."""
    semester = get_semester(db, user.school_id, data.semester_id)
    model, name_attr = TARGETS[data.view]
    target = get_owned(db, model, data.target_id, user.school_id)
    link = ShareLink(
        school_id=user.school_id,
        semester_id=semester.id,
        token=secrets.token_urlsafe(32),
        view=data.view,
        target_id=target.id,
        label=getattr(target, name_attr)[:120],
        created_by=user.id,
        expires_at=_now() + dt.timedelta(days=data.expires_in_days) if data.expires_in_days else None,
    )
    db.add(link)
    db.flush()
    audit(db, user, "create", "share_link", link.id, {"summary": f"Public link created for the timetable of {link.label}"})
    commit(db)
    return _json(link)


@router.delete("/share-links/{link_id}", status_code=204)
def revoke_share_link(link_id: int, db: DbSession, user: EditorUser):
    """Turns a link off for good. Anyone who has it sees "no longer active"."""
    link = get_owned(db, ShareLink, link_id, user.school_id)
    if link.revoked_at is None:
        link.revoked_at = _now()
        # Followers are no longer needed: forget their devices.
        db.execute(delete(PushSubscription).where(PushSubscription.share_link_id == link.id))
        audit(db, user, "revoke", "share_link", link.id, {"summary": f"Public link revoked for the timetable of {link.label}"})
        commit(db)


# --- public, no sign-in -----------------------------------------------------------


def _active_link(db: Session, token: str, request: Request) -> ShareLink:
    """The link behind a public token, or 404 when it is unknown, off, expired or its school is suspended."""
    ratelimit.check(f"public:{ratelimit.client_ip(request)}", settings.rate_limit_public)
    link = db.scalar(select(ShareLink).where(ShareLink.token == token)) if 20 <= len(token) <= 64 else None
    if link is None or link.revoked_at is not None or (link.expires_at is not None and link.expires_at <= _now()):
        raise HTTPException(404, NOT_FOUND)
    if db.get(School, link.school_id).status == "suspended":
        raise HTTPException(404, NOT_FOUND)
    return link


@router.get("/public/timetable/{token}")
def public_timetable(token: str, request: Request, db: DbSession):
    """Shows exactly one timetable and nothing else about the school."""
    link = _active_link(db, token, request)
    document = export.build(db, link.school_id, db.get(Semester, link.semester_id), link.view, link.target_id)
    if not document.tables:
        raise HTTPException(404, NOT_FOUND)  # the section, teacher or room was deleted
    link.view_count += 1
    link.last_viewed_at = _now()
    db.commit()
    table = document.tables[0]
    return {
        "school": document.school,
        "heading": document.heading,
        "view": link.view,
        "title": table.title,
        "subtitle": table.subtitle,
        "days": table.days,
        "rows": [{"label": r.label, "time": r.time, "is_break": r.is_break, "cells": r.cells} for r in table.rows],
        # Set when devices may follow this timetable for change notifications (sections only).
        "push_key": settings.vapid_public_key if push.enabled() and link.view == "section" else None,
    }


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class FollowIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: PushKeys


class UnfollowIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.post("/public/timetable/{token}/follow", status_code=201)
def follow(token: str, data: FollowIn, request: Request, db: DbSession):
    """Registers a device for a notification whenever this section's timetable changes. No account, no name."""
    link = _active_link(db, token, request)
    if not push.enabled() or link.view != "section":
        raise HTTPException(422, "Notifications are not available for this timetable.")
    if not push.allowed_endpoint(data.endpoint):
        raise HTTPException(422, "This browser's notification service is not supported.")
    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.share_link_id == link.id, PushSubscription.endpoint == data.endpoint)
    )
    if existing is None:
        followers = db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.share_link_id == link.id))
        if followers >= MAX_FOLLOWERS:
            raise HTTPException(429, "This timetable has too many followers already.")
        db.add(
            PushSubscription(
                school_id=link.school_id, share_link_id=link.id, endpoint=data.endpoint, p256dh=data.keys.p256dh, auth=data.keys.auth
            )
        )
    else:
        existing.p256dh, existing.auth = data.keys.p256dh, data.keys.auth  # browsers may rotate keys
    db.commit()
    return {"following": True}


@router.post("/public/timetable/{token}/unfollow")
def unfollow(token: str, data: UnfollowIn, request: Request, db: DbSession):
    link = _active_link(db, token, request)
    db.execute(delete(PushSubscription).where(PushSubscription.share_link_id == link.id, PushSubscription.endpoint == data.endpoint))
    db.commit()
    return {"following": False}


# --- calendar feed and QR code ------------------------------------------------------

# shortcut: Philippine schools only, so one fixed zone with no daylight saving; store a zone per school to go abroad.
TIMEZONE = "Asia/Manila"
UTC_OFFSET = dt.timedelta(hours=8)


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar lines longer than 75 bytes continue on the next line after a space."""
    raw, parts = line.encode(), []
    while len(raw) > 75:
        cut = 75
        while raw[cut] & 0xC0 == 0x80:  # never split a UTF-8 character
            cut -= 1
        parts.append(raw[:cut].decode())
        raw = b" " + raw[cut:]
    parts.append(raw.decode())
    return "\r\n".join(parts)


def calendar(db: Session, link: ShareLink) -> str:
    """The timetable as weekly repeating events from the first to the last day of the semester."""
    semester = db.get(Semester, link.semester_id)
    state = load_state(db, link.school_id, semester)
    attr = {"section": "section_id", "teacher": "teacher_id", "room": "room_id"}[link.view]
    until = (dt.datetime.combine(semester.end_date, dt.time(23, 59, 59)) - UTC_OFFSET).strftime("%Y%m%dT%H%M%SZ")
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SHS Scheduler//Timetable//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_text(link.label)} timetable",
        f"X-WR-TIMEZONE:{TIMEZONE}",
        "BEGIN:VTIMEZONE",
        f"TZID:{TIMEZONE}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    seen = set()
    for entry in sorted(state.entries, key=lambda e: (e.day, e.period_id, e.id)):
        if getattr(entry, attr) != link.target_id or entry.period_id not in state.slots:
            continue
        key = eng._class_key(entry)  # a combined class is one event
        if key in seen:
            continue
        seen.add(key)
        slot = state.slots[entry.period_id]
        first = semester.start_date + dt.timedelta(days=(entry.day - 1 - semester.start_date.weekday()) % 7)
        start = dt.datetime.combine(first, dt.time(slot.start // 60, slot.start % 60))
        end = dt.datetime.combine(first, dt.time(slot.end // 60, slot.end % 60))
        subject = state.subjects.get(entry.subject_id)
        teacher = state.teachers.get(entry.teacher_id) if entry.teacher_id is not None else None
        room = state.rooms.get(entry.room_id) if entry.room_id is not None else None
        title = subject.code if subject else "Class"
        if link.view != "section":
            members = eng.siblings(state, entry)
            title += " · " + " + ".join(sorted(state.sections[e.section_id].name for e in members if e.section_id in state.sections))
        details = [subject.name if subject else "", f"Teacher: {teacher.name}" if teacher and link.view != "teacher" else "", entry.remarks or ""]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{entry.id}-{link.id}@shs-scheduler",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID={TIMEZONE}:{start:%Y%m%dT%H%M%S}",
            f"DTEND;TZID={TIMEZONE}:{end:%Y%m%dT%H%M%S}",
            f"RRULE:FREQ=WEEKLY;UNTIL={until}",
            f"SUMMARY:{_ics_text(title)}",
            *([f"LOCATION:{_ics_text(room.name)}"] if room else []),
            f"DESCRIPTION:{_ics_text(chr(10).join(d for d in details if d))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


@router.get("/public/timetable/{token}/calendar.ics")
def calendar_feed(token: str, request: Request, db: DbSession):
    """Subscribe to this in a phone or Google calendar; the calendar app refreshes it by itself."""
    link = _active_link(db, token, request)
    return Response(
        calendar(db, link),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{link.view}-timetable.ics"'},
    )


@router.get("/public/timetable/{token}/qr.svg")
def qr_code(token: str, request: Request, db: DbSession):
    """A QR code of the link, to print and post in the classroom."""
    link = _active_link(db, token, request)
    buffer = io.BytesIO()
    segno.make(link.url, error="m").save(buffer, kind="svg", scale=8, border=2, title=f"Timetable of {link.label}")
    return Response(buffer.getvalue(), media_type="image/svg+xml")
