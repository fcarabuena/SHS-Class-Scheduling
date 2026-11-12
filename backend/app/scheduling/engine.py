"""Conflict detection for a weekly timetable.

Pure Python with no database access, so every rule can be unit-tested on
small hand-built states and reused by the automatic scheduler later.

Hard constraints checked (one conflict code each):

1. TEACHER_DOUBLE_BOOKED   a teacher is in two classes at the same time
2. ROOM_DOUBLE_BOOKED      a room hosts two classes at the same time
3. SECTION_DOUBLE_BOOKED   a section has two classes at the same time
4. TEACHER_NOT_QUALIFIED   the teacher is not qualified for the subject
5. TEACHER_UNAVAILABLE     the teacher marked the time as unavailable
6. ROOM_TYPE_MISMATCH      the room is not the type the subject requires
7. ROOM_OVER_CAPACITY      the class is larger than the room
8. TEACHER_DAILY_OVERLOAD / TEACHER_WEEKLY_OVERLOAD   load limits
9. SUBJECT_HOURS_UNDER / SUBJECT_HOURS_OVER           required weekly hours

"Same time" always means overlapping clock time on the same day, never
"same period number", so schools with two shifts are handled correctly.

Entries that share a ``group`` are one combined class: several sections
taught together by one teacher in one room. A combined class counts once
for double-booking and load, and its sections' head counts are added
together for room capacity.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Hashable

DAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}

ERROR = "error"
INCOMPLETE = "incomplete"

ROOM_CODES = {"ROOM_DOUBLE_BOOKED", "ROOM_TYPE_MISMATCH", "ROOM_OVER_CAPACITY"}
TEACHER_CODES = {
    "TEACHER_DOUBLE_BOOKED",
    "TEACHER_NOT_QUALIFIED",
    "TEACHER_UNAVAILABLE",
    "TEACHER_DAILY_OVERLOAD",
    "TEACHER_WEEKLY_OVERLOAD",
}
SLOT_CODES = {
    "TEACHER_DOUBLE_BOOKED",
    "ROOM_DOUBLE_BOOKED",
    "SECTION_DOUBLE_BOOKED",
    "TEACHER_UNAVAILABLE",
    "TEACHER_DAILY_OVERLOAD",
}


# --- inputs -----------------------------------------------------------------


@dataclass(frozen=True)
class Slot:
    """A teaching period of a shift's bell schedule. Times are minutes from midnight."""

    id: int
    shift_id: int
    name: str
    start: int
    end: int

    @property
    def minutes(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class TeacherInfo:
    id: int
    name: str
    max_daily_minutes: int
    max_weekly_minutes: int
    qualified: frozenset[int] = frozenset()
    # (day_of_week, period_id) pairs the teacher cannot teach in.
    unavailable: frozenset[tuple[int, int]] = frozenset()
    # Slots the teacher would like to teach in (a soft preference).
    preferred: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class RoomInfo:
    id: int
    name: str
    type: str
    capacity: int


@dataclass(frozen=True)
class SectionInfo:
    id: int
    name: str
    shift_id: int
    student_count: int


@dataclass(frozen=True)
class SubjectInfo:
    id: int
    code: str
    name: str
    room_type: str
    heavy: bool = False


@dataclass(frozen=True)
class Requirement:
    """A section must take a subject for this many minutes a week (teacher loading row)."""

    section_id: int
    subject_id: int
    minutes: int
    teacher_id: int | None = None
    group: int | None = None
    id: int | None = None


@dataclass(frozen=True)
class Entry:
    """One class meeting on the timetable."""

    id: int
    section_id: int
    subject_id: int
    day: int
    period_id: int
    teacher_id: int | None = None
    room_id: int | None = None
    pinned: bool = False
    group: int | None = None


@dataclass
class State:
    days: list[int]
    slots: dict[int, Slot]
    teachers: dict[int, TeacherInfo]
    rooms: dict[int, RoomInfo]
    sections: dict[int, SectionInfo]
    subjects: dict[int, SubjectInfo]
    requirements: list[Requirement] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)

    def with_entries(self, entries: Iterable[Entry]) -> State:
        return replace(self, entries=list(entries))

    def replacing(self, changed: Iterable[Entry]) -> State:
        """A copy where the given entries replace (or are added to) the current ones."""
        by_id = {e.id: e for e in changed}
        kept = [by_id.pop(e.id, e) for e in self.entries]
        return replace(self, entries=kept + list(by_id.values()))


