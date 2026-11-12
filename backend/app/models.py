"""Database schema.

Every tenant-owned table carries ``school_id`` so that all queries can be
scoped to the signed-in user's school. No student personal data is stored
anywhere: sections only hold a head count.
"""

import datetime as dt
import enum
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- enums ------------------------------------------------------------------


class Role(str, enum.Enum):
    admin = "admin"
    scheduler = "scheduler"
    teacher = "teacher"


class SubjectType(str, enum.Enum):
    core = "core"
    applied = "applied"
    specialized = "specialized"


class RoomType(str, enum.Enum):
    lecture = "lecture"
    computer_lab = "computer_lab"
    science_lab = "science_lab"
    shop = "shop"
    home_economics = "home_economics"
    gym = "gym"


class AvailabilityKind(str, enum.Enum):
    unavailable = "unavailable"
    preferred = "preferred"


def _enum(e: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR + CHECK so adding a value is a simple migration.
    return Enum(e, native_enum=False, length=32, values_callable=lambda x: [m.value for m in x])


def _school_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)


DEFAULT_SCHOOL_SETTINGS: dict[str, Any] = {
    # Admin-editable defaults. Verify against current DepEd rules / RA 4670.
    "default_max_daily_hours": 6,
    "default_max_weekly_hours": 30,
    "school_days": [1, 2, 3, 4, 5],  # 1 = Monday ... 6 = Saturday
    "soft_constraint_weights": {
        "max_consecutive_periods": 5,
        "balance_teacher_load": 3,
        "avoid_section_gaps": 4,
        "prefer_teacher_slots": 2,
        "minimize_room_changes": 2,
        "spread_subject_days": 3,
        "heavy_subjects_not_last": 2,
    },
}


# --- tenant & access --------------------------------------------------------


class School(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    deped_school_id: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))
    division: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: dict(DEFAULT_SCHOOL_SETTINGS))
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# --- calendar ---------------------------------------------------------------


