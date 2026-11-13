"""Subscription plans and their limits. The plans themselves are data: app/data/plans.json."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import School, Section, Teacher

PLANS_FILE = Path(__file__).parent / "data" / "plans.json"

# What each limit counts, and how to say it.
LIMITS = {"max_sections": (Section, "sections"), "max_teachers": (Teacher, "teachers")}


@lru_cache
def load_plans() -> dict[str, Any]:
    return json.loads(PLANS_FILE.read_text(encoding="utf-8"))


def default_plan() -> str:
    return load_plans()["default_plan"]


def plan_of(school: School) -> tuple[str, dict[str, Any]]:
    """The school's plan; an unknown plan code falls back to the default plan."""
    plans = load_plans()["plans"]
    code = school.plan if school.plan in plans else default_plan()
    return code, plans[code]


def usage(db: Session, school_id: int) -> dict[str, int]:
    return {
        noun: db.scalar(select(func.count()).select_from(model).where(model.school_id == school_id)) or 0
        for model, noun in LIMITS.values()
    }


def enforce_limit(db: Session, school_id: int, model: type) -> None:
    """Called before a new section or teacher is added. Raises 402 at the plan limit."""
    for key, (limited, noun) in LIMITS.items():
        if limited is not model:
            continue
        _, plan = plan_of(db.get(School, school_id))
        limit = plan.get(key)
        if limit is None:
            return
        have = db.scalar(select(func.count()).select_from(model).where(model.school_id == school_id)) or 0
        if have >= limit:
            raise HTTPException(
                402, f"Your {plan['name']} plan allows up to {limit} {noun}. Upgrade the plan to add more."
            )
