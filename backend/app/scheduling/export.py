"""Timetable export: one grid per section, teacher or room, as Excel or PDF."""

import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus import Table as PdfTable
from reportlab.platypus import TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Period, School, SchoolYear, Semester, Shift
from . import engine as eng
from .state import load_state

VIEWS = ("section", "teacher", "room")


@dataclass
class Row:
    label: str
    time: str
    is_break: bool
    cells: list[list[str]]  # one list of text lines per day


@dataclass
class Table:
    title: str
    subtitle: str
    days: list[str]
    rows: list[Row] = field(default_factory=list)


@dataclass
class Document:
    school: str
    heading: str
    view: str
    tables: list[Table] = field(default_factory=list)
    # People who sign the printed timetable: {"label", "name", "position"} each.
    signatories: list[dict[str, str]] = field(default_factory=list)


def build(db: Session, school_id: int, semester: Semester, view: str, only_id: int | None = None) -> Document:
    state = load_state(db, school_id, semester)
    school = db.get(School, school_id)
    year = db.get(SchoolYear, semester.school_year_id)
    ordinal = "1st" if semester.number == 1 else "2nd"
    document = Document(school.name, f"School year {year.name}, {ordinal} semester", view)
    document.signatories = [
        s for s in (school.settings or {}).get("signatories") or [] if isinstance(s, dict) and s.get("name")
    ]

    shifts = {s.id: s.name for s in db.scalars(select(Shift).where(Shift.school_id == school_id))}
    periods = list(
        db.scalars(select(Period).where(Period.school_id == school_id).order_by(Period.start_time, Period.sort_order))
    )
    days = [eng.DAY_NAMES[d] for d in state.days]

    def name(table: dict, item_id: int | None, attr: str = "name") -> str:
        item = table.get(item_id)
        return getattr(item, attr) if item else ""

    def grid(title: str, subtitle: str, entries: list[eng.Entry], shift_ids: set[int], lines) -> Table:
        by_cell: dict[tuple[int, int], list[eng.Entry]] = defaultdict(list)
        for entry in entries:
            by_cell[(entry.day, entry.period_id)].append(entry)
        table = Table(title, subtitle, days)
        for period in periods:
            if period.shift_id not in shift_ids:
                continue
            label = period.name if len(shift_ids) == 1 else f"{shifts.get(period.shift_id, '')} {period.name}".strip()
            time = f"{period.start_time:%H:%M}-{period.end_time:%H:%M}"
            cells = []
            for day in state.days:
                here = by_cell.get((day, period.id), [])
                cells.append([] if period.is_break or not here else [*lines(here), here[0].remarks or ""])
            table.rows.append(Row(label, time, period.is_break, cells))
        return table

    def sections_of(entries: list[eng.Entry]) -> str:
        return " + ".join(sorted(name(state.sections, e.section_id) for e in entries))

    def subject_of(entries: list[eng.Entry]) -> str:
        return " / ".join(dict.fromkeys(name(state.subjects, e.subject_id, "code") for e in entries))

    if view == "section":
        for section in sorted(state.sections.values(), key=lambda s: s.name):
            if only_id not in (None, section.id):
                continue
            mine = [e for e in state.entries if e.section_id == section.id]
            document.tables.append(
                grid(
                    section.name,
                    f"{shifts.get(section.shift_id, '')} shift · {section.student_count} students",
                    mine,
                    {section.shift_id},
                    lambda es: [subject_of(es), name(state.teachers, es[0].teacher_id), name(state.rooms, es[0].room_id)],
                )
            )
        return document

    attr, table = ("teacher_id", state.teachers) if view == "teacher" else ("room_id", state.rooms)
    for item in sorted(table.values(), key=lambda x: x.name):
        if only_id not in (None, item.id):
            continue
        mine = [e for e in state.entries if getattr(e, attr) == item.id]
        if not mine and only_id is None:
            continue  # the "everyone" export skips empty timetables
        used = {state.slots[e.period_id].shift_id for e in mine if e.period_id in state.slots} or set(shifts)
        if view == "teacher":
            minutes = sum(eng._teacher_minutes(state, item.id).values())
            subtitle = f"{eng.hours_text(minutes)} a week scheduled · limit {eng.hours_text(item.max_weekly_minutes)}"
            lines = lambda es: [subject_of(es), sections_of(es), name(state.rooms, es[0].room_id)]  # noqa: E731
        else:
            subtitle = f"{item.type.replace('_', ' ').capitalize()} room · holds {item.capacity}"
            lines = lambda es: [subject_of(es), sections_of(es), name(state.teachers, es[0].teacher_id)]  # noqa: E731
        document.tables.append(grid(item.name, subtitle, mine, used, lines))
    return document


# --- Excel ------------------------------------------------------------------

_THIN = Side(style="thin", color="999999")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD_FILL = PatternFill("solid", fgColor="D1FAE5")
_BREAK_FILL = PatternFill("solid", fgColor="F5F5F4")


