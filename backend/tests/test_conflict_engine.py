"""Unit tests for the conflict engine: one section per hard constraint.

These build tiny timetables by hand and need no database.
"""

from dataclasses import replace

import pytest

from app.scheduling.engine import (
    Entry,
    Requirement,
    RoomInfo,
    SectionInfo,
    Slot,
    State,
    SubjectInfo,
    TeacherInfo,
    check_placement,
    detect,
    errors,
    find_substitutes,
    suggest_fixes,
    teacher_loads,
)

MON, TUE, WED = 1, 2, 3
# Morning shift (id 1): periods 1-3. Afternoon shift (id 2): periods 11-12.
# Period 3 (10:00-11:00) and period 11 (10:30-11:30) overlap in clock time.
P1, P2, P3, A1, A2 = 1, 2, 3, 11, 12
MATH, SCI, ICT = 1, 2, 3
ANA, BEN = 1, 2
R1, R2, LAB = 1, 2, 3
S_A, S_B, S_PM = 1, 2, 3


def make_state(entries=(), requirements=(), **overrides) -> State:
    state = State(
        days=[1, 2, 3, 4, 5],
        slots={
            P1: Slot(P1, 1, "Period 1", 480, 540),
            P2: Slot(P2, 1, "Period 2", 540, 600),
            P3: Slot(P3, 1, "Period 3", 600, 660),
            A1: Slot(A1, 2, "Period 1", 630, 690),
            A2: Slot(A2, 2, "Period 2", 690, 750),
        },
        teachers={
            ANA: TeacherInfo(ANA, "Ana", 360, 1800, frozenset({MATH, SCI, ICT})),
            BEN: TeacherInfo(BEN, "Ben", 360, 1800, frozenset({MATH, SCI})),
        },
        rooms={
            R1: RoomInfo(R1, "Room 1", "lecture", 45),
            R2: RoomInfo(R2, "Room 2", "lecture", 45),
            LAB: RoomInfo(LAB, "Lab", "computer_lab", 40),
        },
        sections={
            S_A: SectionInfo(S_A, "11-A", 1, 40),
            S_B: SectionInfo(S_B, "11-B", 1, 40),
            S_PM: SectionInfo(S_PM, "12-C", 2, 30),
        },
        subjects={
            MATH: SubjectInfo(MATH, "MATH", "Mathematics", "lecture"),
            SCI: SubjectInfo(SCI, "SCI", "Science", "lecture"),
            ICT: SubjectInfo(ICT, "ICT", "Computer", "computer_lab"),
        },
        requirements=list(requirements),
        entries=list(entries),
    )
    return replace(state, **overrides)


def entry(id, section=S_A, subject=MATH, day=MON, period=P1, teacher=ANA, room=R1, **kw) -> Entry:
    return Entry(id=id, section_id=section, subject_id=subject, day=day, period_id=period, teacher_id=teacher, room_id=room, **kw)


def codes(state: State) -> list[str]:
    return [c.code for c in detect(state)]


def test_a_valid_timetable_has_no_conflicts():
    state = make_state(
        [entry(1), entry(2, section=S_B, teacher=BEN, room=R2), entry(3, period=P2, subject=SCI)],
        [Requirement(S_A, MATH, 60), Requirement(S_A, SCI, 60), Requirement(S_B, MATH, 60)],
    )
    assert detect(state) == []


# --- 1. teacher double-booking ------------------------------------------------


def test_teacher_double_booked_in_the_same_period():
    state = make_state([entry(1), entry(2, section=S_B, room=R2)])
    conflict = next(c for c in detect(state) if c.code == "TEACHER_DOUBLE_BOOKED")
    assert conflict.entry_ids == (1, 2) and conflict.teacher_id == ANA and conflict.severity == "error"
    assert "Ana" in conflict.message and "Monday" in conflict.message


