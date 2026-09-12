"""merge toonflow and style_presets branches"""

from alembic import op
import sqlalchemy as sa

revision = '837cb0e56934'
down_revision = ('20260910_03_style_presets_expand', '20260910_05')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
