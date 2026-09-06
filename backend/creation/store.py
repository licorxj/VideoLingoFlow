"""AI 剧集创作项目数据读写脚本。

覆盖:项目主表(cp_creations)、项目人物(cp_creation_characters)、章节
(cp_creation_chapters)、分镜(cp_creation_shots)、资产明细(cp_creation_assets)。

配套模块:
    libraries.py   公共角色库 / 图片素材库 / 视频素材库
    audio_refs.py  音频素材 vf: 引用(音色/音效/背景音乐存于 voiceforge 库)
    paths.py       路径约定:公共素材 data/ 相对路径,过程文件绝对路径

典型用法:
    from backend.creation import create_creation, add_chapter, add_shot, register_asset, export_creation

    creation = create_creation("星尘旅人", genre_tags="科幻,冒险", art_style_tags="赛博朋克")
    chapter = add_chapter(creation["id"], title="第一章", original_text="……", summary="……")
    shot = add_shot(chapter["id"], characters=["林远"], scene_descriptions=["废弃空间站走廊"],
                    dialogues=[("林远", "这里有生命信号。")])
    register_asset(creation["id"], "scene_image", chapter_id=chapter["id"], shot_id=shot["id"],
                   paths=["D:/runtime/project/shots/s1/img_001.png"])
"""

import uuid
from pathlib import Path

from sqlalchemy import func, select

from backend.control_plane.database import session_scope
from backend.control_plane.models import CREATION_ASSET_KINDS, Creation, CreationAsset, CreationChapter, CreationCharacter, CreationShot
from backend.creation import audio_refs, paths
from backend.creation.common import NotFoundError, ValidationError, ensure_tag_list, row_to_dict

_CREATION_FIELDS = {"name", "description", "genre_tags", "art_style_tags", "audience_tags", "status", "script_text", "owner_id", "project_id"}
_CREATION_CHARACTER_FIELDS = {"name", "gender", "age", "personality", "occupation", "aliases", "relationship_note", "voice_design", "voice_ref", "character_lib_id"}
_CHAPTER_FIELDS = {"title", "original_text", "summary", "order_no"}
_SHOT_FIELDS = {"characters", "scene_descriptions", "dialogues", "bgm_design", "sfx_design", "order_no"}
_ASSET_FIELDS = {"name", "ref_id", "paths", "sequence", "duration_seconds", "description", "metadata_json", "chapter_id", "shot_id"}


def _new_dialogue_id() -> str:
    return "dlg_" + uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- 项目主表


def create_creation(
    name: str,
    *,
    description: str = "",
    genre_tags=None,
    art_style_tags=None,
    audience_tags=None,
    script_text: str = "",
    status: str = "draft",
    owner_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    """新建 AI 剧集创作项目。标签支持 list 或逗号分隔字符串。"""
    if not name or not str(name).strip():
        raise ValidationError("项目名称不能为空")
    with session_scope() as session:
        row = Creation(
            name=str(name).strip(),
            description=description,
            genre_tags=ensure_tag_list(genre_tags),
            art_style_tags=ensure_tag_list(art_style_tags),
            audience_tags=ensure_tag_list(audience_tags),
            script_text=script_text,
            status=status,
            owner_id=owner_id,
            project_id=project_id,
        )
        session.add(row)
        session.flush()
        return row_to_dict(row)


def get_creation(creation_id: str, *, with_detail: bool = False) -> dict:
    """读取项目;with_detail=True 时附带人物、章节(含分镜)与资产明细。"""
    with session_scope() as session:
        row = session.get(Creation, creation_id)
        if row is None:
            raise NotFoundError(f"创作项目不存在: {creation_id}")
        data = row_to_dict(row)
        if with_detail:
            data["characters"] = [row_to_dict(item) for item in session.scalars(select(CreationCharacter).where(CreationCharacter.creation_id == creation_id).order_by(CreationCharacter.created_at)).all()]
            chapters = session.scalars(select(CreationChapter).where(CreationChapter.creation_id == creation_id).order_by(CreationChapter.order_no)).all()
            chapter_ids = [chapter.id for chapter in chapters]
            shots: dict[str, list] = {}
            if chapter_ids:
                for shot in session.scalars(select(CreationShot).where(CreationShot.chapter_id.in_(chapter_ids)).order_by(CreationShot.order_no)).all():
                    shots.setdefault(shot.chapter_id, []).append(row_to_dict(shot))
            data["chapters"] = [{**row_to_dict(chapter), "shots": shots.get(chapter.id, [])} for chapter in chapters]
            data["assets"] = [row_to_dict(item) for item in session.scalars(select(CreationAsset).where(CreationAsset.creation_id == creation_id).order_by(CreationAsset.created_at)).all()]
        return data


def list_creations(*, owner_id: str = "", project_id: str = "", keyword: str = "") -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(Creation).order_by(Creation.created_at)).all()
    result = []
    for row in rows:
        if owner_id and row.owner_id != owner_id:
            continue
        if project_id and row.project_id != project_id:
            continue
        if keyword and keyword not in row.name and keyword not in row.description:
            continue
        result.append(row_to_dict(row))
    return result


