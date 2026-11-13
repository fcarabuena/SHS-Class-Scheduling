"""Teacher loading (assignments) and the weekly timetable (schedule entries).

Every change returns the fresh overview (entries, conflicts, loads), so the
screens stay in step with the server after each edit.
"""

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import CurrentUser, DbSession, EditorUser
from ..models import (
    CurriculumEntry,
    Period,
    Room,
    ScheduleEntry,
    SchoolYear,
    Section,
    Semester,
    SolverJob,
    Subject,
    Teacher,
    TeachingAssignment,
    User,
)
from ..scheduling import engine as eng
from ..scheduling import export, jobs
from ..scheduling.state import conflict_json, load_state, overview, pick_room
from ..notify import notify_teacher, notify_users, users_of_teacher
from ..services import audit, check_references, commit, get_owned

router = APIRouter(prefix="/api", tags=["schedule"])


# --- request bodies ---------------------------------------------------------


class AssignmentIn(BaseModel):
    semester_id: int
    section_id: int
    subject_id: int
    teacher_id: int | None = None


class AssignmentUpdate(BaseModel):
    teacher_id: int | None


class SemesterRef(BaseModel):
    semester_id: int | None = None


class CombineIn(BaseModel):
    assignment_ids: list[int] = Field(min_length=2, max_length=10)


class EntryCreate(BaseModel):
    assignment_id: int
    day_of_week: int = Field(ge=1, le=6)
    period_id: int
    # Omit to let the server pick a free room of the right type and size.
    room_id: int | None = None


class EntryUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=1, le=6)
    period_id: int | None = None
    room_id: int | None = None
    pinned: bool | None = None
    remarks: str | None = Field(default=None, max_length=120)


class SolveIn(BaseModel):
    semester_id: int | None = None
    # "rebuild" keeps pinned classes and re-places the rest; "fill" keeps everything already placed.
    mode: str = Field(default="rebuild", pattern="^(rebuild|fill)$")
    time_limit: int = Field(default=30, ge=5, le=300)


class CheckIn(BaseModel):
    entry_id: int | None = None
    assignment_id: int | None = None


# --- helpers ----------------------------------------------------------------


def _conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(422, message)


def get_semester(db: Session, school_id: int, semester_id: int | None) -> Semester:
    """The requested semester, or the active semester of the active school year."""
    if semester_id is not None:
        return get_owned(db, Semester, semester_id, school_id)
    semester = db.scalars(
        select(Semester)
        .join(SchoolYear, SchoolYear.id == Semester.school_year_id)
        .where(Semester.school_id == school_id)
        .order_by(SchoolYear.is_active.desc(), Semester.is_active.desc(), SchoolYear.start_date.desc(), Semester.number)
    ).first()
    if semester is None:
        raise _unprocessable("Create a school year first.")
    return semester


def _respond(db: Session, user: User, semester: Semester, **extra: Any) -> dict[str, Any]:
    return {**overview(load_state(db, user.school_id, semester), semester), **extra}


class Names:
    """Readable labels for the audit log."""

    def __init__(self, db: Session):
        self.db = db

    def _get(self, model: type, item_id: int | None, attr: str) -> str:
        obj = self.db.get(model, item_id) if item_id is not None else None
        return getattr(obj, attr) if obj else "none"

    def section(self, item_id: int | None) -> str:
        return self._get(Section, item_id, "name")

    def subject(self, item_id: int | None) -> str:
        return self._get(Subject, item_id, "code")

    def teacher(self, item_id: int | None) -> str:
        return self._get(Teacher, item_id, "full_name")

    def room(self, item_id: int | None) -> str:
        return self._get(Room, item_id, "name")

    def slot(self, day: int, period_id: int) -> str:
        return f"{eng.DAY_NAMES.get(day, day)[:3]} {self._get(Period, period_id, 'name')}"

    def klass(self, row: TeachingAssignment | ScheduleEntry) -> str:
        return f"{self.section(row.section_id)} · {self.subject(row.subject_id)}"


def _group_of(db: Session, assignment: TeachingAssignment) -> list[TeachingAssignment]:
    if assignment.combined_group_id is None:
        return [assignment]
    return list(
        db.scalars(
            select(TeachingAssignment)
            .where(
                TeachingAssignment.school_id == assignment.school_id,
                TeachingAssignment.semester_id == assignment.semester_id,
                TeachingAssignment.combined_group_id == assignment.combined_group_id,
            )
            .order_by(TeachingAssignment.id)
        )
    )


