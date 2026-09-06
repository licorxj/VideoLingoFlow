import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
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


CREATION_ASSET_KINDS = {"character", "scene_image", "voiceover", "shot_video", "sfx", "bgm", "shot_render", "chapter_render"}


class Creation(TimestampedVersioned, Base):
    """AI 剧集创作项目主表(AGI 项目)。"""
    __tablename__ = "cp_creations"
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("cp_users.id", ondelete="SET NULL"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("cp_projects.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    genre_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    art_style_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    audience_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    script_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    characters: Mapped[list["CreationCharacter"]] = relationship(back_populates="creation", cascade="all, delete-orphan")
    chapters: Mapped[list["CreationChapter"]] = relationship(back_populates="creation", cascade="all, delete-orphan")
    assets: Mapped[list["CreationAsset"]] = relationship(back_populates="creation", cascade="all, delete-orphan")


class CreationCharacter(TimestampedVersioned, Base):
    """创作项目内的人物设定,可通过 character_lib_id 关联公共角色库。"""
    __tablename__ = "cp_creation_characters"
    __table_args__ = (
        UniqueConstraint("creation_id", "name", name="uq_cp_creation_characters_creation_name"),
        Index("ix_cp_creation_characters_lib", "character_lib_id"),
    )
    creation_id: Mapped[str] = mapped_column(ForeignKey("cp_creations.id", ondelete="CASCADE"), nullable=False)
    character_lib_id: Mapped[str | None] = mapped_column(ForeignKey("cp_characters.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    age: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occupation: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    relationship_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voice_design: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voice_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    creation: Mapped[Creation] = relationship(back_populates="characters")


class CreationChapter(TimestampedVersioned, Base):
    """创作项目的章节内容。"""
    __tablename__ = "cp_creation_chapters"
    __table_args__ = (UniqueConstraint("creation_id", "order_no", name="uq_cp_creation_chapters_creation_order"),)
    creation_id: Mapped[str] = mapped_column(ForeignKey("cp_creations.id", ondelete="CASCADE"), nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    creation: Mapped[Creation] = relationship(back_populates="chapters")
    shots: Mapped[list["CreationShot"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class CreationShot(TimestampedVersioned, Base):
    """章节下的分镜;场景描述与对话(含对话 id)以 JSON 列表存储。"""
    __tablename__ = "cp_creation_shots"
    __table_args__ = (UniqueConstraint("chapter_id", "order_no", name="uq_cp_creation_shots_chapter_order"),)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("cp_creation_chapters.id", ondelete="CASCADE"), nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    characters: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scene_descriptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dialogues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    bgm_design: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sfx_design: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chapter: Mapped[CreationChapter] = relationship(back_populates="shots")


class CreationAsset(TimestampedVersioned, Base):
    """项目资产明细,asset_kind 区分:character/scene_image/voiceover/shot_video/sfx/bgm/shot_render/chapter_render。"""
    __tablename__ = "cp_creation_assets"
    __table_args__ = (
        Index("ix_cp_creation_assets_creation_kind", "creation_id", "asset_kind"),
        Index("ix_cp_creation_assets_chapter_shot", "chapter_id", "shot_id"),
    )
    creation_id: Mapped[str] = mapped_column(ForeignKey("cp_creations.id", ondelete="CASCADE"), nullable=False)
    asset_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("cp_creation_chapters.id", ondelete="SET NULL"))
    shot_id: Mapped[str | None] = mapped_column(ForeignKey("cp_creation_shots.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    ref_id: Mapped[str | None] = mapped_column(String(128))
    paths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sequence: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    creation: Mapped[Creation] = relationship(back_populates="assets")


class Character(TimestampedVersioned, Base):
    """公共角色库(跨项目共享)。"""
    __tablename__ = "cp_characters"
    __table_args__ = (Index("ix_cp_characters_origin", "origin_creation_id"),)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gender: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    age: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occupation: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    voice_design: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voice_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    images_dir: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    origin_creation_id: Mapped[str | None] = mapped_column(ForeignKey("cp_creations.id", ondelete="SET NULL"))


class ImageAsset(TimestampedVersioned, Base):
    """公共图片素材库,path 为项目根相对路径(data/ 内)。"""
    __tablename__ = "cp_images"
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    aspect_ratio: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    group_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    custom_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class VideoAsset(TimestampedVersioned, Base):
    """公共视频素材库,path 为项目根相对路径(data/ 内)。"""
    __tablename__ = "cp_videos"
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    group_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    custom_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class VideoDubWorkspace(TimestampedVersioned, Base):
    """视频配音工作台工程:视频文件 + 字幕/片段/轨道布局(JSON state)。"""
    __tablename__ = "cp_videodub_workspaces"
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    video_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    video_storage_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


CONTROL_PLANE_TABLES = {table.name for table in Base.metadata.tables.values()}
