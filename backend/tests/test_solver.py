"""Unit tests for the CP-SAT timetable generator. No database needed."""

from app.scheduling.engine import Entry, Requirement, RoomInfo, SectionInfo, SubjectInfo, TeacherInfo, detect, errors
from app.scheduling.solver import Options, precheck, solve

from .test_conflict_engine import A1, ANA, BEN, ICT, LAB, MATH, MON, P1, P2, P3, R1, R2, S_A, S_B, S_PM, SCI, TUE, entry, make_state

FAST = Options(time_limit=5)


def placed(result, section, subject) -> list[Entry]:
    return [e for e in result.entries if (e.section_id, e.subject_id) == (section, subject)]


def assert_valid(state, result) -> None:
    assert errors(detect(state.with_entries(result.entries))) == []


def test_generates_a_complete_conflict_free_timetable():
    reqs = [
        Requirement(S_A, MATH, 240, ANA),
        Requirement(S_A, SCI, 180, BEN),
        Requirement(S_A, ICT, 60, ANA),
        Requirement(S_B, MATH, 240, BEN),
        Requirement(S_B, SCI, 180, ANA),
    ]
    state = make_state([], reqs)
    result = solve(state, FAST)
    assert result.status == "complete" and result.shortages == []
    assert result.placed_minutes == result.required_minutes == 900 and result.added == 15
    assert detect(state.with_entries(result.entries)) == []  # no errors and nothing short
    assert {e.room_id for e in placed(result, S_A, ICT)} == {LAB}  # room type respected
    assert all(e.id < 0 for e in result.entries)  # new classes, not saved yet


def test_spreads_a_subject_over_different_days():
    state = make_state([], [Requirement(S_A, MATH, 180, ANA)])
    result = solve(state, FAST)
    assert len({e.day for e in placed(result, S_A, MATH)}) == 3


def test_teacher_unavailable_slots_and_daily_limit_are_respected():
    unavailable = frozenset((MON, p) for p in (P1, P2, P3))
    state = make_state([], [Requirement(S_A, MATH, 240, ANA)])
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 60, 1800, frozenset({MATH}), unavailable)
    result = solve(state, FAST)
    assert result.status == "complete"
    days = [e.day for e in placed(result, S_A, MATH)]
    assert sorted(days) == [2, 3, 4, 5]  # one hour a day, never Monday
    assert_valid(state, result)


def test_teacher_weekly_limit_leaves_a_shortage_with_an_explanation():
    state = make_state([], [Requirement(S_A, MATH, 240, ANA)])
    state.teachers[ANA] = TeacherInfo(ANA, "Ana", 360, 120, frozenset({MATH}))
    result = solve(state, FAST)
    assert result.status == "partial" and result.placed_minutes == 120
    shortage = result.shortages[0]
    assert (shortage.section_ids, shortage.subject_id, shortage.placed_minutes) == ([S_A], MATH, 120)
    assert "MATH for 11-A: 2 h could not be placed" in shortage.message
    assert "Ana would pass the weekly limit" in shortage.message
    assert any("weekly limit is 2 h" in problem for problem in result.problems)
    assert_valid(state, result)


def test_more_hours_than_the_week_has_is_explained_before_solving():
    state = make_state([], [Requirement(S_A, MATH, 600, ANA), Requirement(S_A, SCI, 600, BEN)])  # 20 h, 15 h of periods
    assert any("11-A needs 20 h of classes a week, but its shift only has 15 h" in p for p in precheck(state))
    result = solve(state, FAST)
    assert result.status == "partial" and result.placed_minutes == 900
    assert all("the section already has a class" in s.message for s in result.shortages)


def test_pinned_classes_stay_and_the_rest_is_rebuilt_around_them():
    pinned = entry(1, day=TUE, period=P3, pinned=True)
    loose = entry(2, day=MON, period=P1)
    state = make_state([pinned, loose], [Requirement(S_A, MATH, 180, ANA), Requirement(S_B, MATH, 60, ANA)])
    result = solve(state, FAST)
    assert result.status == "complete" and result.kept == 1
    assert pinned in result.entries and loose not in result.entries
    assert len(placed(result, S_A, MATH)) == 3  # the pinned hour counts towards the 3 h
    assert not any((e.day, e.period_id) == (TUE, P3) for e in placed(result, S_B, MATH))  # Ana is busy then
    assert_valid(state, result)