def _entries_of(db: Session, assignment: TeachingAssignment) -> list[ScheduleEntry]:
    return list(
        db.scalars(
            select(ScheduleEntry).where(
                ScheduleEntry.school_id == assignment.school_id,
                ScheduleEntry.semester_id == assignment.semester_id,
                ScheduleEntry.section_id == assignment.section_id,
                ScheduleEntry.subject_id == assignment.subject_id,
            )
        )
    )


def _siblings(db: Session, entry: ScheduleEntry) -> list[ScheduleEntry]:
    """The entry plus the other sections' rows of the same combined class meeting."""
    if entry.combined_group_id is None:
        return [entry]
    return list(
        db.scalars(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.school_id == entry.school_id,
                ScheduleEntry.semester_id == entry.semester_id,
                ScheduleEntry.combined_group_id == entry.combined_group_id,
                ScheduleEntry.day_of_week == entry.day_of_week,
                ScheduleEntry.period_id == entry.period_id,
            )
            .order_by(ScheduleEntry.id)
        )
    )


def _check_slot(state: eng.State, section_ids: list[int], day: int, period_id: int) -> None:
    if day not in state.days:
        raise _unprocessable("That day is not a school day.")
    slot = state.slots.get(period_id)
    if slot is None:
        raise _unprocessable("That period does not exist or is a break.")
    for section_id in section_ids:
        section = state.sections.get(section_id)
        if section is None or section.shift_id != slot.shift_id:
            raise _unprocessable("That period belongs to a different shift than the section.")


def _engine_entry(state: eng.State, entry_id: int) -> eng.Entry:
    return next(e for e in state.entries if e.id == entry_id)


# --- overview ---------------------------------------------------------------


@router.get("/schedule")
def get_schedule(db: DbSession, user: CurrentUser, semester_id: int | None = None):
    """Assignments, timetable entries, conflicts and teacher loads for a semester."""
    return _respond(db, user, get_semester(db, user.school_id, semester_id))


# --- teacher loading --------------------------------------------------------


@router.post("/assignments", status_code=201)
def create_assignment(data: AssignmentIn, db: DbSession, user: EditorUser):
    values = data.model_dump()
    check_references(db, TeachingAssignment, values, user.school_id)
    semester = db.get(Semester, data.semester_id)
    if db.get(Section, data.section_id).school_year_id != semester.school_year_id:
        raise _unprocessable("The section belongs to a different school year than the semester.")
    assignment = TeachingAssignment(school_id=user.school_id, **values)
    db.add(assignment)
    db.flush()
    audit(db, user, "create", "assignment", assignment.id, {**values, "summary": _assignment_summary(db, assignment)})
    commit(db)
    return _respond(db, user, semester)


def _assignment_summary(db: Session, assignment: TeachingAssignment) -> str:
    names = Names(db)
    return f"{names.klass(assignment)}: teacher {names.teacher(assignment.teacher_id)}"


@router.put("/assignments/{assignment_id}")
def update_assignment(assignment_id: int, data: AssignmentUpdate, db: DbSession, user: EditorUser):
    """Sets the teacher. Scheduled classes (and combined sections) follow."""
    assignment = get_owned(db, TeachingAssignment, assignment_id, user.school_id)
    if data.teacher_id is not None:
        get_owned(db, Teacher, data.teacher_id, user.school_id)
    names = Names(db)
    before = names.teacher(assignment.teacher_id)
    if assignment.teacher_id != data.teacher_id:
        label = names.klass(assignment)
        notify_teacher(db, user.school_id, data.teacher_id, "loading", "You were given a class", f"{label} is now yours.", "/timetable", user.id)
        notify_teacher(
            db, user.school_id, assignment.teacher_id, "loading", "A class was taken off your load", f"{label} is no longer yours.", "/timetable", user.id
        )
    for member in _group_of(db, assignment):
        member.teacher_id = data.teacher_id
        for entry in _entries_of(db, member):
            entry.teacher_id = data.teacher_id
    audit(
        db,
        user,
        "update",
        "assignment",
        assignment.id,
        {"teacher_id": data.teacher_id, "summary": f"{names.klass(assignment)}: teacher {before} → {names.teacher(data.teacher_id)}"},
    )
    commit(db)
    return _respond(db, user, db.get(Semester, assignment.semester_id))