def _sheet_title(title: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", title).strip()[:31] or "Sheet"
    candidate, n = base, 2
    while candidate.lower() in used:
        suffix = f" ({n})"
        candidate, n = base[: 31 - len(suffix)] + suffix, n + 1
    used.add(candidate.lower())
    return candidate


def to_xlsx(document: Document) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    for table in document.tables:
        sheet = workbook.create_sheet(_sheet_title(table.title, used))
        sheet.append([document.school])
        sheet.append([document.heading])
        sheet.append([f"{table.title} - {table.subtitle}"])
        sheet["A1"].font = Font(bold=True, size=14)
        sheet["A3"].font = Font(bold=True, size=12)
        sheet.append([])
        sheet.append(["Period", "Time", *table.days])
        for row in table.rows:
            cells = ["Break"] * len(table.days) if row.is_break else ["\n".join(filter(None, c)) for c in row.cells]
            sheet.append([row.label, row.time, *cells])
        for index, row in enumerate(sheet.iter_rows(min_row=5), start=0):
            is_break = index > 0 and table.rows[index - 1].is_break
            for cell in row:
                cell.border = _BORDER
                cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                if index == 0:
                    cell.font, cell.fill = Font(bold=True), _HEAD_FILL
                elif is_break:
                    cell.font, cell.fill = Font(italic=True, color="78716C"), _BREAK_FILL
            if index > 0 and not is_break:
                sheet.row_dimensions[row[0].row].height = 48
        if document.signatories:
            row_number = sheet.max_row + 2
            for index, person in enumerate(document.signatories):
                column = 1 + index * 2 if index < 4 else 1 + (index - 4) * 2
                top = row_number if index < 4 else row_number + 6
                sheet.cell(top, column, f"{person.get('label', '')}:")
                sheet.cell(top + 3, column, person.get("name", "")).font = Font(bold=True)
                sheet.cell(top + 4, column, person.get("position", ""))
        sheet.column_dimensions["A"].width = 18
        sheet.column_dimensions["B"].width = 13
        for column in range(3, 3 + len(table.days)):
            sheet.column_dimensions[get_column_letter(column)].width = 24
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- PDF --------------------------------------------------------------------


def to_pdf(document: Document) -> bytes:
    buffer = io.BytesIO()
    page = landscape(A4)
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Timetable by {document.view}",
        author=document.school,
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#57534e"))
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=7.5, leading=9, alignment=1)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", fontSize=8.5)
    sign = ParagraphStyle("sign", parent=styles["Normal"], fontSize=9, leading=11)

    story = []
    for index, table in enumerate(document.tables):
        if index:
            story.append(PageBreak())
        story += [
            Paragraph(escape(document.school), styles["Title"]),
            Paragraph(escape(document.heading), small),
            Spacer(1, 3 * mm),
            Paragraph(escape(table.title), styles["Heading2"]),
            Paragraph(escape(table.subtitle), small),
            Spacer(1, 3 * mm),
        ]
        data = [[Paragraph(text, head) for text in ("Period", *table.days)]]
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#a8a29e")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d1fae5")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for number, row in enumerate(table.rows, start=1):
            label = Paragraph(f"<b>{escape(row.label)}</b><br/>{row.time}", cell)
            if row.is_break:
                data.append([label, Paragraph("<i>Break</i>", cell), *[""] * (len(table.days) - 1)])
                style += [
                    ("SPAN", (1, number), (-1, number)),
                    ("BACKGROUND", (0, number), (-1, number), colors.HexColor("#f5f5f4")),
                ]
                continue
            cells = []
            for lines in row.cells:
                text = [escape(line) for line in lines if line]
                if text:
                    text[0] = f"<b>{text[0]}</b>"
                cells.append(Paragraph("<br/>".join(text), cell))
            data.append([label, *cells])
        first = 30 * mm
        width = (page[0] - 24 * mm - first) / len(table.days)
        grid = PdfTable(data, colWidths=[first, *[width] * len(table.days)], repeatRows=1)
        grid.setStyle(TableStyle(style))
        story.append(grid)
        if document.signatories:
            people = document.signatories
            blocks = [
                Paragraph(
                    f"{escape(p.get('label', ''))}:<br/><br/><br/><b>{escape(p.get('name', ''))}</b><br/>{escape(p.get('position', ''))}",
                    sign,
                )
                for p in people
            ]
            per_row = min(4, len(blocks))
            rows = [blocks[i : i + per_row] + [""] * (per_row - len(blocks[i : i + per_row])) for i in range(0, len(blocks), per_row)]
            signatures = PdfTable(rows, colWidths=[(page[0] - 24 * mm) / per_row] * per_row)
            signatures.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 10)]))
            story += [Spacer(1, 6 * mm), KeepTogether(signatures)]
    pdf.build(story)
    return buffer.getvalue()


FORMATS = {
    "xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "pdf": (to_pdf, "application/pdf"),
}
