from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MediaType = Literal["video", "audio", "image", "subtitle"]


class AssetRecord(BaseModel):
    id: str
    name: str
    type: MediaType
    relative_path: str
    source: str
    size: int
    mime_type: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    recommended: bool = False


class ImportCandidate(AssetRecord):
    category: Literal["video", "audio", "subtitle", "cover", "other"]
    selected: bool = False


class ImportRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    use_dub_segments: bool = False
    include_audio: bool = False
    cover_id: str | None = None
    title: str | None = Field(default=None, max_length=500)


class ProjectWriteRequest(BaseModel):
    project: dict[str, Any]
    expected_revision: int


class CharactersWriteRequest(BaseModel):
    characters: list[dict[str, Any]] = Field(default_factory=list)
    expected_revision: int


class AgentRunRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    expert_role: Literal["auto", "general", "design", "audio", "editing", "storytelling"] = "auto"
    auto_mode: bool = False
    expected_revision: int | None = None
    manual_config: dict[str, str] | None = None


class AgentApprovalRequest(BaseModel):
    tool_call_ids: list[str] = Field(default_factory=list)
    approved: bool
