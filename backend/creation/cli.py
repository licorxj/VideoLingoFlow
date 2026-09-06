"""快捷查看命令,便于在终端直接核对创作数据。

用法:
    python -m backend.creation.cli creation list [关键词]
    python -m backend.creation.cli creation show <creation_id>
    python -m backend.creation.cli asset list <creation_id> [asset_kind]
    python -m backend.creation.cli character list [关键词]
    python -m backend.creation.cli image list [关键词]
    python -m backend.creation.cli video list [关键词]
    python -m backend.creation.cli audio resolve <vf:引用>
    python -m backend.creation.cli audio voices [关键词]
    python -m backend.creation.cli audio assets [asset_type]
"""

import argparse
import json
import sys

from backend.creation import audio_refs, libraries, store


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.creation.cli", description="AI 剧集创作数据快捷查看命令")
    sub = parser.add_subparsers(dest="group", required=True)

    creation = sub.add_parser("creation", help="创作项目")
    creation_sub = creation.add_subparsers(dest="action", required=True)
    creation_list = creation_sub.add_parser("list")
    creation_list.add_argument("keyword", nargs="?", default="")
    creation_show = creation_sub.add_parser("show")
    creation_show.add_argument("creation_id")

    asset = sub.add_parser("asset", help="项目资产明细")
    asset_sub = asset.add_subparsers(dest="action", required=True)
    asset_list = asset_sub.add_parser("list")
    asset_list.add_argument("creation_id")
    asset_list.add_argument("asset_kind", nargs="?", default="")

    character = sub.add_parser("character", help="公共角色库")
    character_sub = character.add_subparsers(dest="action", required=True)
    character_list = character_sub.add_parser("list")
    character_list.add_argument("keyword", nargs="?", default="")

    image = sub.add_parser("image", help="图片素材库")
    image_sub = image.add_subparsers(dest="action", required=True)
    image_list = image_sub.add_parser("list")
    image_list.add_argument("keyword", nargs="?", default="")

    video = sub.add_parser("video", help="视频素材库")
    video_sub = video.add_subparsers(dest="action", required=True)
    video_list = video_sub.add_parser("list")
    video_list.add_argument("keyword", nargs="?", default="")

    audio = sub.add_parser("audio", help="voiceforge 音频引用")
    audio_sub = audio.add_subparsers(dest="action", required=True)
    audio_resolve = audio_sub.add_parser("resolve")
    audio_resolve.add_argument("ref")
    audio_voices = audio_sub.add_parser("voices")
    audio_voices.add_argument("keyword", nargs="?", default="")
    audio_assets = audio_sub.add_parser("assets")
    audio_assets.add_argument("asset_type", nargs="?", default="")

    args = parser.parse_args(argv)
    try:
        if args.group == "creation":
            if args.action == "list":
                _print(store.list_creations(keyword=args.keyword))
            else:
                _print(store.get_creation(args.creation_id, with_detail=True))
        elif args.group == "asset":
            _print(store.list_assets(args.creation_id, asset_kind=args.asset_kind))
        elif args.group == "character":
            _print(libraries.list_characters(keyword=args.keyword))
        elif args.group == "image":
            _print(libraries.list_images(keyword=args.keyword))
        elif args.group == "video":
            _print(libraries.list_videos(keyword=args.keyword))
        elif args.group == "audio":
            if args.action == "resolve":
                _print(audio_refs.resolve_audio_ref(args.ref))
            elif args.action == "voices":
                _print(audio_refs.list_voices(args.keyword))
            else:
                _print(audio_refs.list_audio_assets(asset_type=args.asset_type))
    except (store.NotFoundError, store.ValidationError, ValueError, LookupError, FileNotFoundError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
