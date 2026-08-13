"""旧版 Windows 客户端数据迁移脚本。

把 %LOCALAPPDATA%\\Social Auto Upload Web UI\\ 的数据迁移到项目 data/ 目录：
  - cookies/、cookiesFile/、db/  三个目录直接覆盖
  - videoFile/ 中的素材调用后端 /api/materials/upload 上传

使用方法：先执行 start.bat / start.sh 启动后端，再运行本脚本。
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import requests


def default_source() -> Path:
    """解析旧版数据目录。Windows 下用 %LOCALAPPDATA%，其他平台回退到 fixture。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / "Social Auto Upload Web UI"
    return Path(__file__).resolve().parent / "legacy_fixture"


def default_target() -> Path:
    """解析新版 data 目录。优先 SAU_DATA_DIR，否则 {项目根}/data。"""
    env = os.environ.get("SAU_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_",
    re.IGNORECASE,
)

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v", ".wmv", ".mpeg", ".mpg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}
ALLOWED_EXTS = VIDEO_EXTS | IMAGE_EXTS


# drafts / materials 表的期望列定义，与 backend/init_db.py 保持一致。
# 旧版数据库缺这些列时迁移后会补齐；旧列（不在 EXPECTED_* 中）保留不动。
EXPECTED_DRAFTS_COLUMNS: list[tuple[str, str]] = [
    ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    ("type", "TEXT DEFAULT 'video'"),
    ("title", "TEXT DEFAULT ''"),
    ("cover_path", "TEXT DEFAULT ''"),
    ("draft_data", "TEXT DEFAULT '{}'"),
    ("channels_summary", "TEXT DEFAULT '[]'"),
    ("video_duration", "REAL DEFAULT 0"),
    ("video_file_size", "INTEGER DEFAULT 0"),
    ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
]

