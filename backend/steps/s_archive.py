"""s_archive: 将上游多个产物文件归档到指定目录。

支持：
  - 复制 / 剪切两种操作
  - 目标目录：任务 output 目录 或 自定义相对/绝对路径
  - 可选新建子文件夹（以文件名命名 或 三位数序号自动升序）
  - 可选文件重命名（三位数序号 / 前缀 / 后缀）
  - 文件名/文件夹名非法字符清洗；目标重名时自动升序命名
"""
import os
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_ArchiveArtifacts(BaseStep):
    step_id = "archive_artifacts"
    step_name = "产物文件归档"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        # 归档节点每次都执行，不缓存产物判断
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ---------- 路径与命名工具 ----------
    @staticmethod
    def _sanitize_name(name: str) -> str:
        name = (name or "").strip()
        # 替换文件系统非法字符
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
        name = name.strip(". ")
        if not name:
            name = "untitled"
        if len(name) > 200:
            stem, ext = os.path.splitext(name)
            name = stem[:200 - len(ext)] + ext
        return name

    def _extract_paths(self, raw) -> list:
        """从上游输入（字符串 / 字典 / 嵌套列表）中提取文件路径字符串。"""
        paths: list = []
        items = raw if isinstance(raw, list) else [raw]
        for it in items:
            if isinstance(it, str):
                if it.strip():
                    paths.append(it.strip())
            elif isinstance(it, dict):
                for k in ("path", "file", "filepath", "output", "url", "text"):
                    v = it.get(k)
                    if isinstance(v, str) and v.strip():
                        paths.append(v.strip())
                        break
                else:
                    for v in it.values():
                        if isinstance(v, str) and v.strip():
                            paths.append(v.strip())
                            break
            elif isinstance(it, list):
                paths.extend(self._extract_paths(it))
        return paths

    def _unique_name(self, dest_dir: Path, desired: str) -> str:
        """检测 dest_dir 内是否已有同名；有则按 stem_N 自动升序。"""
        candidate = dest_dir / desired
        if not candidate.exists():
            return desired
        stem, ext = os.path.splitext(desired)
        i = 2
        while True:
            cand = dest_dir / f"{stem}_{i}{ext}"
            if not cand.exists():
                return f"{stem}_{i}{ext}"
            i += 1

    def _next_seq_folder(self, root: Path) -> str:
        """扫描 root 下形如 NNN 的子文件夹，取最大序号 +1（三位数）。"""
        max_n = 0
        for child in root.iterdir():
            if child.is_dir():
                m = re.match(r"^(\d{3})", child.name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
        return f"{max_n + 1:03d}"

    def _unique_folder_name(self, root: Path, desired: str) -> str:
        candidate = root / desired
        if not candidate.exists():
            return desired
        i = 2
        while True:
            cand = root / f"{desired}_{i}"
            if not cand.exists():
                return f"{desired}_{i}"
            i += 1

    # ---------- 主流程 ----------
    def run(self, task_dir: str, callback: Optional[Callable] = None, cancel_callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # 多连线接入时 step_inputs["any"] 可能是列表；兼容单值/其它端口兜底
        raw = step_inputs.get("any", "")
        if not raw:
            raw = step_inputs.get("output", "") or step_inputs.get("filepath", "")
        paths = self._extract_paths(raw)

        # 解析为任务内绝对路径并过滤存在项
        existing: list = []
        seen = set()
        for p in paths:
            ap = p if os.path.isabs(p) else os.path.join(task_dir, p)
            ap = os.path.normpath(ap)
            if ap in seen:
                continue
            if os.path.exists(ap):
                seen.add(ap)
                existing.append(ap)

        if not existing:
            raise ValueError("未收到任何有效的上游产物文件/目录，无法归档")

        if callback:
            callback(5, f"准备归档 {len(existing)} 个产物...")

        # 目标根目录
        target_type = node_config.get("targetType", "output")
        custom_path = (node_config.get("customPath") or "").strip()
        if target_type == "custom" and custom_path:
            root = Path(custom_path)
            if not root.is_absolute():
                root = Path(task_dir) / custom_path
        else:
            root = Path(task_dir) / "output"
        root.mkdir(parents=True, exist_ok=True)

        # 子文件夹
        use_subfolder = bool(node_config.get("useSubfolder"))
        subfolder_naming = node_config.get("subfolderNaming", "by_name")
        if use_subfolder:
            if subfolder_naming == "by_name":
                base = os.path.splitext(os.path.basename(existing[0]))[0] or "archive"
                folder_name = self._unique_folder_name(root, self._sanitize_name(base))
            else:
                folder_name = self._next_seq_folder(root)
            dest_dir = root / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)
        else:
            dest_dir = root

        operation = node_config.get("operation", "copy")
        rename_enabled = bool(node_config.get("renameEnabled"))
        rename_mode = node_config.get("renameMode", "seq")
        prefix = (node_config.get("prefix") or "").strip()
        suffix = (node_config.get("suffix") or "").strip()

        archived: list = []
        total = len(existing)
        seq_counter = 0
        for idx, src in enumerate(existing):
            if cancel_callback and cancel_callback():
                break
            src_name = os.path.basename(src)
            stem, ext = os.path.splitext(src_name)

            if rename_enabled:
                if rename_mode == "seq":
                    seq_counter += 1
                    new_name = f"{seq_counter:03d}{ext}"
                elif rename_mode == "prefix":
                    new_name = f"{prefix}{src_name}" if prefix else src_name
                elif rename_mode == "suffix":
                    new_name = f"{stem}{suffix}{ext}"
                else:
                    new_name = src_name
            else:
                new_name = src_name

            new_name = self._sanitize_name(new_name)
            dest_name = self._unique_name(dest_dir, new_name)
            dest_path = dest_dir / dest_name

            # 源已在目标位置（如重复连线同一产物），跳过
            if os.path.abspath(src) == os.path.abspath(str(dest_path)):
                archived.append(str(dest_path))
                continue

            if operation == "move":
                shutil.move(src, str(dest_path))
            elif os.path.isdir(src):
                shutil.copytree(src, str(dest_path))
            else:
                shutil.copy2(src, str(dest_path))
            archived.append(str(dest_path))

            if callback:
                callback(int(10 + (idx + 1) / total * 85), f"归档 {idx + 1}/{total}: {dest_name}")

        if callback:
            callback(100, f"归档完成，共 {len(archived)} 项 -> {dest_dir}")

        return {
            "artifacts": archived,
            "outputs": {"output": str(dest_dir)},
        }


StepArchiveArtifacts = S_ArchiveArtifacts
