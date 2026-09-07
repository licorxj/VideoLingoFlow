"""Credential store: 第三方能力密钥的统一存放与解析。

设计要点
--------
配置文件（``config.yaml``、``*_interfaces.json``）属于随软件分发 / 随 git 更新的资产，
因此其中**只保存密钥引用名**，形如::

    api_key: "secret://OPENAI_API_KEY"

真实密钥保存在 control-plane 数据库（``data/control-plane.db``）的 ``cp_credentials`` 表中。
该数据库属于用户私有资产：不随软件分发，git 更新也不会覆盖。

调用处通过 :func:`resolve` / :func:`resolve_deep` 把引用名还原为真实值；
对外下发（API 响应）时用 :func:`mask_deep` 脱敏，避免明文回到前端。
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

SECRET_PREFIX = "secret://"

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")

# 需要脱敏的字段名（保守白名单，避免误伤 custom_params 里的 "key" 之类参数名）
SECRET_FIELD_NAMES: Set[str] = {
    "api_key",
    "apikey",
    "api_secret",
    "sdk_api_key",
    "wallet_api_key",
    "router_api_key",
    "access_key",
    "secret_key",
    "access_token",
    "hf_token",
    "token",
    "password",
}

_CACHE_TTL_SECONDS = 30.0
# 缓存结构（均为进程内状态，name 为密钥名）：
#   _cache[name]           = (keys_list, rotate, expire)  密钥列表 + 轮询开关
#   _index_cache[name]     = (current_index, expire)      手动模式的当前下标（DB 同步）
#   _rotation_cursor[name] = next_index                   rotate 模式进程内轮询游标
#   _persisted_index[name] = last_persisted_index          已回写 DB 的游标（节流：至少轮完一圈才回写）
_cache: Dict[str, tuple] = {}
_index_cache: Dict[str, tuple] = {}
_rotation_cursor: Dict[str, int] = {}
_persisted_index: Dict[str, int] = {}
_cache_lock = threading.Lock()
_cursor_lock = threading.Lock()


class CredentialError(Exception):
    """凭据操作失败（名称非法、重名、不存在等）。"""


# --------------------------------------------------------------------------- #
# 引用名与掩码
# --------------------------------------------------------------------------- #
def is_secret_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_PREFIX)


def to_ref(name: str) -> str:
    return SECRET_PREFIX + normalize_name(name)


def from_ref(value: Any) -> Optional[str]:
    if not is_secret_ref(value):
        return None
    name = value[len(SECRET_PREFIX):].strip()
    return name or None


def normalize_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise CredentialError("密钥名称不能为空")
    if cleaned.startswith(SECRET_PREFIX):
        cleaned = cleaned[len(SECRET_PREFIX):]
    cleaned = cleaned.strip().upper()
    if not _NAME_RE.match(cleaned):
        raise CredentialError("密钥名称只能包含字母、数字和下划线，且以字母开头")
    return cleaned


MASK_MARK = "*" * 6


def mask_value(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 8:
        return text[:1] + "*" * max(len(text) - 1, 0)
    return f"{text[:4]}{MASK_MARK}{text[-4:]}"


def is_masked_value(value: Any) -> bool:
    """判断值是否为下发过的掩码串（前端未修改时原样回传）。"""
    return isinstance(value, str) and MASK_MARK in value


# --------------------------------------------------------------------------- #
# 多 key 编解码：DB 中 value 为 JSON 数组；历史纯文本视为单 key
# --------------------------------------------------------------------------- #
def _parse_keys(value: Any) -> List[str]:
    if not value:
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(k).strip() for k in parsed if str(k).strip()]
        except Exception:
            pass
    return [text]


def _encode_keys(keys: List[str]) -> str:
    return json.dumps(keys, ensure_ascii=False)


def encode_input_value(value: str) -> str:
    """把前端提交的多行文本（每行一个 key）编码为 DB 存储格式。"""
    keys = [line.strip() for line in (value or "").splitlines() if line.strip()]
    return _encode_keys(keys)


def merge_preserving_masked(old: Any, new: Any) -> Any:
    """合并新旧配置：新值若是掩码则沿用旧值，避免掩码回写覆盖真实密钥。

    仅对 dict 递归处理，其余类型以新值为准。
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new
    merged = dict(new)
    for key, old_value in old.items():
        new_value = merged.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            merged[key] = merge_preserving_masked(old_value, new_value)
        elif is_masked_value(new_value) and not is_masked_value(old_value):
            merged[key] = old_value
    return merged