def _dissolve_if_alone(db: Session, assignment: TeachingAssignment) -> None:
    """A combined group with one member left is no longer combined."""
    if assignment.combined_group_id is None:
        return
    group = _group_of(db, assignment)
    if len(group) == 1:
        group[0].combined_group_id = None
        for entry in _entries_of(db, group[0]):
            entry.combined_group_id = None


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, db: DbSession, user: EditorUser):
    """Removes a subject from a section, together with its scheduled classes."""
    assignment = get_owned(db, TeachingAssignment, assignment_id, user.school_id)
    semester = db.get(Semester, assignment.semester_id)
    entries = _entries_of(db, assignment)
    summary = f"{Names(db).klass(assignment)} removed with {len(entries)} scheduled class(es)"
    others = [a for a in _group_of(db, assignment) if a.id != assignment.id]
    for entry in entries:
        db.delete(entry)
    db.delete(assignment)
    db.flush()
    if others:
        _dissolve_if_alone(db, others[0])
    audit(db, user, "delete", "assignment", assignment_id, {"summary": summary})
    commit(db)
    return _respond(db, user, semester)


@router.post("/assignments/generate")
def generate_assignments(data: SemesterRef, db: DbSession, user: EditorUser):
    """Adds every subject the curriculum requires for each section this semester."""
    semester = get_semester(db, user.school_id, data.semester_id)
    sections = db.scalars(
        select(Section).where(Section.school_id == user.school_id, Section.school_year_id == semester.school_year_id)
    ).all()
    curriculum = db.scalars(
        select(CurriculumEntry).where(
            CurriculumEntry.school_id == user.school_id, CurriculumEntry.semester_number == semester.number
        )
    ).all()
    existing = {
        (a.section_id, a.subject_id)
        for a in db.scalars(
            select(TeachingAssignment).where(
                TeachingAssignment.school_id == user.school_id, TeachingAssignment.semester_id == semester.id
            )
        )
    }
    created = 0
    for section in sections:
        for row in curriculum:
            if (row.strand_id, row.grade_level) != (section.strand_id, section.grade_level):
                continue
            if (section.id, row.subject_id) in existing:
                continue
            db.add(
                TeachingAssignment(
                    school_id=user.school_id, semester_id=semester.id, section_id=section.id, subject_id=row.subject_id
                )
            )
            existing.add((section.id, row.subject_id))
            created += 1
    audit(db, user, "generate", "assignment", None, {"summary": f"{created} subject(s) added from the curriculum"})
    commit(db)
    return _respond(db, user, semester, created=created)


@router.post("/assignments/auto-assign")
def auto_assign_teachers(data: SemesterRef, db: DbSession, user: EditorUser):
    """Gives every subject without a teacher the least-loaded qualified teacher who still has room."""
    semester = get_semester(db, user.school_id, data.semester_id)
    state = load_state(db, user.school_id, semester)
    active = db.scalars(select(Teacher.id).where(Teacher.school_id == user.school_id, Teacher.is_active.is_(True)))
    picked = eng.suggest_teachers(state, active)
    names = Names(db)
    for assignment_id, teacher_id in picked.items():
        row = db.get(TeachingAssignment, assignment_id)
        row.teacher_id = teacher_id
        for entry in _entries_of(db, row):  # classes already placed without a teacher
            entry.teacher_id = teacher_id
        notify_teacher(db, user.school_id, teacher_id, "loading", "You were given a class", f"{names.klass(row)} is now yours.", "/timetable", user.id)
    left = sum(1 for r in state.requirements if r.teacher_id is None) - len(picked)
    summary = f"Teachers assigned automatically to {len(picked)} subject(s); {left} still without a teacher"
    audit(db, user, "auto_assign", "assignment", None, {"summary": summary})
    commit(db)
    return _respond(db, user, semester, assigned=len(picked), left=left)


