"""Creates a demo school with fictional data.

    python -m app.seed

All names are invented placeholders. Safe to run twice: it does nothing if
the demo admin account already exists (it then only adds the demo teacher
loading and timetable if the school has none yet).
"""

import datetime as dt

from sqlalchemy import select

from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    CurriculumEntry,
    Period,
    Role,
    Room,
    ScheduleEntry,
    School,
    SchoolYear,
    Section,
    Semester,
    Shift,
    Strand,
    Subject,
    Teacher,
    TeachingAssignment,
    User,
)
from .routers.templates import apply_template
from .scheduling import engine as eng
from .scheduling.state import load_state, pick_room
from .security import hash_password

DEMO_PASSWORD = "DemoPass#2026"
DEMO_USERS = [
    ("admin@demo.example", "Demo Administrator", Role.admin),
    ("scheduler@demo.example", "Demo Scheduler", Role.scheduler),
    ("teacher@demo.example", "Demo Teacher", Role.teacher),
]

ROOMS = [
    *[(f"R{100 + i}", f"Room {100 + i}", "lecture", 45) for i in range(1, 9)],
    ("CL1", "Computer Laboratory 1", "computer_lab", 40),
    ("CL2", "Computer Laboratory 2", "computer_lab", 40),
    ("SL1", "Science Laboratory", "science_lab", 40),
    ("GYM", "Covered Court", "gym", 120),
]

# (employee id, fictional name, subject-code prefixes the teacher can handle)
TEACHERS = [
    ("T-0001", "Amihan Dela Cruz", ["CORE-GENMATH", "CORE-STAT", "STEM-PRECAL", "STEM-BASCAL"]),
    ("T-0002", "Bayani Santos", ["CORE-GENMATH", "CORE-STAT", "ABM-BMATH", "ABM-BFIN"]),
    ("T-0003", "Carmela Reyes", ["CORE-ORALCOM", "CORE-RW", "CORE-21LIT", "APP-EAPP"]),
    ("T-0004", "Dakila Ramos", ["CORE-KPWKP", "CORE-PAGBASA", "APP-FPL"]),
    ("T-0005", "Estrella Bautista", ["CORE-ELS", "CORE-PHYSCI", "CORE-EARTHSCI", "CORE-DRRR"]),
    ("T-0006", "Fidel Navarro", ["STEM-CHEM1", "STEM-CHEM2", "STEM-BIO1", "STEM-BIO2"]),
    ("T-0007", "Gloria Mendoza", ["STEM-PHYS1", "STEM-PHYS2", "CORE-PHYSCI"]),
    ("T-0008", "Hiraya Castillo", ["CORE-PERDEV", "CORE-UCSP", "CORE-PHILO", "HUMSS-DISS", "HUMSS-DIASS"]),
    ("T-0009", "Isagani Flores", ["HUMSS-PPG", "HUMSS-IWRBS", "HUMSS-TNCT", "HUMSS-CESC", "HUMSS-CW", "HUMSS-CNF"]),
    ("T-0010", "Juana Villanueva", ["ABM-ORGMAN", "ABM-MKTG", "ABM-FABM1", "ABM-FABM2", "ABM-APPECON", "ABM-ETHICS", "APP-ENTREP"]),
    ("T-0011", "Kidlat Aquino", ["ICT-CSS1", "ICT-CSS2", "ICT-PROG1", "ICT-PROG2", "APP-ETECH", "CORE-MIL"]),
    ("T-0012", "Ligaya Torres", ["CORE-PE1", "CORE-PE2", "CORE-PE3", "CORE-PE4", "CORE-CPAR"]),
    ("T-0013", "Makisig Garcia", ["APP-PR1", "APP-PR2", "APP-III", "CORE-MIL"]),
]