# --------------------------------------------------------------------------- #
# 数据库访问
# --------------------------------------------------------------------------- #
def _fetch_meta(name: str) -> Optional[Tuple[List[str], bool]]:
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    with session_scope() as session:
        row = session.execute(
            select(Credential.value, Credential.rotate).where(Credential.name == name)
        ).one_or_none()
    if row is None:
        return None
    return _parse_keys(row.value), bool(row.rotate)


def _fetch_index(name: str) -> int:
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    with session_scope() as session:
        idx = session.execute(
            select(Credential.current_index).where(Credential.name == name)
        ).scalar_one_or_none()
    return int(idx or 0)


def _persist_index(name: str, idx: int) -> None:
    from sqlalchemy import update

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    with session_scope() as session:
        session.execute(
            update(Credential).where(Credential.name == name).values(current_index=idx)
        )


def _get_meta(key: str) -> Optional[Tuple[List[str], bool]]:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[2] > now:
            return hit[0], hit[1]
    try:
        meta = _fetch_meta(key)
    except Exception:
        # 数据库不可用时不应阻塞主流程，按"未配置"处理
        return None
    if meta is None:
        return None
    with _cache_lock:
        _cache[key] = (meta[0], meta[1], now + _CACHE_TTL_SECONDS)
    return meta


def _next_index(key: str, keys: List[str], rotate: bool) -> int:
    """取本次调用应使用的 key 下标。

    - rotate=False（手动模式）：使用 DB 的 current_index（带短缓存），
      可在密钥管理页手动切换使用中的 key。
    - rotate=True（轮询模式）：进程内原子推进游标，实现 round-robin；
      游标至少每轮完一圈才回写 DB（节流），重启后可从该位置继续。
    """
    if not rotate:
        now = time.monotonic()
        with _cache_lock:
            hit = _index_cache.get(key)
            if hit is not None and hit[1] > now:
                return int(hit[0])
        try:
            idx = _fetch_index(key)
        except Exception:
            idx = 0
        with _cache_lock:
            _index_cache[key] = (idx, now + _CACHE_TTL_SECONDS)
        return idx

    with _cursor_lock:
        idx = _rotation_cursor.get(key)
        if idx is None:
            try:
                idx = _fetch_index(key)
            except Exception:
                idx = 0
        _rotation_cursor[key] = idx + 1

    with _cursor_lock:
        last = _persisted_index.get(key)
        if last is None or idx - last >= len(keys):
            _persisted_index[key] = idx
            should_persist = True
        else:
            should_persist = False
    if should_persist:
        try:
            _persist_index(key, idx)
        except Exception:
            pass
    return idx


def get_raw(name: str) -> Optional[str]:
    """按名称取"当前生效"的密钥明文；多 key 时按轮询/手动下标取。不存在返回 None。"""
    try:
        key = normalize_name(name)
    except CredentialError:
        return None
    meta = _get_meta(key)
    if meta is None:
        return None
    keys, rotate = meta
    if not keys:
        return ""
    idx = _next_index(key, keys, rotate)
    return keys[idx % len(keys)]


def invalidate(name: Optional[str] = None) -> None:
    def _drop(mapping: Dict[str, Any], key: str) -> None:
        mapping.pop(key, None)

    try:
        normalized = normalize_name(name) if name else None
    except CredentialError:
        normalized = None
    with _cache_lock:
        if normalized is None:
            _cache.clear()
            _index_cache.clear()
        else:
            _drop(_cache, normalized)
            _drop(_index_cache, normalized)
    with _cursor_lock:
        if normalized is None:
            _rotation_cursor.clear()
            _persisted_index.clear()
        else:
            _drop(_rotation_cursor, normalized)
            _drop(_persisted_index, normalized)


def resolve(value: Any) -> Any:
    """把 ``secret://NAME`` 还原为真实值；非引用原样返回。"""
    name = from_ref(value)
    if name is None:
        return value
    raw = get_raw(name)
    return raw if raw is not None else ""


def resolve_deep(obj: Any) -> Any:
    """递归解析结构中的密钥引用（返回新对象，不修改入参）。"""
    if isinstance(obj, dict):
        return {k: resolve_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_deep(v) for v in obj]
    return resolve(obj)