def update_creation(creation_id: str, **fields) -> dict:
    unknown = set(fields) - _CREATION_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    for key in ("genre_tags", "art_style_tags", "audience_tags"):
        if key in fields:
            fields[key] = ensure_tag_list(fields[key])
    if "name" in fields and not str(fields.get("name") or "").strip():
        raise ValidationError("项目名称不能为空")
    with session_scope() as session:
        row = _require_creation(session, creation_id)
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def set_script(creation_id: str, script_text: str) -> dict:
    """写入/替换剧本全文。"""
    return update_creation(creation_id, script_text=script_text)


def delete_creation(creation_id: str) -> None:
    """删除项目及其人物、章节、分镜、资产明细。"""
    with session_scope() as session:
        row = _require_creation(session, creation_id)
        session.delete(row)


# ---------------------------------------------------------------- 项目人物


def add_creation_character(
    creation_id: str,
    name: str,
    *,
    gender: str = "",
    age: str = "",
    personality: str = "",
    occupation: str = "",
    aliases=None,
    relationship_note: str = "",
    voice_design: str = "",
    voice_ref: str = "",
    character_lib_id: str | None = None,
) -> dict:
    """为项目添加人物设定;voice_ref 为 vf:voices:<id> 音色引用,character_lib_id 关联公共角色库。"""
    if not name or not str(name).strip():
        raise ValidationError("人物姓名不能为空")
    if voice_ref and not audio_refs.is_audio_ref(voice_ref):
        raise ValidationError(f"voice_ref 必须是 vf: 格式的音频素材引用: {voice_ref}")
    with session_scope() as session:
        _require_creation(session, creation_id)
        _require_character_lib(session, character_lib_id)
        if session.scalar(select(CreationCharacter.id).where(CreationCharacter.creation_id == creation_id, CreationCharacter.name == name)):
            raise ValidationError(f"项目内已存在同名人物: {name}")
        row = CreationCharacter(
            creation_id=creation_id,
            name=str(name).strip(),
            gender=gender,
            age=age,
            personality=personality,
            occupation=occupation,
            aliases=ensure_tag_list(aliases),
            relationship_note=relationship_note,
            voice_design=voice_design,
            voice_ref=voice_ref,
            character_lib_id=character_lib_id,
        )
        session.add(row)
        session.flush()
        return row_to_dict(row)


