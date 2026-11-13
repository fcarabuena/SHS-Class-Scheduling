import datetime as dt
from typing import Any, Literal

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import AvailabilityKind, Role, RoomType, SubjectType

GradeLevel = Literal[11, 12]
SemesterNumber = Literal[1, 2]
Code = Field(min_length=1, max_length=20)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int


def _strip(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


class In(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, v: Any) -> Any:
        return _strip(v)


def _normalize_email(v: str) -> str:
    v = v.strip().lower()
    local, _, domain = v.partition("@")
    if not local or "." not in domain or " " in v:
        raise ValueError("Enter a valid email address")
    return v


Email = Annotated[str, Field(max_length=254), AfterValidator(_normalize_email)]


# --- auth & users -----------------------------------------------------------


class RegisterIn(In):
    school_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    email: Email
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(Out):
    school_id: int
    email: str
    full_name: str
    role: Role
    teacher_id: int | None
    is_active: bool
    is_platform_admin: bool = False


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(In):
    email: Email
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=128)
    role: Role
    teacher_id: int | None = None


class UserUpdate(In):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: str | None = Field(default=None, min_length=10, max_length=128)
    role: Role | None = None
    teacher_id: int | None = None
    is_active: bool | None = None


# --- school -----------------------------------------------------------------


class SchoolIn(In):
    name: str = Field(min_length=2, max_length=200)
    deped_school_id: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=300)
    division: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    logo_url: str | None = Field(default=None, max_length=500)
    settings: dict[str, Any] | None = None

    @field_validator("settings")
    @classmethod
    def _check_signatories(cls, settings: dict[str, Any] | None) -> dict[str, Any] | None:
        """Signatories printed under exported timetables: label, name, position."""
        if settings is None or "signatories" not in settings:
            return settings
        rows = settings["signatories"]
        if not isinstance(rows, list) or len(rows) > 6:
            raise ValueError("signatories must be a list of at most 6 people")
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("each signatory needs a label, a name and a position")
            item = {key: str(row.get(key) or "").strip() for key in ("label", "name", "position")}
            if not item["label"] or not item["name"]:
                raise ValueError("each signatory needs a label (for example 'Prepared by') and a name")
            if len(item["label"]) > 60 or len(item["name"]) > 120 or len(item["position"]) > 120:
                raise ValueError("a signatory's label, name or position is too long")
            cleaned.append(item)
        return {**settings, "signatories": cleaned}


class SchoolOut(Out):
    name: str
    deped_school_id: str | None
    address: str | None
    division: str | None
    region: str | None
    logo_url: str | None
    settings: dict[str, Any]
    onboarding_completed: bool


# --- calendar ---------------------------------------------------------------