def mask_deep(obj: Any) -> Any:
    """递归脱敏：命中白名单字段名的明文值替换为掩码，引用名保留。"""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k in SECRET_FIELD_NAMES and isinstance(v, str) and not is_secret_ref(v):
                result[k] = mask_value(v)
            else:
                result[k] = mask_deep(v)
        return result
    if isinstance(obj, list):
        return [mask_deep(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# 管理接口（供设置页「密钥管理」使用）
# --------------------------------------------------------------------------- #
def _to_dict(row, *, reveal: bool = False) -> Dict[str, Any]:
    keys = _parse_keys(row.value)
    rotate = bool(getattr(row, "rotate", False))
    current_index = int(getattr(row, "current_index", 0) or 0)
    active = keys[current_index % len(keys)] if keys else ""
    return {
        "id": row.id,
        "name": row.name,
        "purpose": row.purpose or "",
        "masked": mask_value(active),
        "keys_count": len(keys),
        "rotate": rotate,
        "current_index": current_index,
        "value": "\n".join(keys) if reveal else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_credentials(*, reveal: bool = False, keyword: str = "") -> List[Dict[str, Any]]:
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    keyword = (keyword or "").strip().lower()
    with session_scope() as session:
        rows = list(session.execute(select(Credential).order_by(Credential.name)).scalars())
    items = [_to_dict(r, reveal=reveal) for r in rows]
    if keyword:
        items = [
            i for i in items
            if keyword in i["name"].lower() or keyword in (i["purpose"] or "").lower()
        ]
    return items


def get_credential(credential_id: str, *, reveal: bool = False) -> Optional[Dict[str, Any]]:
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    with session_scope() as session:
        row = session.get(Credential, credential_id)
        return _to_dict(row, reveal=reveal) if row else None


def create_credential(name: str, value: str, purpose: str = "", *, rotate: bool = True) -> Dict[str, Any]:
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    key = normalize_name(name)
    with session_scope() as session:
        exists = session.execute(
            select(Credential.id).where(Credential.name == key)
        ).scalar_one_or_none()
        if exists:
            raise CredentialError(f"密钥名称 {key} 已存在")
        row = Credential(
            name=key,
            value=encode_input_value(value),
            purpose=purpose or "",
            rotate=bool(rotate),
        )
        session.add(row)
        session.flush()
        result = _to_dict(row, reveal=True)
    invalidate(key)
    return result


def update_credential(
    credential_id: str,
    *,
    name: Optional[str] = None,
    value: Optional[str] = None,
    purpose: Optional[str] = None,
    rotate: Optional[bool] = None,
) -> Dict[str, Any]:
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    with session_scope() as session:
        row = session.get(Credential, credential_id)
        if not row:
            raise CredentialError("密钥不存在")
        old_name = row.name
        if name is not None:
            new_name = normalize_name(name)
            if new_name != row.name:
                exists = session.execute(
                    select(Credential.id).where(Credential.name == new_name)
                ).scalar_one_or_none()
                if exists:
                    raise CredentialError(f"密钥名称 {new_name} 已存在")
                row.name = new_name
        if value is not None:
            row.value = encode_input_value(value)
        if purpose is not None:
            row.purpose = purpose
        if rotate is not None:
            row.rotate = bool(rotate)
        session.flush()
        result = _to_dict(row, reveal=True)
    invalidate(old_name)
    if name is not None:
        invalidate(normalize_name(name))
    return result


def delete_credential(credential_id: str) -> Dict[str, Any]:
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Credential

    with session_scope() as session:
        row = session.get(Credential, credential_id)
        if not row:
            raise CredentialError("密钥不存在")
        removed = {"id": row.id, "name": row.name}
        session.delete(row)
        session.flush()
    invalidate(removed["name"])
    return removed


def usage_of(credential_id: str) -> Dict[str, Any]:
    """统计该密钥被哪些配置项引用，避免误删后调用失败。"""
    from backend.config.config_manager import config

    target_ref = None
    refs: List[str] = []
    try:
        item = get_credential(credential_id)
        if not item:
            return {"name": "", "references": refs}
        target_ref = to_ref(item["name"])
    except Exception:
        return {"name": "", "references": refs}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                walk(v, f"{path}[{idx}]")
        elif isinstance(node, str) and node == target_ref:
            refs.append(path)

    try:
        walk(config.get_all(), "")
    except Exception:
        pass
    return {"name": item["name"], "references": refs}