def update_creation_character(character_id: str, **fields) -> dict:
    unknown = set(fields) - _CREATION_CHARACTER_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    if fields.get("voice_ref") and not audio_refs.is_audio_ref(fields["voice_ref"]):
        raise ValidationError(f"voice_ref 必须是 vf: 格式的音频素材引用: {fields['voice_ref']}")
    if "aliases" in fields:
        fields["aliases"] = ensure_tag_list(fields["aliases"])
    with session_scope() as session:
        row = session.get(CreationCharacter, character_id)
        if row is None:
            raise NotFoundError(f"项目人物不存在: {character_id}")
        if "character_lib_id" in fields:
            _require_character_lib(session, fields["character_lib_id"])
        if "name" in fields:
            new_name = str(fields["name"] or "").strip()
            if not new_name:
                raise ValidationError("人物姓名不能为空")
            fields["name"] = new_name
            if session.scalar(select(CreationCharacter.id).where(CreationCharacter.creation_id == row.creation_id, CreationCharacter.name == new_name, CreationCharacter.id != character_id)):
                raise ValidationError(f"项目内已存在同名人物: {new_name}")
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def remove_creation_character(character_id: str) -> None:
    with session_scope() as session:
        row = session.get(CreationCharacter, character_id)
        if row is None:
            raise NotFoundError(f"项目人物不存在: {character_id}")
        session.delete(row)


def publish_character_to_library(creation_character_id: str, *, tags=None) -> dict:
    """把项目人物发布到公共角色库,并回写 character_lib_id 建立关联。"""
    from backend.control_plane.models import Character

    with session_scope() as session:
        row = session.get(CreationCharacter, creation_character_id)
        if row is None:
            raise NotFoundError(f"项目人物不存在: {creation_character_id}")
        if row.character_lib_id:
            existing = session.get(Character, row.character_lib_id)
            if existing is not None:
                return row_to_dict(existing)
        character = Character(
            name=row.name,
            tags=ensure_tag_list(tags),
            gender=row.gender,
            age=row.age,
            personality=row.personality,
            occupation=row.occupation,
            aliases=list(row.aliases or []),
            voice_design=row.voice_design,
            voice_ref=row.voice_ref,
            origin_creation_id=row.creation_id,
        )
        session.add(character)
        session.flush()
        row.character_lib_id = character.id
        session.flush()
        return row_to_dict(character)


# ---------------------------------------------------------------- 章节


def add_chapter(creation_id: str, *, order_no: int | None = None, title: str = "", original_text: str = "", summary: str = "") -> dict:
    """新增章节;order_no 缺省时追加到末尾。"""
    with session_scope() as session:
        _require_creation(session, creation_id)
        if order_no is None:
            order_no = (session.scalar(select(func.max(CreationChapter.order_no)).where(CreationChapter.creation_id == creation_id)) or 0) + 1
        if session.scalar(select(CreationChapter.id).where(CreationChapter.creation_id == creation_id, CreationChapter.order_no == order_no)):
            raise ValidationError(f"章节序号已存在: {order_no}")
        row = CreationChapter(creation_id=creation_id, order_no=order_no, title=title, original_text=original_text, summary=summary)
        session.add(row)
        session.flush()
        return row_to_dict(row)


def get_chapter(chapter_id: str, *, with_shots: bool = True) -> dict:
    with session_scope() as session:
        row = session.get(CreationChapter, chapter_id)
        if row is None:
            raise NotFoundError(f"章节不存在: {chapter_id}")
        data = row_to_dict(row)
        if with_shots:
            data["shots"] = [row_to_dict(shot) for shot in session.scalars(select(CreationShot).where(CreationShot.chapter_id == chapter_id).order_by(CreationShot.order_no)).all()]
        return data


def list_chapters(creation_id: str, *, with_shots: bool = False) -> list[dict]:
    with session_scope() as session:
        _require_creation(session, creation_id)
        rows = session.scalars(select(CreationChapter).where(CreationChapter.creation_id == creation_id).order_by(CreationChapter.order_no)).all()
        data = [row_to_dict(row) for row in rows]
        if with_shots:
            chapter_ids = [item["id"] for item in data]
            shots: dict[str, list] = {}
            if chapter_ids:
                for shot in session.scalars(select(CreationShot).where(CreationShot.chapter_id.in_(chapter_ids)).order_by(CreationShot.order_no)).all():
                    shots.setdefault(shot.chapter_id, []).append(row_to_dict(shot))
            for item in data:
                item["shots"] = shots.get(item["id"], [])
        return data


