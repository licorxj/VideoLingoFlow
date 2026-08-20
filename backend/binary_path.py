"""平台路径选择。"""

import os
import platform
import sys
from pathlib import Path

_CP312 = (3, 12)

# 二进制根目录
_BINARY_ROOTS = ("auth_binaries", "control_plane_binaries")


def detect_target() -> str | None:
    """计算当前平台的编译目标名；不支持时返回 None。"""
    if sys.version_info[:2] != _CP312:
        return None
    machine = (platform.machine() or "").lower()
    if sys.platform.startswith("win"):
        return "win-amd64" if machine in ("amd64", "x86_64") else None
    if sys.platform == "darwin":
        if machine in ("arm64", "aarch64"):
            return "macos-arm64"
        if machine in ("x86_64", "amd64"):
            return "macos-x86_64"
        return None
    if sys.platform.startswith("linux"):
        return "linux-x86_64" if machine in ("x86_64", "amd64") else None
    return None


def binary_directory(package_name: str) -> Path | None:
    """返回 backend.<package_name> 匹配当前平台的二进制包目录；无匹配返回 None。"""
    target = detect_target()
    if not target:
        return None
    root = Path(__file__).resolve().parent  # backend/
    for kind in _BINARY_ROOTS:
        candidate = root / kind / "cp312" / target / "backend" / package_name
        if candidate.is_dir():
            return candidate
    return None


def prepend_binary_path(package_name: str, current_path: list[str]) -> None:
    """将匹配平台的二进制目录前置插入包的 __path__。"""
    if os.environ.get("VIDEOLINGO_USE_SOURCE", "").strip() in ("1", "true", "yes"):
        return
    directory = binary_directory(package_name)
    if directory is None:
        return
    text = str(directory)
    if text in current_path:
        current_path.remove(text)
    current_path.insert(0, text)