@router.post("/assignments/combine")
def combine_assignments(data: CombineIn, db: DbSession, user: EditorUser):
    """Teaches the same subject to several sections together as one class."""
    ids = list(dict.fromkeys(data.assignment_ids))
    picked = [get_owned(db, TeachingAssignment, i, user.school_id) for i in ids]
    # Joining an existing combined class brings its other sections along.
    members = {m.id: m for a in picked for m in _group_of(db, a)}
    group = sorted(members.values(), key=lambda a: a.id)
    if len(group) < 2:
        raise _unprocessable("Choose at least two sections to combine.")
    if len({a.semester_id for a in group}) > 1 or len({a.subject_id for a in group}) > 1:
        raise _unprocessable("Only the same subject in the same semester can be combined.")
    sections = [db.get(Section, a.section_id) for a in group]
    if len({s.shift_id for s in sections}) > 1:
        raise _unprocessable("Sections in different shifts cannot be combined.")
    if any(_entries_of(db, a) for a in group):
        raise _conflict("Remove the classes already on the timetable for these sections before combining them.")
    teacher_id = next((a.teacher_id for a in group if a.teacher_id is not None), None)
    for member in group:
        member.combined_group_id = group[0].id
        member.teacher_id = teacher_id
    names = Names(db)
    summary = f"{names.subject(group[0].subject_id)} combined for " + ", ".join(s.name for s in sections)
    audit(db, user, "combine", "assignment", group[0].id, {"assignment_ids": [a.id for a in group], "summary": summary})
    commit(db)
    return _respond(db, user, db.get(Semester, group[0].semester_id))


@router.post("/assignments/{assignment_id}/separate")
def separate_assignment(assignment_id: int, db: DbSession, user: EditorUser):
    """Takes a section out of a combined class. Its scheduled classes stay where they are."""
    assignment = get_owned(db, TeachingAssignment, assignment_id, user.school_id)
    if assignment.combined_group_id is None:
        raise _unprocessable("This subject is not combined with another section.")
    others = [a for a in _group_of(db, assignment) if a.id != assignment.id]
    assignment.combined_group_id = None
    for entry in _entries_of(db, assignment):
        entry.combined_group_id = None
    db.flush()
    if others:
        # Keep the remaining group id stable even if the leaver gave it its id.
        if others[0].combined_group_id == assignment.id and len(others) > 1:
            for member in others:
                for entry in _entries_of(db, member):
                    entry.combined_group_id = others[0].id
                member.combined_group_id = others[0].id
            db.flush()
        _dissolve_if_alone(db, others[0])
    audit(db, user, "separate", "assignment", assignment.id, {"summary": f"{Names(db).klass(assignment)} separated"})
    commit(db)
    return _respond(db, user, db.get(Semester, assignment.semester_id))


# --- timetable --------------------------------------------------------------


@router.post("/schedule/entries", status_code=201)
def create_entry(data: EntryCreate, db: DbSession, user: EditorUser):
    """Places one class meeting of an assignment (all sections, if combined)."""
    assignment = get_owned(db, TeachingAssignment, data.assignment_id, user.school_id)
    semester = db.get(Semester, assignment.semester_id)
    group = _group_of(db, assignment)
    section_ids = [a.section_id for a in group]
    state = load_state(db, user.school_id, semester)
    _check_slot(state, section_ids, data.day_of_week, data.period_id)
    if not eng.cell_is_free(state, section_ids, data.day_of_week, data.period_id):
        raise _conflict("A class is already scheduled in that slot for this section.")
    if "room_id" in data.model_fields_set and data.room_id is not None:
        room_id = get_owned(db, Room, data.room_id, user.school_id).id
    elif "room_id" in data.model_fields_set:
        room_id = None
    else:
        room_id = pick_room(state, section_ids, assignment.subject_id, data.day_of_week, data.period_id)

    created = []
    for member in group:
        entry = ScheduleEntry(
            school_id=user.school_id,
            semester_id=semester.id,
            section_id=member.section_id,
            subject_id=member.subject_id,
            teacher_id=member.teacher_id,
            room_id=room_id,
            day_of_week=data.day_of_week,
            period_id=data.period_id,
            combined_group_id=member.combined_group_id,
        )
        db.add(entry)
        created.append(entry)
    db.flush()
    names = Names(db)
    for entry in created:
        summary = f"{names.klass(entry)} placed on {names.slot(entry.day_of_week, entry.period_id)} in {names.room(room_id)}"
        audit(db, user, "create", "schedule_entry", entry.id, {"summary": summary, **_entry_values(entry)})
    _tell_teacher(db, user, created[0].teacher_id, summary)
    commit(db)
    return _respond(db, user, semester, entry_id=created[0].id)