def update_chapter(chapter_id: str, **fields) -> dict:
    unknown = set(fields) - _CHAPTER_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    with session_scope() as session:
        row = session.get(CreationChapter, chapter_id)
        if row is None:
            raise NotFoundError(f"章节不存在: {chapter_id}")
        if "order_no" in fields and fields["order_no"] != row.order_no:
            if session.scalar(select(CreationChapter.id).where(CreationChapter.creation_id == row.creation_id, CreationChapter.order_no == fields["order_no"], CreationChapter.id != chapter_id)):
                raise ValidationError(f"章节序号已存在: {fields['order_no']}")
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def remove_chapter(chapter_id: str) -> None:
    """删除章节及其下全部分镜。"""
    with session_scope() as session:
        row = session.get(CreationChapter, chapter_id)
        if row is None:
            raise NotFoundError(f"章节不存在: {chapter_id}")
        session.delete(row)


# ---------------------------------------------------------------- 分镜


def add_shot(
    chapter_id: str,
    *,
    order_no: int | None = None,
    characters=None,
    scene_descriptions=None,
    dialogues=None,
    bgm_design: str = "",
    sfx_design: str = "",
) -> dict:
    """新增分镜;order_no 缺省时追加到末尾。

    characters 接受姓名列表或 [{"name": .., "character_lib_id": ..}];dialogues
    接受 (人物, 内容) 元组或 {"character": .., "content": ..} 字典,缺省时自动
    生成 dialogue_id。
    """
    with session_scope() as session:
        chapter = session.get(CreationChapter, chapter_id)
        if chapter is None:
            raise NotFoundError(f"章节不存在: {chapter_id}")
        if order_no is None:
            order_no = (session.scalar(select(func.max(CreationShot.order_no)).where(CreationShot.chapter_id == chapter_id)) or 0) + 1
        if session.scalar(select(CreationShot.id).where(CreationShot.chapter_id == chapter_id, CreationShot.order_no == order_no)):
            raise ValidationError(f"分镜序号已存在: {order_no}")
        row = CreationShot(
            chapter_id=chapter_id,
            order_no=order_no,
            characters=_normalize_shot_characters(characters),
            scene_descriptions=[str(item) for item in (scene_descriptions or [])],
            dialogues=_normalize_dialogues(dialogues),
            bgm_design=bgm_design,
            sfx_design=sfx_design,
        )
        session.add(row)
        session.flush()
        return row_to_dict(row)


def get_shot(shot_id: str) -> dict:
    with session_scope() as session:
        row = session.get(CreationShot, shot_id)
        if row is None:
            raise NotFoundError(f"分镜不存在: {shot_id}")
        return row_to_dict(row)


def update_shot(shot_id: str, **fields) -> dict:
    unknown = set(fields) - _SHOT_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    with session_scope() as session:
        row = session.get(CreationShot, shot_id)
        if row is None:
            raise NotFoundError(f"分镜不存在: {shot_id}")
        if "order_no" in fields and fields["order_no"] != row.order_no:
            if session.scalar(select(CreationShot.id).where(CreationShot.chapter_id == row.chapter_id, CreationShot.order_no == fields["order_no"], CreationShot.id != shot_id)):
                raise ValidationError(f"分镜序号已存在: {fields['order_no']}")
        if "characters" in fields:
            fields["characters"] = _normalize_shot_characters(fields["characters"])
        if "dialogues" in fields:
            fields["dialogues"] = _normalize_dialogues(fields["dialogues"])
        if "scene_descriptions" in fields:
            fields["scene_descriptions"] = [str(item) for item in (fields["scene_descriptions"] or [])]
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def add_dialogue(shot_id: str, character: str, content: str, *, dialogue_id: str | None = None) -> dict:
    """向分镜追加一条对话。"""
    with session_scope() as session:
        row = session.get(CreationShot, shot_id)
        if row is None:
            raise NotFoundError(f"分镜不存在: {shot_id}")
        entry = {"dialogue_id": dialogue_id or _new_dialogue_id(), "character": str(character).strip(), "content": str(content)}
        if not entry["character"]:
            raise ValidationError("对话人物不能为空")
        row.dialogues = [*list(row.dialogues or []), entry]
        session.flush()
        return entry


