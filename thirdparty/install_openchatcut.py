#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenChatCut（AI剪辑台）安装脚本 —— 跨平台（Windows / Linux / macOS）

由主项目「AI剪辑台」页面（POST /api/openchatcut/install）后台调用，
也可手动执行。任意 Python 3 可运行，仅用标准库。

用法:
    python thirdparty/install_openchatcut.py           # 拉取项目 + 安装依赖 + 构建前端
    python thirdparty/install_openchatcut.py --force   # 强制更新项目并重新安装重建
    python thirdparty/install_openchatcut.py --skip-build   # 只拉取/装依赖，不构建前端
    python thirdparty/install_openchatcut.py --check   # 仅检测是否已安装（退出码 0/1）

职责:
  1. 检测 Node.js（要求 >= 24 < 25，与上游 OpenChatCut 要求一致）
  2. 拉取项目：thirdparty/openchatcut 缺失时从上游 GitHub 仓库 clone（--depth 1）；
     已存在 git 拷贝时尝试 git pull --ff-only 更新
  3. npm install（ONNXRUNTIME_NODE_INSTALL=skip，CPU 模式跳过 CUDA Provider 下载）
  4. npm run build 构建前端产物 → thirdparty/openchatcut/dist
     （主项目启动剪辑台时直接跑该构建产物，不再走 dev server）
  5. .env.local 缺失时从官方模板 .env.example 复制一份
     （实际接口参数由主项目「AI剪辑台」设置页注入，不修改其源码）

平台适配:
  - Windows: shutil.which 经 PATHEXT 自动定位 npm.cmd / git.exe；控制台输出兼容 GBK
  - Linux / macOS: 定位 npm / node / git 普通可执行文件，逻辑一致
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

THIRDPARTY = Path(__file__).resolve().parent
OPENCHATCUT_DIR = THIRDPARTY / "openchatcut"
UPSTREAM_REPO = "https://github.com/0xsline/OpenChatCut.git"

# 输出实时刷新：即使 stdout 被管道/重定向（后端捕获日志），进度也能即时写入
try:
    sys.stdout.reconfigure(line_buffering=True, errors="replace")
    sys.stderr.reconfigure(line_buffering=True, errors="replace")
except Exception:
    pass


def log(msg: str, prefix: str = "[INFO]") -> None:
    print(f"  {prefix} {msg}")


def warn(msg: str) -> None:
    log(msg, prefix="[WARN]")


def ok(msg: str) -> None:
    log(msg, prefix="[ OK ]")


def is_windows() -> bool:
    return os.name == "nt"


def find_exe(candidates: list[str]) -> str | None:
    """按候选名查找可执行文件（Windows 上 which 会自动匹配 .cmd/.exe 等 PATHEXT）。"""
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return None


