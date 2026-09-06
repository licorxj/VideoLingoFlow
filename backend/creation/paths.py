"""素材路径约定。

公共素材库文件统一存放在项目根目录 data/ 内,数据库中以项目根相对路径
记录(data/ 开头、POSIX 分隔符,不含 ..);任务运行期产生的过程文件存放
在运行时项目文件夹内,数据库中以绝对路径记录。读取时用 resolve_storage_path
统一还原为绝对路径。
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"


def normalize_public_path(path: str | Path) -> str:
    """把公共素材路径规范为 data/ 开头的项目根相对路径。"""
    value = Path(str(path))
    if value.is_absolute():
        try:
            value = value.resolve().relative_to(PROJECT_ROOT)
        except ValueError:
            raise ValueError(f"公共素材必须位于项目 data 目录内: {path}") from None
    else:
        value = Path(os.path.normpath(value))
    rel = value.as_posix()
    if rel == "." or not rel.startswith("data/") or ".." in rel.split("/"):
        raise ValueError(f"公共素材路径必须以 data/ 开头且不得包含 ..: {path}")
    return rel


def resolve_public_path(rel_path: str | Path) -> Path:
    """把 data/ 相对路径解析为绝对路径(已是绝对路径则原样返回)。"""
    value = Path(str(rel_path))
    if value.is_absolute():
        return value
    rel = value.as_posix()
    if not rel.startswith("data/") or ".." in rel.split("/"):
        raise ValueError(f"非法公共素材路径: {rel_path}")
    return PROJECT_ROOT / value


def normalize_runtime_path(path: str | Path) -> str:
    """项目过程文件必须以绝对路径入库,返回规范化后的绝对路径字符串。"""
    value = Path(path)
    if not value.is_absolute():
        raise ValueError(f"项目过程文件必须以绝对路径记录: {path}")
    return str(value)


def resolve_storage_path(value: str | Path) -> Path:
    """读取时还原路径:绝对路径直接使用,相对路径按项目根解析。"""
    p = Path(str(value))
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p