def test_teacher_is_not_double_booked_on_different_days_or_periods():
    state = make_state([entry(1), entry(2, section=S_B, room=R2, day=TUE), entry(3, section=S_B, room=R2, period=P2)])
    assert "TEACHER_DOUBLE_BOOKED" not in codes(state)


def test_teacher_double_booked_across_shifts_when_clock_times_overlap():
    # Morning period 3 (10:00-11:00) overlaps afternoon period 1 (10:30-11:30).
    overlapping = make_state([entry(1, period=P3), entry(2, section=S_PM, period=A1, room=R2)])
    assert "TEACHER_DOUBLE_BOOKED" in codes(overlapping)
    back_to_back = make_state([entry(1, period=P2), entry(2, section=S_PM, period=A1, room=R2)])
    assert "TEACHER_DOUBLE_BOOKED" not in codes(back_to_back)


# --- 2. room double-booking ---------------------------------------------------


def test_room_double_booked():
    state = make_state([entry(1), entry(2, section=S_B, teacher=BEN)])
    conflict = next(c for c in detect(state) if c.code == "ROOM_DOUBLE_BOOKED")
    assert conflict.entry_ids == (1, 2) and conflict.room_id == R1
    assert "TEACHER_DOUBLE_BOOKED" not in codes(state)


def test_room_double_booked_across_overlapping_shifts():
    state = make_state([entry(1, period=P3), entry(2, section=S_PM, period=A1, teacher=BEN)])
    assert "ROOM_DOUBLE_BOOKED" in codes(state)


def test_entries_without_a_room_never_clash_on_rooms():
    state = make_state([entry(1, room=None), entry(2, section=S_B, teacher=BEN, room=None)])
    assert "ROOM_DOUBLE_BOOKED" not in codes(state)


# --- 3. section double-booking ------------------------------------------------


def test_section_double_booked():
    state = make_state([entry(1), entry(2, subject=SCI, teacher=BEN, room=R2)])
    conflict = next(c for c in detect(state) if c.code == "SECTION_DOUBLE_BOOKED")
    assert conflict.entry_ids == (1, 2) and conflict.section_id == S_A


# --- 4. teacher qualification -------------------------------------------------


def test_teacher_not_qualified_for_the_subject():
    state = make_state([entry(1, subject=ICT, teacher=BEN, room=LAB)])
    conflict = next(c for c in detect(state) if c.code == "TEACHER_NOT_QUALIFIED")
    assert conflict.teacher_id == BEN and conflict.subject_id == ICT and "ICT" in conflict.message
    assert "TEACHER_NOT_QUALIFIED" not in codes(make_state([entry(1, subject=ICT, teacher=ANA, room=LAB)]))


def test_entry_without_a_teacher_has_no_teacher_conflicts():
    assert errors(detect(make_state([entry(1, teacher=None)]))) == []


# --- 5. teacher unavailable slots ---------------------------------------------


def test_teacher_unavailable_slot():
    ana = TeacherInfo(ANA, "Ana", 360, 1800, frozenset({MATH}), unavailable=frozenset({(MON, P1)}))
    state = make_state([entry(1), entry(2, day=TUE)])
    state.teachers[ANA] = ana
    found = [c for c in detect(state) if c.code == "TEACHER_UNAVAILABLE"]
    assert [c.entry_ids for c in found] == [(1,)]  # Tuesday is fine


def test_teacher_unavailable_slot_blocks_overlapping_period_of_another_shift():
    ana = TeacherInfo(ANA, "Ana", 360, 1800, frozenset({MATH}), unavailable=frozenset({(MON, P3)}))
    state = make_state([entry(1, section=S_PM, period=A1)])
    state.teachers[ANA] = ana
    assert "TEACHER_UNAVAILABLE" in codes(state)


# --- 6. room type -------------------------------------------------------------


def test_room_type_mismatch():
    in_lecture_room = make_state([entry(1, subject=ICT, room=R1)])
    conflict = next(c for c in detect(in_lecture_room) if c.code == "ROOM_TYPE_MISMATCH")
    assert conflict.room_id == R1 and "computer lab" in conflict.message
    assert "ROOM_TYPE_MISMATCH" not in codes(make_state([entry(1, subject=ICT, room=LAB)]))


