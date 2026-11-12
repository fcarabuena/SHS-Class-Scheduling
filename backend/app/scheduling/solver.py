"""Automatic timetable generation with OR-Tools CP-SAT.

Works on the same :class:`engine.State` as the conflict engine and obeys the
same hard constraints, so a generated timetable has no conflicts by
construction. Required hours are the one constraint that is relaxed: when
not everything fits, the solver returns the fullest timetable it can find
and :func:`explain_shortage` says what blocked the rest.

Fixed classes are never moved: pinned classes always, and every existing
class in "fill" mode. Soft preferences are weighted by the school's
``soft_constraint_weights`` setting.
"""

from __future__ import annotations

import os
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from . import engine as eng

DEFAULT_WEIGHTS = {
    "max_consecutive_periods": 5,
    "balance_teacher_load": 3,
    "avoid_section_gaps": 4,
    "prefer_teacher_slots": 2,
    "minimize_room_changes": 2,
    "spread_subject_days": 3,
    "heavy_subjects_not_last": 2,
}
# A teacher teaching more than this many periods in a row is penalised.
MAX_CONSECUTIVE = 3
# Cost of one unplaced minute; far above anything the soft preferences add up to.
SHORT_WEIGHT = 2000


@dataclass
class Options:
    mode: str = "rebuild"  # "rebuild" keeps pinned classes only; "fill" keeps everything placed
    time_limit: float = 30.0
    weights: dict[str, float] = field(default_factory=dict)
    seed: int = 1


@dataclass
class Shortage:
    section_ids: list[int]
    subject_id: int
    teacher_id: int | None
    required_minutes: int
    placed_minutes: int
    message: str


@dataclass
class Result:
    status: str  # "complete", "partial", "nothing_to_do" or "failed"
    entries: list[eng.Entry]
    required_minutes: int = 0
    placed_minutes: int = 0
    added: int = 0
    kept: int = 0
    shortages: list[Shortage] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    proven_optimal: bool = False
    seconds: float = 0.0


@dataclass
class _Unit:
    """One class to schedule: a requirement, or several combined into one."""

    index: int
    requirements: list[eng.Requirement]
    section_ids: list[int]
    subject_id: int
    teacher_id: int | None
    minutes: int
    shift_id: int
    students: int
    group: int | None
    rooms: list[int] = field(default_factory=list)


def _units(state: eng.State) -> list[_Unit]:
    grouped: dict[Any, list[eng.Requirement]] = defaultdict(list)
    for req in state.requirements:
        if req.section_id in state.sections:
            grouped[("g", req.group) if req.group is not None else ("r", req.section_id, req.subject_id)].append(req)
    units = []
    for reqs in grouped.values():
        sections = [r.section_id for r in reqs]
        units.append(
            _Unit(
                index=len(units),
                requirements=reqs,
                section_ids=sections,
                subject_id=reqs[0].subject_id,
                teacher_id=reqs[0].teacher_id,
                minutes=max(r.minutes for r in reqs),
                shift_id=state.sections[sections[0]].shift_id,
                students=sum(state.sections[s].student_count for s in sections),
                group=reqs[0].group,
            )
        )
    return units


def precheck(state: eng.State) -> list[str]:
    """Problems in the data that no timetable can solve, in plain words."""
    problems: list[str] = []
    shift_minutes: dict[int, int] = defaultdict(int)
    for slot in state.slots.values():
        shift_minutes[slot.shift_id] += slot.minutes * len(state.days)
    need: dict[int, int] = defaultdict(int)
    for req in state.requirements:
        need[req.section_id] += req.minutes
    for section_id, minutes in sorted(need.items()):
        section = state.sections.get(section_id)
        if section and minutes > shift_minutes[section.shift_id]:
            problems.append(
                f"{section.name} needs {eng.hours_text(minutes)} of classes a week, but its shift only has "
                f"{eng.hours_text(shift_minutes[section.shift_id])} of periods. Add periods, add a school day, "
                "or reduce the subjects' weekly hours."
            )
    for load in eng.teacher_loads(state):
        teacher = state.teachers[load.teacher_id]
        problems += [f"{teacher.name}: {issue}" for issue in load.issues]
    without = sum(1 for r in state.requirements if r.teacher_id is None)
    if without:
        problems.append(f"{without} subject(s) have no teacher yet; they are scheduled without one.")
    for unit in _units(state):
        subject = state.subjects.get(unit.subject_id)
        if subject and not _eligible_rooms(state, unit):
            names = " + ".join(state.sections[s].name for s in unit.section_ids)
            problems.append(
                f"No {subject.room_type.replace('_', ' ')} room holds the {unit.students} students of {names} "
                f"for {subject.code}; it is scheduled without a room."
            )
    return problems