EXPECTED_MATERIALS_COLUMNS: list[tuple[str, str]] = [
    ("id", "TEXT PRIMARY KEY"),
    ("original_filename", "TEXT NOT NULL"),
    ("stored_path", "TEXT NOT NULL"),
    ("file_type", "TEXT NOT NULL"),
    ("mime_type", "TEXT"),
    ("file_size", "INTEGER DEFAULT 0"),
    ("storage_type", "TEXT NOT NULL DEFAULT 'local'"),
    ("width", "INTEGER DEFAULT 0"),
    ("height", "INTEGER DEFAULT 0"),
    ("duration", "REAL DEFAULT 0"),
    ("thumbnail_path", "TEXT DEFAULT ''"),
    ("upload_time", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
]


def _table_exists(cursor: sqlite3.Cursor, table: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def _get_existing_columns(cursor: sqlite3.Cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def align_table_schema(
    cursor: sqlite3.Cursor,
    table: str,
    expected: list[tuple[str, str]],
) -> tuple[str, list[str]]:
    """缺表建表 + 缺列补列。返回 (status, info)。

    status:
      - "created":  表不存在，已创建
      - "added":    表存在，补齐了部分列（info 是补齐的列名列表）
      - "unchanged": 表存在且 schema 已对齐

    SQLite 限制：表有数据时，ALTER TABLE ADD COLUMN 不允许 DEFAULT <非常量>
    （如 CURRENT_TIMESTAMP）。遇到这种情况退化用空默认补列（NULL）。
    """
    if not _table_exists(cursor, table):
        cols_sql = ", ".join(f"{name} {definition}" for name, definition in expected)
        cursor.execute(f"CREATE TABLE {table} ({cols_sql})")
        return "created", [name for name, _ in expected]

    existing = _get_existing_columns(cursor, table)
    added: list[str] = []
    for col_name, col_def in expected:
        if col_name in existing:
            continue
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError as e:
            if "non-constant default" not in str(e):
                raise
            # 退化：去掉 DEFAULT 子句，用 NULL 默认补列
            fallback_def = re.sub(r"\s+DEFAULT\s+\S+", "", col_def, flags=re.IGNORECASE).strip()
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {fallback_def}")
        added.append(col_name)
    return ("added", added) if added else ("unchanged", [])


def align_db_tables(db_path: Path, dry_run: bool = False) -> None:
    """打开 db_path，对齐 drafts 和 materials 表结构。dry_run=True 时只打印不修改。"""
    expectations: list[tuple[str, list[tuple[str, str]]]] = [
        ("drafts", EXPECTED_DRAFTS_COLUMNS),
        ("materials", EXPECTED_MATERIALS_COLUMNS),
    ]
    if dry_run:
        for table, _ in expectations:
            print(f"      ⊘ dry-run: 将对齐 {table} 表结构")
        return
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        for table, expected in expectations:
            status, info = align_table_schema(cursor, table, expected)
            if status == "created":
                print(f"      ✓ {table}: 表不存在已创建（{len(info)} 列）")
            elif status == "added":
                print(f"      ✓ {table}: 补齐列 {', '.join(info)}")
            else:
                print(f"      ⊘ {table}: schema 已对齐")
        conn.commit()
    finally:
        conn.close()


def strip_uuid_prefix(name: str) -> str:
    """剥掉 {uuid}_ 前缀，仅剥一次。"""
    return UUID_PREFIX.sub("", name, count=1)


def is_allowed_ext(filename: str) -> bool:
    """判断文件扩展名是否在新版素材库白名单内。"""
    return Path(filename).suffix.lower() in ALLOWED_EXTS


def check_backend(api_base: str, timeout: float = 2.0) -> bool:
    """探测后端健康状态。返回 True 表示可访问。

    使用 /api/materials/list 端点做轻量级 ping。
    """
    try:
        resp = requests.get(
            f"{api_base}/api/materials/list",
            params={"page": 1, "page_size": 1},
            timeout=timeout,
        )
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _timestamp() -> str:
    """返回 YYYYMMDD_HHMMSS 格式时间戳。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_data(
    data_dir: Path,
    dry_run: bool = False,
    skip: bool = False,
) -> Path | None:
    """把 data 目录整个复制到 data.bak.YYYYMMDD_HHMMSS/data/ 下。返回备份路径。

    备份采用 data/ 子目录包装布局（例如 <backup>/data/cookies/foo.json），
    方便直接 `cp -r <backup>/data/* <target>/` 整体恢复。

    - skip=True  时返回 None（不创建任何目录）
    - dry_run=True 时返回预期的备份路径但不实际复制
    """
    if skip:
        return None
    backup_path = data_dir.parent / f"data.bak.{_timestamp()}"
    if dry_run:
        return backup_path
    shutil.copytree(data_dir, backup_path / "data")
    return backup_path


def copy_directory(
    src: Path,
    dst: Path,
    dry_run: bool = False,
) -> tuple[int, int]:
    """递归把 src 下的所有文件覆盖到 dst 下。

    返回 (copied, failed) 计数。已存在于 dst 的文件被覆盖，但 dst 中
    不在 src 下的文件不会被删除（覆盖语义，非镜像语义）。
    """
    if not src.exists():
        return 0, 0
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    failed = 0
    for src_file in src.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src)
        dst_file = dst / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            copied += 1
            continue
        try:
            shutil.copy2(src_file, dst_file)
            copied += 1
        except OSError as e:
            print(f"ERROR: copy {src_file} -> {dst_file}: {e}", file=sys.stderr)
            failed += 1
    return copied, failed


def upload_material(
    src: Path,
    api_base: str,
    dry_run: bool = False,
    timeout: float = 300.0,
) -> bool:
    """把 src 调后端 /api/materials/upload 上传。返回 True/False。

    - 文件名 uuid 前缀被剥离后作为 multipart.filename 传递
    - mime 用 mimetypes.guess_type 推断
    - dry_run=True 时不实际发送请求
    """
    original_name = strip_uuid_prefix(src.name)
    if dry_run:
        return True
    mime_type, _ = mimetypes.guess_type(original_name)
    mime_type = mime_type or "application/octet-stream"
    try:
        with open(src, "rb") as f:
            resp = requests.post(
                f"{api_base}/api/materials/upload",
                files={"file": (original_name, f, mime_type)},
                timeout=timeout,
            )
        resp.raise_for_status()
        return True
    except (requests.exceptions.RequestException, OSError) as e:
        print(f"ERROR: 上传 {src.name} 失败: {e}", file=sys.stderr)
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="旧版 Windows 客户端数据迁移到新版 data/ 目录",
    )
    parser.add_argument(
        "--source", type=Path, default=None,
        help="旧版数据目录，默认 %%LOCALAPPDATA%%\\Social Auto Upload Web UI",
    )
    parser.add_argument(
        "--target", type=Path, default=None,
        help="新版 data 目录，默认 {项目根}/data",
    )
    parser.add_argument(
        "--api-base", type=str, default="http://127.0.0.1:5409",
        help="后端 API 根地址，默认 http://127.0.0.1:5409",
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="只列出将要执行的操作，不真正修改文件",
    )
    parser.add_argument(
        "--skip-backup", dest="skip_backup", action="store_true",
        help="跳过备份（仅当你已手动备份时使用）",
    )
    parser.add_argument(
        "--yes", dest="yes", action="store_true",
        help="跳过交互式确认",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """脚本主入口。返回退出码。"""
    args = parse_args(argv if argv is not None else sys.argv[1:])

    source = args.source or default_source()
    target = args.target or default_target()
    api_base = args.api_base.rstrip("/")

    print(f"[1/5] 解析源/目标路径...")
    print(f"      源: {source}")
    print(f"      目标: {target}")
    if not source.exists():
        print(f"ERROR: 旧版数据目录不存在: {source}", file=sys.stderr)
        return 1

    # 阶段 2: 备份
    print(f"[2/5] 备份当前 data ...")
    if args.skip_backup:
        print(f"      ⊘ 已跳过（--skip-backup）")
    elif not target.exists():
        print(f"      ⊘ 目标 data 不存在，跳过")
    else:
        try:
            backup_path = backup_data(target, dry_run=args.dry_run)
        except OSError as e:
            print(f"ERROR: 备份失败: {e}", file=sys.stderr)
            return 2
        if backup_path is None:
            print(f"      ⊘ 已跳过")
        elif args.dry_run:
            print(f"      ⊘ dry-run 模式，预览路径 {backup_path}")
        else:
            print(f"      ✓ 已备份到 {backup_path}")

    # 确保目标子目录存在
    for sub in ["cookies", "cookiesFile", "db", "materials"]:
        (target / sub).mkdir(parents=True, exist_ok=True)

    # 阶段 3: 后端探测
    print(f"[3/5] 探测后端健康状态 ({api_base})...")
    if not args.dry_run and not check_backend(api_base):
        print(f"ERROR: 后端不可达，请先执行 start.bat / start.sh 启动后端", file=sys.stderr)
        return 3
    print(f"      ✓ 后端正常")

    # 阶段 4: 拷贝
    print(f"[4/5] 拷贝 cookies/cookiesFile/db ...")
    copy_stats: dict = {}
    for sub in ["cookies", "cookiesFile", "db"]:
        src_sub = source / sub
        if not src_sub.exists():
            print(f"      ⊘ {sub}/ 源目录不存在，跳过")
            copy_stats[sub] = (0, 0)
            continue
        copied, failed = copy_directory(src_sub, target / sub, dry_run=args.dry_run)
        copy_stats[sub] = (copied, failed)
        marker = "⊘" if args.dry_run else "✓"
        print(f"      {marker} {sub + '/':<14}复制 {copied} 个文件" + (f", 失败 {failed}" if failed else ""))

    # 阶段 4.5: 修正 db 中 drafts / materials 表结构（缺表建表，缺列补列）
    db_file = target / "db" / "database.db"
    if db_file.exists():
        print(f"[4.5/5] 修正 drafts / materials 表结构...")
        try:
            align_db_tables(db_file, dry_run=args.dry_run)
        except sqlite3.Error as e:
            print(f"      ⚠ 表结构修正失败: {e}", file=sys.stderr)
    else:
        print(f"[4.5/5] ⊘ db/database.db 不存在，跳过表结构修正")

    # 阶段 5: 迁移素材
    print(f"[5/5] 迁移素材库 (videoFile/)...")
    vf = source / "videoFile"
    upload_ok = 0
    upload_fail = 0
    upload_skip = 0
    if not vf.exists():
        print(f"      ⊘ videoFile/ 源目录不存在，跳过")
    else:
        files = sorted(p for p in vf.rglob("*") if p.is_file())
        total = len(files)
        for i, f in enumerate(files, 1):
            if not is_allowed_ext(f.name):
                upload_skip += 1
                print(f"      [{i}/{total}] 跳过 {f.name} (非素材类型) ⊘")
                continue
            print(f"      [{i}/{total}] 上传 {strip_uuid_prefix(f.name)} ... ", end="", flush=True)
            ok = upload_material(f, api_base=api_base, dry_run=args.dry_run)
            if ok:
                upload_ok += 1
                print("✓" if not args.dry_run else "⊘ dry-run")
            else:
                upload_fail += 1
                print("✗")

    # 报告
    print()
    print("=" * 40)
    print("迁移报告")
    print("=" * 40)
    for sub in ["cookies", "cookiesFile", "db"]:
        c, f = copy_stats.get(sub, (0, 0))
        suffix = f", 失败 {f}" if f else ""
        print(f"  {sub + '/':<14}复制 {c} 个文件{suffix}")
    print(f"  {'videoFile/':<14}成功 {upload_ok}, 失败 {upload_fail}, 跳过 {upload_skip}")
    if not args.skip_backup and target.exists():
        # 找最新的备份
        backups = sorted(target.parent.glob("data.bak.*"), key=lambda p: p.name, reverse=True)
        if backups:
            print(f"  备份位置:       {backups[0]}")
    print("=" * 40)

    return 0


if __name__ == "__main__":
    sys.exit(main())