def _tell_teacher(db: Session, user: User, teacher_id: int | None, what: str) -> None:
    """Lets the teacher's own account know their timetable changed (repeats are folded into one message)."""
    notify_teacher(db, user.school_id, teacher_id, "timetable", "Your timetable changed", what, "/timetable", user.id)


def _entry_values(entry: ScheduleEntry) -> dict[str, Any]:
    return {
        "section_id": entry.section_id,
        "subject_id": entry.subject_id,
        "teacher_id": entry.teacher_id,
        "room_id": entry.room_id,
        "day_of_week": entry.day_of_week,
        "period_id": entry.period_id,
        "pinned": entry.pinned,
        "remarks": entry.remarks,
    }


def _swap_partner(db: Session, moving: list[ScheduleEntry], day: int, period_id: int) -> ScheduleEntry | None:
    """Who is in the target slot. Raises if the slot cannot be taken or swapped."""
    occupants = list(
        db.scalars(
            select(ScheduleEntry).where(
                ScheduleEntry.semester_id == moving[0].semester_id,
                ScheduleEntry.section_id.in_([e.section_id for e in moving]),
                ScheduleEntry.day_of_week == day,
                ScheduleEntry.period_id == period_id,
                ScheduleEntry.id.notin_([e.id for e in moving]),
            )
        )
    )
    if not occupants:
        return None
    if len(moving) > 1 or occupants[0].combined_group_id is not None:
        raise _conflict("That slot is taken. Combined classes cannot be swapped; move the other class first.")
    if occupants[0].pinned:
        raise _conflict("That slot holds a pinned class. Unpin it before swapping.")
    return occupants[0]


@router.put("/schedule/entries/{entry_id}")
def update_entry(entry_id: int, data: EntryUpdate, db: DbSession, user: EditorUser):
    """Moves a class (swapping with whatever is in the target slot), or changes its room or pin."""
    entry = get_owned(db, ScheduleEntry, entry_id, user.school_id)
    semester = db.get(Semester, entry.semester_id)
    moving = _siblings(db, entry)
    fields = data.model_fields_set
    names = Names(db)
    changes: list[str] = []

    new_day = data.day_of_week if data.day_of_week is not None else entry.day_of_week
    new_period = data.period_id if data.period_id is not None else entry.period_id
    is_move = (new_day, new_period) != (entry.day_of_week, entry.period_id)
    room_change = "room_id" in fields and data.room_id != entry.room_id
    still_pinned = entry.pinned and data.pinned is not False
    if still_pinned and (is_move or room_change):
        raise _conflict("This class is pinned. Unpin it before changing it.")

    if data.pinned is not None and data.pinned != entry.pinned:
        for row in moving:
            row.pinned = data.pinned
        changes.append("pinned" if data.pinned else "unpinned")

    if "remarks" in fields:
        text = (data.remarks or "").strip() or None
        if text != entry.remarks:
            for row in moving:
                row.remarks = text
            changes.append(f"remarks: {text}" if text else "remarks cleared")

    if room_change:
        if data.room_id is not None:
            get_owned(db, Room, data.room_id, user.school_id)
        changes.append(f"room {names.room(entry.room_id)} → {names.room(data.room_id)}")
        for row in moving:
            row.room_id = data.room_id

    if is_move:
        state = load_state(db, user.school_id, semester)
        _check_slot(state, [e.section_id for e in moving], new_day, new_period)
        partner = _swap_partner(db, moving, new_day, new_period)
        old = (entry.day_of_week, entry.period_id)
        changes.append(f"{names.slot(*old)} → {names.slot(new_day, new_period)}")
        if partner is not None:
            partner.day_of_week, partner.period_id = old
            changes.append(f"swapped with {names.subject(partner.subject_id)}")
            audit(
                db,
                user,
                "move",
                "schedule_entry",
                partner.id,
                {"summary": f"{names.klass(partner)}: {names.slot(new_day, new_period)} → {names.slot(*old)} (swap)", **_entry_values(partner)},
            )
        for row in moving:
            row.day_of_week, row.period_id = new_day, new_period

    if changes:
        action = "move" if is_move else "update"
        for row in moving:
            summary = f"{names.klass(row)}: {', '.join(changes)}"
            audit(db, user, action, "schedule_entry", row.id, {"summary": summary, **_entry_values(row)})
        if is_move or room_change:
            _tell_teacher(db, user, entry.teacher_id, summary)
            if is_move and partner is not None:
                _tell_teacher(db, user, partner.teacher_id, f"{names.klass(partner)} moved to {names.slot(*old)}")
    commit(db)
    return _respond(db, user, semester)