# --- outputs ----------------------------------------------------------------


@dataclass(frozen=True)
class Conflict:
    code: str
    severity: str
    message: str
    entry_ids: tuple[int, ...] = ()
    teacher_id: int | None = None
    room_id: int | None = None
    section_id: int | None = None
    subject_id: int | None = None
    day: int | None = None

    @property
    def key(self) -> str:
        parts = [self.code, *map(str, self.entry_ids), self.teacher_id, self.room_id, self.section_id, self.subject_id, self.day]
        return ":".join("" if p is None else str(p) for p in parts)


@dataclass(frozen=True)
class TeacherLoad:
    teacher_id: int
    assigned_minutes: int
    scheduled_minutes: int
    max_daily_minutes: int
    max_weekly_minutes: int
    # Most minutes that fit in a week given the daily limit and unavailable slots.
    capacity_minutes: int
    status: str  # "ok", "full" or "over"
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fix:
    kind: str  # "move", "room" or "teacher"
    label: str
    entry_id: int
    day: int | None = None
    period_id: int | None = None
    room_id: int | None = None
    teacher_id: int | None = None
    remaining_errors: int = 0


# --- helpers ----------------------------------------------------------------


def hours_text(minutes: int) -> str:
    hours = minutes / 60
    return f"{hours:g} h" if hours == round(hours, 2) else f"{hours:.2f} h"


def _when(state: State, entry: Entry) -> str:
    slot = state.slots.get(entry.period_id)
    return f"{DAY_NAMES.get(entry.day, entry.day)} {slot.name if slot else ''}".strip()


def _class_key(entry: Entry) -> Hashable:
    """Entries of one combined class in one slot share a key."""
    return ("g", entry.group, entry.day, entry.period_id) if entry.group is not None else ("e", entry.id)


def _overlap(a: Slot, b: Slot) -> bool:
    return a.start < b.end and b.start < a.end


def _name(table: dict, item_id: int | None, attr: str = "name") -> str:
    item = table.get(item_id)
    return getattr(item, attr) if item else "?"


def _classes(state: State, entries: Iterable[Entry]) -> dict[Hashable, list[Entry]]:
    grouped: dict[Hashable, list[Entry]] = defaultdict(list)
    for entry in entries:
        if entry.period_id in state.slots:
            grouped[_class_key(entry)].append(entry)
    return grouped


def _teacher_minutes(state: State, teacher_id: int) -> dict[int, int]:
    """Scheduled teaching minutes per day; a combined class counts once."""
    per_day: dict[int, int] = defaultdict(int)
    classes = _classes(state, (e for e in state.entries if e.teacher_id == teacher_id))
    for members in classes.values():
        per_day[members[0].day] += state.slots[members[0].period_id].minutes
    return per_day


# --- detection --------------------------------------------------------------


def _double_bookings(state: State, code: str, attr: str, table: dict, noun: str) -> list[Conflict]:
    found: list[Conflict] = []
    buckets: dict[tuple[int, int], list[Entry]] = defaultdict(list)
    for entry in state.entries:
        resource = getattr(entry, attr)
        if resource is not None and entry.period_id in state.slots:
            buckets[(resource, entry.day)].append(entry)
    for (resource, day), entries in buckets.items():
        classes = list(_classes(state, entries).values()) if attr != "section_id" else [[e] for e in entries]
        for i, first in enumerate(classes):
            for second in classes[i + 1 :]:
                a, b = first[0], second[0]
                if not _overlap(state.slots[a.period_id], state.slots[b.period_id]):
                    continue
                subjects = " and ".join(sorted({_name(state.subjects, e.subject_id, "code") for e in (a, b)}))
                found.append(
                    Conflict(
                        code=code,
                        severity=ERROR,
                        message=f"{noun} {_name(table, resource)} has two classes at the same time on {_when(state, a)} ({subjects}).",
                        entry_ids=tuple(sorted(e.id for e in first + second)),
                        day=day,
                        **{attr: resource},
                    )
                )
    return found


