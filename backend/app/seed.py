"""Creates a demo school with fictional data.

    python -m app.seed

All names are invented placeholders. Safe to run twice: it does nothing if
the demo admin account already exists.
"""

import datetime as dt

from sqlalchemy import select

from .db import SessionLocal
from .models import Period, Role, Room, School, SchoolYear, Section, Semester, Shift, Strand, Subject, Teacher, User
from .routers.templates import apply_template
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


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == DEMO_USERS[0][0])):
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
        db.commit()

    print("Demo school created. Sign in with any of:")
    for email, _, role in DEMO_USERS:
        print(f"  {role.value:<10} {email}  /  {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