@router.delete("/schedule/entries/{entry_id}")
def delete_entry(entry_id: int, db: DbSession, user: EditorUser):
    entry = get_owned(db, ScheduleEntry, entry_id, user.school_id)
    if entry.pinned:
        raise _conflict("This class is pinned. Unpin it before removing it.")
    semester = db.get(Semester, entry.semester_id)
    names = Names(db)
    for row in _siblings(db, entry):
        summary = f"{names.klass(row)} removed from {names.slot(row.day_of_week, row.period_id)}"
        audit(db, user, "delete", "schedule_entry", row.id, {"summary": summary, **_entry_values(row)})
        db.delete(row)
    _tell_teacher(db, user, entry.teacher_id, summary)
    commit(db)
    return _respond(db, user, semester)


@router.delete("/schedule")
def clear_schedule(db: DbSession, user: EditorUser, semester_id: int | None = None, section_id: int | None = None):
    """Removes every unpinned class of a semester (optionally of one section)."""
    semester = get_semester(db, user.school_id, semester_id)
    query = select(ScheduleEntry).where(
        ScheduleEntry.school_id == user.school_id, ScheduleEntry.semester_id == semester.id, ScheduleEntry.pinned.is_(False)
    )
    if section_id is not None:
        query = query.where(ScheduleEntry.section_id == section_id)
    rows = db.scalars(query).all()
    for row in rows:
        db.delete(row)
    scope = f" for {Names(db).section(section_id)}" if section_id is not None else ""
    audit(db, user, "clear", "schedule_entry", None, {"summary": f"{len(rows)} unpinned class(es) removed{scope}"})
    commit(db)
    return _respond(db, user, semester, removed=len(rows))


# --- real-time checks and suggested fixes -----------------------------------


@router.post("/schedule/check")
def check_slots(data: CheckIn, db: DbSession, user: CurrentUser):
    """For a class being dragged: what each slot of the week would lead to.

    Give ``entry_id`` to move an existing class or ``assignment_id`` to place
    a new one. Nothing is saved.
    """
    if (data.entry_id is None) == (data.assignment_id is None):
        raise _unprocessable("Give either entry_id or assignment_id.")

    if data.entry_id is not None:
        row = get_owned(db, ScheduleEntry, data.entry_id, user.school_id)
        semester = db.get(Semester, row.semester_id)
        state = load_state(db, user.school_id, semester)
        moving = eng.siblings(state, _engine_entry(state, row.id))
        relevant: set[str] | None = eng.SLOT_CODES
    else:
        assignment = get_owned(db, TeachingAssignment, data.assignment_id, user.school_id)
        semester = db.get(Semester, assignment.semester_id)
        state = load_state(db, user.school_id, semester)
        # Not saved yet: negative ids keep the trial entries apart from real ones.
        moving = [
            eng.Entry(-index, a.section_id, a.subject_id, 0, 0, a.teacher_id, None, False, a.combined_group_id)
            for index, a in enumerate(_group_of(db, assignment), start=1)
        ]
        relevant = None

    ids = [e.id for e in moving]
    section_ids = [e.section_id for e in moving]
    shift_id = state.sections[section_ids[0]].shift_id
    current = (moving[0].day, moving[0].period_id)
    pinned = any(e.pinned for e in moving)
    cells = []
    for day in state.days:
        for slot in state.slots.values():
            if slot.shift_id != shift_id:
                continue
            cell: dict[str, Any] = {"day_of_week": day, "period_id": slot.id, "status": "ok", "swap": False, "messages": []}
            cells.append(cell)
            if (day, slot.id) == current:
                cell["status"] = "current"
                continue
            if pinned:
                cell.update(status="blocked", messages=["This class is pinned."])
                continue
            changed = [replace(e, day=day, period_id=slot.id) for e in moving]
            occupants = [
                e for e in state.entries if e.section_id in section_ids and (e.day, e.period_id) == (day, slot.id) and e.id not in ids
            ]
            if occupants:
                swappable = (
                    data.entry_id is not None
                    and len(moving) == 1
                    and len(occupants) == 1
                    and not occupants[0].pinned
                    and occupants[0].group is None
                )
                if not swappable:
                    cell.update(status="blocked", messages=["Another class is already in this slot."])
                    continue
                cell["swap"] = True
                changed.append(replace(occupants[0], day=current[0], period_id=current[1]))
            after = eng.for_entries(eng.errors(eng.detect(state.replacing(changed))), [e.id for e in changed])
            found = [c for c in after if relevant is None or c.code in relevant]
            if found:
                cell.update(status="conflict", messages=list(dict.fromkeys(c.message for c in found)))
    return {"cells": cells}


