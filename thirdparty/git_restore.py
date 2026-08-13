#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thirdparty 子项目 git 元数据释放工具（纯标准库）

背景：
  主仓库分发时，各三方子项目（QM-LocalRouter/cutia/pi/social-auto-upload-web-ui）
  自带的 .git 若原样保留，会因"嵌入式 git 仓库"导致其源码/构建产物不随主仓库上传。
  因此分发时将各子项目 .git 打包为 thirdparty/.git-archives/*.git.zip 随仓库携带，
  在「安装」或「更新」入口检测到子项目缺少 .git 时，用本脚本解压释放。

用法:
    python thirdparty/git_restore.py             # 释放全部缺失 .git 的子项目
    python thirdparty/git_restore.py --check     # 仅检查，输出哪些子项目缺 .git（不写盘）

安全：
  解压成员名校验，拒绝包含绝对路径或 .. 的条目（归档由本仓库生成，正常不含）。
"""
import argparse
import sys
import zipfile
from pathlib import Path

THIRDPARTY = Path(__file__).resolve().parent
ARCHIVES = THIRDPARTY / ".git-archives"

PROJECTS = {
    "QM-LocalRouter": "QM-LocalRouter.git.zip",
    "cutia": "cutia.git.zip",
    "pi": "pi.git.zip",
    "social-auto-upload-web-ui": "social-auto-upload-web-ui.git.zip",
}


def _safe_member(name: str) -> bool:
    """拒绝绝对路径 / 盘符 / 上级目录穿越。"""
    if name.startswith("/") or name.startswith("\\"):
        return False
    if len(name) > 1 and name[1] == ":":
        return False
    parts = name.replace("\\", "/").split("/")
    return ".." not in parts


def missing_git() -> list[str]:
    """返回缺少 .git 的子项目名列表。"""
    return [proj for proj in PROJECTS if not (THIRDPARTY / proj / ".git").is_dir()]


def restore_one(project: str) -> bool:
    proj_dir = THIRDPARTY / project
    if (proj_dir / ".git").is_dir():
        return True  # 已有 git 信息，无需释放
    archive = ARCHIVES / PROJECTS[project]
    if not archive.is_file():
        print(f"  [WARN] {project}: 无 .git 且无归档 {archive.name}，跳过 git 释放")
        return False
    if not proj_dir.is_dir():
        print(f"  [WARN] {project}: 目录不存在（{proj_dir}），跳过")
        return False
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if not _safe_member(info.filename):
                    raise RuntimeError(f"归档包含非法路径: {info.filename}")
            zf.extractall(proj_dir)
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {project}: git 释放失败: {e}")
        return False
    print(f"  [OK] {project}: 已释放 .git（{archive.name}）")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="释放 thirdparty 子项目 git 元数据")
    parser.add_argument("--check", action="store_true", help="仅检查缺失情况，不释放")
    args = parser.parse_args()

    missing = missing_git()
    if args.check:
        if missing:
            print(f"[git_restore] 缺失 .git 的项目: {', '.join(missing)}")
            return 1
        print("[git_restore] 全部子项目均具备 .git")
        return 0

    print("[git_restore] 释放第三方项目 git 信息...")
    if not ARCHIVES.is_dir():
        print("  [WARN] 无 .git-archives 目录（可能为源码包独立分发），跳过")
        return 0
    restored = 0
    for proj in PROJECTS:
        if restore_one(proj):
            restored += 1
    print(f"[git_restore] 完成（{restored}/{len(PROJECTS)} 项目具备 git 信息）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
