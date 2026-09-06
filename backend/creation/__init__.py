"""AI 剧集创作数据层。

    store.py      项目数据读写(项目/人物/章节/分镜/资产明细)
    libraries.py  公共角色库、图片素材库、视频素材库
    audio_refs.py 音频素材 vf: 引用与 voiceforge 读写辅助
    paths.py      路径约定(公共素材 data/ 相对路径,过程文件绝对路径)
    cli.py        终端快捷查看命令:python -m backend.creation.cli
"""

from backend.creation.audio_refs import (
    add_audio_asset,
    audio_ref_abspath,
    delete_audio_asset,
    is_audio_ref,
    list_audio_assets,
    list_voices,
    make_audio_asset_ref,
    make_export_ref,
    make_voice_ref,
    parse_audio_ref,
    resolve_audio_ref,
    update_audio_asset,
)
from backend.creation.common import CreationDataError, NotFoundError, ValidationError
from backend.creation.libraries import (
    add_image,
    add_video,
    create_character,
    delete_character,
    delete_image,
    delete_video,
    get_character,
    get_image,
    get_video,
    list_characters,
    list_images,
    list_videos,
    update_character,
    update_image,
    update_video,
)
from backend.creation.paths import (
    normalize_public_path,
    normalize_runtime_path,
    resolve_public_path,
    resolve_storage_path,
)
from backend.creation.store import (
    add_chapter,
    add_creation_character,
    add_dialogue,
    add_shot,
    append_asset_paths,
    create_creation,
    delete_creation,
    export_creation,
    get_chapter,
    get_creation,
    get_shot,
    list_assets,
    list_chapters,
    list_creations,
    publish_character_to_library,
    register_asset,
    remove_asset,
    remove_chapter,
    remove_creation_character,
    remove_dialogue,
    remove_shot,
    set_script,
    update_asset,
    update_chapter,
    update_creation,
    update_creation_character,
    update_shot,
)

__all__ = [
    # 项目数据
    "create_creation", "get_creation", "list_creations", "update_creation", "set_script", "delete_creation", "export_creation",
    "add_creation_character", "update_creation_character", "remove_creation_character", "publish_character_to_library",
    "add_chapter", "get_chapter", "list_chapters", "update_chapter", "remove_chapter",
    "add_shot", "get_shot", "update_shot", "add_dialogue", "remove_dialogue", "remove_shot",
    "register_asset", "list_assets", "update_asset", "append_asset_paths", "remove_asset",
    # 公共素材库
    "create_character", "get_character", "list_characters", "update_character", "delete_character",
    "add_image", "get_image", "list_images", "update_image", "delete_image",
    "add_video", "get_video", "list_videos", "update_video", "delete_video",
    # 音频引用(voiceforge)
    "is_audio_ref", "make_voice_ref", "make_audio_asset_ref", "make_export_ref", "parse_audio_ref",
    "resolve_audio_ref", "audio_ref_abspath", "list_voices", "list_audio_assets",
    "add_audio_asset", "update_audio_asset", "delete_audio_asset",
    # 路径
    "normalize_public_path", "normalize_runtime_path", "resolve_public_path", "resolve_storage_path",
    # 异常
    "CreationDataError", "NotFoundError", "ValidationError",
]
