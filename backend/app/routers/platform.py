"""Notifications, the platform (all-schools) admin, and billing hooks."""

import datetime as dt
import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import billing
from ..config import settings
from ..deps import AdminUser, CurrentUser, DbSession, PlatformAdmin
from ..models import AuditLog, Notification, ScheduleEntry, School, Section, Teacher, User
from ..services import commit

router = APIRouter(prefix="/api", tags=["platform"])


# --- notifications ----------------------------------------------------------


class ReadIn(BaseModel):
    # Leave empty to mark everything as read.
    ids: list[int] | None = None


@router.get("/notifications")
def list_notifications(db: DbSession, user: CurrentUser, limit: int = 50):
    mine = Notification.user_id == user.id
    items = db.scalars(
        select(Notification).where(mine).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(max(1, min(limit, 200)))
    ).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(mine, Notification.read_at.is_(None)))
    return {
        "unread": unread or 0,
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "count": n.count,
                "created_at": n.created_at,
                "read": n.read_at is not None,
            }
            for n in items
        ],
    }


@router.post("/notifications/read")
def mark_read(data: ReadIn, db: DbSession, user: CurrentUser):
    query = select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if data.ids is not None:
        query = query.where(Notification.id.in_(data.ids))
    now = dt.datetime.now(dt.timezone.utc)
    changed = 0
    for row in db.scalars(query):
        row.read_at = now
        changed += 1
    db.commit()
    return {"marked": changed}


# --- billing: what a school sees ---------------------------------------------


def _plan_json(db: DbSession, school: School) -> dict[str, Any]:
    code, plan = billing.plan_of(school)
    used = billing.usage(db, school.id)
    return {
        "plan": code,
        "plan_name": plan["name"],
        "renews_at": school.plan_renews_at,
        "status": school.status,
        "limits": [
            {"what": noun, "used": used[noun], "limit": plan.get(key)} for key, (_, noun) in billing.LIMITS.items()
        ],
    }


@router.get("/billing")
def my_plan(db: DbSession, admin: AdminUser):
    """The school's plan and how much of each limit is used."""
    return _plan_json(db, db.get(School, admin.school_id))


# --- platform admin: every school --------------------------------------------


class SchoolAdminIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|suspended)$")
    plan: str | None = None
    plan_renews_at: dt.date | None = None
    billing_ref: str | None = Field(default=None, max_length=100)


def _count(db: DbSession, model: type) -> dict[int, int]:
    return dict(db.execute(select(model.school_id, func.count()).group_by(model.school_id)).all())


@router.get("/platform/schools")
def list_schools(db: DbSession, admin: PlatformAdmin):
    """Every school with usage counts only. Timetables and names of staff are not exposed here."""
    users, teachers, sections, classes = (_count(db, m) for m in (User, Teacher, Section, ScheduleEntry))
    last = dict(db.execute(select(AuditLog.school_id, func.max(AuditLog.created_at)).group_by(AuditLog.school_id)).all())
    plans = billing.load_plans()
    return {
        "plans": [{"code": code, "name": plan["name"]} for code, plan in plans["plans"].items()],
        "schools": [
            {
                "id": s.id,
                "name": s.name,
                "division": s.division,
                "status": s.status,
                "plan": billing.plan_of(s)[0],
                "plan_renews_at": s.plan_renews_at,
                "billing_ref": s.billing_ref,
                "created_at": s.created_at,
                "last_activity": last.get(s.id),
                "users": users.get(s.id, 0),
                "teachers": teachers.get(s.id, 0),
                "sections": sections.get(s.id, 0),
                "classes": classes.get(s.id, 0),
            }
            for s in db.scalars(select(School).order_by(School.name))
        ],
    }


def _apply(school: School, values: dict[str, Any]) -> list[str]:
    changes = []
    for key, value in values.items():
        if getattr(school, key) != value:
            changes.append(f"{key.replace('_', ' ')} {getattr(school, key) or 'none'} → {value or 'none'}")
            setattr(school, key, value)
    return changes


@router.put("/platform/schools/{school_id}")
def update_school_account(school_id: int, data: SchoolAdminIn, db: DbSession, admin: PlatformAdmin):
    """Suspends or reactivates a school, or changes its plan."""
    school = db.get(School, school_id)
    if school is None:
        raise HTTPException(404, "Not found")
    values = data.model_dump(exclude_unset=True)
    if values.get("plan") is not None and values["plan"] not in billing.load_plans()["plans"]:
        raise HTTPException(422, "That plan does not exist.")
    if values.get("status") == "suspended" and school.id == admin.school_id:
        raise HTTPException(422, "You cannot suspend the school your own account belongs to.")
    changes = _apply(school, {k: v for k, v in values.items() if not (k in ("status", "plan") and v is None)})
    if changes:
        # Recorded in the affected school's own history, so its admin can see it.
        db.add(
            AuditLog(
                school_id=school.id,
                user_id=admin.id,
                action="update",
                entity_type="school_account",
                entity_id=school.id,
                changes={"summary": "Account changed by the service administrator: " + "; ".join(changes)},
            )
        )
    commit(db)
    return {"id": school.id, "status": school.status, "plan": billing.plan_of(school)[0], "plan_renews_at": school.plan_renews_at}


# --- billing webhook: what a payment provider calls ---------------------------


class BillingEvent(BaseModel):
    event: str = Field(pattern=r"^subscription\.(updated|cancelled)$")
    school_id: int | None = None
    billing_ref: str | None = Field(default=None, max_length=100)
    plan: str | None = None
    renews_at: dt.date | None = None
    status: str | None = Field(default=None, pattern="^(active|suspended)$")


@router.post("/billing/webhook")
async def billing_webhook(request: Request, db: DbSession):
    """Keeps a school's plan in step with the payment provider.

    The call must carry ``X-Signature: sha256=<hex>``, the HMAC-SHA256 of the
    raw body with BILLING_WEBHOOK_SECRET. The school is found by ``school_id``
    or, once linked, by ``billing_ref`` (the provider's customer id).
    """
    if not settings.billing_webhook_secret:
        raise HTTPException(503, "The billing webhook is not configured.")
    body = await request.body()
    expected = "sha256=" + hmac.new(settings.billing_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("x-signature", "")):
        raise HTTPException(401, "Invalid signature.")
    try:
        event = BillingEvent.model_validate(json.loads(body))
    except (ValueError, TypeError):
        raise HTTPException(422, "Unrecognised billing event.") from None

    school = db.get(School, event.school_id) if event.school_id is not None else None
    if school is None and event.billing_ref:
        school = db.scalar(select(School).where(School.billing_ref == event.billing_ref))
    if school is None:
        raise HTTPException(404, "No school matches this event.")

    values: dict[str, Any] = {}
    if event.event == "subscription.cancelled":
        values = {"plan": billing.default_plan(), "plan_renews_at": None}
    else:
        if event.plan is not None:
            if event.plan not in billing.load_plans()["plans"]:
                raise HTTPException(422, "That plan does not exist.")
            values["plan"] = event.plan
        values["plan_renews_at"] = event.renews_at
        if event.status is not None:
            values["status"] = event.status
    if event.billing_ref and event.school_id is not None:
        values["billing_ref"] = event.billing_ref
    changes = _apply(school, values)
    if changes:
        db.add(
            AuditLog(
                school_id=school.id,
                user_id=None,
                action="billing",
                entity_type="school_account",
                entity_id=school.id,
                changes={"summary": f"Billing ({event.event}): " + "; ".join(changes)},
            )
        )
    db.commit()
    return {"ok": True, "school_id": school.id, "plan": billing.plan_of(school)[0], "status": school.status}