class _DateRange(In):
    start_date: dt.date
    end_date: dt.date

    @model_validator(mode="after")
    def _check_range(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class SemesterDates(_DateRange):
    pass


class SemesterIn(_DateRange):
    is_active: bool = False


class SemesterOut(Out):
    school_year_id: int
    number: int
    start_date: dt.date
    end_date: dt.date
    is_active: bool


class SchoolYearIn(_DateRange):
    name: str = Field(min_length=4, max_length=20)
    is_active: bool = True


class SchoolYearSetupIn(SchoolYearIn):
    """Onboarding: a school year together with its two semesters."""

    first_semester: SemesterDates
    second_semester: SemesterDates

    @model_validator(mode="after")
    def _check_semesters(self):
        s1, s2 = self.first_semester, self.second_semester
        if s1.start_date < self.start_date or s2.end_date > self.end_date:
            raise ValueError("Semesters must fall inside the school year")
        if s2.start_date <= s1.end_date:
            raise ValueError("The second semester must start after the first semester ends")
        return self


class SchoolYearOut(Out):
    name: str
    start_date: dt.date
    end_date: dt.date
    is_active: bool
    semesters: list[SemesterOut]


class _TimeRange(In):
    start_time: dt.time
    end_time: dt.time

    @model_validator(mode="after")
    def _check_times(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ShiftIn(_TimeRange):
    name: str = Field(min_length=1, max_length=60)


class PeriodIn(_TimeRange):
    name: str = Field(min_length=1, max_length=60)
    is_break: bool = False


class PeriodOut(Out):
    shift_id: int
    name: str
    sort_order: int
    start_time: dt.time
    end_time: dt.time
    is_break: bool


class ShiftOut(Out):
    name: str
    start_time: dt.time
    end_time: dt.time
    periods: list[PeriodOut]


# --- curriculum -------------------------------------------------------------


class TrackIn(In):
    code: str = Code
    name: str = Field(min_length=1, max_length=120)


class TrackOut(Out):
    code: str
    name: str


class StrandIn(In):
    track_id: int
    code: str = Code
    name: str = Field(min_length=1, max_length=160)


class StrandOut(Out):
    track_id: int
    code: str
    name: str


class SubjectIn(In):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    type: SubjectType
    hours_per_week: float = Field(gt=0, le=40)
    required_room_type: RoomType = RoomType.lecture
    is_heavy: bool = False


class SubjectOut(Out):
    code: str
    name: str
    type: SubjectType
    hours_per_week: float
    required_room_type: RoomType
    is_heavy: bool


class CurriculumEntryIn(In):
    strand_id: int
    subject_id: int
    grade_level: GradeLevel
    semester_number: SemesterNumber
    hours_per_week: float | None = Field(default=None, gt=0, le=40)


class CurriculumEntryOut(Out):
    strand_id: int
    subject_id: int
    grade_level: int
    semester_number: int
    hours_per_week: float | None


# --- resources --------------------------------------------------------------


class RoomIn(In):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    type: RoomType = RoomType.lecture
    capacity: int = Field(gt=0, le=2000)


class RoomOut(Out):
    code: str
    name: str
    type: RoomType
    capacity: int


class AvailabilityIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    day_of_week: int = Field(ge=1, le=6)
    period_id: int
    kind: AvailabilityKind


class TeacherIn(In):
    employee_id: str = Field(min_length=1, max_length=30)
    full_name: str = Field(min_length=2, max_length=200)
    # When omitted, the school's configured defaults are used.
    max_daily_hours: float | None = Field(default=None, gt=0, le=24)
    max_weekly_hours: float | None = Field(default=None, gt=0, le=100)
    is_active: bool = True
    qualified_subject_ids: list[int] = []
    availability: list[AvailabilityIn] = []

    @model_validator(mode="after")
    def _check_limits(self):
        if self.max_daily_hours and self.max_weekly_hours and self.max_daily_hours > self.max_weekly_hours:
            raise ValueError("max_daily_hours cannot exceed max_weekly_hours")
        slots = [(a.day_of_week, a.period_id) for a in self.availability]
        if len(slots) != len(set(slots)):
            raise ValueError("A slot can only be marked once (unavailable or preferred)")
        return self


class TeacherOut(Out):
    employee_id: str
    full_name: str
    max_daily_hours: float
    max_weekly_hours: float
    is_active: bool
    qualified_subject_ids: list[int]
    availability: list[AvailabilityIn]


class SectionIn(In):
    name: str = Field(min_length=1, max_length=80)
    strand_id: int
    grade_level: GradeLevel
    shift_id: int
    adviser_id: int | None = None
    student_count: int = Field(default=0, ge=0, le=500)
    # When omitted, the active school year is used.
    school_year_id: int | None = None


class SectionOut(Out):
    school_year_id: int
    name: str
    strand_id: int
    grade_level: int
    shift_id: int
    adviser_id: int | None
    student_count: int


# --- misc -------------------------------------------------------------------


class AuditLogOut(Out):
    user_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    changes: dict[str, Any] | None
    created_at: dt.datetime


class ImportRowError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    dry_run: bool
    created: int
    updated: int
    errors: list[ImportRowError]


class ApplyTemplateIn(BaseModel):
    strand_codes: list[str] = Field(min_length=1)


class ApplyTemplateOut(BaseModel):
    tracks: int
    strands: int
    subjects: int
    curriculum_entries: int
