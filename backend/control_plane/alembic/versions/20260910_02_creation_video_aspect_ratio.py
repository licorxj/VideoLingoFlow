"""creation video aspect ratio: default canvas/video ratio picked at project kickoff"""

import sqlalchemy as sa
from alembic import op

revision = "20260910_02_creation_video_aspect_ratio"
down_revision = "20260909_11"
branch_labels = None
depends_on = None

_TABLE = "cp_creations"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "video_aspect_ratio" not in columns:
        op.add_column(_TABLE, sa.Column("video_aspect_ratio", sa.String(16),
                                        nullable=False, server_default="16:9"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "video_aspect_ratio" in columns:
        op.drop_column(_TABLE, "video_aspect_ratio")
