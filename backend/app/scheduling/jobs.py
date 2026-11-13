"""Runs the automatic scheduler in the background and reports progress.

Jobs run on a small thread pool inside the API process. That is enough for a
single server; a job that was running when the server stopped is reported as
failed the next time it is looked at.
"""

import datetime as dt
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import DEFAULT_SCHOOL_SETTINGS, School, Semester, SolverJob
from ..notify import notify_users
from . import engine as eng
from . import solver
from .state import load_state

ACTIVE = ("queued", "running")

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="solver")
_stop_flags: dict[int, threading.Event] = {}
_lock = threading.Lock()


def fingerprint(state: eng.State) -> str:
    """Changes whenever the timetable or the teacher loading changes."""
    payload = [
        sorted((e.id, e.section_id, e.subject_id, e.day, e.period_id, e.teacher_id, e.room_id, e.pinned, e.group) for e in state.entries),
        sorted((r.id or 0, r.section_id, r.subject_id, r.minutes, r.teacher_id, r.group) for r in state.requirements),
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def is_running_here(job_id: int) -> bool:
    with _lock:
        return job_id in _stop_flags


def request_stop(job_id: int) -> None:
    with _lock:
        flag = _stop_flags.get(job_id)
    if flag:
        flag.set()


def submit(job_id: int) -> None:
    with _lock:
        _stop_flags[job_id] = threading.Event()
    _pool.submit(_run, job_id)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _run(job_id: int) -> None:
    with _lock:
        stop = _stop_flags[job_id]
    try:
        with SessionLocal() as db:
            job = db.get(SolverJob, job_id)
            if job is None:
                return
            try:
                _solve(db, job, stop)
            except Exception as exc:  # the job must always end in a final state
                db.rollback()
                job = db.get(SolverJob, job_id)
                if job is not None:
                    job.status, job.error, job.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:500], _now()
                    db.commit()
    finally:
        with _lock:
            _stop_flags.pop(job_id, None)


def _solve(db: Session, job: SolverJob, stop: threading.Event) -> None:
    semester = db.get(Semester, job.semester_id)
    state = load_state(db, job.school_id, semester)
    settings = db.get(School, job.school_id).settings or {}
    weights = settings.get("soft_constraint_weights") or DEFAULT_SCHOOL_SETTINGS["soft_constraint_weights"]
    job.status = "running"
    job.progress = {"solutions": 0, "placed_hours": 0, "required_hours": 0, "seconds": 0}
    db.commit()

    last_saved = 0.0

    def on_progress(progress: dict[str, Any]) -> None:
        # Called from solver threads: only this function touches the session while solving.
        nonlocal last_saved
        with _lock:
            if time.monotonic() - last_saved < 0.5:
                return
            last_saved = time.monotonic()
            job.progress = progress
            db.commit()

    result = solver.solve(
        state,
        solver.Options(mode=job.mode, time_limit=job.time_limit, weights=weights),
        on_progress=on_progress,
        should_stop=stop.is_set,
    )
    with _lock:
        job.progress = {
            "solutions": (job.progress or {}).get("solutions", 0),
            "placed_hours": round(result.placed_minutes / 60, 2),
            "required_hours": round(result.required_minutes / 60, 2),
            "seconds": result.seconds,
        }
        job.result = {
            "status": result.status,
            "stopped_early": stop.is_set(),
            "proven_optimal": result.proven_optimal,
            "placed_hours": round(result.placed_minutes / 60, 2),
            "required_hours": round(result.required_minutes / 60, 2),
            "added": result.added,
            "kept": result.kept,
            "removed": len(state.entries) - result.kept,
            "seconds": result.seconds,
            "problems": result.problems,
            "shortages": [
                {
                    "section_ids": s.section_ids,
                    "subject_id": s.subject_id,
                    "teacher_id": s.teacher_id,
                    "required_hours": round(s.required_minutes / 60, 2),
                    "placed_hours": round(s.placed_minutes / 60, 2),
                    "message": s.message,
                }
                for s in result.shortages
            ],
            "base": fingerprint(state),
            "kept_ids": [e.id for e in result.entries if e.id > 0],
            "new_entries": [
                {
                    "section_id": e.section_id,
                    "subject_id": e.subject_id,
                    "teacher_id": e.teacher_id,
                    "room_id": e.room_id,
                    "day_of_week": e.day,
                    "period_id": e.period_id,
                    "combined_group_id": e.group,
                }
                for e in result.entries
                if e.id < 0
            ],
        }
        job.status = "failed" if result.status == "failed" else "done"
        job.error = result.problems[-1][:500] if result.status == "failed" and result.problems else None
        job.finished_at = _now()
        if job.user_id is not None and job.status == "done":
            placed, required = job.result["placed_hours"], job.result["required_hours"]
            notify_users(
                db,
                job.school_id,
                [job.user_id],
                "solver",
                "Auto-schedule finished",
                f"{placed:g} of {required:g} hours can be placed. Review the result and apply it.",
                "/timetable",
            )
        db.commit()
