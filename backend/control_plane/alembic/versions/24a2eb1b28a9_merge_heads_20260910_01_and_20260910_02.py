"""merge heads: 20260910_01 and 20260910_02"""

from alembic import op
import sqlalchemy as sa

revision = '24a2eb1b28a9'
down_revision = ('20260910_01_credential_register_url', '20260910_02_creation_video_aspect_ratio')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