@router.get("/schedule/entries/{entry_id}/suggestions")
def entry_suggestions(entry_id: int, db: DbSession, user: CurrentUser):
    """Conflicts of one class and the changes that would clear them."""
    row = get_owned(db, ScheduleEntry, entry_id, user.school_id)
    state = load_state(db, user.school_id, db.get(Semester, row.semester_id))
    ids = [e.id for e in eng.siblings(state, _engine_entry(state, row.id))]
    return {
        "conflicts": [conflict_json(c) for c in eng.for_entries(eng.detect(state), ids)],
        "fixes": [
            {
                "kind": fix.kind,
                "label": fix.label,
                "day_of_week": fix.day,
                "period_id": fix.period_id,
                "room_id": fix.room_id,
                "teacher_id": fix.teacher_id,
                "remaining_errors": fix.remaining_errors,
            }
            for fix in eng.suggest_fixes(state, row.id)
        ],
    }


# --- export -----------------------------------------------------------------


@router.get("/schedule/export")
def export_schedule(
    db: DbSession,
    user: CurrentUser,
    view: str = "section",
    format: str = "xlsx",
    semester_id: int | None = None,
    id: int | None = None,
):
    """Timetables by section, teacher or room as an Excel workbook or a PDF."""
    if view not in export.VIEWS:
        raise _unprocessable("view must be section, teacher or room")
    if format not in export.FORMATS:
        raise _unprocessable("format must be xlsx or pdf")
    semester = get_semester(db, user.school_id, semester_id)
    document = export.build(db, user.school_id, semester, view, id)
    if not document.tables:
        raise HTTPException(404, "There is nothing to export for that selection.")
    render, media_type = export.FORMATS[format]
    audit(db, user, "export", "schedule", None, {"summary": f"Timetable by {view} exported as {format.upper()}"})
    commit(db)
    return Response(
        render(document),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="timetable-by-{view}.{format}"'},
    )


# --- automatic scheduling ---------------------------------------------------


def _job_json(job: SolverJob) -> dict[str, Any]:
    result = dict(job.result or {})
    for private in ("base", "kept_ids", "new_entries"):
        result.pop(private, None)
    return {
        "id": job.id,
        "semester_id": job.semester_id,
        "status": job.status,
        "mode": job.mode,
        "time_limit": job.time_limit,
        "progress": job.progress,
        "result": result or None,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "applied_at": job.applied_at,
    }


def _refresh(db: Session, job: SolverJob) -> SolverJob:
    """A job left unfinished by a server restart can never finish; say so."""
    if job.status in jobs.ACTIVE and not jobs.is_running_here(job.id):
        job.status = "failed"
        job.error = "The server restarted while this was running. Please start it again."
        db.commit()
    return job


@router.post("/solver/jobs", status_code=202)
def start_solver(data: SolveIn, db: DbSession, user: EditorUser):
    """Starts generating a timetable in the background. Nothing is saved until it is applied."""
    semester = get_semester(db, user.school_id, data.semester_id)
    running = db.scalars(
        select(SolverJob).where(SolverJob.school_id == user.school_id, SolverJob.status.in_(jobs.ACTIVE))
    ).all()
    if any(_refresh(db, job).status in jobs.ACTIVE for job in running):
        raise _conflict("The automatic scheduler is already running for your school.")
    job = SolverJob(
        school_id=user.school_id,
        semester_id=semester.id,
        user_id=user.id,
        status="queued",
        mode=data.mode,
        time_limit=data.time_limit,
    )
    db.add(job)
    db.flush()
    audit(db, user, "start", "solver_job", job.id, {"summary": f"Automatic scheduling started ({data.mode}, up to {data.time_limit} s)"})
    commit(db)
    jobs.submit(job.id)
    return _job_json(job)


