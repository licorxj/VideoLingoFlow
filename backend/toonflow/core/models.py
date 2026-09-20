# -*- coding: utf-8 -*-
"""Toonflow 核心表（tf_ 前缀，结构对齐源系统 o_* 表的精简版）。

- id 沿用源系统的 INTEGER 自增主键（迁移其逻辑时保持一致）；
- 时间戳沿用源系统的 unix 毫秒整数（createTime/updateTime）；
- 状态沿用源系统的中文字面量（生成中/已完成/生成失败），集中为常量枚举。

只建创作链所需的表；剪辑/轨道等源系统残留不做迁移。
"""
from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TfBase(DeclarativeBase):
    pass


# 源系统状态字面量（集中管理，语义不改）
STATE_GENERATING = "生成中"
STATE_DONE = "已完成"
STATE_FAILED = "生成失败"
STATE_VIDEO_DONE = "生成成功"


def _ms() -> int:
    import time

    return int(time.time() * 1000)


class TfProject(TfBase):
    """项目（源 o_project）。"""
    __tablename__ = "tf_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover: Mapped[str] = mapped_column(Text, nullable=False, default="")
    introduce: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artStyle: Mapped[str] = mapped_column(Text, nullable=False, default="")       # 画风（art_skills 目录名）
    directorManual: Mapped[str] = mapped_column(Text, nullable=False, default="") # 视觉/导演手册
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="")           # 制作模式
    videoRatio: Mapped[str] = mapped_column(Text, nullable=False, default="16:9")
    imageQuality: Mapped[str] = mapped_column(Text, nullable=False, default="1K")
    # 视频分辨率档位：480P / 720P / 1080P（新增列，旧库由 seed._ensure_columns 幂等补齐）
    videoResolution: Mapped[str] = mapped_column(Text, nullable=False, default="720P")
    # 叙事/导演风格（story_skills 目录名），决定注入哪套 driector_skills 技法
    storyStyle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfNovel(TfBase):
    """小说章节（源 o_novel）。"""
    __tablename__ = "tf_novels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    reel: Mapped[str] = mapped_column(Text, nullable=False, default="")           # 卷
    chapter: Mapped[str] = mapped_column(Text, nullable=False, default="")        # 章节名
    chapterData: Mapped[str] = mapped_column(Text, nullable=False, default="")    # 原文
    event: Mapped[str] = mapped_column(Text, nullable=False, default="")          # 事件提取结果（|分隔7字段）
    eventState: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # 0未提取 1完成 -1失败
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfScript(TfBase):
    """剧本（源 o_script）。"""
    __tablename__ = "tf_scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scriptData: Mapped[str] = mapped_column(Text, nullable=False, default="")     # 剧本正文
    extractState: Mapped[int] = mapped_column(Integer, nullable=False, default=0) # 资产提取状态（同 eventState 语义）
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfAsset(TfBase):
    """资产：role(角色)/scene(场景)/tool(道具)/clip(分镜片段)/audio；衍生资产用 assetsId 自引用（源 o_assets）。"""
    __tablename__ = "tf_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assetsId: Mapped[int | None] = mapped_column(Integer, index=True)             # 父资产（衍生）
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(Text, nullable=False, default="role")
    describe: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")         # 生图提示词
    promptState: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imageId: Mapped[int | None] = mapped_column(Integer)                          # 主图 → tf_images.id
    startTime: Mapped[int | None] = mapped_column(Integer)
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfImage(TfBase):
    """生成图（源 o_image）：一个资产/分镜可多次生成出多张候选。"""
    __tablename__ = "tf_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, default=STATE_GENERATING)
    model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolution: Mapped[str] = mapped_column(Text, nullable=False, default="1K")
    filePath: Mapped[str] = mapped_column(Text, nullable=False, default="")       # oss 相对路径
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfStoryboard(TfBase):
    """分镜（源 o_storyboard）。"""
    __tablename__ = "tf_storyboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scriptId: Mapped[int | None] = mapped_column(Integer, index=True)
    videoDesc: Mapped[str] = mapped_column(Text, nullable=False, default="")      # 12字段结构化画面描述
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")         # 分镜图提示词
    videoPrompt: Mapped[str] = mapped_column(Text, nullable=False, default="")    # 视频提示词（o_modelPrompt 流程产出）
    assetIds: Mapped[str] = mapped_column(Text, nullable=False, default="")       # 关联资产ID JSON 数组
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    track: Mapped[str] = mapped_column(Text, nullable=False, default="")          # 分组
    filePath: Mapped[str] = mapped_column(Text, nullable=False, default="")       # 分镜图
    state: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shouldGenerateImage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orderNo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfScriptAsset(TfBase):
    """剧本-资产关联（源 o_scriptAssets，M:N）。"""
    __tablename__ = "tf_script_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scriptId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assetId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class TfAssetRoleAudio(TfBase):
    """角色-音色绑定（源 o_assetsRole2Audio），音色指向配音谷 vf_voices.id。"""
    __tablename__ = "tf_assets_role_audio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assetId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)     # role 资产
    audioId: Mapped[str] = mapped_column(Text, nullable=False, default="")        # vf_voices.id
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)