# --- 7. room capacity ---------------------------------------------------------


def test_room_over_capacity():
    state = make_state([entry(1)])
    state.rooms[R1] = RoomInfo(R1, "Room 1", "lecture", 39)
    conflict = next(c for c in detect(state) if c.code == "ROOM_OVER_CAPACITY")
    assert "39" in conflict.message and "40" in conflict.message
    state.rooms[R1] = RoomInfo(R1, "Room 1", "lecture", 40)  # exactly full is allowed
    assert "ROOM_OVER_CAPACITY" not in codes(state)


# --- 8. load limits -----------------------------------------------------------


def test_teacher_daily_overload():
    state = make_state([entry(1, period=P1), entry(2, period=P2), entry(3, period=P3)])
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 120, 1800, frozenset({MATH}))
    conflict = next(c for c in detect(state) if c.code == "TEACHER_DAILY_OVERLOAD")
    assert conflict.day == MON and conflict.entry_ids == (1, 2, 3)
    assert "3 h" in conflict.message and "2 h" in conflict.message
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 180, 1800, frozenset({MATH}))  # at the limit
    assert "TEACHER_DAILY_OVERLOAD" not in codes(state)


def test_teacher_weekly_overload():
    state = make_state([entry(1, day=MON), entry(2, day=TUE), entry(3, day=WED)])
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 360, 120, frozenset({MATH}))
    conflict = next(c for c in detect(state) if c.code == "TEACHER_WEEKLY_OVERLOAD")
    assert conflict.teacher_id == ANA and conflict.entry_ids == (1, 2, 3)
    assert "TEACHER_DAILY_OVERLOAD" not in codes(state)


# --- 9. required weekly hours -------------------------------------------------


def test_subject_hours_under_is_reported_as_incomplete():
    state = make_state([entry(1)], [Requirement(S_A, MATH, 240)])
    conflict = next(c for c in detect(state) if c.code == "SUBJECT_HOURS_UNDER")
    assert conflict.severity == "incomplete" and conflict.section_id == S_A and conflict.subject_id == MATH
    assert "1 h" in conflict.message and "4 h" in conflict.message
    assert errors(detect(state)) == []


def test_subject_with_nothing_scheduled_is_incomplete():
    assert codes(make_state([], [Requirement(S_A, MATH, 60)])) == ["SUBJECT_HOURS_UNDER"]


def test_subject_hours_over():
    state = make_state([entry(1, day=MON), entry(2, day=TUE)], [Requirement(S_A, MATH, 60)])
    conflict = next(c for c in detect(state) if c.code == "SUBJECT_HOURS_OVER")
    assert conflict.severity == "error" and conflict.entry_ids == (1, 2)


def test_subject_hours_allow_rounding_up_to_whole_periods():
    # 90 required minutes cannot be met exactly with 60-minute periods:
    # two periods (120) is the smallest that satisfies it, three is too many.
    two = make_state([entry(1, day=MON), entry(2, day=TUE)], [Requirement(S_A, MATH, 90)])
    assert codes(two) == []
    three = make_state([entry(1, day=MON), entry(2, day=TUE), entry(3, day=WED)], [Requirement(S_A, MATH, 90)])
    assert "SUBJECT_HOURS_OVER" in codes(three)


# --- combined sections --------------------------------------------------------


def test_combined_sections_are_one_class_not_a_double_booking():
    state = make_state([entry(1, group=7), entry(2, section=S_B, group=7)])
    state.rooms[R1] = RoomInfo(R1, "Room 1", "lecture", 80)
    assert errors(detect(state)) == []


def test_combined_sections_add_their_head_counts_for_capacity():
    state = make_state([entry(1, group=7), entry(2, section=S_B, group=7)])  # 80 students, room holds 45
    conflict = next(c for c in detect(state) if c.code == "ROOM_OVER_CAPACITY")
    assert conflict.entry_ids == (1, 2) and "80" in conflict.message