SECTIONS = [
    ("11-STEM-Sampaguita", "STEM", 11, "Morning", 40),
    ("11-ABM-Narra", "ABM", 11, "Morning", 38),
    ("11-HUMSS-Mabini", "HUMSS", 11, "Morning", 42),
    ("11-ICT-Kalayaan", "ICT", 11, "Afternoon", 36),
    ("12-STEM-Ilang-Ilang", "STEM", 12, "Morning", 37),
    ("12-ABM-Molave", "ABM", 12, "Afternoon", 35),
    ("12-HUMSS-Rizal", "HUMSS", 12, "Afternoon", 41),
    ("12-ICT-Bagwis", "ICT", 12, "Afternoon", 33),
]


def _bell_schedule(school_id: int, shift: Shift, first: dt.time, labels: list[tuple[str, int, bool]]) -> None:
    cursor = dt.datetime.combine(dt.date.today(), first)
    for order, (name, minutes, is_break) in enumerate(labels, start=1):
        end = cursor + dt.timedelta(minutes=minutes)
        shift.periods.append(
            Period(
                school_id=school_id,
                name=name,
                sort_order=order,
                start_time=cursor.time(),
                end_time=end.time(),
                is_break=is_break,
            )
        )
        cursor = end


def seed_schedule(db: Session, school_id: int) -> int:
    """Demo teacher loading and a conflict-free starter timetable.

    Subjects come from the curriculum, each goes to the least-loaded qualified
    teacher, and classes are dropped into the first slots the conflict engine
    accepts. Whatever does not fit is left for the user to place. Returns the
    number of classes placed (0 if the school already has assignments).
    """
    if db.scalar(select(TeachingAssignment.id).where(TeachingAssignment.school_id == school_id).limit(1)):
        return 0
    semester = db.scalars(
        select(Semester).where(Semester.school_id == school_id).order_by(Semester.is_active.desc(), Semester.number)
    ).first()
    if semester is None:
        return 0
    sections = db.scalars(
        select(Section).where(Section.school_id == school_id, Section.school_year_id == semester.school_year_id)
    ).all()
    curriculum = db.scalars(
        select(CurriculumEntry).where(
            CurriculumEntry.school_id == school_id, CurriculumEntry.semester_number == semester.number
        )
    ).all()
    rows: dict[tuple[int, int], TeachingAssignment] = {}
    for section in sections:
        for item in curriculum:
            if (item.strand_id, item.grade_level) == (section.strand_id, section.grade_level):
                rows[(section.id, item.subject_id)] = TeachingAssignment(
                    school_id=school_id, semester_id=semester.id, section_id=section.id, subject_id=item.subject_id
                )
    db.add_all(rows.values())
    db.flush()

    state = load_state(db, school_id, semester)
    load = {teacher_id: 0 for teacher_id in state.teachers}
    for req in state.requirements:
        able = [
            t for t in state.teachers.values()
            if req.subject_id in t.qualified and load[t.id] + req.minutes <= t.max_weekly_minutes
        ]
        if able:
            teacher = min(able, key=lambda t: (load[t.id], t.id))
            load[teacher.id] += req.minutes
            rows[(req.section_id, req.subject_id)].teacher_id = teacher.id
    db.flush()

    state = load_state(db, school_id, semester)
    placed: list[eng.Entry] = []
    next_id = -1
    for per_day in (1, 2):  # first spread each subject over the week, then fill up
        for req in state.requirements:
            section = state.sections[req.section_id]
            if req.teacher_id is None:
                continue
            for day in state.days:
                mine = [e for e in placed if (e.section_id, e.subject_id) == (req.section_id, req.subject_id)]
                if sum(state.slots[e.period_id].minutes for e in mine) >= req.minutes:
                    break
                if sum(e.day == day for e in mine) >= per_day:
                    continue
                for slot in sorted(state.slots.values(), key=lambda s: s.start):
                    current = state.with_entries(placed)
                    if slot.shift_id != section.shift_id or not eng.cell_is_free(current, [section.id], day, slot.id):
                        continue
                    room_id = pick_room(current, [section.id], req.subject_id, day, slot.id)
                    if room_id is None:
                        continue
                    trial = eng.Entry(next_id, section.id, req.subject_id, day, slot.id, req.teacher_id, room_id)
                    after = eng.errors(eng.detect(state.with_entries([*placed, trial])))
                    if not eng.for_entries(after, [trial.id]):
                        placed.append(trial)
                        next_id -= 1
                        break
    db.add_all(
        ScheduleEntry(
            school_id=school_id,
            semester_id=semester.id,
            section_id=e.section_id,
            subject_id=e.subject_id,
            teacher_id=e.teacher_id,
            room_id=e.room_id,
            day_of_week=e.day,
            period_id=e.period_id,
        )
        for e in placed
    )
    return len(placed)


