import sqlalchemy as sa
from alembic import op


revision = "20260807_04"
down_revision = "20260807_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    event_columns = {column["name"] for column in inspector.get_columns("cp_task_events")}
    event_sequence_added = "event_sequence" not in event_columns
    if "event_sequence" not in event_columns:
        op.add_column("cp_task_events", sa.Column("event_sequence", sa.BigInteger(), nullable=True))
    if "correlation_id" not in event_columns:
        op.add_column("cp_task_events", sa.Column("correlation_id", sa.String(length=64), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, task_id FROM cp_task_events ORDER BY created_at, id")).fetchall()
    sequences = {}
    for event_id, task_id in rows:
        sequences[task_id] = sequences.get(task_id, 0) + 1
        connection.execute(sa.text("UPDATE cp_task_events SET event_sequence = :sequence WHERE id = :id"), {"sequence": sequences[task_id], "id": event_id})
    missing_sequences = connection.execute(sa.text("SELECT 1 FROM cp_task_events WHERE event_sequence IS NULL LIMIT 1")).scalar()
    event_sequence_nullable = next(column["nullable"] for column in inspector.get_columns("cp_task_events") if column["name"] == "event_sequence") if not event_sequence_added else True
    constraint_names = {constraint["name"] for constraint in inspector.get_unique_constraints("cp_task_events")}
    index_names = {index["name"] for index in inspector.get_indexes("cp_task_events")}
    with op.batch_alter_table("cp_task_events") as batch_op:
        if missing_sequences is None and event_sequence_nullable:
            batch_op.alter_column("event_sequence", nullable=False)
        if "uq_cp_task_events_task_sequence" not in constraint_names:
            batch_op.create_unique_constraint("uq_cp_task_events_task_sequence", ["task_id", "event_sequence"])
        if "ix_cp_task_events_task_sequence" not in index_names:
            batch_op.create_index("ix_cp_task_events_task_sequence", ["task_id", "event_sequence"])


def downgrade() -> None:
    op.drop_index("ix_cp_task_events_task_sequence", table_name="cp_task_events")
    op.drop_constraint("uq_cp_task_events_task_sequence", "cp_task_events", type_="unique")
    op.drop_column("cp_task_events", "correlation_id")
    op.drop_column("cp_task_events", "event_sequence")