class TfVideo(TfBase):
    """生成的视频候选（源 o_video）。"""
    __tablename__ = "tf_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    videoTrackId: Mapped[int | None] = mapped_column(Integer, index=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, default=STATE_GENERATING)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filePath: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfVideoTrack(TfBase):
    """视频轨道（源 o_videoTrack）：分镜→选定视频的映射，供下游配音/合成消费。"""
    __tablename__ = "tf_video_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    storyboardId: Mapped[int | None] = mapped_column(Integer, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selectVideoId: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="")
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)
    updateTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, onupdate=_ms)


class TfPrompt(TfBase):
    """提示词模板（源 o_prompt）：data=原文，useData=用户改写（优先生效）。"""
    __tablename__ = "tf_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    data: Mapped[str] = mapped_column(Text, nullable=False, default="")
    useData: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def effective(self) -> str:
        return (self.useData or "").strip() or self.data or ""


class TfAgentDeploy(TfBase):
    """Agent→能力 映射（源 o_agentDeploy）：key 形如 productionAgent:storyboardPanelAgent。"""
    __tablename__ = "tf_agent_deploy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    desc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    temperature: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    maxOutputTokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TfSetting(TfBase):
    """KV 设置（源 o_setting）。"""
    __tablename__ = "tf_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")


class TfTask(TfBase):
    """生成任务台账（源 o_tasks）：withTaskRecord 包装每次 AI 调用。"""
    __tablename__ = "tf_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projectId: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(Text, nullable=False, default="")           # image/video/tts/text
    state: Mapped[str] = mapped_column(Text, nullable=False, default=STATE_GENERATING)
    remark: Mapped[str] = mapped_column(Text, nullable=False, default="")
    startTime: Mapped[int | None] = mapped_column(Integer)
    endTime: Mapped[int | None] = mapped_column(Integer)
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms)


class TfMemory(TfBase):
    """Agent 向量化记忆（源 memories 表）：按 isolationKey(=agent:项目) 隔离存取。

    type=message 原始会话消息（embedding 已算）；type=summary 由 LLM 压缩的摘要，
    relatedMessageIds 指回被压缩的原始消息，支撑 deepRetrieve「摘要召回→原文展开」。
    """
    __tablename__ = "tf_memories"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    isolationKey: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    type: Mapped[str] = mapped_column(Text, nullable=False, default="message")    # message / summary
    role: Mapped[str] = mapped_column(Text, nullable=False, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[str] = mapped_column(Text, nullable=False, default="")      # JSON float 数组
    relatedMessageIds: Mapped[str] = mapped_column(Text, nullable=False, default="")  # JSON 数组
    summarized: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # 1=已被摘要
    createTime: Mapped[int] = mapped_column(Integer, nullable=False, default=_ms, index=True)


TF_TABLES = (TfProject, TfNovel, TfScript, TfAsset, TfImage, TfStoryboard,
             TfVideo, TfVideoTrack, TfScriptAsset, TfAssetRoleAudio,
             TfPrompt, TfAgentDeploy, TfSetting, TfTask, TfMemory)