@router.get("/solver/jobs/latest")
def latest_solver_job(db: DbSession, user: CurrentUser, semester_id: int | None = None):
    semester = get_semester(db, user.school_id, semester_id)
    job = db.scalars(
        select(SolverJob)
        .where(SolverJob.school_id == user.school_id, SolverJob.semester_id == semester.id)
        .order_by(SolverJob.id.desc())
    ).first()
    return _job_json(_refresh(db, job)) if job else None


@router.get("/solver/jobs/{job_id}")
def get_solver_job(job_id: int, db: DbSession, user: CurrentUser):
    return _job_json(_refresh(db, get_owned(db, SolverJob, job_id, user.school_id)))


@router.post("/solver/jobs/{job_id}/cancel")
def cancel_solver_job(job_id: int, db: DbSession, user: EditorUser):
    """Stops the search. The best timetable found so far is kept as the result."""
    job = _refresh(db, get_owned(db, SolverJob, job_id, user.school_id))
    if job.status in jobs.ACTIVE:
        jobs.request_stop(job.id)
    return _job_json(job)


@router.post("/solver/jobs/{job_id}/apply")
def apply_solver_job(job_id: int, db: DbSession, user: EditorUser):
    """Replaces the timetable with the generated one."""
    job = get_owned(db, SolverJob, job_id, user.school_id)
    if job.status != "done" or not job.result:
        raise _conflict("This run has no finished timetable to apply.")
    if job.applied_at is not None:
        raise _conflict("This timetable was already applied.")
    semester = db.get(Semester, job.semester_id)
    state = load_state(db, user.school_id, semester)
    if jobs.fingerprint(state) != job.result["base"]:
        raise _conflict("The timetable or teacher loading changed after this was generated. Run the scheduler again.")
    kept = set(job.result["kept_ids"])
    removed = 0
    for row in db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.school_id == user.school_id, ScheduleEntry.semester_id == semester.id)
    ):
        if row.id not in kept:
            db.delete(row)
            removed += 1
    db.flush()
    new_entries = job.result["new_entries"]
    db.add_all(ScheduleEntry(school_id=user.school_id, semester_id=semester.id, **values) for values in new_entries)
    job.applied_at = func.now()
    summary = f"Generated timetable applied: {len(new_entries)} class(es) placed, {removed} replaced, {len(kept)} kept"
    audit(db, user, "apply", "solver_job", job.id, {"summary": summary})
    teachers = {values["teacher_id"] for values in new_entries} | {e.teacher_id for e in state.entries}
    recipients = [uid for teacher_id in teachers for uid in users_of_teacher(db, user.school_id, teacher_id, user.id)]
    notify_users(
        db, user.school_id, recipients, "timetable", "A new timetable was published", "Open your timetable to see your classes.", "/timetable"
    )
    commit(db)
    return _respond(db, user, semester)


# --- substitution finder ----------------------------------------------------


@router.get("/substitutes")
def substitutes(teacher_id: int, day_of_week: int, db: DbSession, user: CurrentUser, semester_id: int | None = None):
    """For an absent teacher on one day: each class and who could cover it."""
    get_owned(db, Teacher, teacher_id, user.school_id)
    semester = get_semester(db, user.school_id, semester_id)
    state = load_state(db, user.school_id, semester)
    mine = [e for e in state.entries if e.teacher_id == teacher_id and e.day == day_of_week and e.period_id in state.slots]
    classes = []
    seen: set[Any] = set()
    for entry in sorted(mine, key=lambda e: (state.slots[e.period_id].start, e.id)):
        key = eng._class_key(entry)
        if key in seen:
            continue  # a combined class is covered once
        seen.add(key)
        members = eng.siblings(state, entry)
        classes.append(
            {
                "entry_id": entry.id,
                "period_id": entry.period_id,
                "subject_id": entry.subject_id,
                "room_id": entry.room_id,
                "section_ids": [e.section_id for e in members],
                "candidates": [
                    {
                        "teacher_id": c.teacher_id,
                        "qualified": c.qualified,
                        "knows_section": c.knows_section,
                        "day_hours": round(c.day_minutes / 60, 2),
                        "week_hours": round(c.week_minutes / 60, 2),
                        "notes": list(c.notes),
                    }
                    for c in eng.find_substitutes(state, entry.id)
                ],
            }
        )
    return {"teacher_id": teacher_id, "day_of_week": day_of_week, "classes": classes}