def test_fill_mode_keeps_every_existing_class():
    existing = [entry(1, day=MON, period=P1), entry(2, day=MON, period=P2)]
    state = make_state(existing, [Requirement(S_A, MATH, 240, ANA)])
    result = solve(state, Options(mode="fill", time_limit=5))
    assert result.kept == 2 and result.added == 2 and all(e in result.entries for e in existing)
    assert result.status == "complete"


def test_a_clash_between_pinned_classes_does_not_stop_the_solver():
    clash = [entry(1, pinned=True), entry(2, section=S_B, room=R2, pinned=True)]  # Ana twice on Monday period 1
    state = make_state(clash, [Requirement(S_A, MATH, 120, ANA), Requirement(S_B, MATH, 120, ANA)])
    result = solve(state, FAST)
    assert result.status == "complete" and result.kept == 2
    remaining = {c.code for c in errors(detect(state.with_entries(result.entries)))}
    assert remaining == {"TEACHER_DOUBLE_BOOKED"}  # only the one the user pinned


def test_rooms_are_never_double_booked_and_sizes_are_respected():
    # One room that holds 45 and one that holds 30: the 40-student sections must take turns in the big one.
    state = make_state([], [Requirement(S_A, MATH, 300, ANA), Requirement(S_B, MATH, 300, BEN)])
    state.rooms = {R1: RoomInfo(R1, "Room 1", "lecture", 45), R2: RoomInfo(R2, "Room 2", "lecture", 30)}
    result = solve(state, FAST)
    assert result.status == "complete" and {e.room_id for e in result.entries} == {R1}
    assert_valid(state, result)


def test_a_class_too_big_for_every_room_is_placed_without_one_and_reported():
    state = make_state([], [Requirement(S_A, ICT, 60, ANA)])
    state.sections[S_A] = SectionInfo(S_A, "11-A", 1, 60)
    result = solve(state, FAST)
    assert [e.room_id for e in result.entries] == [None]
    assert any("No computer lab room holds the 60 students of 11-A" in p for p in result.problems)


def test_combined_sections_are_scheduled_together():
    reqs = [Requirement(S_A, MATH, 120, ANA, group=7, id=1), Requirement(S_B, MATH, 120, ANA, group=7, id=2)]
    state = make_state([], reqs)
    state.rooms[R1] = RoomInfo(R1, "Hall", "lecture", 90)
    result = solve(state, FAST)
    a = {(e.day, e.period_id, e.room_id) for e in placed(result, S_A, MATH)}
    b = {(e.day, e.period_id, e.room_id) for e in placed(result, S_B, MATH)}
    assert result.status == "complete" and a == b and len(a) == 2
    assert {room for _, _, room in a} == {R1} and {e.group for e in result.entries} == {7}
    assert_valid(state, result)


def test_overlapping_shifts_do_not_double_book_a_teacher():
    # Morning period 3 and afternoon period 1 overlap by clock; Ana teaches in both shifts.
    state = make_state([], [Requirement(S_A, MATH, 900, ANA), Requirement(S_PM, MATH, 300, ANA)])
    result = solve(state, FAST)
    assert_valid(state, result)
    morning_p3 = {e.day for e in placed(result, S_A, MATH) if e.period_id == P3}
    afternoon_p1 = {e.day for e in placed(result, S_PM, MATH) if e.period_id == A1}
    assert not morning_p3 & afternoon_p1


def test_soft_preferences_preferred_slots_and_heavy_subjects():
    preferred = frozenset((d, P1) for d in range(1, 6))
    state = make_state([], [Requirement(S_A, MATH, 300, ANA), Requirement(S_A, SCI, 300, BEN)])
    state.teachers[BEN] = TeacherInfo(BEN, "Ben", 360, 1800, frozenset({MATH, SCI}), preferred=preferred)
    state.subjects[MATH] = SubjectInfo(MATH, "MATH", "Mathematics", "lecture", heavy=True)
    result = solve(state, FAST)
    assert {e.period_id for e in placed(result, S_A, SCI)} == {P1}  # Ben gets his preferred period
    assert P3 not in {e.period_id for e in placed(result, S_A, MATH)}  # heavy subject is not last


def test_nothing_to_schedule_and_stop_request():
    assert solve(make_state([], []), FAST).status == "nothing_to_do"
    seen = []
    state = make_state([], [Requirement(S_A, MATH, 240, ANA)])
    result = solve(state, FAST, on_progress=seen.append, should_stop=lambda: True)
    assert seen and seen[0]["required_hours"] == 4 and result.status in ("complete", "partial")
