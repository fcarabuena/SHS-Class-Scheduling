"""Loads one semester of a school from the database into an engine State."""

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DEFAULT_SCHOOL_SETTINGS,
    AvailabilityKind,
    CurriculumEntry,
    Period,
    Room,
    ScheduleEntry,
    School,
    Section,
    Semester,
    Subject,
    Teacher,
    TeachingAssignment,
)
from . import engine as eng


def to_minutes(value: dt.time) -> int:
    return value.hour * 60 + value.minute


def _hours(minutes: int) -> float:
    return round(minutes / 60, 2)


def load_state(db: Session, school_id: int, semester: Semester) -> eng.State:
    def rows(model: type, *where: Any) -> list:
        return list(db.scalars(select(model).where(model.school_id == school_id, *where)))

    school = db.get(School, school_id)
    days = sorted((school.settings or {}).get("school_days") or DEFAULT_SCHOOL_SETTINGS["school_days"])

    slots = {
        p.id: eng.Slot(p.id, p.shift_id, p.name, to_minutes(p.start_time), to_minutes(p.end_time))
        for p in rows(Period, Period.is_break.is_(False))
    }
    teachers = {
        t.id: eng.TeacherInfo(
            id=t.id,
            name=t.full_name,
            max_daily_minutes=round(float(t.max_daily_hours) * 60),
            max_weekly_minutes=round(float(t.max_weekly_hours) * 60),
            qualified=frozenset(s.id for s in t.subjects),
            unavailable=frozenset(
                (a.day_of_week, a.period_id) for a in t.availability if a.kind == AvailabilityKind.unavailable
            ),
            preferred=frozenset(
                (a.day_of_week, a.period_id) for a in t.availability if a.kind == AvailabilityKind.preferred
            ),
        )
        for t in rows(Teacher)
    }
    rooms = {r.id: eng.RoomInfo(r.id, r.name, r.type.value, r.capacity) for r in rows(Room)}
    section_rows = rows(Section, Section.school_year_id == semester.school_year_id)
    sections = {s.id: eng.SectionInfo(s.id, s.name, s.shift_id, s.student_count) for s in section_rows}
    subject_rows = rows(Subject)
    subjects = {s.id: eng.SubjectInfo(s.id, s.code, s.name, s.required_room_type.value, s.is_heavy) for s in subject_rows}

    # Weekly hours: the curriculum row may override the subject's default.
    default_hours = {s.id: float(s.hours_per_week) for s in subject_rows}
    overrides = {
        (c.strand_id, c.grade_level, c.subject_id): float(c.hours_per_week)
        for c in rows(CurriculumEntry, CurriculumEntry.semester_number == semester.number)
        if c.hours_per_week is not None
    }
    section_by_id = {s.id: s for s in section_rows}
    requirements = []
    for a in rows(TeachingAssignment, TeachingAssignment.semester_id == semester.id):
        section = section_by_id.get(a.section_id)
        if section is None:
            continue
        hours = overrides.get((section.strand_id, section.grade_level, a.subject_id), default_hours.get(a.subject_id, 0))
        requirements.append(
            eng.Requirement(a.section_id, a.subject_id, round(hours * 60), a.teacher_id, a.combined_group_id, a.id)
        )
    requirements.sort(key=lambda r: r.id)

    entries = [
        eng.Entry(
            id=e.id,
            section_id=e.section_id,
            subject_id=e.subject_id,
            day=e.day_of_week,
            period_id=e.period_id,
            teacher_id=e.teacher_id,
            room_id=e.room_id,
            pinned=e.pinned,
            group=e.combined_group_id,
        )
        for e in rows(ScheduleEntry, ScheduleEntry.semester_id == semester.id)
    ]
    entries.sort(key=lambda e: e.id)
    return eng.State(days, slots, teachers, rooms, sections, subjects, requirements, entries)


def conflict_json(conflict: eng.Conflict) -> dict[str, Any]:
    return {
        "key": conflict.key,
        "code": conflict.code,
        "severity": conflict.severity,
        "message": conflict.message,
        "entry_ids": list(conflict.entry_ids),
        "teacher_id": conflict.teacher_id,
        "room_id": conflict.room_id,
        "section_id": conflict.section_id,
        "subject_id": conflict.subject_id,
        "day_of_week": conflict.day,
    }


def overview(state: eng.State, semester: Semester) -> dict[str, Any]:
    """Everything the loading and timetable screens need, in one response."""
    conflicts = eng.detect(state)
    totals = eng.scheduled_minutes(state)
    return {
        "semester_id": semester.id,
        "semester_number": semester.number,
        "school_year_id": semester.school_year_id,
        "days": state.days,
        "assignments": [
            {
                "id": r.id,
                "section_id": r.section_id,
                "subject_id": r.subject_id,
                "teacher_id": r.teacher_id,
                "combined_group_id": r.group,
                "required_hours": _hours(r.minutes),
                "scheduled_hours": _hours(totals.get((r.section_id, r.subject_id), 0)),
            }
            for r in state.requirements
        ],
        "entries": [
            {
                "id": e.id,
                "section_id": e.section_id,
                "subject_id": e.subject_id,
                "teacher_id": e.teacher_id,
                "room_id": e.room_id,
                "day_of_week": e.day,
                "period_id": e.period_id,
                "pinned": e.pinned,
                "combined_group_id": e.group,
            }
            for e in state.entries
        ],
        "conflicts": [conflict_json(c) for c in conflicts],
        "teacher_loads": [
            {
                "teacher_id": load.teacher_id,
                "assigned_hours": _hours(load.assigned_minutes),
                "scheduled_hours": _hours(load.scheduled_minutes),
                "max_daily_hours": _hours(load.max_daily_minutes),
                "max_weekly_hours": _hours(load.max_weekly_minutes),
                "capacity_hours": _hours(load.capacity_minutes),
                "status": load.status,
                "issues": list(load.issues),
            }
            for load in eng.teacher_loads(state)
        ],
        "summary": {
            "errors": sum(c.severity == eng.ERROR for c in conflicts),
            "incomplete": sum(c.severity == eng.INCOMPLETE for c in conflicts),
        },
    }


def pick_room(state: eng.State, section_ids: list[int], subject_id: int, day: int, period_id: int) -> int | None:
    """A free room of the right type and size, preferring one the section already uses."""
    subject, slot = state.subjects.get(subject_id), state.slots.get(period_id)
    if subject is None or slot is None:
        return None
    students = sum(state.sections[s].student_count for s in section_ids if s in state.sections)
    taken = {
        e.room_id
        for e in state.entries
        if e.day == day and e.period_id in state.slots and eng._overlap(slot, state.slots[e.period_id])
    }
    usage: dict[int, int] = {}
    for e in state.entries:
        if e.section_id in section_ids and e.room_id is not None:
            usage[e.room_id] = usage.get(e.room_id, 0) + 1
    candidates = [
        r for r in state.rooms.values() if r.type == subject.room_type and r.capacity >= students and r.id not in taken
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (-usage.get(r.id, 0), r.capacity, r.name)).id
