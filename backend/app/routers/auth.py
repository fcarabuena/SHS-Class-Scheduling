from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import AdminUser, CurrentUser, DbSession
from ..models import AuditLog, Role, School, User
from ..schemas import AuditLogOut, LoginIn, RegisterIn, TokenOut, UserCreate, UserOut, UserUpdate
from ..security import create_access_token, hash_password, verify_password
from ..services import audit, check_references, commit, get_owned

router = APIRouter(prefix="/api", tags=["auth"])


def _token(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.school_id, user.role.value),
        user=UserOut.model_validate(user),
    )


def _email_taken(db: DbSession, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register_school(data: RegisterIn, db: DbSession):
    """Creates a new school (tenant) together with its first admin account."""
    if _email_taken(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "That email address is already registered.")
    school = School(name=data.school_name)
    db.add(school)
    db.flush()
    user = User(
        school_id=school.id,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=Role.admin,
    )
    db.add(user)
    db.flush()
    audit(db, user, "register", "school", school.id, {"name": school.name})
    commit(db)
    return _token(user)


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: DbSession):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    # Same message for unknown email and wrong password.
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    return _token(user)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


# --- user management (admin only) -------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, admin: AdminUser):
    return db.scalars(select(User).where(User.school_id == admin.school_id).order_by(User.full_name)).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: DbSession, admin: AdminUser):
    if _email_taken(db, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "That email address is already registered.")
    values = data.model_dump()
    check_references(db, User, values, admin.school_id)
    user = User(
        school_id=admin.school_id,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
        teacher_id=data.teacher_id,
    )
    db.add(user)
    db.flush()
    audit(db, admin, "create", "user", user.id, values)
    commit(db)
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: DbSession, admin: AdminUser):
    user = get_owned(db, User, user_id, admin.school_id)
    values = data.model_dump(exclude_unset=True)
    check_references(db, User, values, admin.school_id)
    if user.id == admin.id and (values.get("role", Role.admin) != Role.admin or values.get("is_active") is False):
        raise HTTPException(
            422, "You cannot remove your own admin access."
        )
    if password := values.pop("password", None):
        user.password_hash = hash_password(password)
    for key, value in values.items():
        setattr(user, key, value)
    audit(db, admin, "update", "user", user.id, {**values, "password_changed": bool(password)})
    commit(db)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: DbSession, admin: AdminUser):
    user = get_owned(db, User, user_id, admin.school_id)
    if user.id == admin.id:
        raise HTTPException(422, "You cannot delete your own account.")
    db.delete(user)
    audit(db, admin, "delete", "user", user_id, {"email": user.email})
    commit(db)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(db: DbSession, admin: AdminUser, limit: int = 100, offset: int = 0):
    limit = max(1, min(limit, 500))
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.school_id == admin.school_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(max(0, offset))
    ).all()