def remove_dialogue(shot_id: str, dialogue_id: str) -> None:
    """按对话 id 删除分镜内的一条对话。"""
    with session_scope() as session:
        row = session.get(CreationShot, shot_id)
        if row is None:
            raise NotFoundError(f"分镜不存在: {shot_id}")
        kept = [item for item in (row.dialogues or []) if item.get("dialogue_id") != dialogue_id]
        if len(kept) == len(row.dialogues or []):
            raise NotFoundError(f"对话不存在: {dialogue_id}")
        row.dialogues = kept


def remove_shot(shot_id: str) -> None:
    with session_scope() as session:
        row = session.get(CreationShot, shot_id)
        if row is None:
            raise NotFoundError(f"分镜不存在: {shot_id}")
        session.delete(row)


# ---------------------------------------------------------------- 资产明细


def register_asset(
    creation_id: str,
    asset_kind: str,
    *,
    chapter_id: str | None = None,
    shot_id: str | None = None,
    name: str = "",
    ref_id: str | None = None,
    paths_list=None,
    sequence: int | None = None,
    duration_seconds: float | None = None,
    description: str = "",
    metadata: dict | None = None,
) -> dict:
    """登记一条已生成的项目资产。

    asset_kind: character/scene_image/voiceover/shot_video/sfx/bgm/shot_render/chapter_render。
    paths_list 内允许混用:data/ 开头的公共素材相对路径,或运行时过程文件的
    绝对路径;音频类素材(音色/音效/背景音乐)的 ref_id 使用 vf: 引用。
    """
    if asset_kind not in CREATION_ASSET_KINDS:
        raise ValidationError(f"未知资产类型 {asset_kind},可选: {sorted(CREATION_ASSET_KINDS)}")
    normalized_paths = _normalize_asset_paths(paths_list)
    with session_scope() as session:
        _require_creation(session, creation_id)
        if chapter_id:
            _require_chapter(session, creation_id, chapter_id)
        if shot_id:
            shot = session.get(CreationShot, shot_id)
            if shot is None:
                raise NotFoundError(f"分镜不存在: {shot_id}")
            shot_chapter_id = shot.chapter_id
            if chapter_id and shot_chapter_id != chapter_id:
                raise ValidationError(f"分镜 {shot_id} 不属于章节 {chapter_id}")
        row = CreationAsset(
            creation_id=creation_id,
            asset_kind=asset_kind,
            chapter_id=chapter_id,
            shot_id=shot_id,
            name=name,
            ref_id=ref_id,
            paths=normalized_paths,
            sequence=sequence,
            duration_seconds=duration_seconds,
            description=description,
            metadata_json=dict(metadata or {}),
        )
        session.add(row)
        session.flush()
        return row_to_dict(row)


def list_assets(creation_id: str, *, asset_kind: str = "", chapter_id: str = "", shot_id: str = "") -> list[dict]:
    with session_scope() as session:
        _require_creation(session, creation_id)
        rows = session.scalars(select(CreationAsset).where(CreationAsset.creation_id == creation_id).order_by(CreationAsset.created_at)).all()
    result = []
    for row in rows:
        if asset_kind and row.asset_kind != asset_kind:
            continue
        if chapter_id and row.chapter_id != chapter_id:
            continue
        if shot_id and row.shot_id != shot_id:
            continue
        result.append(row_to_dict(row))
    return result