def _per_entry(state: State) -> list[Conflict]:
    found: list[Conflict] = []
    for members in _classes(state, state.entries).values():
        entry = members[0]
        ids = tuple(sorted(e.id for e in members))
        subject = state.subjects.get(entry.subject_id)
        subject_code = subject.code if subject else "?"
        teacher = state.teachers.get(entry.teacher_id) if entry.teacher_id is not None else None
        room = state.rooms.get(entry.room_id) if entry.room_id is not None else None
        slot = state.slots[entry.period_id]
        where = _when(state, entry)

        if teacher and entry.subject_id not in teacher.qualified:
            found.append(
                Conflict(
                    "TEACHER_NOT_QUALIFIED",
                    ERROR,
                    f"{teacher.name} is not qualified to teach {subject_code} ({where}).",
                    ids,
                    teacher_id=teacher.id,
                    subject_id=entry.subject_id,
                    day=entry.day,
                )
            )
        if teacher and any(
            day == entry.day and period_id in state.slots and _overlap(slot, state.slots[period_id])
            for day, period_id in teacher.unavailable
        ):
            found.append(
                Conflict(
                    "TEACHER_UNAVAILABLE",
                    ERROR,
                    f"{teacher.name} is marked unavailable on {where}.",
                    ids,
                    teacher_id=teacher.id,
                    day=entry.day,
                )
            )
        if room and subject and room.type != subject.room_type:
            found.append(
                Conflict(
                    "ROOM_TYPE_MISMATCH",
                    ERROR,
                    f"{subject_code} needs a {subject.room_type.replace('_', ' ')} room, "
                    f"but {room.name} is a {room.type.replace('_', ' ')} room ({where}).",
                    ids,
                    room_id=room.id,
                    subject_id=entry.subject_id,
                    day=entry.day,
                )
            )
        if room:
            students = sum(state.sections[e.section_id].student_count for e in members if e.section_id in state.sections)
            if students > room.capacity:
                found.append(
                    Conflict(
                        "ROOM_OVER_CAPACITY",
                        ERROR,
                        f"{room.name} holds {room.capacity} but the class has {students} students ({where}).",
                        ids,
                        room_id=room.id,
                        day=entry.day,
                    )
                )
    return found


def _load_limits(state: State) -> list[Conflict]:
    found: list[Conflict] = []
    for teacher in state.teachers.values():
        mine = [e for e in state.entries if e.teacher_id == teacher.id]
        if not mine:
            continue
        per_day = _teacher_minutes(state, teacher.id)
        for day, minutes in sorted(per_day.items()):
            if minutes > teacher.max_daily_minutes:
                found.append(
                    Conflict(
                        "TEACHER_DAILY_OVERLOAD",
                        ERROR,
                        f"{teacher.name} teaches {hours_text(minutes)} on {DAY_NAMES.get(day, day)}; "
                        f"the daily limit is {hours_text(teacher.max_daily_minutes)}.",
                        tuple(sorted(e.id for e in mine if e.day == day)),
                        teacher_id=teacher.id,
                        day=day,
                    )
                )
        week = sum(per_day.values())
        if week > teacher.max_weekly_minutes:
            found.append(
                Conflict(
                    "TEACHER_WEEKLY_OVERLOAD",
                    ERROR,
                    f"{teacher.name} teaches {hours_text(week)} a week; "
                    f"the weekly limit is {hours_text(teacher.max_weekly_minutes)}.",
                    tuple(sorted(e.id for e in mine)),
                    teacher_id=teacher.id,
                )
            )
    return found


def scheduled_minutes(state: State) -> dict[tuple[int, int], int]:
    """Minutes on the timetable per (section, subject)."""
    totals: dict[tuple[int, int], int] = defaultdict(int)
    for entry in state.entries:
        if entry.period_id in state.slots:
            totals[(entry.section_id, entry.subject_id)] += state.slots[entry.period_id].minutes
    return totals


def _required_hours(state: State) -> list[Conflict]:
    found: list[Conflict] = []
    totals = scheduled_minutes(state)
    for req in state.requirements:
        key = (req.section_id, req.subject_id)
        entries = [e for e in state.entries if (e.section_id, e.subject_id) == key and e.period_id in state.slots]
        have = totals.get(key, 0)
        label = f"{_name(state.subjects, req.subject_id, 'code')} for {_name(state.sections, req.section_id)}"
        common = dict(section_id=req.section_id, subject_id=req.subject_id)
        if have < req.minutes:
            found.append(
                Conflict(
                    "SUBJECT_HOURS_UNDER",
                    INCOMPLETE,
                    f"{label} has {hours_text(have)} scheduled of the required {hours_text(req.minutes)} a week.",
                    tuple(sorted(e.id for e in entries)),
                    **common,
                )
            )
        elif entries:
            # Over only when a whole class meeting could be removed and the
            # requirement would still be met (periods rarely divide evenly).
            shortest = min(state.slots[e.period_id].minutes for e in entries)
            if have - shortest >= req.minutes:
                found.append(
                    Conflict(
                        "SUBJECT_HOURS_OVER",
                        ERROR,
                        f"{label} has {hours_text(have)} scheduled but only {hours_text(req.minutes)} a week is required.",
                        tuple(sorted(e.id for e in entries)),
                        **common,
                    )
                )
    return found


