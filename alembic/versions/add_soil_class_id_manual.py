"""Add soil_class_id to RiskAssessment for Sabesp audit (simplified)

Revision ID: add_soil_class_id_v2
Revises:
Create Date: 2026-02-02 21:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_soil_class_id_v2"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add soil_class_id column to risk_assessments table.
    This column stores the MapBiomas Collection 8 class ID for audit purposes.
    """
    # Add soil_class_id column
    op.add_column(
        "risk_assessments", sa.Column("soil_class_id", sa.Integer(), nullable=True)
    )

    print("✓ Added soil_class_id column to risk_assessments")


def downgrade() -> None:
    """Remove soil_class_id column from risk_assessments table."""
    op.drop_column("risk_assessments", "soil_class_id")
    print("✓ Removed soil_class_id column from risk_assessments")