class SchoolYear(Base):
    __tablename__ = "school_years"
    __table_args__ = (UniqueConstraint("school_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    name: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    semesters: Mapped[list["Semester"]] = relationship(
        back_populates="school_year", cascade="all, delete-orphan", order_by="Semester.number"
    )


class Semester(Base):
    __tablename__ = "semesters"
    __table_args__ = (
        UniqueConstraint("school_year_id", "number"),
        CheckConstraint("number IN (1, 2)", name="ck_semesters_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    school_year_id: Mapped[int] = mapped_column(ForeignKey("school_years.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    school_year: Mapped[SchoolYear] = relationship(back_populates="semesters")


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (UniqueConstraint("school_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    name: Mapped[str] = mapped_column(String(60))
    start_time: Mapped[dt.time] = mapped_column(Time)
    end_time: Mapped[dt.time] = mapped_column(Time)

    periods: Mapped[list["Period"]] = relationship(
        back_populates="shift", cascade="all, delete-orphan", order_by="Period.sort_order"
    )


class Period(Base):
    """One row of a shift's bell schedule. Breaks are periods with is_break."""

    __tablename__ = "periods"
    __table_args__ = (UniqueConstraint("shift_id", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[dt.time] = mapped_column(Time)
    end_time: Mapped[dt.time] = mapped_column(Time)
    is_break: Mapped[bool] = mapped_column(Boolean, default=False)

    shift: Mapped[Shift] = relationship(back_populates="periods")


# --- curriculum -------------------------------------------------------------


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("school_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))


class Strand(Base):
    __tablename__ = "strands"
    __table_args__ = (UniqueConstraint("school_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("school_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[SubjectType] = mapped_column(_enum(SubjectType))
    hours_per_week: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    required_room_type: Mapped[RoomType] = mapped_column(_enum(RoomType), default=RoomType.lecture)
    is_heavy: Mapped[bool] = mapped_column(Boolean, default=False)


class CurriculumEntry(Base):
    """Which subject a strand takes in a given grade level and semester."""

    __tablename__ = "curriculum_entries"
    __table_args__ = (
        UniqueConstraint("strand_id", "grade_level", "semester_number", "subject_id"),
        CheckConstraint("grade_level IN (11, 12)", name="ck_curriculum_grade"),
        CheckConstraint("semester_number IN (1, 2)", name="ck_curriculum_semester"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    strand_id: Mapped[int] = mapped_column(ForeignKey("strands.id", ondelete="CASCADE"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    grade_level: Mapped[int] = mapped_column(Integer)
    semester_number: Mapped[int] = mapped_column(Integer)
    # Optional override of Subject.hours_per_week for this strand/grade/semester.
    hours_per_week: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))


# --- resources --------------------------------------------------------------


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("school_id", "code"),
        CheckConstraint("capacity > 0", name="ck_rooms_capacity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[RoomType] = mapped_column(_enum(RoomType), default=RoomType.lecture)
    capacity: Mapped[int] = mapped_column(Integer)


teacher_subjects = Table(
    "teacher_subjects",
    Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class Teacher(Base):
    """Minimum personal data only: name, employee ID and load limits."""

    __tablename__ = "teachers"
    __table_args__ = (UniqueConstraint("school_id", "employee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    employee_id: Mapped[str] = mapped_column(String(30))
    full_name: Mapped[str] = mapped_column(String(200))
    max_daily_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    max_weekly_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    subjects: Mapped[list[Subject]] = relationship(secondary=teacher_subjects, lazy="selectin")
    availability: Mapped[list["TeacherAvailability"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def qualified_subject_ids(self) -> list[int]:
        return sorted(s.id for s in self.subjects)


class TeacherAvailability(Base):
    """A slot a teacher cannot teach in (hard) or would like to teach in (soft)."""

    __tablename__ = "teacher_availability"
    __table_args__ = (
        UniqueConstraint("teacher_id", "day_of_week", "period_id"),
        CheckConstraint("day_of_week BETWEEN 1 AND 6", name="ck_availability_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"))
    day_of_week: Mapped[int] = mapped_column(Integer)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    kind: Mapped[AvailabilityKind] = mapped_column(_enum(AvailabilityKind))

    teacher: Mapped[Teacher] = relationship(back_populates="availability")


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("school_id", "school_year_id", "name"),
        CheckConstraint("grade_level IN (11, 12)", name="ck_sections_grade"),
        CheckConstraint("student_count >= 0", name="ck_sections_students"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    school_year_id: Mapped[int] = mapped_column(ForeignKey("school_years.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    strand_id: Mapped[int] = mapped_column(ForeignKey("strands.id", ondelete="RESTRICT"))
    grade_level: Mapped[int] = mapped_column(Integer)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="RESTRICT"))
    adviser_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"))
    student_count: Mapped[int] = mapped_column(Integer, default=0)


# --- scheduling (used from Phase 1B onward) ---------------------------------


class TeachingAssignment(Base):
    """Teacher loading: who teaches a subject to a section in a semester."""

    __tablename__ = "teaching_assignments"
    __table_args__ = (UniqueConstraint("semester_id", "section_id", "subject_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"))
    # Assignments sharing a group id are taught together as one combined class.
    combined_group_id: Mapped[int | None] = mapped_column(Integer, index=True)


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"
    __table_args__ = (
        # Hard constraint 3: a section has at most one subject per slot.
        # Deferred to commit so two classes can swap slots in one transaction.
        UniqueConstraint(
            "semester_id",
            "section_id",
            "day_of_week",
            "period_id",
            name="uq_schedule_entries_slot",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("day_of_week BETWEEN 1 AND 6", name="ck_schedule_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"), index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Entries sharing a group id are one combined class (same teacher + room).
    combined_group_id: Mapped[int | None] = mapped_column(Integer, index=True)


class SolverJob(Base):
    """One run of the automatic scheduler. The proposed timetable waits in
    ``result`` until a user applies it."""

    __tablename__ = "solver_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = _school_fk()
    semester_id: Mapped[int] = mapped_column(ForeignKey("semesters.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued, running, done, failed
    mode: Mapped[str] = mapped_column(String(20))  # rebuild or fill
    time_limit: Mapped[int] = mapped_column(Integer)
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
