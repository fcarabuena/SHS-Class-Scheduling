"""School profile, onboarding, school calendar and bell schedule."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from ..deps import AdminUser, CurrentUser, DbSession, EditorUser
from ..models import DEFAULT_SCHOOL_SETTINGS, Period, School, SchoolYear, Semester, Shift
from ..schemas import (
    PeriodIn,
    SchoolIn,
    SchoolOut,
    SchoolYearIn,
    SchoolYearOut,
    SchoolYearSetupIn,
    SemesterIn,
    SemesterOut,
    ShiftIn,
    ShiftOut,
)
from ..services import audit, commit, get_owned

router = APIRouter(prefix="/api", tags=["school"])


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(422, message)


# --- school profile ---------------------------------------------------------


@router.get("/school", response_model=SchoolOut)
def get_school(db: DbSession, user: CurrentUser):
    return db.get(School, user.school_id)


@router.put("/school", response_model=SchoolOut)
def update_school(data: SchoolIn, db: DbSession, admin: AdminUser):
    school = db.get(School, admin.school_id)
    values = data.model_dump(exclude_unset=True)
    if (new_settings := values.pop("settings", None)) is not None:
        # Merge so that unknown/missing keys never wipe the defaults.
        school.settings = {**DEFAULT_SCHOOL_SETTINGS, **(school.settings or {}), **new_settings}
        values_for_audit = {**values, "settings": new_settings}
    else:
        values_for_audit = values
    for key, value in values.items():
        setattr(school, key, value)
    audit(db, admin, "update", "school", school.id, values_for_audit)
    commit(db)
    return school


# --- onboarding -------------------------------------------------------------


def _onboarding_steps(db: DbSession, school_id: int) -> dict[str, bool]:
    shifts = db.scalars(select(Shift).where(Shift.school_id == school_id)).all()
    has_year = db.scalar(select(SchoolYear.id).where(SchoolYear.school_id == school_id).limit(1)) is not None
    return {
        "school_year": has_year,
        "shifts": bool(shifts),
        "periods": bool(shifts) and all(any(not p.is_break for p in s.periods) for s in shifts),
    }


@router.get("/onboarding/status")
def onboarding_status(db: DbSession, user: CurrentUser):
    school = db.get(School, user.school_id)
    return {"completed": school.onboarding_completed, "steps": _onboarding_steps(db, school.id)}


@router.post("/onboarding/complete", response_model=SchoolOut)
def complete_onboarding(db: DbSession, admin: AdminUser):
    missing = [name for name, done in _onboarding_steps(db, admin.school_id).items() if not done]
    if missing:
        raise _unprocessable("Onboarding is not finished. Missing: " + ", ".join(missing))
    school = db.get(School, admin.school_id)
    school.onboarding_completed = True
    audit(db, admin, "complete", "onboarding", school.id)
    commit(db)
    return school


# --- school years & semesters -----------------------------------------------


def _deactivate_other_years(db: DbSession, school_id: int, keep_id: int) -> None:
    db.execute(
        update(SchoolYear).where(SchoolYear.school_id == school_id, SchoolYear.id != keep_id).values(is_active=False)
    )


@router.get("/school-years", response_model=list[SchoolYearOut])
def list_school_years(db: DbSession, user: CurrentUser):
    return db.scalars(
        select(SchoolYear).where(SchoolYear.school_id == user.school_id).order_by(SchoolYear.start_date.desc())
    ).all()


@router.post("/school-years", response_model=SchoolYearOut, status_code=status.HTTP_201_CREATED)
def create_school_year(data: SchoolYearSetupIn, db: DbSession, user: EditorUser):
    """Creates a school year with its two semesters in one step."""
    year = SchoolYear(
        school_id=user.school_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        is_active=data.is_active,
    )
    for number, dates in ((1, data.first_semester), (2, data.second_semester)):
        year.semesters.append(
            Semester(
                school_id=user.school_id,
                number=number,
                start_date=dates.start_date,
                end_date=dates.end_date,
                is_active=data.is_active and number == 1,
            )
        )
    db.add(year)
    db.flush()
    if year.is_active:
        _deactivate_other_years(db, user.school_id, year.id)
        db.execute(
            update(Semester)
            .where(Semester.school_id == user.school_id, Semester.school_year_id != year.id)
            .values(is_active=False)
        )
    audit(db, user, "create", "school_year", year.id, data.model_dump())
    commit(db)
    db.refresh(year)
    return year


@router.put("/school-years/{year_id}", response_model=SchoolYearOut)
def update_school_year(year_id: int, data: SchoolYearIn, db: DbSession, user: EditorUser):
    year = get_owned(db, SchoolYear, year_id, user.school_id)
    for key, value in data.model_dump().items():
        setattr(year, key, value)
    db.flush()
    if year.is_active:
        _deactivate_other_years(db, user.school_id, year.id)
    audit(db, user, "update", "school_year", year.id, data.model_dump())
    commit(db)
    db.refresh(year)
    return year


@router.delete("/school-years/{year_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_school_year(year_id: int, db: DbSession, admin: AdminUser):
    year = get_owned(db, SchoolYear, year_id, admin.school_id)
    db.delete(year)
    audit(db, admin, "delete", "school_year", year_id, {"name": year.name})
    commit(db)


@router.put("/semesters/{semester_id}", response_model=SemesterOut)
def update_semester(semester_id: int, data: SemesterIn, db: DbSession, user: EditorUser):
    semester = get_owned(db, Semester, semester_id, user.school_id)
    for key, value in data.model_dump().items():
        setattr(semester, key, value)
    db.flush()
    if semester.is_active:
        db.execute(
            update(Semester)
            .where(Semester.school_id == user.school_id, Semester.id != semester.id)
            .values(is_active=False)
        )
    audit(db, user, "update", "semester", semester.id, data.model_dump())
    commit(db)
    db.refresh(semester)
    return semester


# --- shifts & bell schedule -------------------------------------------------


@router.get("/shifts", response_model=list[ShiftOut])
def list_shifts(db: DbSession, user: CurrentUser):
    return db.scalars(select(Shift).where(Shift.school_id == user.school_id).order_by(Shift.start_time)).all()


@router.post("/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(data: ShiftIn, db: DbSession, user: EditorUser):
    shift = Shift(school_id=user.school_id, **data.model_dump())
    db.add(shift)
    db.flush()
    audit(db, user, "create", "shift", shift.id, data.model_dump())
    commit(db)
    return shift


@router.put("/shifts/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, data: ShiftIn, db: DbSession, user: EditorUser):
    shift = get_owned(db, Shift, shift_id, user.school_id)
    for period in shift.periods:
        if period.start_time < data.start_time or period.end_time > data.end_time:
            raise _unprocessable(f"Period '{period.name}' would fall outside the new shift hours.")
    for key, value in data.model_dump().items():
        setattr(shift, key, value)
    audit(db, user, "update", "shift", shift.id, data.model_dump())
    commit(db)
    return shift


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(shift_id: int, db: DbSession, user: EditorUser):
    shift = get_owned(db, Shift, shift_id, user.school_id)
    db.delete(shift)
    audit(db, user, "delete", "shift", shift_id, {"name": shift.name})
    commit(db)


@router.put("/shifts/{shift_id}/periods", response_model=ShiftOut)
def set_bell_schedule(shift_id: int, periods: list[PeriodIn], db: DbSession, user: EditorUser):
    """Replaces a shift's bell schedule.

    Periods are matched by position, so existing period IDs (and anything
    scheduled in them) survive when times or names are edited.
    """
    shift = get_owned(db, Shift, shift_id, user.school_id)
    if len(periods) > 30:
        raise _unprocessable("A shift can have at most 30 periods.")
    previous_end = shift.start_time
    for index, period in enumerate(periods, start=1):
        if period.start_time < previous_end:
            raise _unprocessable(
                f"Row {index} ('{period.name}') overlaps the previous period or starts before the shift."
            )
        if period.end_time > shift.end_time:
            raise _unprocessable(f"Row {index} ('{period.name}') ends after the shift ends.")
        previous_end = period.end_time

    existing = list(shift.periods)
    for index, data in enumerate(periods):
        if index < len(existing):
            target = existing[index]
        else:
            target = Period(school_id=user.school_id, sort_order=index + 1)
            shift.periods.append(target)
        for key, value in data.model_dump().items():
            setattr(target, key, value)
    for surplus in existing[len(periods):]:
        shift.periods.remove(surplus)

    audit(db, user, "update", "bell_schedule", shift.id, [p.model_dump() for p in periods])
    commit(db)
    db.refresh(shift)
    return shift
