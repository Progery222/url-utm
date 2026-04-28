"""initial alembic revision (schema drift handled by ensure_click_schema on startup)

Revision ID: 001
Revises:
Create Date: 2025-04-28

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