def _eligible_rooms(state: eng.State, unit: _Unit) -> list[int]:
    subject = state.subjects.get(unit.subject_id)
    if subject is None:
        return []
    return sorted(r.id for r in state.rooms.values() if r.type == subject.room_type and r.capacity >= unit.students)


def solve(
    state: eng.State,
    options: Options | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Result:
    options = options or Options()
    weights = {**DEFAULT_WEIGHTS, **{k: v for k, v in (options.weights or {}).items() if isinstance(v, (int, float))}}
    started = time.monotonic()
    units = _units(state)
    for unit in units:
        unit.rooms = _eligible_rooms(state, unit)
    problems = precheck(state)

    fixed = [e for e in state.entries if e.period_id in state.slots and (options.mode == "fill" or e.pinned)]
    required = sum(u.minutes for u in units)
    if not units:
        return Result("nothing_to_do", list(fixed), problems=problems)

    unit_of = {(s, u.subject_id): u for u in units for s in u.section_ids}
    slots_by_shift: dict[int, list[eng.Slot]] = defaultdict(list)
    for slot in sorted(state.slots.values(), key=lambda s: s.start):
        slots_by_shift[slot.shift_id].append(slot)
    # Every moment a period starts; periods covering the same moment clash.
    points = sorted({s.start for s in state.slots.values()})
    covering = {t: [s.id for s in state.slots.values() if s.start <= t < s.end] for t in points}

    model = cp_model.CpModel()
    x: dict[tuple[int, int, int], Any] = {}  # (unit, day, slot) -> BoolVar or the constant 1

    # --- fixed classes -------------------------------------------------------
    section_busy: dict[tuple[int, int, int], int] = {}  # (section, day, slot) -> unit index or -1
    teacher_fixed: dict[tuple[int, int, int], int] = defaultdict(int)  # (teacher, day, slot) -> classes
    room_fixed: dict[tuple[int, int, int], int] = defaultdict(int)
    fixed_classes: dict[Any, list[eng.Entry]] = defaultdict(list)
    for entry in fixed:
        fixed_classes[eng._class_key(entry)].append(entry)
    for members in fixed_classes.values():
        first = members[0]
        unit = unit_of.get((first.section_id, first.subject_id))
        for entry in members:
            section_busy[(entry.section_id, entry.day, entry.period_id)] = unit.index if unit else -1
        if unit:
            x[(unit.index, first.day, first.period_id)] = 1
        if first.teacher_id is not None:
            teacher_fixed[(first.teacher_id, first.day, first.period_id)] += 1
        if first.room_id is not None:
            room_fixed[(first.room_id, first.day, first.period_id)] += 1

    # --- decision variables ----------------------------------------------------
    hints = {(e.section_id, e.subject_id, e.day, e.period_id): e.room_id for e in state.entries if not e.pinned}
    for unit in units:
        teacher = state.teachers.get(unit.teacher_id) if unit.teacher_id is not None else None
        blocked = [state.slots[p] for d, p in (teacher.unavailable if teacher else ()) if p in state.slots]
        blocked_days = [d for d, p in (teacher.unavailable if teacher else ()) if p in state.slots]
        for day in state.days:
            for slot in slots_by_shift[unit.shift_id]:
                key = (unit.index, day, slot.id)
                if key in x:
                    continue  # fixed here
                if any((s, day, slot.id) in section_busy for s in unit.section_ids):
                    continue
                if any(d == day and eng._overlap(slot, b) for d, b in zip(blocked_days, blocked)):
                    continue
                var = model.new_bool_var(f"x{unit.index}_{day}_{slot.id}")
                x[key] = var
                if (unit.section_ids[0], unit.subject_id, day, slot.id) in hints:
                    model.add_hint(var, 1)  # start from the current timetable

    def is_var(value: Any) -> bool:
        return not isinstance(value, int)

    def at_most_one(terms: list[Any], already: int) -> None:
        variables = [t for t in terms if is_var(t)]
        constant = already + sum(1 for t in terms if not is_var(t))
        if constant >= 1:
            for var in variables:  # the fixed class owns the moment
                model.add(var == 0)
        elif len(variables) > 1:
            model.add_at_most_one(variables)

    # --- hard constraints ------------------------------------------------------
    capacities_by_type: dict[str, list[int]] = defaultdict(list)
    for room in state.rooms.values():
        capacities_by_type[room.type].append(room.capacity)
    capacities_by_type = {k: sorted(set(v)) for k, v in capacities_by_type.items()}
    by_teacher: dict[int, list[_Unit]] = defaultdict(list)
    for unit in units:
        if unit.teacher_id is not None:
            by_teacher[unit.teacher_id].append(unit)
    # Fixed classes outside any unit (or of teachers with nothing left to place) still take time.
    fixed_teacher_minutes: dict[tuple[int, int], int] = defaultdict(int)
    for (teacher_id, day, slot_id), count in teacher_fixed.items():
        fixed_teacher_minutes[(teacher_id, day)] += state.slots[slot_id].minutes * count

    for day in state.days:
        for t in points:
            # 1. a teacher teaches one class at a time
            for teacher_id, mine in by_teacher.items():
                terms = [x[(u.index, day, s)] for u in mine for s in covering[t] if is_var(x.get((u.index, day, s), 0))]
                already = sum(teacher_fixed.get((teacher_id, day, s), 0) for s in covering[t])
                at_most_one(terms, already)
            # 2. rooms: at every moment, enough rooms of each type and size.
            # Rooms are not decision variables (that would make every pair of
            # equal rooms interchangeable and the search slow). A class can
            # use any room of its type at least as big as the class, so rooms
            # can be handed out afterwards exactly when, for every size, the
            # classes needing at least that size do not outnumber such rooms.
            for room_type, capacities in capacities_by_type.items():
                wanting = [u for u in units if u.rooms and state.subjects[u.subject_id].room_type == room_type]
                if not wanting:
                    continue
                taken = [
                    state.rooms[room_id].capacity
                    for (room_id, d, s), count in room_fixed.items()
                    if d == day and s in covering[t] and room_id in state.rooms and state.rooms[room_id].type == room_type
                    for _ in range(count)
                ]
                previous = -1
                for capacity in capacities:
                    free = sum(1 for r in state.rooms.values() if r.type == room_type and r.capacity >= capacity)
                    free -= sum(1 for c in taken if c >= capacity)
                    terms = [
                        x[(u.index, day, s)]
                        for u in wanting
                        if u.students > previous
                        for s in covering[t]
                        if is_var(x.get((u.index, day, s), 0))
                    ]
                    previous = capacity
                    if free <= 0:
                        for var in terms:
                            model.add(var == 0)
                    elif len(terms) > free:
                        model.add(sum(terms) <= free)
        # 3. a section has one class per slot
        for section_id in state.sections:
            mine = [u for u in units if section_id in u.section_ids]
            for slot in slots_by_shift[state.sections[section_id].shift_id]:
                terms = [x[(u.index, day, slot.id)] for u in mine if is_var(x.get((u.index, day, slot.id), 0))]
                if len(terms) > 1:
                    model.add_at_most_one(terms)

    # 8. load limits (never tighter than what fixed classes already use)
    day_minutes: dict[tuple[int, int], Any] = {}
    for teacher_id, mine in by_teacher.items():
        teacher = state.teachers.get(teacher_id)
        if teacher is None:
            continue
        week_terms, week_const = [], 0
        for day in state.days:
            terms = [
                state.slots[s].minutes * x[(u.index, day, s)]
                for u in mine
                for s in (sl.id for sl in slots_by_shift[u.shift_id])
                if is_var(x.get((u.index, day, s), 0))
            ]
            const = fixed_teacher_minutes.get((teacher_id, day), 0)
            day_minutes[(teacher_id, day)] = sum(terms) + const
            if terms:
                model.add(sum(terms) + const <= max(teacher.max_daily_minutes, const))
            week_terms += terms
            week_const += const
        if week_terms:
            model.add(sum(week_terms) + week_const <= max(teacher.max_weekly_minutes, week_const))

    # 9. required weekly hours: never too many; too few is allowed but very costly
    shortage_vars = []
    for unit in units:
        cells = [(day, slot) for day in state.days for slot in slots_by_shift[unit.shift_id]]
        variable = [slot.minutes * x[(unit.index, day, slot.id)] for day, slot in cells if is_var(x.get((unit.index, day, slot.id), 0))]
        const = sum(slot.minutes for day, slot in cells if (unit.index, day, slot.id) in x and not is_var(x[(unit.index, day, slot.id)]))
        shortest = min((slot.minutes for slot in slots_by_shift[unit.shift_id]), default=0)
        cap = max(unit.minutes + shortest - 1, const)
        if variable:
            model.add(sum(variable) + const <= cap)
        short = model.new_int_var(0, max(0, unit.minutes - const), f"short{unit.index}")
        model.add(short >= unit.minutes - const - sum(variable))
        shortage_vars.append(short)

    # --- soft preferences ------------------------------------------------------
    cost: list[Any] = [SHORT_WEIGHT * short for short in shortage_vars]

    def occupancy(unit_list: list[_Unit], day: int, slot_id: int) -> Any:
        return sum(x.get((u.index, day, slot_id), 0) for u in unit_list)

    w = weights["spread_subject_days"]
    if w > 0:
        for unit in units:
            for day in state.days:
                terms = [x[(unit.index, day, s.id)] for s in slots_by_shift[unit.shift_id] if (unit.index, day, s.id) in x]
                if len(terms) > 1:
                    extra = model.new_int_var(0, len(terms), f"extra{unit.index}_{day}")
                    model.add(extra >= sum(terms) - 1)
                    cost.append(int(w * 10) * extra)

    w = weights["avoid_section_gaps"]
    if w > 0:
        for section_id, section in state.sections.items():
            mine = [u for u in units if section_id in u.section_ids]
            slots = slots_by_shift[section.shift_id]
            if not mine or len(slots) < 3:
                continue
            for day in state.days:
                busy = [
                    occupancy(mine, day, s.id) + (1 if section_busy.get((section_id, day, s.id), 0) == -1 else 0) for s in slots
                ]
                before = [model.new_bool_var(f"b{section_id}_{day}_{i}") for i in range(len(slots))]
                after = [model.new_bool_var(f"a{section_id}_{day}_{i}") for i in range(len(slots))]
                for i in range(len(slots)):
                    for j in range(i):
                        model.add(before[i] >= busy[j])
                    for j in range(i + 1, len(slots)):
                        model.add(after[i] >= busy[j])
                for i in range(1, len(slots) - 1):
                    gap = model.new_bool_var(f"gap{section_id}_{day}_{i}")
                    model.add(gap >= before[i] + after[i] - 1 - busy[i])
                    cost.append(int(w * 10) * gap)

    w = weights["prefer_teacher_slots"]
    if w > 0:
        for unit in units:
            teacher = state.teachers.get(unit.teacher_id) if unit.teacher_id is not None else None
            for day, slot_id in teacher.preferred if teacher else ():
                var = x.get((unit.index, day, slot_id))
                if var is not None and is_var(var):
                    cost.append(-int(w * 5) * var)

    w = weights["heavy_subjects_not_last"]
    if w > 0:
        for unit in units:
            subject = state.subjects.get(unit.subject_id)
            slots = slots_by_shift[unit.shift_id]
            if subject and subject.heavy and slots:
                for day in state.days:
                    var = x.get((unit.index, day, slots[-1].id))
                    if var is not None and is_var(var):
                        cost.append(int(w * 10) * var)

    w = weights["max_consecutive_periods"]
    if w > 0:
        for teacher_id, mine in by_teacher.items():
            for shift_id, slots in slots_by_shift.items():
                relevant = [u for u in mine if u.shift_id == shift_id]
                if not relevant or len(slots) <= MAX_CONSECUTIVE:
                    continue
                for day in state.days:
                    for start in range(len(slots) - MAX_CONSECUTIVE):
                        window = slots[start : start + MAX_CONSECUTIVE + 1]
                        # A break between two periods resets the run.
                        if any(a.end != b.start for a, b in zip(window, window[1:])):
                            continue
                        total = sum(occupancy(relevant, day, s.id) for s in window)
                        over = model.new_bool_var(f"run{teacher_id}_{day}_{shift_id}_{start}")
                        model.add(over >= total - MAX_CONSECUTIVE)
                        cost.append(int(w * 10) * over)

    w = weights["balance_teacher_load"]
    if w > 0:
        for teacher_id in by_teacher:
            teacher = state.teachers.get(teacher_id)
            if teacher is None:
                continue
            ceiling = max([teacher.max_daily_minutes, *(fixed_teacher_minutes.get((teacher_id, d), 0) for d in state.days)])
            busiest = model.new_int_var(0, ceiling, f"busiest{teacher_id}")
            for day in state.days:
                if (teacher_id, day) in day_minutes:
                    model.add(busiest >= day_minutes[(teacher_id, day)])
            cost.append(int(w) * busiest)

    model.minimize(sum(cost))

    # --- solve -----------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, float(options.time_limit))
    solver.parameters.num_workers = max(1, min(8, os.cpu_count() or 1))
    solver.parameters.random_seed = options.seed

    class Progress(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.count = 0

        def on_solution_callback(self) -> None:
            self.count += 1
            missing = sum(self.value(v) for v in shortage_vars)
            if on_progress:
                on_progress(
                    {
                        "solutions": self.count,
                        "placed_hours": round((required - missing) / 60, 2),
                        "required_hours": round(required / 60, 2),
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )
            if should_stop and should_stop():
                self.stop_search()

    status = solver.solve(model, Progress())
    seconds = round(time.monotonic() - started, 2)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Cannot normally happen: placing nothing new is always allowed.
        problems.append(f"The solver could not produce a timetable ({solver.status_name(status)}).")
        return Result("failed", list(fixed), required, problems=problems, seconds=seconds)

    # --- read the answer back ---------------------------------------------------
    entries = list(fixed)
    next_id = -1
    added = 0
    chosen = [(units[u], day, slot_id) for (u, day, slot_id), var in x.items() if is_var(var) and solver.value(var)]
    rooms = _assign_rooms(state, fixed, chosen, keep_home=weights["minimize_room_changes"] > 0)
    roomless = sum(1 for (unit, day, slot_id) in chosen if unit.rooms and rooms.get((unit.index, day, slot_id)) is None)
    if roomless:
        problems.append(f"{roomless} class(es) were placed without a room because overlapping shifts left none free.")
    for unit, day, slot_id in sorted(chosen, key=lambda c: (c[0].index, c[1], state.slots[c[2]].start)):
        room_id = rooms.get((unit.index, day, slot_id))
        for req in unit.requirements:
            entries.append(
                eng.Entry(next_id, req.section_id, req.subject_id, day, slot_id, req.teacher_id, room_id, False, req.group)
            )
            next_id -= 1
            added += 1

    result_state = state.with_entries(entries)
    shortages = []
    missing_total = 0
    for unit, short in zip(units, shortage_vars):
        missing = solver.value(short)
        if missing <= 0:
            continue
        missing_total += missing
        shortages.append(
            Shortage(
                section_ids=unit.section_ids,
                subject_id=unit.subject_id,
                teacher_id=unit.teacher_id,
                required_minutes=unit.minutes,
                placed_minutes=unit.minutes - missing,
                message=explain_shortage(result_state, unit, missing),
            )
        )
    return Result(
        status="partial" if shortages else "complete",
        entries=entries,
        required_minutes=required,
        placed_minutes=required - missing_total,
        added=added,
        kept=len(fixed),
        shortages=shortages,
        problems=problems,
        proven_optimal=status == cp_model.OPTIMAL,
        seconds=seconds,
    )


def _assign_rooms(
    state: eng.State, fixed: list[eng.Entry], chosen: list[tuple[_Unit, int, int]], keep_home: bool
) -> dict[tuple[int, int, int], int | None]:
    """Hands out rooms to the placed classes.

    Classes are served from the biggest down, so a class that fits few rooms
    is never crowded out by one that fits many. Each section keeps to the
    room it already uses most, which keeps room changes low.
    """
    busy: dict[int, list[tuple[int, eng.Slot]]] = defaultdict(list)  # room -> [(day, slot)]
    usage: dict[int, Counter[int]] = defaultdict(Counter)  # section -> room -> meetings
    for entry in fixed:
        if entry.room_id is not None:
            busy[entry.room_id].append((entry.day, state.slots[entry.period_id]))
            usage[entry.section_id][entry.room_id] += 1
    assigned: dict[tuple[int, int, int], int | None] = {}
    order = sorted(chosen, key=lambda c: (-c[0].students, c[1], state.slots[c[2]].start, c[0].index))
    for unit, day, slot_id in order:
        slot = state.slots[slot_id]
        free = [r for r in unit.rooms if not any(d == day and eng._overlap(slot, s) for d, s in busy[r])]
        if not free:
            assigned[(unit.index, day, slot_id)] = None
            continue
        home = sum((usage[s] for s in unit.section_ids), Counter())
        room_id = min(free, key=lambda r: (-home[r] if keep_home else 0, state.rooms[r].capacity, r))
        assigned[(unit.index, day, slot_id)] = room_id
        busy[room_id].append((day, slot))
        for section_id in unit.section_ids:
            usage[section_id][room_id] += 1
    return assigned


def explain_shortage(state: eng.State, unit: _Unit, missing: int) -> str:
    """Why the rest of a class could not be placed, from what blocks each remaining slot."""
    subject = state.subjects.get(unit.subject_id)
    teacher = state.teachers.get(unit.teacher_id) if unit.teacher_id is not None else None
    names = " + ".join(state.sections[s].name for s in unit.section_ids)
    reasons: Counter[str] = Counter()
    week = sum(eng._teacher_minutes(state, teacher.id).values()) if teacher else 0
    per_day = eng._teacher_minutes(state, teacher.id) if teacher else {}
    room_label = subject.room_type.replace("_", " ") if subject else "suitable"
    for day in state.days:
        for slot in state.slots.values():
            if slot.shift_id != unit.shift_id:
                continue
            if not eng.cell_is_free(state, unit.section_ids, day, slot.id):
                reasons["the section already has a class"] += 1
                continue
            same_time = [
                e for e in state.entries if e.day == day and e.period_id in state.slots and eng._overlap(slot, state.slots[e.period_id])
            ]
            if teacher:
                if any(d == day and p in state.slots and eng._overlap(slot, state.slots[p]) for d, p in teacher.unavailable):
                    reasons[f"{teacher.name} is unavailable"] += 1
                    continue
                if any(e.teacher_id == teacher.id for e in same_time):
                    reasons[f"{teacher.name} is teaching another class"] += 1
                    continue
                if per_day.get(day, 0) + slot.minutes > teacher.max_daily_minutes:
                    reasons[f"{teacher.name} would pass the daily limit"] += 1
                    continue
                if week + slot.minutes > teacher.max_weekly_minutes:
                    reasons[f"{teacher.name} would pass the weekly limit"] += 1
                    continue
            if unit.rooms and all(any(e.room_id == r for e in same_time) for r in unit.rooms):
                reasons[f"every {room_label} room big enough is taken"] += 1
                continue
            reasons["using it would break another class's rule"] += 1
    head = f"{subject.code if subject else '?'} for {names}: {eng.hours_text(missing)} could not be placed."
    if not reasons:
        return head
    detail = "; ".join(f"{count} slot{'s' if count != 1 else ''} where {reason}" for reason, count in reasons.most_common())
    return f"{head} Of the week's slots: {detail}."
