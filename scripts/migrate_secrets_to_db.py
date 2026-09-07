"""把配置文件中的历史明文密钥迁移到数据库，并替换为 ``secret://NAME`` 引用。

用法（在项目根目录执行）::

    python scripts/migrate_secrets_to_db.py            # 预演，只列出将要迁移的项
    python scripts/migrate_secrets_to_db.py --apply    # 实际迁移（原文件会先备份为 *.bak）

覆盖范围：
    * backend/config/config.yaml —— llm.api_key / llm.router_api_key / aigc.<provider>.<key>
    * backend/config/*_interfaces.json —— 各能力接口 config 中的密钥字段

已经是 ``secret://`` 引用或为空的字段会被跳过；迁移后请重启后端使引用生效。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config.credential_store import (  # noqa: E402
    SECRET_FIELD_NAMES,
    SECRET_PREFIX,
    create_credential,
    get_raw,
    normalize_name,
)

CONFIG_YAML = ROOT / "backend" / "config" / "config.yaml"
INTERFACE_FILES = [
    ROOT / "backend" / "config" / "asr_interfaces.json",
    ROOT / "backend" / "config" / "tts_interfaces.json",
    ROOT / "backend" / "config" / "imagegen_interfaces.json",
    ROOT / "backend" / "config" / "videogen_interfaces.json",
    ROOT / "backend" / "config" / "ocr_interfaces.json",
    ROOT / "backend" / "config" / "separation_interfaces.json",
]

# config.yaml 中需要迁移的点号路径
YAML_PATHS = [
    "llm.api_key",
    "llm.router_api_key",
    "aigc.runninghub.api_key",
    "aigc.runninghub.wallet_api_key",
]


def _sanitize(raw: str, fallback_prefix: str = "IFACE") -> str:
    """把任意标识转换为合法的密钥名称。"""
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in raw).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback_prefix}_{cleaned}" if cleaned else fallback_prefix
    return normalize_name(cleaned)


def _unique_name(base: str, value: str, used: Dict[str, str]) -> str:
    """若同名已存在：值相同则复用，值不同则追加序号。"""
    if base in used:
        if used[base] == value:
            return base
        idx = 2
        while f"{base}_{idx}" in used:
            idx += 1
        return f"{base}_{idx}"
    existing = get_raw(base)
    if existing is None:
        return base
    if existing == value:
        return base
    idx = 2
    while get_raw(f"{base}_{idx}") is not None:
        idx += 1
    return f"{base}_{idx}"


def _should_migrate(value: Any) -> bool:
    return isinstance(value, str) and value.strip() and not value.startswith(SECRET_PREFIX)


def collect_yaml() -> List[Tuple[str, str, str]]:
    """返回 [(名称, 明文值, 点号路径)]"""
    from backend.config.config_manager import config

    found: List[Tuple[str, str, str]] = []
    for path in YAML_PATHS:
        value = config.get(path)
        if _should_migrate(value):
            name = _sanitize(path.replace(".", "_"))
            found.append((name, value, path))
    return found


def collect_interfaces() -> List[Tuple[str, str, Tuple[Path, str, str]]]:
    """返回 [(名称, 明文值, (文件, 接口id, 字段))]；字段支持 "sdk_extra_args.xxx" 嵌套路径"""
    found: List[Tuple[str, str, Tuple[Path, str, str]]] = []
    for file in INTERFACE_FILES:
        if not file.exists():
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print(f"[跳过] {file.name} 解析失败：{exc}")
            continue
        for iface in data.get("interfaces", []):
            cfg = iface.get("config") or {}
            iface_id = str(iface.get("id") or "").strip()
            for field, value in cfg.items():
                if field in SECRET_FIELD_NAMES and _should_migrate(value):
                    name = _sanitize(f"{iface_id}_{field}" if iface_id else field)
                    found.append((name, value, (file, iface_id, field)))
            # 嵌套容器：sdk_extra_args / custom_params 的 default
            for field, value in (cfg.get("sdk_extra_args") or {}).items():
                if isinstance(value, str) and field in SECRET_FIELD_NAMES and _should_migrate(value):
                    base = f"{iface_id}_sdk_extra_args_{field}" if iface_id else f"sdk_extra_args_{field}"
                    found.append((_sanitize(base), value, (file, iface_id, f"sdk_extra_args.{field}")))
            for cp in cfg.get("custom_params") or []:
                if not isinstance(cp, dict):
                    continue
                cp_key = str(cp.get("key") or "")
                value = cp.get("default")
                if cp_key in SECRET_FIELD_NAMES and _should_migrate(value):
                    base = f"{iface_id}_custom_{cp_key}" if iface_id else f"custom_{cp_key}"
                    found.append((_sanitize(base), value, (file, iface_id, f"custom_params.{cp_key}")))
    return found


def apply_yaml(items: List[Tuple[str, str, str]], used: Dict[str, str]) -> None:
    from backend.config.config_manager import config

    for name, value, path in items:
        final = _unique_name(name, value, used)
        if final not in used:
            create_credential(final, value, purpose=f"由 config.yaml 的 {path} 迁移")
            used[final] = value
        config.set(path, f"{SECRET_PREFIX}{final}")
        print(f"  · {path} -> {SECRET_PREFIX}{final}")


def apply_interfaces(items: List[Tuple[str, str, Tuple[Path, str, str]]], used: Dict[str, str]) -> None:
    grouped: Dict[Path, List[Tuple[str, str, str, str]]] = {}
    for name, value, (file, iface_id, field) in items:
        grouped.setdefault(file, []).append((name, value, iface_id, field))

    for file, entries in grouped.items():
        data = json.loads(file.read_text(encoding="utf-8-sig"))
        by_id = {str(i.get("id")): i for i in data.get("interfaces", [])}
        for name, value, iface_id, field in entries:
            final = _unique_name(name, value, used)
            if final not in used:
                create_credential(final, value, purpose=f"由 {file.stem} 的 {iface_id}.{field} 迁移")
                used[final] = value
            iface = by_id.get(iface_id)
            if iface is not None:
                if "." in field:
                    container, leaf = field.split(".", 1)
                    cfg = iface.setdefault("config", {}).setdefault(container, {})
                    cfg[leaf] = f"{SECRET_PREFIX}{final}"
                else:
                    iface.setdefault("config", {})[field] = f"{SECRET_PREFIX}{final}"
                print(f"  · {file.stem}: {iface_id}.{field} -> {SECRET_PREFIX}{final}")
        file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移配置文件中的明文密钥到数据库")
    parser.add_argument("--apply", action="store_true", help="实际执行迁移（默认仅预演）")
    args = parser.parse_args()

    yaml_items = collect_yaml()
    iface_items = collect_interfaces()
    total = len(yaml_items) + len(iface_items)

    if total == 0:
        print("未发现需要迁移的明文密钥。")
        return 0

    print(f"发现 {total} 处明文密钥：")
    for name, _value, path in yaml_items:
        print(f"  [config.yaml] {path} -> {SECRET_PREFIX}{name}")
    for name, _value, (_file, iface_id, field) in iface_items:
        print(f"  [{_file.stem}] {iface_id}.{field} -> {SECRET_PREFIX}{name}")

    if not args.apply:
        print("\n预演结束，未做任何修改。确认无误后加 --apply 执行。")
        return 0

    for target in [CONFIG_YAML] + [f for f in INTERFACE_FILES if f.exists()]:
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)
    print("\n已备份原文件为 *.bak，开始迁移…")

    used: Dict[str, str] = {}
    apply_yaml(yaml_items, used)
    apply_interfaces(iface_items, used)

    print(f"\n迁移完成，共 {total} 处。请重启后端使引用生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