def test_combined_class_counts_once_towards_teacher_load():
    state = make_state([entry(1, group=7), entry(2, section=S_B, group=7)])
    state.rooms[R1] = RoomInfo(R1, "Room 1", "lecture", 80)
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 60, 60, frozenset({MATH}))
    assert errors(detect(state)) == []


def test_combined_class_still_clashes_with_a_different_class():
    state = make_state([entry(1, group=7), entry(2, section=S_B, group=7), entry(3, section=S_PM, period=P1, room=R2)])
    assert "TEACHER_DOUBLE_BOOKED" in codes(state)


# --- teacher loading ----------------------------------------------------------


def load_of(state: State, teacher_id: int):
    return next(load for load in teacher_loads(state) if load.teacher_id == teacher_id)


def test_teacher_load_adds_assigned_hours_and_flags_weekly_limit():
    reqs = [Requirement(S_A, MATH, 240, ANA), Requirement(S_B, MATH, 240, ANA), Requirement(S_A, SCI, 240, BEN)]
    state = make_state([entry(1)], reqs)
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 360, 420, frozenset({MATH}))
    ana, ben = load_of(state, ANA), load_of(state, BEN)
    assert (ana.assigned_minutes, ana.scheduled_minutes, ana.status) == (480, 60, "over")
    assert "weekly limit is 7 h" in ana.issues[0]
    assert (ben.assigned_minutes, ben.status, ben.issues) == (240, "ok", ())


def test_teacher_load_counts_a_combined_class_once():
    reqs = [Requirement(S_A, MATH, 240, ANA, group=5), Requirement(S_B, MATH, 240, ANA, group=5)]
    assert load_of(make_state([], reqs), ANA).assigned_minutes == 240


def test_teacher_load_respects_daily_limit_and_unavailable_time():
    # 1 h/day over 5 days = 5 h capacity even though the weekly limit is 30 h.
    state = make_state([], [Requirement(S_A, MATH, 360, ANA)])
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 60, 1800, frozenset({MATH}))
    load = load_of(state, ANA)
    assert load.capacity_minutes == 300 and load.status == "over" and "daily limit" in load.issues[0]

    # Unavailable all Monday: only 4 days x 1 h remain.
    blocked = frozenset((MON, p) for p in (P1, P2, P3, A1, A2))
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 60, 1800, frozenset({MATH}), blocked)
    assert load_of(state, ANA).capacity_minutes == 240


def test_teacher_load_flags_unqualified_assignment():
    state = make_state([], [Requirement(S_A, ICT, 60, BEN)])
    assert load_of(state, BEN).issues == ("Not qualified for: ICT.",)


# --- what-if checks and suggested fixes ---------------------------------------


def test_check_placement_reports_what_a_move_would_break():
    state = make_state([entry(1), entry(2, section=S_B, room=R2, period=P2)])
    moving = [state.entries[1]]
    assert {c.code for c in check_placement(state, moving, MON, P1)} == {"TEACHER_DOUBLE_BOOKED"}
    assert check_placement(state, moving, TUE, P1) == []
    assert state.entries[1].period_id == P2  # the real timetable is untouched


def test_suggested_fix_moves_a_double_booked_class_to_a_free_slot():
    state = make_state([entry(1), entry(2, section=S_B, room=R2)])
    fixes = suggest_fixes(state, 2)
    moves = [f for f in fixes if f.kind == "move"]
    assert moves and moves[0].label == "Move to Monday Period 2"
    for fix in moves:
        fixed = state.replacing([replace(state.entries[1], day=fix.day, period_id=fix.period_id)])
        assert errors(detect(fixed)) == []


def test_suggested_fix_offers_another_qualified_teacher():
    state = make_state([entry(1), entry(2, section=S_B, room=R2)])
    teachers = [f for f in suggest_fixes(state, 2) if f.kind == "teacher"]
    assert [(f.teacher_id, f.label) for f in teachers] == [(BEN, "Reassign MATH to Ben")]


