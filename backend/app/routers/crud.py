"""Generic, tenant-scoped CRUD routers for the configurable master data."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import CurrentUser, DbSession, EditorUser
from ..models import (
    CurriculumEntry,
    Period,
    Room,
    School,
    Section,
    Strand,
    Subject,
    Teacher,
    TeacherAvailability,
    Track,
    User,
)
from ..schemas import (
    CurriculumEntryIn,
    CurriculumEntryOut,
    RoomIn,
    RoomOut,
    SectionIn,
    SectionOut,
    StrandIn,
    StrandOut,
    SubjectIn,
    SubjectOut,
    TeacherIn,
    TeacherOut,
    TrackIn,
    TrackOut,
)
from ..services import active_school_year, audit, check_references, commit, get_owned

Prepare = Callable[[Session, User, dict[str, Any]], None]
Apply = Callable[[Session, User, Any, dict[str, Any]], None]


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(422, message)


def _default_apply(db: Session, user: User, obj: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(obj, key, value)


def save(
    db: Session,
    user: User,
    model: type,
    entity: str,
    values: dict[str, Any],
    obj: Any = None,
    prepare: Prepare | None = None,
    apply: Apply = _default_apply,
) -> Any:
    """Validates and stages a create (obj is None) or update. Caller commits."""
    if prepare:
        prepare(db, user, values)
    check_references(db, model, values, user.school_id)
    action = "update"
    if obj is None:
        action = "create"
        obj = model(school_id=user.school_id)
        apply(db, user, obj, dict(values))
        db.add(obj)
    else:
        apply(db, user, obj, dict(values))
    db.flush()
    audit(db, user, action, entity, obj.id, values)
    return obj


def make_crud(
    path: str,
    model: type,
    schema_in: type[BaseModel],
    schema_out: type[BaseModel],
    *,
    entity: str,
    order_by: tuple,
    filters: tuple[str, ...] = (),
    prepare: Prepare | None = None,
    apply: Apply = _default_apply,
) -> APIRouter:
    router = APIRouter(prefix=f"/api/{path}", tags=[entity])

    @router.get("", response_model=list[schema_out])
    def list_items(request: Request, db: DbSession, user: CurrentUser):
        query = select(model).where(model.school_id == user.school_id)
        for name in filters:
            raw = request.query_params.get(name)
            if raw is None:
                continue
            try:
                query = query.where(getattr(model, name) == int(raw))
            except ValueError:
                raise _unprocessable(f"{name} must be a number") from None
        return db.scalars(query.order_by(*order_by)).all()

    @router.get("/{item_id}", response_model=schema_out)
    def get_item(item_id: int, db: DbSession, user: CurrentUser):
        return get_owned(db, model, item_id, user.school_id)

    @router.post("", response_model=schema_out, status_code=status.HTTP_201_CREATED)
    def create_item(data: schema_in, db: DbSession, user: EditorUser):  # type: ignore[valid-type]
        obj = save(db, user, model, entity, data.model_dump(), prepare=prepare, apply=apply)
        commit(db)
        return obj

    @router.put("/{item_id}", response_model=schema_out)
    def update_item(item_id: int, data: schema_in, db: DbSession, user: EditorUser):  # type: ignore[valid-type]
        obj = get_owned(db, model, item_id, user.school_id)
        save(db, user, model, entity, data.model_dump(), obj=obj, prepare=prepare, apply=apply)
        commit(db)
        return obj

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(item_id: int, db: DbSession, user: EditorUser):
        obj = get_owned(db, model, item_id, user.school_id)
        db.delete(obj)
        audit(db, user, "delete", entity, item_id)
        commit(db)

    return router


# --- resource-specific behaviour --------------------------------------------


def prepare_teacher(db: Session, user: User, values: dict[str, Any]) -> None:
    settings = db.get(School, user.school_id).settings or {}
    if values.get("max_daily_hours") is None:
        values["max_daily_hours"] = settings.get("default_max_daily_hours", 6)
    if values.get("max_weekly_hours") is None:
        values["max_weekly_hours"] = settings.get("default_max_weekly_hours", 30)
    if values["max_daily_hours"] > values["max_weekly_hours"]:
        raise _unprocessable("max_daily_hours cannot exceed max_weekly_hours")
    values.setdefault("qualified_subject_ids", [])
    values.setdefault("availability", [])


def apply_teacher(db: Session, user: User, teacher: Teacher, values: dict[str, Any]) -> None:
    subject_ids = set(values.pop("qualified_subject_ids"))
    slots = values.pop("availability")
    _default_apply(db, user, teacher, values)

    subjects = (
        db.scalars(select(Subject).where(Subject.school_id == user.school_id, Subject.id.in_(subject_ids))).all()
        if subject_ids
        else []
    )
    if len(subjects) != len(subject_ids):
        raise _unprocessable("qualified_subject_ids contains a subject that does not exist")
    teacher.subjects = list(subjects)

    period_ids = {s["period_id"] for s in slots}
    if period_ids:
        valid = set(
            db.scalars(
                select(Period.id).where(
                    Period.school_id == user.school_id, Period.id.in_(period_ids), Period.is_break.is_(False)
                )
            )
        )
        if valid != period_ids:
            raise _unprocessable("availability refers to a period that does not exist or is a break")
    if teacher.id is not None:
        teacher.availability.clear()
        db.flush()  # delete old rows before inserting, to respect the unique slot rule
    for slot in slots:
        teacher.availability.append(TeacherAvailability(school_id=user.school_id, **slot))


def prepare_section(db: Session, user: User, values: dict[str, Any]) -> None:
    if values.get("school_year_id") is None:
        year = active_school_year(db, user.school_id)
        if year is None:
            raise _unprocessable("Create a school year before adding sections.")
        values["school_year_id"] = year.id


routers = [
    make_crud("tracks", Track, TrackIn, TrackOut, entity="track", order_by=(Track.code,)),
    make_crud(
        "strands", Strand, StrandIn, StrandOut, entity="strand", order_by=(Strand.code,), filters=("track_id",)
    ),
    make_crud("subjects", Subject, SubjectIn, SubjectOut, entity="subject", order_by=(Subject.type, Subject.code)),
    make_crud(
        "curriculum",
        CurriculumEntry,
        CurriculumEntryIn,
        CurriculumEntryOut,
        entity="curriculum_entry",
        order_by=(CurriculumEntry.strand_id, CurriculumEntry.grade_level, CurriculumEntry.semester_number),
        filters=("strand_id", "grade_level", "semester_number"),
    ),
    make_crud("rooms", Room, RoomIn, RoomOut, entity="room", order_by=(Room.code,)),
    make_crud(
        "teachers",
        Teacher,
        TeacherIn,
        TeacherOut,
        entity="teacher",
        order_by=(Teacher.full_name,),
        prepare=prepare_teacher,
        apply=apply_teacher,
    ),
    make_crud(
        "sections",
        Section,
        SectionIn,
        SectionOut,
        entity="section",
        order_by=(Section.grade_level, Section.name),
        filters=("school_year_id", "strand_id", "shift_id"),
        prepare=prepare_section,
    ),
]