def detect(state: State) -> list[Conflict]:
    """All conflicts in the timetable, hard-constraint violations first."""
    conflicts = [
        *_double_bookings(state, "TEACHER_DOUBLE_BOOKED", "teacher_id", state.teachers, "Teacher"),
        *_double_bookings(state, "ROOM_DOUBLE_BOOKED", "room_id", state.rooms, "Room"),
        *_double_bookings(state, "SECTION_DOUBLE_BOOKED", "section_id", state.sections, "Section"),
        *_per_entry(state),
        *_load_limits(state),
        *_required_hours(state),
    ]
    return sorted(conflicts, key=lambda c: (c.severity != ERROR, c.code, c.day or 0, c.entry_ids))


def errors(conflicts: Iterable[Conflict]) -> list[Conflict]:
    return [c for c in conflicts if c.severity == ERROR]


def for_entries(conflicts: Iterable[Conflict], entry_ids: Iterable[int]) -> list[Conflict]:
    wanted = set(entry_ids)
    return [c for c in conflicts if wanted.intersection(c.entry_ids)]


# --- teacher loading --------------------------------------------------------


def teacher_loads(state: State) -> list[TeacherLoad]:
    """Planned and scheduled load of every teacher, checked against their limits."""
    assigned: dict[int, int] = defaultdict(int)
    unqualified: dict[int, set[str]] = defaultdict(set)
    seen_groups: set[tuple[int, int]] = set()
    for req in state.requirements:
        if req.teacher_id is None:
            continue
        teacher = state.teachers.get(req.teacher_id)
        if teacher and req.subject_id not in teacher.qualified:
            unqualified[req.teacher_id].add(_name(state.subjects, req.subject_id, "code"))
        if req.group is not None:
            if (req.teacher_id, req.group) in seen_groups:
                continue  # a combined class is one load
            seen_groups.add((req.teacher_id, req.group))
        assigned[req.teacher_id] += req.minutes

    loads: list[TeacherLoad] = []
    for teacher in state.teachers.values():
        capacity = 0
        for day in state.days:
            free = _free_minutes(state, teacher, day)
            capacity += min(teacher.max_daily_minutes, free)
        capacity = min(capacity, teacher.max_weekly_minutes)
        have = assigned.get(teacher.id, 0)
        issues: list[str] = []
        if have > teacher.max_weekly_minutes:
            issues.append(
                f"Assigned {hours_text(have)} a week; the weekly limit is {hours_text(teacher.max_weekly_minutes)}."
            )
        elif have > capacity:
            issues.append(
                f"Assigned {hours_text(have)} a week, but only {hours_text(capacity)} fits within the "
                f"{hours_text(teacher.max_daily_minutes)} daily limit and the teacher's available time."
            )
        if unqualified.get(teacher.id):
            issues.append("Not qualified for: " + ", ".join(sorted(unqualified[teacher.id])) + ".")
        over = have > min(capacity, teacher.max_weekly_minutes)
        status = "over" if over else "full" if have == min(capacity, teacher.max_weekly_minutes) and have > 0 else "ok"
        loads.append(
            TeacherLoad(
                teacher_id=teacher.id,
                assigned_minutes=have,
                scheduled_minutes=sum(_teacher_minutes(state, teacher.id).values()),
                max_daily_minutes=teacher.max_daily_minutes,
                max_weekly_minutes=teacher.max_weekly_minutes,
                capacity_minutes=capacity,
                status=status,
                issues=tuple(issues),
            )
        )
    return loads


def _free_minutes(state: State, teacher: TeacherInfo, day: int) -> int:
    """Clock minutes on a day covered by a teaching period the teacher is available for."""
    blocked = [state.slots[p] for d, p in teacher.unavailable if d == day and p in state.slots]
    spans = sorted(
        (slot.start, slot.end)
        for slot in state.slots.values()
        if not any(_overlap(slot, b) for b in blocked)
    )
    total, cursor = 0, -1
    for start, end in spans:  # union, so overlapping shifts are not counted twice
        start = max(start, cursor)
        if end > start:
            total += end - start
            cursor = end
    return total