def test_suggested_fix_offers_a_suitable_room():
    state = make_state([entry(1, subject=ICT, room=R1)])
    fixes = suggest_fixes(state, 1)
    assert [(f.kind, f.room_id) for f in fixes] == [("room", LAB)]


def test_suggested_room_fix_skips_rooms_that_are_taken_or_too_small():
    state = make_state([entry(1), entry(2, section=S_B, teacher=BEN)])  # both in Room 1
    state.rooms[R2] = RoomInfo(R2, "Room 2", "lecture", 10)
    assert [f for f in suggest_fixes(state, 2) if f.kind == "room"] == []


def test_suggested_moves_only_use_the_sections_own_shift_and_free_cells():
    state = make_state([entry(1), entry(2, section=S_B, room=R2), entry(3, section=S_B, room=R2, period=P2, teacher=BEN)])
    moves = [f for f in suggest_fixes(state, 2, per_kind=50) if f.kind == "move"]
    assert moves and all(f.period_id in (P1, P2, P3) for f in moves)
    assert (MON, P2) not in {(f.day, f.period_id) for f in moves}  # 11-B already has a class there


@pytest.mark.parametrize("pinned,expected_empty", [(True, True), (False, False)])
def test_pinned_entries_get_no_suggestions(pinned, expected_empty):
    state = make_state([entry(1), entry(2, section=S_B, room=R2, pinned=pinned)])
    assert (suggest_fixes(state, 2) == []) is expected_empty


def test_no_suggestions_for_an_entry_without_conflicts():
    assert suggest_fixes(make_state([entry(1)]), 1) == []


# --- substitution finder ------------------------------------------------------


def test_substitutes_must_be_free_available_and_within_the_daily_limit():
    cara, dan, eve = 3, 4, 5
    state = make_state([entry(1), entry(2, section=S_B, teacher=BEN, room=R2), entry(3, section=S_B, teacher=dan, room=R2, period=P2)])
    state.teachers[cara] = TeacherInfo(cara, "Cara", 360, 1800, frozenset({MATH}), unavailable=frozenset({(MON, P1)}))
    state.teachers[dan] = TeacherInfo(dan, "Dan", 60, 1800, frozenset({MATH}))  # already teaches 1 h on Monday
    state.teachers[eve] = TeacherInfo(eve, "Eve", 360, 1800, frozenset())
    found = find_substitutes(state, 1)  # who can cover Ana's Monday period 1 class?
    assert [s.teacher_id for s in found] == [eve]  # Ben is teaching, Cara unavailable, Dan at his daily limit
    assert found[0].qualified is False and found[0].notes == ("Not qualified for this subject",)
    assert found[0].day_minutes == 60


def test_substitutes_are_ranked_qualified_first_then_familiar_then_lightest_day():
    cara, dan, eve = 3, 4, 5
    state = make_state(
        [
            entry(1),  # the class to cover: 11-A MATH, Monday period 1
            entry(2, period=P2, subject=SCI, teacher=dan, room=R2),  # Dan already teaches 11-A
            entry(3, section=S_B, period=P3, teacher=eve, room=R2),
        ]
    )
    state.teachers[cara] = TeacherInfo(cara, "Cara", 360, 1800, frozenset({MATH}))
    state.teachers[dan] = TeacherInfo(dan, "Dan", 360, 1800, frozenset({MATH, SCI}))
    state.teachers[eve] = TeacherInfo(eve, "Eve", 360, 60, frozenset({MATH}))
    state.teachers[BEN] = TeacherInfo(BEN, "Ben", 360, 1800, frozenset())
    found = find_substitutes(state, 1)
    assert [s.teacher_id for s in found] == [dan, cara, eve, BEN]
    assert found[0].knows_section and found[0].day_minutes == 120
    assert found[2].notes == ("Would pass the weekly limit this week",)
    assert find_substitutes(state, 999) == []
