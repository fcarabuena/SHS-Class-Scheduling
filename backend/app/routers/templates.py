"""Editable DepEd SHS seed template (tracks, strands, subjects, curriculum).

The template is plain data in app/data/shs_template.json. Applying it copies
rows into the school's own tables, where they can be edited freely.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, EditorUser
from ..models import CurriculumEntry, Strand, Subject, Track
from ..schemas import ApplyTemplateIn, ApplyTemplateOut
from ..services import audit, commit

router = APIRouter(prefix="/api/templates", tags=["templates"])

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "data" / "shs_template.json"


@lru_cache
def load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


@router.get("/shs")
def get_template(user: CurrentUser):
    template = load_template()
    return {
        "note": template.get("note"),
        "tracks": template["tracks"],
        "subject_count": len(template["subjects"]),
    }


def apply_template(db, user, strand_codes: list[str]) -> ApplyTemplateOut:
    template = load_template()
    wanted = {code.strip().upper() for code in strand_codes}
    known = {s["code"] for t in template["tracks"] for s in t["strands"]}
    if unknown := wanted - known:
        raise HTTPException(
            422, "Unknown strand code(s): " + ", ".join(sorted(unknown))
        )

    school_id = user.school_id
    counts = {"tracks": 0, "strands": 0, "subjects": 0, "curriculum_entries": 0}

    tracks = {t.code: t for t in db.scalars(select(Track).where(Track.school_id == school_id))}
    strands = {s.code: s for s in db.scalars(select(Strand).where(Strand.school_id == school_id))}
    subjects = {s.code: s for s in db.scalars(select(Subject).where(Subject.school_id == school_id))}

    for t in template["tracks"]:
        chosen = [s for s in t["strands"] if s["code"] in wanted]
        if not chosen:
            continue
        if t["code"] not in tracks:
            tracks[t["code"]] = Track(school_id=school_id, code=t["code"], name=t["name"])
            db.add(tracks[t["code"]])
            db.flush()
            counts["tracks"] += 1
        for s in chosen:
            if s["code"] not in strands:
                strands[s["code"]] = Strand(
                    school_id=school_id, track_id=tracks[t["code"]].id, code=s["code"], name=s["name"]
                )
                db.add(strands[s["code"]])
                counts["strands"] += 1
    db.flush()

    subject_defs = {s["code"]: s for s in template["subjects"]}
    curriculum = template["curriculum"]
    excluded = template.get("common_exclusions", {})

    for strand_code in sorted(wanted):
        rows = [r for r in curriculum["COMMON"] if r[0] not in excluded.get(strand_code, [])]
        rows += curriculum.get(strand_code, [])
        strand = strands[strand_code]
        existing = {
            (e.subject_id, e.grade_level, e.semester_number)
            for e in db.scalars(select(CurriculumEntry).where(CurriculumEntry.strand_id == strand.id))
        }
        for subject_code, grade, semester in rows:
            if subject_code not in subjects:
                d = subject_defs[subject_code]
                subjects[subject_code] = Subject(
                    school_id=school_id,
                    code=d["code"],
                    name=d["name"],
                    type=d["type"],
                    hours_per_week=d["hours"],
                    required_room_type=d.get("room", "lecture"),
                    is_heavy=d.get("heavy", False),
                )
                db.add(subjects[subject_code])
                db.flush()
                counts["subjects"] += 1
            key = (subjects[subject_code].id, grade, semester)
            if key not in existing:
                existing.add(key)
                db.add(
                    CurriculumEntry(
                        school_id=school_id,
                        strand_id=strand.id,
                        subject_id=key[0],
                        grade_level=grade,
                        semester_number=semester,
                    )
                )
                counts["curriculum_entries"] += 1

    audit(db, user, "apply_template", "curriculum", None, {"strand_codes": sorted(wanted), **counts})
    return ApplyTemplateOut(**counts)


@router.post("/shs/apply", response_model=ApplyTemplateOut)
def apply_template_endpoint(data: ApplyTemplateIn, db: DbSession, user: EditorUser):
    """Adds the chosen strands with their subjects. Existing codes are kept as-is."""
    result = apply_template(db, user, data.strand_codes)
    commit(db)
    return result
