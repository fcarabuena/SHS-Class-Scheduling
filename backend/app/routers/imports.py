"""CSV / Excel bulk import for strands, subjects, sections, teachers and rooms.

Rows are matched to existing records by their natural key (code, employee ID
or section name) and updated; new keys are created. Each row is validated
with the same schema as the regular API, and bad rows are reported with
their row number without blocking the good ones.
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import Response
from openpyxl import load_workbook
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import DbSession, EditorUser
from ..models import Room, Section, Shift, Strand, Subject, Teacher, Track, User
from ..schemas import ImportResult, ImportRowError, RoomIn, SectionIn, StrandIn, SubjectIn, TeacherIn
from ..services import active_school_year, audit, integrity_message
from .crud import apply_teacher, prepare_section, prepare_teacher, save

router = APIRouter(prefix="/api/import", tags=["import"])

Row = dict[str, str]


class RowError(Exception):
    pass


def _lookup(db: Session, user: User, model: type, column: str, value: str, label: str) -> int:
    obj_id = db.scalar(
        select(model.id).where(model.school_id == user.school_id, func.lower(getattr(model, column)) == value.lower())
    )
    if obj_id is None:
        raise RowError(f"{label} '{value}' was not found")
    return obj_id


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _enum_value(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


# --- per-resource row converters (file columns -> API schema fields) ---------


def _strand_row(db: Session, user: User, row: Row) -> dict[str, Any]:
    return {
        "track_id": _lookup(db, user, Track, "code", row["track_code"], "Track"),
        "code": row["code"],
        "name": row["name"],
    }


def _subject_row(db: Session, user: User, row: Row) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "type": _enum_value(row["type"]),
        "hours_per_week": row["hours_per_week"],
        "required_room_type": _enum_value(row.get("required_room_type") or "lecture"),
        "is_heavy": _bool(row.get("is_heavy", "")),
    }


def _room_row(db: Session, user: User, row: Row) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row.get("name") or row["code"],
        "type": _enum_value(row.get("type") or "lecture"),
        "capacity": row["capacity"],
    }


def _teacher_row(db: Session, user: User, row: Row) -> dict[str, Any]:
    codes = [c.strip() for c in (row.get("qualified_subjects") or "").replace(",", ";").split(";") if c.strip()]
    return {
        "employee_id": row["employee_id"],
        "full_name": row["full_name"],
        "max_daily_hours": row.get("max_daily_hours") or None,
        "max_weekly_hours": row.get("max_weekly_hours") or None,
        "qualified_subject_ids": [_lookup(db, user, Subject, "code", c, "Subject") for c in codes],
    }


def _section_row(db: Session, user: User, row: Row) -> dict[str, Any]:
    adviser = row.get("adviser_employee_id")
    return {
        "name": row["name"],
        "strand_id": _lookup(db, user, Strand, "code", row["strand_code"], "Strand"),
        "grade_level": int(row["grade_level"]) if row["grade_level"].isdigit() else row["grade_level"],
        "shift_id": _lookup(db, user, Shift, "name", row["shift_name"], "Shift"),
        "adviser_id": _lookup(db, user, Teacher, "employee_id", adviser, "Teacher") if adviser else None,
        "student_count": row.get("student_count") or 0,
    }


@dataclass(frozen=True)
class ImportSpec:
    model: type
    schema: type[BaseModel]
    entity: str
    key: str  # natural key used to match existing rows
    required: tuple[str, ...]
    optional: tuple[str, ...]
    example: tuple[str, ...]
    convert: Callable[[Session, User, Row], dict[str, Any]]
    prepare: Callable | None = None
    apply: Callable | None = None

    @property
    def columns(self) -> tuple[str, ...]:
        return self.required + self.optional


SPECS: dict[str, ImportSpec] = {
    "strands": ImportSpec(
        Strand, StrandIn, "strand", "code",
        ("track_code", "code", "name"), (),
        ("ACAD", "STEM", "Science, Technology, Engineering and Mathematics"),
        _strand_row,
    ),
    "subjects": ImportSpec(
        Subject, SubjectIn, "subject", "code",
        ("code", "name", "type", "hours_per_week"), ("required_room_type", "is_heavy"),
        ("CORE-GENMATH", "General Mathematics", "core", "4", "lecture", "yes"),
        _subject_row,
    ),
    "rooms": ImportSpec(
        Room, RoomIn, "room", "code",
        ("code", "capacity"), ("name", "type"),
        ("R101", "45", "Room 101", "lecture"),
        _room_row,
    ),
    "teachers": ImportSpec(
        Teacher, TeacherIn, "teacher", "employee_id",
        ("employee_id", "full_name"), ("max_daily_hours", "max_weekly_hours", "qualified_subjects"),
        ("T-0001", "Sample Teacher", "6", "30", "CORE-GENMATH;CORE-STAT"),
        _teacher_row, prepare_teacher, apply_teacher,
    ),
    "sections": ImportSpec(
        Section, SectionIn, "section", "name",
        ("name", "strand_code", "grade_level", "shift_name"), ("adviser_employee_id", "student_count"),
        ("11-STEM-A", "STEM", "11", "Morning", "T-0001", "40"),
        _section_row, prepare_section,
    ),
}


def _spec(resource: str) -> ImportSpec:
    if resource not in SPECS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown import type")
    return SPECS[resource]


# --- file parsing -----------------------------------------------------------


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_table(filename: str, content: bytes) -> list[list[str]]:
    """Returns the rows of a CSV or XLSX file as lists of trimmed strings."""
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The Excel file could not be read.") from None
        sheet = workbook.worksheets[0]
        rows = [[_cell(c) for c in row] for row in sheet.iter_rows(values_only=True)]
        workbook.close()
        return rows
    if name.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252", errors="replace")
        return [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text))]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload a .csv or .xlsx file.")


def _error_text(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "row"
        parts.append(f"{field}: {err['msg'].removeprefix('Value error, ')}")
    return "; ".join(parts)


def run_import(db: Session, user: User, spec: ImportSpec, table: list[list[str]], dry_run: bool) -> ImportResult:
    table = [row for row in table if any(row)]
    if not table:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")
    header = [h.lower().replace(" ", "_") for h in table[0]]
    if missing := [c for c in spec.required if c not in header]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Missing column(s): {', '.join(missing)}. Expected columns: {', '.join(spec.columns)}.",
        )
    if len(table) - 1 > settings.max_import_rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {settings.max_import_rows} rows per file.")

    created = updated = 0
    errors: list[ImportRowError] = []
    seen: set[str] = set()

    for number, cells in enumerate(table[1:], start=2):  # row 1 is the header
        row = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header) if h in spec.columns}
        try:
            if blank := [c for c in spec.required if not row.get(c)]:
                raise RowError(f"missing value for {', '.join(blank)}")
            key = row[spec.key].lower()
            if key in seen:
                raise RowError(f"duplicate {spec.key} '{row[spec.key]}' in this file")
            with db.begin_nested():  # a bad row rolls back only itself
                values = spec.schema.model_validate(spec.convert(db, user, row)).model_dump()
                query = select(spec.model).where(
                    spec.model.school_id == user.school_id, func.lower(getattr(spec.model, spec.key)) == key
                )
                if spec.model is Section:
                    year = active_school_year(db, user.school_id)
                    query = query.where(Section.school_year_id == (year.id if year else None))
                existing = db.scalars(query).first()
                if existing is not None:
                    # Matching is case-insensitive; keep the stored spelling of the key.
                    values[spec.key] = getattr(existing, spec.key)
                if existing is not None and spec.model is Teacher and "qualified_subjects" not in header:
                    # Column absent: keep the teacher's current qualifications.
                    values["qualified_subject_ids"] = existing.qualified_subject_ids
                if existing is not None and spec.model is Teacher:
                    values["availability"] = [
                        {"day_of_week": a.day_of_week, "period_id": a.period_id, "kind": a.kind}
                        for a in existing.availability
                    ]
                kwargs = {"prepare": spec.prepare}
                if spec.apply:
                    kwargs["apply"] = spec.apply
                save(db, user, spec.model, spec.entity, values, obj=existing, **kwargs)
            seen.add(key)
            if existing is None:
                created += 1
            else:
                updated += 1
        except RowError as exc:
            errors.append(ImportRowError(row=number, message=str(exc)))
        except ValidationError as exc:
            errors.append(ImportRowError(row=number, message=_error_text(exc)))
        except HTTPException as exc:
            errors.append(ImportRowError(row=number, message=str(exc.detail)))
        except IntegrityError as exc:
            errors.append(ImportRowError(row=number, message=integrity_message(exc)))

    if dry_run:
        db.rollback()
    else:
        audit(db, user, "import", spec.entity, None, {"created": created, "updated": updated, "errors": len(errors)})
        db.commit()
    return ImportResult(dry_run=dry_run, created=created, updated=updated, errors=errors)


# --- endpoints --------------------------------------------------------------


@router.get("/{resource}/template")
def download_template(resource: str, user: EditorUser):
    spec = _spec(resource)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(spec.columns)
    writer.writerow(spec.example)
    return Response(
        "﻿" + buffer.getvalue(),  # BOM so Excel opens it as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{resource}-template.csv"'},
    )


@router.post("/{resource}", response_model=ImportResult)
async def import_file(resource: str, file: UploadFile, db: DbSession, user: EditorUser, dry_run: bool = False):
    spec = _spec(resource)
    content = await file.read(settings.max_import_bytes + 1)
    if len(content) > settings.max_import_bytes:
        raise HTTPException(413, "The file is too large (limit 2 MB).")
    return run_import(db, user, spec, parse_table(file.filename or "", content), dry_run)