def node_major_version(node: str) -> int | None:
    try:
        result = subprocess.run(
            [node, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
        )
        match = re.match(r"v?(\d+)", (result.stdout or "").strip())
        return int(match.group(1)) if match else None
    except (OSError, subprocess.SubprocessError):
        return None


def check_only() -> int:
    """--check：依赖已就绪返回 0，未安装返回 1（供后端/自动化探测）。

    构建产物状态只打印不参与退出码：依赖装好即可启动（缺 dist 时启动会回退 dev 模式）。
    """
    deps_ready = (OPENCHATCUT_DIR / "node_modules").is_dir()
    build_ready = (OPENCHATCUT_DIR / "dist" / "index.html").is_file()
    print(f"deps_ready={deps_ready}")
    print(f"build_ready={build_ready}")
    return 0 if deps_ready else 1


def ensure_project() -> bool:
    """拉取项目：目录缺失时从上游 clone；已存在 git 拷贝时尝试 fast-forward 更新。

    - 已有 package.json 且是 git 仓库 → git pull --ff-only（失败仅告警，用现有源码继续）
    - 已有 package.json 但非 git 拷贝 → 跳过拉取，直接使用现有源码
    - 目录缺失 / 缺 package.json   → git clone --depth 1 上游仓库
    """
    pkg = OPENCHATCUT_DIR / "package.json"
    git = find_exe(["git.exe", "git"])

    if pkg.is_file():
        if (OPENCHATCUT_DIR / ".git").exists() and git:
            log("已存在本地拷贝，尝试 git pull --ff-only 更新…")
            try:
                result = subprocess.run(
                    [git, "-C", str(OPENCHATCUT_DIR), "pull", "--ff-only"],
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                )
                if result.returncode == 0:
                    ok("项目已更新到最新")
                else:
                    warn("git pull 未成功（无网络/有本地改动/浅拷贝冲突），使用现有源码继续")
            except (OSError, subprocess.SubprocessError) as exc:
                warn(f"git pull 失败: {exc}，使用现有源码继续")
        else:
            ok("项目已就位（非 git 拷贝，跳过拉取更新）")
        return True

    if not git:
        warn("未找到 git，无法拉取 OpenChatCut 项目，请先安装 git（https://git-scm.com）后重试")
        return False

    log(f"从上游拉取项目：{UPSTREAM_REPO}")
    try:
        result = subprocess.run(
            [git, "clone", "--depth", "1", UPSTREAM_REPO, str(OPENCHATCUT_DIR)],
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"git clone 失败: {exc}")
        return False
    if result.returncode != 0:
        warn("git clone 失败：请检查网络连通性（如需代理请为 git 配置 proxy）后重试")
        return False
    if not pkg.is_file():
        warn("拉取完成但未找到 package.json，上游仓库结构可能已变化")
        return False
    ok("项目拉取完成")
    return True


def run_npm(args: list[str], env_extra: dict | None = None, timeout: int | None = None) -> int:
    """在 openchatcut 目录执行 npm 子命令，返回退出码（输出实时透传）。"""
    npm = find_exe(["npm.cmd", "npm"])
    if not npm:
        warn("未找到 npm（通常随 Node.js 一起安装）")
        return 1
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        result = subprocess.run(
            [npm, *args],
            cwd=str(OPENCHATCUT_DIR),
            env=env,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except OSError as exc:
        warn(f"npm {' '.join(args)} 启动失败: {exc}")
        return 1
    except subprocess.TimeoutExpired:
        warn(f"npm {' '.join(args)} 超时（{timeout}s）")
        return 1
    return result.returncode


def install(force: bool, skip_build: bool) -> int:
    print("=" * 60)
    print("  OpenChatCut（AI剪辑台）安装：拉取项目 + 依赖 + 前端构建")
    print(f"  平台: {platform.system()} {platform.release()} ({platform.machine()})")
    print("=" * 60)

    # 1) Node.js 检测（OpenChatCut 要求 >= 24 < 25；缺失时明确提醒，不浪费时间拉取）
    node = find_exe(["node.exe", "node"])
    if not node:
        warn("未检测到 Node.js，无法安装剪辑台")
        warn("请先安装 Node.js 24.x（https://nodejs.org，建议 LTS），安装后重新打开终端/重启主程序再试")
        return 1
    major = node_major_version(node)
    log(f"Node.js 版本: v{major if major is not None else '未知'}（{node}）")
    if major is None:
        warn("无法解析 Node 版本，继续尝试安装")
    elif major != 24:
        warn("OpenChatCut 要求 Node.js >= 24 < 25，版本不匹配可能导致启动失败")

    # 2) 拉取项目（目录缺失时自动 clone；已有拷贝时尝试更新）
    if not ensure_project():
        return 1

    # 3) npm install（依赖）
    if not (OPENCHATCUT_DIR / "node_modules").is_dir() or force:
        log("执行 npm install（CPU 模式：ONNXRUNTIME_NODE_INSTALL=skip 跳过 CUDA Provider）…")
        code = run_npm(["install"], env_extra={"ONNXRUNTIME_NODE_INSTALL": "skip"})
        if code != 0:
            warn(f"npm install 失败（exit {code}），AI剪辑台将无法启动")
            return 1
        ok("依赖安装完成")
    else:
        ok("依赖已就绪（node_modules 已存在，如需重装请加 --force）")

    # 4) npm run build（前端构建产物 → dist/，启动时直接用产物，不跑 dev server）
    dist_index = OPENCHATCUT_DIR / "dist" / "index.html"
    if skip_build:
        log("已指定 --skip-build，跳过前端构建（启动时将回退 dev 模式）")
    elif dist_index.is_file() and not force:
        ok("前端构建产物已就绪（dist/index.html，如需重建请加 --force）")
    else:
        log("执行 npm run build 构建前端产物（首次构建需要几分钟）…")
        code = run_npm(["run", "build"], timeout=3600)
        if code != 0:
            warn(f"npm run build 失败（exit {code}）；依赖已安装，启动时将回退 dev 模式")
            warn("可加 --skip-build 仅安装依赖，或查看日志排查 prebuild（sync:mediapipe / sync:whisper-cli）失败原因")
            return 1
        ok("前端构建完成（dist/）")

    # 5) .env.local 缺失时从官方模板复制（空值占位；实际参数由主项目设置页注入）
    env_file = OPENCHATCUT_DIR / ".env.local"
    if not env_file.exists():
        example = OPENCHATCUT_DIR / ".env.example"
        if example.exists():
            shutil.copyfile(str(example), str(env_file))
            ok("已从 .env.example 生成 .env.local（接口参数请在「AI剪辑台」页面保存后注入）")
    else:
        ok(".env.local 已存在（保持不变）")

    ok("OpenChatCut 安装完成，可在「AI剪辑台」页面点击 启动 / 打开剪辑台")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenChatCut（AI剪辑台）安装：拉取项目 + 依赖 + 前端构建（跨平台）")
    parser.add_argument("--force", action="store_true", help="忽略已有 node_modules / dist，强制重新安装并重建")
    parser.add_argument("--skip-build", action="store_true", help="只安装依赖，跳过 npm run build")
    parser.add_argument("--check", action="store_true", help="仅检测是否就绪（不安装）")
    args = parser.parse_args()

    if args.check:
        return check_only()
    return install(args.force, args.skip_build)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        warn("已取消")
        sys.exit(130)
