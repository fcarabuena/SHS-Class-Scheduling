"""Combined teaching assignments; deferrable slot constraint for swaps.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SLOT_COLUMNS = ["semester_id", "section_id", "day_of_week", "period_id"]
NEW_NAME = "uq_schedule_entries_slot"


def _slot_constraint_name() -> str | None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints("schedule_entries"):
        if constraint["column_names"] == SLOT_COLUMNS:
            return constraint["name"]
    return None


def upgrade() -> None:
    op.add_column("teaching_assignments", sa.Column("combined_group_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_teaching_assignments_combined_group_id"), "teaching_assignments", ["combined_group_id"], unique=False
    )
    # Checked at commit, so two classes can swap slots inside one transaction.
    old = _slot_constraint_name()
    if old:
        op.drop_constraint(old, "schedule_entries", type_="unique")
    op.create_unique_constraint(NEW_NAME, "schedule_entries", SLOT_COLUMNS, deferrable=True, initially="DEFERRED")


def downgrade() -> None:
    op.drop_constraint(NEW_NAME, "schedule_entries", type_="unique")
    op.create_unique_constraint(None, "schedule_entries", SLOT_COLUMNS)
    op.drop_index(op.f("ix_teaching_assignments_combined_group_id"), table_name="teaching_assignments")
    op.drop_column("teaching_assignments", "combined_group_id")
