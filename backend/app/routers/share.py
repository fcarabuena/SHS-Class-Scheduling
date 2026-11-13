"""Public share links: a read-only timetable anyone with the link can open."""

import datetime as dt
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import ratelimit
from ..config import settings
from ..deps import DbSession, EditorUser
from ..models import Room, School, Section, Semester, ShareLink, Teacher
from ..scheduling import export
from ..services import audit, commit, get_owned
from .schedule import get_semester

router = APIRouter(prefix="/api", tags=["share"])

TARGETS = {"section": (Section, "name"), "teacher": (Teacher, "full_name"), "room": (Room, "name")}
NOT_FOUND = "This link does not exist or is no longer active."


class ShareLinkIn(BaseModel):
    view: str = Field(pattern="^(section|teacher|room)$")
    target_id: int
    semester_id: int | None = None
    # Leave empty for a link that works until it is revoked.
    expires_in_days: int | None = Field(default=None, ge=1, le=366)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _json(link: ShareLink) -> dict[str, Any]:
    expired = link.expires_at is not None and link.expires_at <= _now()
    return {
        "id": link.id,
        "semester_id": link.semester_id,
        "view": link.view,
        "target_id": link.target_id,
        "label": link.label,
        "url": f"{settings.public_app_url.rstrip('/')}/share/{link.token}",
        "created_at": link.created_at,
        "expires_at": link.expires_at,
        "status": "revoked" if link.revoked_at else "expired" if expired else "active",
        "view_count": link.view_count,
        "last_viewed_at": link.last_viewed_at,
    }


@router.get("/share-links")
def list_share_links(db: DbSession, user: EditorUser, semester_id: int | None = None):
    semester = get_semester(db, user.school_id, semester_id)
    links = db.scalars(
        select(ShareLink)
        .where(ShareLink.school_id == user.school_id, ShareLink.semester_id == semester.id, ShareLink.revoked_at.is_(None))
        .order_by(ShareLink.id.desc())
    )
    return [_json(link) for link in links]


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
        audit(db, user, "revoke", "share_link", link.id, {"summary": f"Public link revoked for the timetable of {link.label}"})
        commit(db)


@router.get("/public/timetable/{token}")
def public_timetable(token: str, request: Request, db: DbSession):
    """No sign-in needed. Shows exactly one timetable and nothing else about the school."""
    ratelimit.check(f"public:{ratelimit.client_ip(request)}", settings.rate_limit_public)
    link = db.scalar(select(ShareLink).where(ShareLink.token == token)) if 20 <= len(token) <= 64 else None
    if link is None or link.revoked_at is not None or (link.expires_at is not None and link.expires_at <= _now()):
        raise HTTPException(404, NOT_FOUND)
    school = db.get(School, link.school_id)
    if school.status == "suspended":
        raise HTTPException(404, NOT_FOUND)
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
    }