def update_asset(asset_id: str, **fields) -> dict:
    unknown = set(fields) - _ASSET_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    if "paths" in fields:
        fields["paths"] = _normalize_asset_paths(fields["paths"])
    with session_scope() as session:
        row = session.get(CreationAsset, asset_id)
        if row is None:
            raise NotFoundError(f"项目资产不存在: {asset_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def append_asset_paths(asset_id: str, new_paths) -> dict:
    """向资产追加产物路径(过程文件产出多次迭代时使用)。"""
    if isinstance(new_paths, (str,)):
        new_paths = [new_paths]
    with session_scope() as session:
        row = session.get(CreationAsset, asset_id)
        if row is None:
            raise NotFoundError(f"项目资产不存在: {asset_id}")
        row.paths = [*list(row.paths or []), *_normalize_asset_paths(new_paths)]
        session.flush()
        return row_to_dict(row)


def remove_asset(asset_id: str) -> None:
    with session_scope() as session:
        row = session.get(CreationAsset, asset_id)
        if row is None:
            raise NotFoundError(f"项目资产不存在: {asset_id}")
        session.delete(row)


def export_creation(creation_id: str) -> dict:
    """一次性导出项目全部数据(主表+人物+章节含分镜+资产明细),供 AI 创作流程取数。"""
    return get_creation(creation_id, with_detail=True)


# ---------------------------------------------------------------- 内部辅助


def _require_creation(session, creation_id: str) -> Creation:
    row = session.get(Creation, creation_id)
    if row is None:
        raise NotFoundError(f"创作项目不存在: {creation_id}")
    return row


def _require_character_lib(session, character_lib_id: str | None) -> None:
    from backend.control_plane.models import Character

    if character_lib_id is None:
        return
    if session.get(Character, character_lib_id) is None:
        raise NotFoundError(f"公共角色库中不存在该角色: {character_lib_id}")


def _require_chapter(session, creation_id: str, chapter_id: str) -> CreationChapter:
    row = session.get(CreationChapter, chapter_id)
    if row is None or row.creation_id != creation_id:
        raise NotFoundError(f"章节不存在或不属于该项目: {chapter_id}")
    return row


def _normalize_shot_characters(entries) -> list:
    result = []
    for entry in entries or []:
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                result.append(name)
        elif isinstance(entry, dict) and str(entry.get("name", "")).strip():
            normalized = {"name": str(entry["name"]).strip()}
            if entry.get("character_lib_id"):
                normalized["character_lib_id"] = entry["character_lib_id"]
            result.append(normalized)
        else:
            raise ValidationError(f"分镜人物格式应为姓名或 {{name, character_lib_id}}: {entry!r}")
    return result


def _normalize_dialogues(entries) -> list[dict]:
    result = []
    for entry in entries or []:
        if isinstance(entry, dict):
            character = str(entry.get("character", "")).strip()
            content = str(entry.get("content", ""))
            dialogue_id = str(entry.get("dialogue_id") or "").strip() or _new_dialogue_id()
        elif isinstance(entry, (tuple, list)) and len(entry) == 2:
            character, content = str(entry[0]).strip(), str(entry[1])
            dialogue_id = _new_dialogue_id()
        else:
            raise ValidationError(f"对话格式应为 {{dialogue_id, character, content}} 或 (人物, 内容): {entry!r}")
        if not character:
            raise ValidationError(f"对话缺少人物: {entry!r}")
        result.append({"dialogue_id": dialogue_id, "character": character, "content": content})
    return result


def _normalize_asset_paths(values) -> list[str]:
    """资产路径归一化:绝对路径(过程文件)原样校验入库,相对路径必须是 data/ 内的公共素材。"""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    normalized = []
    for item in values:
        value = str(item)
        normalized.append(paths.normalize_runtime_path(value) if Path(value).is_absolute() else paths.normalize_public_path(value))
    return normalized