# --- what-if checks and suggested fixes -------------------------------------


def siblings(state: State, entry: Entry) -> list[Entry]:
    """The entry plus the other sections' entries of the same combined class meeting."""
    if entry.group is None:
        return [entry]
    return [e for e in state.entries if e.group == entry.group and e.day == entry.day and e.period_id == entry.period_id]


def cell_is_free(state: State, section_ids: Iterable[int], day: int, period_id: int, ignore: Iterable[int] = ()) -> bool:
    wanted, skip = set(section_ids), set(ignore)
    return not any(
        e.section_id in wanted and e.day == day and e.period_id == period_id and e.id not in skip for e in state.entries
    )


def check_placement(state: State, moving: list[Entry], day: int, period_id: int) -> list[Conflict]:
    """Hard-constraint violations the given entries would have if placed in a slot."""
    changed = [replace(e, day=day, period_id=period_id) for e in moving]
    return for_entries(errors(detect(state.replacing(changed))), [e.id for e in moving])


def suggest_fixes(state: State, entry_id: int, per_kind: int = 4) -> list[Fix]:
    """Changes that clear the entry's hard-constraint violations without creating new ones."""
    entry = next((e for e in state.entries if e.id == entry_id), None)
    if entry is None or entry.pinned:
        return []
    group = siblings(state, entry)
    ids = [e.id for e in group]
    baseline = errors(detect(state))
    mine = for_entries(baseline, ids)
    codes = {c.code for c in mine}
    if not codes:
        return []

    def outcome(changed: list[Entry], family: set[str]) -> int | None:
        """Total errors left if the change helps, otherwise None."""
        after = errors(detect(state.replacing(changed)))
        still = {c.code for c in for_entries(after, [e.id for e in changed])}
        if still & family & codes or len(after) >= len(baseline):
            return None
        return len(after)

    fixes: list[Fix] = []
    subject = _name(state.subjects, entry.subject_id, "code")

    if codes & ROOM_CODES:
        options = []
        for room in state.rooms.values():
            if room.id == entry.room_id:
                continue
            left = outcome([replace(e, room_id=room.id) for e in group], ROOM_CODES)
            if left is not None:
                options.append(Fix("room", f"Use {room.name}", entry.id, room_id=room.id, remaining_errors=left))
        fixes += sorted(options, key=lambda f: (f.remaining_errors, f.label))[:per_kind]

    if codes & SLOT_CODES:
        options = []
        section = state.sections.get(entry.section_id)
        sections = [e.section_id for e in group]
        for day in state.days:
            for slot in state.slots.values():
                if section is None or slot.shift_id != section.shift_id:
                    continue
                if (day, slot.id) == (entry.day, entry.period_id) or not cell_is_free(state, sections, day, slot.id, ids):
                    continue
                left = outcome([replace(e, day=day, period_id=slot.id) for e in group], SLOT_CODES)
                if left is not None:
                    label = f"Move to {DAY_NAMES.get(day, day)} {slot.name}"
                    options.append(Fix("move", label, entry.id, day=day, period_id=slot.id, remaining_errors=left))
        # Prefer the same day, then the nearest day.
        fixes += sorted(options, key=lambda f: (f.remaining_errors, abs(f.day - entry.day), state.slots[f.period_id].start))[
            :per_kind
        ]

    if codes & TEACHER_CODES:
        options = []
        group_filter = (lambda e: e.group == entry.group) if entry.group is not None else (lambda e: e.section_id == entry.section_id)
        taught = [e for e in state.entries if e.subject_id == entry.subject_id and group_filter(e)]
        for teacher in state.teachers.values():
            if teacher.id == entry.teacher_id or entry.subject_id not in teacher.qualified:
                continue
            left = outcome([replace(e, teacher_id=teacher.id) for e in taught], TEACHER_CODES)
            if left is not None:
                label = f"Reassign {subject} to {teacher.name}"
                options.append(Fix("teacher", label, entry.id, teacher_id=teacher.id, remaining_errors=left))
        fixes += sorted(options, key=lambda f: (f.remaining_errors, f.label))[:per_kind]

    return fixes