def seed() -> None:
    with SessionLocal() as db:
        if existing := db.scalar(select(User).where(User.email == DEMO_USERS[0][0])):
            placed = seed_schedule(db, existing.school_id)
            db.commit()
            if placed:
                print(f"Demo school already exists - added teacher loading and {placed} timetable classes.")
            else:
                print("Demo data already exists - nothing to do.")
            return

        school = School(name="Demo Senior High School", division="Sample Division", region="Sample Region")
        db.add(school)
        db.flush()
        sid = school.id

        users = [
            User(school_id=sid, email=email, full_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD))
            for email, name, role in DEMO_USERS
        ]
        db.add_all(users)

        year = SchoolYear(
            school_id=sid, name="2026-2027", start_date=dt.date(2026, 6, 15), end_date=dt.date(2027, 3, 31)
        )
        year.semesters = [
            Semester(school_id=sid, number=1, start_date=dt.date(2026, 6, 15), end_date=dt.date(2026, 10, 30), is_active=True),
            Semester(school_id=sid, number=2, start_date=dt.date(2026, 11, 9), end_date=dt.date(2027, 3, 31)),
        ]
        db.add(year)

        morning = Shift(school_id=sid, name="Morning", start_time=dt.time(6, 0), end_time=dt.time(12, 0))
        afternoon = Shift(school_id=sid, name="Afternoon", start_time=dt.time(12, 30), end_time=dt.time(18, 30))
        pattern = [
            ("Period 1", 60, False), ("Period 2", 60, False), ("Recess", 20, True),
            ("Period 3", 60, False), ("Period 4", 60, False), ("Period 5", 60, False),
        ]
        _bell_schedule(sid, morning, dt.time(6, 0), pattern)
        _bell_schedule(sid, afternoon, dt.time(12, 30), pattern)
        db.add_all([morning, afternoon])
        db.flush()

        apply_template(db, users[0], ["ABM", "HUMSS", "STEM", "ICT"])
        db.flush()

        db.add_all(Room(school_id=sid, code=c, name=n, type=t, capacity=cap) for c, n, t, cap in ROOMS)

        subjects = {s.code: s for s in db.scalars(select(Subject).where(Subject.school_id == sid))}
        teachers = {}
        for employee_id, name, codes in TEACHERS:
            teachers[employee_id] = Teacher(
                school_id=sid,
                employee_id=employee_id,
                full_name=name,
                max_daily_hours=6,
                max_weekly_hours=30,
                subjects=[subjects[c] for c in codes if c in subjects],
            )
        db.add_all(teachers.values())
        db.flush()
        users[2].teacher_id = teachers["T-0003"].id

        strands = {s.code: s for s in db.scalars(select(Strand).where(Strand.school_id == sid))}
        shifts = {"Morning": morning, "Afternoon": afternoon}
        advisers = list(teachers.values())
        for index, (name, strand, grade, shift, count) in enumerate(SECTIONS):
            db.add(
                Section(
                    school_id=sid,
                    school_year_id=year.id,
                    name=name,
                    strand_id=strands[strand].id,
                    grade_level=grade,
                    shift_id=shifts[shift].id,
                    adviser_id=advisers[index].id,
                    student_count=count,
                )
            )

        school.onboarding_completed = True
        db.flush()
        seed_schedule(db, sid)
        db.commit()

    print("Demo school created. Sign in with any of:")
    for email, _, role in DEMO_USERS:
        print(f"  {role.value:<10} {email}  /  {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
