"""受保护编译模块的平台路径选择。

仅使用标准库，不记录 Token、状态文件内容或设备信息。
规则：
- 仅 CPython 3.12 且平台目录存在时，将对应平台二进制目录前置插入包的 __path__，
  使普通导入优先发现 Nuitka 编译扩展（.pyd / .so）；
- 平台不匹配、版本不符或目录缺失时保持默认源码导入。
"""

import os
import platform
import sys
from pathlib import Path

_CP312 = (3, 12)

# 二进制根目录（相对 backend/），与私有编译仓库 Release 归档的包路径保持一致：
#   backend/auth_binaries/cp312/<target>/backend/auth
#   backend/control_plane_binaries/cp312/<target>/backend/control_plane
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
    """将匹配平台的二进制目录前置插入包的 __path__；无匹配时保持不变。

    设置环境变量 VIDEOLINGO_USE_SOURCE=1 时强制回退源码导入
    （开发/调试用途，跳过可能滞后的编译产物）。
    """
    if os.environ.get("VIDEOLINGO_USE_SOURCE", "").strip() in ("1", "true", "yes"):
        return
    directory = binary_directory(package_name)
    if directory is None:
        return
    text = str(directory)
    if text in current_path:
        current_path.remove(text)
    current_path.insert(0, text)
