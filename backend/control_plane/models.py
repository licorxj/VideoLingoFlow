import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampedVersioned:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class User(TimestampedVersioned, Base):
    __tablename__ = "cp_users"
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Role(TimestampedVersioned, Base):
    __tablename__ = "cp_roles"
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    users: Mapped[list["UserRole"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class UserRole(Base):
    __tablename__ = "cp_user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("cp_roles.id", ondelete="CASCADE"), primary_key=True)
    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="users")


class Session(TimestampedVersioned, Base):
    __tablename__ = "cp_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class Project(TimestampedVersioned, Base):
    __tablename__ = "cp_projects"
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("cp_users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    legacy_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    workflows: Mapped[list["WorkflowVersion"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(TimestampedVersioned, Base):
    __tablename__ = "cp_project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_cp_project_members_project_user"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("cp_projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("cp_users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    project: Mapped[Project] = relationship(back_populates="members")


class WorkflowVersion(TimestampedVersioned, Base):
    __tablename__ = "cp_workflow_versions"
    __table_args__ = (UniqueConstraint("project_id", "workflow_key", "revision", name="uq_cp_workflow_versions_revision"),)
    project_id: Mapped[str] = mapped_column(ForeignKey("cp_projects.id", ondelete="CASCADE"), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(256), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    project: Mapped[Project] = relationship(back_populates="workflows")


class Task(TimestampedVersioned, Base):
    __tablename__ = "cp_tasks"
    __table_args__ = (Index("ix_cp_tasks_status_created", "status", "created_at"), Index("ix_cp_tasks_project_status", "project_id", "status"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("cp_projects.id", ondelete="SET NULL"))
    workflow_version_id: Mapped[str | None] = mapped_column(ForeignKey("cp_workflow_versions.id", ondelete="SET NULL"))
    legacy_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    idempotency_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    queue: Mapped[str] = mapped_column(String(128), nullable=False, default="videolingo_io")
    resource_class: Mapped[str] = mapped_column(String(32), nullable=False, default="io")
    cancel_reason: Mapped[str | None] = mapped_column(String(256))
    error_class: Mapped[str | None] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    deletion_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    project: Mapped[Project | None] = relationship(back_populates="tasks")
    nodes: Mapped[list["TaskNode"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    events: Mapped[list["TaskEvent"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskNode(TimestampedVersioned, Base):
    __tablename__ = "cp_task_nodes"
    __table_args__ = (UniqueConstraint("task_id", "node_key", name="uq_cp_task_nodes_task_node"), Index("ix_cp_task_nodes_status", "status"))
    task_id: Mapped[str] = mapped_column(ForeignKey("cp_tasks.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resource_class: Mapped[str] = mapped_column(String(32), nullable=False, default="io")
    queue: Mapped[str] = mapped_column(String(128), nullable=False, default="videolingo_io")
    cancel_reason: Mapped[str | None] = mapped_column(String(256))
    error_class: Mapped[str | None] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    worker_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkpoint_key: Mapped[str | None] = mapped_column(String(256))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    task: Mapped[Task] = relationship(back_populates="nodes")
    checkpoints: Mapped[list["Checkpoint"]] = relationship(back_populates="node", cascade="all, delete-orphan")


class Checkpoint(TimestampedVersioned, Base):
    __tablename__ = "cp_checkpoints"
    __table_args__ = (
        UniqueConstraint("node_id", "checkpoint_key", name="uq_cp_checkpoints_node_key"),
        Index("ix_cp_checkpoints_reuse", "node_id", "input_hash", "step_version", "config_hash"),
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("cp_task_nodes.id", ondelete="CASCADE"), nullable=False)
    checkpoint_key: Mapped[str] = mapped_column(String(256), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    step_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    output_object_key: Mapped[str | None] = mapped_column(String(1024))
    output_checksum: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    node: Mapped[TaskNode] = relationship(back_populates="checkpoints")


class Asset(TimestampedVersioned, Base):
    __tablename__ = "cp_assets"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_cp_assets_object_key"),
        Index("ix_cp_assets_project_kind", "project_id", "kind"),
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("cp_projects.id", ondelete="CASCADE"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("cp_tasks.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(256), nullable=False, default="application/octet-stream")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskEvent(TimestampedVersioned, Base):
    __tablename__ = "cp_task_events"
    __table_args__ = (Index("ix_cp_task_events_task_sequence", "task_id", "event_sequence"), UniqueConstraint("task_id", "event_sequence", name="uq_cp_task_events_task_sequence"))
    task_id: Mapped[str] = mapped_column(ForeignKey("cp_tasks.id", ondelete="CASCADE"), nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    task: Mapped[Task] = relationship(back_populates="events")


class AuditEvent(TimestampedVersioned, Base):
    __tablename__ = "cp_audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("cp_users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class JoinApplication(TimestampedVersioned, Base):
    __tablename__ = "cp_join_applications"
    __table_args__ = (Index("ix_cp_join_applications_status", "status"),)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("cp_users.id", ondelete="SET NULL"))
    review_note: Mapped[str | None] = mapped_column(Text)


class Quota(TimestampedVersioned, Base):
    __tablename__ = "cp_quotas"
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "quota_key", name="uq_cp_quotas_subject_key"),)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(32), nullable=False)
    quota_key: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False)
    used_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


CONTROL_PLANE_TABLES = {table.name for table in Base.metadata.tables.values()}
