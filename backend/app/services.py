"""Helpers shared by the routers: tenancy checks, audit logging, commits."""

from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from psycopg import errors as pg_errors
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuditLog, Base, SchoolYear, User

_TABLE_TO_MODEL = {m.class_.__table__.name: m.class_ for m in Base.registry.mappers}

# Never written to the audit log.
_SENSITIVE_KEYS = {"password", "password_hash"}


def audit(db: Session, user: User, action: str, entity_type: str, entity_id: int | None, changes: Any = None) -> None:
    """Adds an audit row to the current transaction (committed with the change)."""
    if isinstance(changes, dict):
        changes = {k: v for k, v in changes.items() if k not in _SENSITIVE_KEYS}
    db.add(
        AuditLog(
            school_id=user.school_id,
            user_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=jsonable_encoder(changes) if changes is not None else None,
        )
    )


def integrity_message(exc: IntegrityError) -> str:
    orig = exc.orig
    if isinstance(orig, pg_errors.UniqueViolation):
        return "A record with the same code or name already exists."
    if isinstance(orig, pg_errors.ForeignKeyViolation):
        return "This record is still used by other records, so it cannot be removed or changed this way."
    if isinstance(orig, pg_errors.CheckViolation):
        return "One of the values is outside the allowed range."
    return "The change conflicts with existing data."


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, integrity_message(exc)) from None


def get_owned(db: Session, model: type, item_id: int, school_id: int):
    """Loads a row only if it belongs to the given school, otherwise 404."""
    obj = db.get(model, item_id)
    if obj is None or obj.school_id != school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return obj


def check_references(db: Session, model: type, values: dict[str, Any], school_id: int) -> None:
    """Rejects foreign keys that point at another school's rows (or nothing)."""
    for column in model.__table__.columns:
        value = values.get(column.name)
        if value is None:
            continue
        for fk in column.foreign_keys:
            target = _TABLE_TO_MODEL.get(fk.column.table.name)
            if target is None or fk.column.table.name == "schools":
                continue
            obj = db.get(target, value)
            if obj is None or obj.school_id != school_id:
                raise HTTPException(
                    422, f"{column.name}: record {value} does not exist"
                )


def active_school_year(db: Session, school_id: int) -> SchoolYear | None:
    return db.scalars(
        select(SchoolYear)
        .where(SchoolYear.school_id == school_id, SchoolYear.is_active)
        .order_by(SchoolYear.start_date.desc())
    ).first()
