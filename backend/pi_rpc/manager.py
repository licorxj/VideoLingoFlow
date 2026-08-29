import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from backend.config.config_manager import config

from .client import PiRpcClient, PiRpcError
from .store import PiSessionStore


def _find_node_executable() -> Path:
    """Locate a usable Node executable.

    PATH-based lookup can fail when the process manager rebuilds the child PATH or
    re-executes the backend through a venv launcher, so probe common locations too.
    """
    candidates = [
        os.environ.get("VIDEOLINGO_PI_NODE_PATH", ""),
        shutil.which("node") or "",
        r"X:\nodejs\node.exe",
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs", "node.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "nodejs", "node.exe"),
        os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvm", "node.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "nodejs", "node.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"


def _find_node_modules(start: Path) -> Path | None:
    """向上查找包含 node_modules 的最近目录（用于解析 Pi CLI 的依赖）。"""
    current = start
    while True:
        candidate = current / "node_modules"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


# 全局默认人设（第一优先级，代码固定，不可通过前端修改）。
# 每个助手会话都会在系统提示最前面注入此身份与权利边界。
_DEFAULT_PERSONA = (
    "You are 小π Agent (Xiao Pi), the built-in intelligent assistant of VideoLingoFlow (Chinese name: 流连视听). "
    "You are the project's default assistant; this global identity applies to every role you take. "
    "Help users understand the project architecture and features; help create, edit, configure, and optimize "
    "project settings, nodes, workflows, and capability interfaces; help execute legitimate project tasks. "
    "You may act as a workflow node for specific complex tasks. Reply in the user's language unless they request otherwise.\n"
    "Maintenance abilities: clear Pi local caches by category (sessions / models / staging) when asked; workflow node "
    "tasks may come with recommended Skill/MCP packages that the user picked in the node configuration.\n"
    "Identity boundaries:\n"
    "- PROJECT_ROOT is the absolute root of this VideoLingoFlow checkout. Resolve every relative project path from PROJECT_ROOT.\n"
    "- Never access backend/auth or anything below it.\n"
    "- Never read, reveal, modify, or help derive authentication credentials, registration, subscription, payment, "
    "or entitlement logic; refuse requests to bypass, disable, or emulate paid-feature protection.\n"
    "- Never damage, delete, corrupt, or migrate data structures without an explicit, reviewed, reversible plan.\n"
    "- Never read or write a path blocked by the effective blacklists; never bypass runtime path controls via shell or indirection.\n"
    "Knowledge use:\n"
    "- The role persona and capability document below are loaded into this conversation; treat them as primary instructions.\n"
    "- Knowledge documents provide architecture and API references; consult them as needed instead of assuming details.\n"
    "- For a general task, locate the relevant capability document through the capability index, then read that document "
    "with the read tool before acting; do not load every capability document into context."
)


class PiSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, PiRpcClient] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._store = PiSessionStore(str(self._root() / "data" / "workspace" / "pi-sessions" / "pi_sessions.db"))

    def _root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _config(self, key: str, default: Any = None) -> Any:
        return config.get(f"pi.{key}", default)

    def runtime(self) -> dict[str, Any]:
        """返回 Pi 运行环境的轻量诊断（不启动子进程）。

        状态取值：disabled / missing_runtime / incompatible_runtime /
        missing_dependencies / available。message 给出可操作的中文原因。
        """
        root = self._root()
        node = str(self._config("node_path", "") or os.getenv("VIDEOLINGO_PI_NODE_PATH", ""))
        cli = str(self._config("cli_path", "") or os.getenv("VIDEOLINGO_PI_CLI_PATH", ""))
        node_path = Path(node) if node else _find_node_executable()
        cli_path = Path(cli) if cli else root / "thirdparty" / "pi" / "packages" / "coding-agent" / "dist" / "cli.js"
        enabled = bool(self._config("enabled", True))
        checks: dict[str, Any] = {}
        if not enabled:
            return {"enabled": False, "status": "disabled", "message": "Pi 智能助手已禁用（pi.enabled=false）", "checks": checks, "node_path": str(node_path), "cli_path": str(cli_path), "session_count": len(self._sessions)}
        if not node_path.is_file():
            return {"enabled": True, "status": "missing_runtime", "message": f"未找到 Node 可执行文件：{node_path}", "checks": {"node": False}, "node_path": str(node_path), "cli_path": str(cli_path), "session_count": len(self._sessions)}
        if not cli_path.is_file():
            return {"enabled": True, "status": "missing_runtime", "message": f"未找到 Pi CLI：{cli_path}", "checks": {"node": True, "cli": False}, "node_path": str(node_path), "cli_path": str(cli_path), "session_count": len(self._sessions)}
        node_version = ""
        node_ok = True
        try:
            out = subprocess.run([str(node_path), "--version"], capture_output=True, text=True, timeout=10)
            node_version = (out.stdout or out.stderr).strip()
            match = re.search(r"v(\d+)\.(\d+)\.", node_version)
            if match:
                node_ok = (int(match.group(1)), int(match.group(2))) >= (22, 19)
        except Exception:
            node_ok = False
        if not node_ok:
            return {"enabled": True, "status": "incompatible_runtime", "message": f"Node 版本过低（{node_version or '未知'}），Pi 需要 Node >= 22.19", "checks": {"node": True, "cli": True, "node_version": False}, "node_version": node_version, "node_path": str(node_path), "cli_path": str(cli_path), "session_count": len(self._sessions)}
        node_modules = _find_node_modules(cli_path)
        if not node_modules:
            return {"enabled": True, "status": "missing_dependencies", "message": "Pi 依赖未安装：请在 thirdparty\\pi 目录执行 npm install（或重新运行 start-prod.bat / start-local-prod.bat 自动安装）", "checks": {"node": True, "cli": True, "node_version": True, "dependencies": False}, "node_path": str(node_path), "cli_path": str(cli_path), "session_count": len(self._sessions)}
        return {"enabled": True, "status": "available", "message": "Pi 运行环境正常", "checks": {"node": True, "cli": True, "node_version": True, "dependencies": True}, "node_version": node_version, "node_path": str(node_path), "cli_path": str(cli_path), "session_count": len(self._sessions)}

    def diagnose(self) -> dict[str, Any]:
        """在 runtime() 基础上，真实启动一次 Pi CLI 以捕获实际的启动错误。"""
        info = self.runtime()
        if info["status"] != "available":
            return info
        node_path = Path(info["node_path"])
        cli_path = Path(info["cli_path"])
        node_modules = _find_node_modules(cli_path)
        launch_ok = False
        launch_error = ""
        try:
            out = subprocess.run(
                [str(node_path), str(cli_path), "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(node_modules.parent) if node_modules else None,
            )
            if out.returncode == 0:
                launch_ok = True
            else:
                launch_error = (out.stderr or out.stdout).strip()[:800]
        except subprocess.TimeoutExpired:
            launch_ok = True
        except Exception as exc:
            launch_error = str(exc)[:800]
        checks = {**info.get("checks", {}), "launch": launch_ok}
        if not launch_ok:
            return {**info, "status": "launch_failed", "message": f"Pi CLI 启动失败：{launch_error}", "checks": checks, "launch_error": launch_error}
        return {**info, "checks": checks}

    def _allowed_root(self, cwd: str) -> Path:
        root = self._root().resolve()
        raw_path = Path(cwd)
        candidate = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
        workspace = (root / "data" / "workspace").resolve()
        if candidate != root and root not in candidate.parents and workspace not in candidate.parents and candidate != workspace:
            raise PiRpcError("cwd must be inside the VideoLingo project or data/workspace")
        return candidate

    def _model(self, requested: str | None) -> str:
        model = requested or self._config("model") or config.get("llm.step_models.agent_model") or config.get("llm.step_models.default_model")
        if not model or len(str(model)) > 200 or any(char in str(model) for char in "\r\n"):
            raise PiRpcError("Invalid Pi model")
        return str(model)

    def _tools(self, requested: list[str] | None) -> list[str]:
        allowed = set(self._config("allow_tools", ["read", "grep", "find", "ls", "write", "edit", "bash"]) or [])
        tools = requested or self.settings().get("tools_enabled") or list(allowed)
        if not tools or not set(tools).issubset(allowed):
            raise PiRpcError("Requested Pi tools are not allowed")
        return sorted(set(tools))

    def settings(self) -> dict[str, Any]:
        root = self._root()
        defaults = {
            "model_mode": "router",
            "custom_base_url": "",
            "custom_api_key": "",
            "custom_model": "",
            "base_docs_paths": [
                str(root / "backend" / "config" / "agent" / "project-architecture.md"),
                str(root / "backend" / "config" / "agent" / "backend-api-catalog.md"),
                str(root / "backend" / "config" / "agent" / "skills-index.md"),
            ],
            "read_blacklist": [],
            "write_blacklist": [],
            "tools_enabled": ["read", "write", "edit", "grep", "find", "ls"],
            "skills": self._store.integrations("skill"),
            "mcps": self._store.integrations("mcp"),
            "assistants": self._store.assistants(),
        }
        return {**defaults, **self._store.get_settings()}

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {"model_mode", "custom_base_url", "custom_api_key", "custom_model", "base_docs_paths", "read_blacklist", "write_blacklist", "tools_enabled"}
        for key, value in values.items():
            if key in allowed:
                if key in {"read_blacklist", "write_blacklist"}:
                    value = self._path_list(value)
                if key == "base_docs_paths":
                    value = [str(path) for path in self._document_paths(value)]
                if key == "tools_enabled":
                    allowed_tools = set(self._config("allow_tools", ["read", "grep", "find", "ls", "write", "edit", "bash"]) or [])
                    if not isinstance(value, list) or not value or not set(value).issubset(allowed_tools):
                        raise PiRpcError("Invalid agent tools")
                    value = sorted(set(value))
                self._store.set_setting(key, value)
        return self.settings()

    def _path_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise PiRpcError("Path blacklist must be a list")
        return [str(self._allowed_root(str(item))) for item in value[:50] if str(item).strip()]

    def _document_paths(self, value: Any) -> list[Path]:
        if not isinstance(value, list):
            raise PiRpcError("Document paths must be a list")
        root = self._root().resolve()
        documents: list[Path] = []
        for item in value[:10]:
            raw_path = Path(str(item))
            path = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
            if root not in path.parents or not path.is_file() or path.suffix.lower() != ".md":
                raise PiRpcError("Agent document path must be a Markdown file inside the project")
            documents.append(path)
        return documents

    def _document_context(self, paths: list[Path]) -> str:
        remaining = 24000
        sections: list[str] = []
        for path in paths:
            if remaining <= 0:
                break
            try:
                content = path.read_text(encoding="utf-8")[:remaining]
            except OSError as exc:
                raise PiRpcError(f"Unable to read agent document: {path}") from exc
            relative = path.relative_to(self._root().resolve()).as_posix()
            sections.append(f"\n\n--- Knowledge document: {relative} ---\n{content}")
            remaining -= len(content)
        return "".join(sections)

    def _environment_summary(self) -> str:
        """构建宿主运行时环境摘要，注入系统提示，让 Pi 无需探测即可了解运行环境。"""
        import platform as _platform
        try:
            root = self._root().resolve()
            sep = "\\" if os.name == "nt" else "/"
            router_url = str(config.get("llm.router_url") or "").strip()
            lines = [
                "## Runtime environment summary (injected automatically)",
                f"- OS: {_platform.system()} {_platform.release()} ({_platform.machine()})",
                f"- Python: {_platform.python_version()}",
                f"- PROJECT_ROOT: {root}",
                f"- Working directory: {Path.cwd()}",
                f"- Path separator: {sep}",
            ]
            if router_url:
                lines.append(f"- LLM router endpoint: {router_url}")
            return "\n".join(lines)
        except Exception:
            return ""

    def update_assistant(self, assistant_id: str, values: dict[str, Any]) -> dict[str, Any]:
        if assistant_id not in {"general", "node", "workflow", "execution", "files", "publish", "installer"}:
            raise PiRpcError("Unknown assistant")
        root = self._root().resolve()
        result = {
            "persona": str(values.get("persona", ""))[:8000],
            "docs_path": str(values.get("docs_path", ""))[:500],
            "read_blacklist": self._path_list(values.get("read_blacklist", [])),
            "write_blacklist": self._path_list(values.get("write_blacklist", [])),
        }
        if result["docs_path"]:
            result["docs_path"] = str(self._document_paths([result["docs_path"]])[0])
        self._store.set_assistant(assistant_id, result)
        return result

    def scan(self, kind: str) -> list[dict[str, Any]]:
        root = self._root()
        if kind == "docs":
            directory = root / "backend" / "config" / "agent" / "docs"
            return [{"name": path.name, "path": str(path)} for path in sorted(directory.glob("*.md"))] if directory.is_dir() else []
        if kind in ("skill", "skills"):
            candidates = [
                root / "backend" / "config" / "agent" / "skills",
                Path.home() / ".claude" / "skills",
                Path.home() / ".codex" / "skills",
                Path.home() / ".trae" / "skills",
                Path.home() / ".agents" / "skills",
                Path.home() / ".agent" / "skills",
            ]
        elif kind in ("mcp", "mcps"):
            candidates = [
                root / "backend" / "config" / "agent" / "mcp",
                Path.home() / ".claude" / "mcps",
                Path.home() / ".trae" / "mcps",
                Path.home() / ".agents" / "mcps",
                Path.home() / ".agent" / "mcps",
            ]
        else:
            raise PiRpcError("Unknown integration type")
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for directory in candidates:
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if path.is_dir() or path.suffix.lower() in {".json", ".md", ".yaml", ".yml"}:
                    resolved = str(path.resolve())
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    item_id = f"{kind}:{resolved}"
                    items.append({
                        "item_id": item_id,
                        "name": path.stem if path.is_file() else path.name,
                        "path": resolved,
                        "description": self._integration_description(kind, path),
                        "enabled": False,
                    })
        existing = {item["item_id"]: item["enabled"] for item in self._store.integrations(kind)}
        for item in items:
            item["enabled"] = existing.get(item["item_id"], False)
        self._store.replace_integrations(kind, items)
        return items

    def _integration_description(self, kind: str, path: Path) -> str:
        """提取 Skill/MCP 包的人类可读介绍，供节点弹窗右侧预览。"""
        try:
            if kind == "skill":
                if path.is_dir():
                    for candidate in ("SKILL.md", "skill.md", "README.md"):
                        markdown = path / candidate
                        if markdown.is_file():
                            return self._frontmatter_description(markdown)
                    return ""
                if path.suffix.lower() == ".md":
                    return self._frontmatter_description(path)
                return ""
            # kind == "mcp"
            if path.is_dir():
                for candidate in ("mcp.json", "MCP.json", "README.md", "SKILL.md", "skill.md"):
                    target = path / candidate
                    if not target.is_file():
                        continue
                    if target.suffix.lower() == ".json":
                        desc = self._json_description(target)
                        if desc:
                            return desc
                    else:
                        desc = self._frontmatter_description(target)
                        if desc:
                            return desc
                # 嵌套结构（如 ~/.trae/mcps/<pkg>/search/<skill>/SKILL.md）：递归查找
                return self._recursive_description(path, [200])
            if path.suffix.lower() == ".json":
                return self._json_description(path)
            if path.suffix.lower() == ".md":
                return self._frontmatter_description(path)
            return ""
        except Exception:
            return ""

    def _recursive_description(self, directory: Path, budget: list[int]) -> str:
        """递归查找 SKILL.md / README.md / mcp.json 的描述，受扫描量限制。"""
        if budget[0] <= 0:
            return ""
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return ""
        for entry in entries:
            budget[0] -= 1
            if budget[0] <= 0:
                return ""
            try:
                if entry.is_dir():
                    desc = self._recursive_description(entry, budget)
                    if desc:
                        return desc
                elif entry.name.lower() in ("skill.md", "readme.md", "mcp.json", "server_metadata.json"):
                    desc = self._json_description(entry) if entry.suffix.lower() == ".json" else self._frontmatter_description(entry)
                    if desc:
                        return desc
            except OSError:
                continue
        return ""

    @staticmethod
    def _json_description(path: Path) -> str:
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return ""
        if isinstance(payload, dict):
            desc = payload.get("description") or payload.get("name") or payload.get("server_name") or ""
            return str(desc).strip()[:400]
        return ""

    @staticmethod
    def _frontmatter_description(path: Path) -> str:
        """读取 Markdown 前导 frontmatter 的 description（支持 > 引用块），无则取正文首段。"""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        match = re.match(r"\A---\s*\n(.*?)\n---", text, re.DOTALL)
        if match:
            frontmatter = match.group(1)
            desc_match = re.search(r"(?m)^\s*description:\s*(.*?)$", frontmatter)
            if desc_match:
                first = desc_match.group(1).strip()
                if first.startswith(">"):
                    lines = frontmatter.splitlines()
                    idx = next((i for i, line in enumerate(lines) if "description:" in line), -1)
                    parts = [line.strip() for line in lines[idx + 1:] if line.strip() and line.startswith(" ")]
                    folded = " ".join(parts) or first
                    return folded[:400]
                if first:
                    return first[:400]
            body = text[len(match.group(0)):]
        else:
            body = re.sub(r"(?m)^#+ .*$", "", text)
        cleaned = " ".join(body.split()).strip()
        return cleaned[:300]

    def set_integration(self, kind: str, item_id: str, enabled: bool) -> None:
        if kind not in {"skill", "mcp"}:
            raise PiRpcError("Unknown integration type")
        self._store.set_integration(kind, item_id, enabled)

    def clear_cache(self, category: str = "all") -> dict[str, int]:
        """分类清除小 π Agent 缓存。

        - sessions: 删除已结束的会话目录与记录（活跃会话保留）
        - models:   删除 Pi 模型清单缓存（models-store.json，启动时自动重建）
        - staging:  清空暂存安装目录
        - all:      以上全部
        """
        category = str(category or "all").lower()
        if category not in {"sessions", "models", "staging", "all"}:
            raise PiRpcError("Unknown cache category")
        root = self._root()
        result = {"sessions": 0, "models": 0, "staging": 0}
        if category in ("sessions", "all"):
            active = {client.info.session_id for client in self._sessions.values() if not client.info.closed}
            sessions_root = root / "data" / "workspace" / "pi-sessions"
            if sessions_root.is_dir():
                for entry in sessions_root.iterdir():
                    if entry.name in active:
                        continue
                    if entry.name.startswith("pi_sessions.db"):
                        # 数据库文件保留（只清记录），避免删除后重建空库导致表缺失
                        continue
                    try:
                        if entry.is_dir():
                            shutil.rmtree(entry)
                        else:
                            entry.unlink(missing_ok=True)
                        result["sessions"] += 1
                    except OSError:
                        continue
            self._store.clear_sessions()
        if category in ("models", "all"):
            store_file = root / "data" / "workspace" / "pi-agent-config" / "models-store.json"
            if store_file.is_file():
                try:
                    store_file.unlink()
                    result["models"] = 1
                except OSError:
                    pass
        if category in ("staging", "all"):
            staging = root / "data" / "workspace" / "pi-install-staging"
            if staging.is_dir():
                for entry in staging.iterdir():
                    try:
                        if entry.is_dir():
                            shutil.rmtree(entry)
                        else:
                            entry.unlink(missing_ok=True)
                        result["staging"] += 1
                    except OSError:
                        continue
        return result

    def staging(self) -> list[dict[str, str]]:
        """List ready-to-install packages under the Pi install staging directory."""
        directory = self._root() / "data" / "workspace" / "pi-install-staging"
        if not directory.is_dir():
            return []
        return [{"name": path.name, "path": str(path)} for path in sorted(directory.iterdir()) if path.is_dir()]

    def models(self) -> list[dict[str, Any]]:
        """Aggregate the model catalog shipped with Pi (providers/data/*.json).

        Each file is a provider manifest shaped as {"<api>": {"<modelId>": {...}}}.
        Returns a flat list of model records with provider/api/baseUrl metadata.
        """
        data_dir = self._root() / "thirdparty" / "pi" / "packages" / "ai" / "dist" / "providers" / "data"
        records: list[dict[str, Any]] = []
        if not data_dir.is_dir():
            return records
        for manifest in sorted(data_dir.glob("*.json")):
            if manifest.name == ".manifest.json":
                continue
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            provider_name = manifest.stem
            for api, models in payload.items():
                if not isinstance(models, dict):
                    continue
                for model_id, meta in models.items():
                    if not isinstance(meta, dict):
                        continue
                    records.append({
                        "id": str(meta.get("id", model_id)),
                        "name": str(meta.get("name", model_id)),
                        "api": str(meta.get("api", api)),
                        "provider": str(meta.get("provider", provider_name)),
                        "baseUrl": str(meta.get("baseUrl", "")),
                        "reasoning": bool(meta.get("reasoning", False)),
                        "contextWindow": int(meta.get("contextWindow", 0) or 0),
                        "maxTokens": int(meta.get("maxTokens", 0) or 0),
                    })
        return records

    def install(self, kind: str, name: str, level: str, source_dir: str) -> dict[str, Any]:
        """Install a Skill/MCP package.

        - level "project": copied into backend/config/agent/{skills,mcps}/{name},
          authorized by default (enabled=True).
        - level "system": copied into ~/.agent/{skills,mcps}/{name},
          disabled by default; the user must enable it in the 小π Agent settings.
        """
        if kind not in {"skill", "mcp"}:
            raise PiRpcError("Unknown integration type")
        if level not in {"project", "system"}:
            raise PiRpcError("Install level must be 'project' or 'system'")
        name = str(name).strip()
        if not name or len(name) > 80 or any(char in name for char in "\\/:*?\"<>|\r\n"):
            raise PiRpcError("Invalid package name")
        source = self._allowed_root(source_dir)
        if not source.is_dir():
            raise PiRpcError("Source directory does not exist")
        plural = "skills" if kind == "skill" else "mcps"
        target = (
            self._root().resolve() / "backend" / "config" / "agent" / plural / name
            if level == "project"
            else Path.home() / ".agent" / plural / name
        )
        if target.exists():
            raise PiRpcError(f"Package already installed: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        self.scan(kind)
        enabled = level == "project"
        self._store.set_integration(kind, f"{kind}:{target.resolve()}", enabled)
        return {"kind": kind, "name": name, "level": level, "target": str(target), "enabled": enabled}

    def _read_attachment_context(self, paths: list[str]) -> str:
        """校验附件路径并生成文件路径注入上下文。

        AI 使用 read 工具按路径读取文件内容，因此这里只做路径白名单/黑名单校验，
        不把文件全文注入 prompt。路径必须在 PROJECT_ROOT 内或 data/workspace 内。
        """
        if not paths:
            return ""
        root = self._root().resolve()
        sections: list[str] = []
        for item in paths[:20]:
            raw_path = Path(str(item))
            path = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
            if path.exists() and (root in path.parents or str(path).startswith(str(root / "data" / "workspace"))):
                relative = path.relative_to(root) if root in path.parents else path
                sections.append(f"- {relative.as_posix()}")
            else:
                raise PiRpcError(f"Attachment path is not allowed or does not exist: {item}")
        if not sections:
            return ""
        return (
            "The user attached the following files (relative to PROJECT_ROOT). "
            "Use the read tool to load each file before answering; resolve paths against PROJECT_ROOT.\n"
            + "\n".join(sections)
        )

    _MENTION_PATTERN = re.compile(r"(@skill|@mcp|&doc):([A-Za-z0-9_\-\u4e00-\u9fff.]+)")

    def _resolve_mentions(self, message: str) -> tuple[str, str]:
        """解析消息中的 @skill:/@mcp:/&doc: 引用，返回 (净化后的消息, 注入上下文)。

        - @skill:<名称> 或 @skill:<路径>：注入对应 Skill 的 SKILL.md 内容
        - @mcp:<名称>   或 @mcp:<路径>：注入对应 MCP 配置文件内容
        - &doc:<路径>：注入知识文档内容
        """
        matches = self._MENTION_PATTERN.findall(message)
        if not matches:
            return message, ""
        remaining = self._MENTION_PATTERN.sub("", message).strip()
        root = self._root().resolve()
        sections: list[str] = []
        for kind, name in matches:
            if kind == "@skill":
                path = self._find_skill_path(name)
                if path and path.is_file():
                    sections.append(f"\n\n--- Attached skill: {path.name} ({path.as_posix()}) ---\n{path.read_text(encoding='utf-8')[:24000]}")
            elif kind == "@mcp":
                path = self._find_mcp_path(name)
                if path:
                    sections.append(f"\n\n--- Attached MCP: {path.name} ({path.as_posix()}) ---\n{path.read_text(encoding='utf-8')[:24000]}")
            elif kind == "&doc":
                doc_path = Path(str(name))
                candidate = (doc_path if doc_path.is_absolute() else root / doc_path).resolve()
                if not (root in candidate.parents and candidate.is_file() and candidate.suffix.lower() == ".md"):
                    docs_dir = root / "backend" / "config" / "agent" / "docs"
                    fallback = docs_dir / name
                    if docs_dir.is_dir() and fallback.is_file() and fallback.suffix.lower() == ".md":
                        candidate = fallback.resolve()
                    else:
                        continue
                sections.append(f"\n\n--- Attached knowledge document: {candidate.as_posix()} ---\n{candidate.read_text(encoding='utf-8')[:24000]}")
        return remaining, "".join(sections)

    def _find_skill_path(self, name: str) -> Path | None:
        root = self._root().resolve()
        candidates = [
            root / "backend" / "config" / "agent" / "skills",
            Path.home() / ".agent" / "skills",
        ]
        for directory in candidates:
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if path.name == name and path.is_dir() and (path / "SKILL.md").is_file():
                    return path / "SKILL.md"
                if path.is_file() and path.name == name and path.suffix.lower() in {".md", ".json", ".yaml", ".yml"}:
                    return path
        return None

    def _find_mcp_path(self, name: str) -> Path | None:
        root = self._root().resolve()
        candidates = [
            root / "backend" / "config" / "agent" / "mcp",
            Path.home() / ".agent" / "mcps",
        ]
        for directory in candidates:
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if path.name == name and path.is_dir():
                    for config in sorted(path.iterdir()):
                        if config.is_file() and config.suffix.lower() in {".json", ".yaml", ".yml", ".md"}:
                            return config
                if path.is_file() and path.name == name:
                    return path
        return None

    async def prompt(
        self,
        session_id: str,
        message: str,
        attachments: list[str] | None = None,
        streaming_behavior: str | None = None,
    ) -> dict[str, Any]:
        """发送用户消息，自动解析 @skill/@mcp/&doc 引用并拼装附件路径上下文。"""
        client = await self.get(session_id)
        clean_message, mention_context = self._resolve_mentions(message)
        attachment_context = self._read_attachment_context(attachments or [])
        parts = [part for part in (mention_context, attachment_context, clean_message) if part]
        final_message = "\n\n".join(parts)
        return await client.prompt(
            final_message,
            streaming_behavior,
            float(self._config("prompt_timeout", 30) or 30),
        )

    async def create(
        self,
        session_id: str | None = None,
        project_id: str = "default",
        cwd: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
    ) -> PiRpcClient:
        async with self._lock:
            if session_id and session_id in self._sessions:
                existing = self._sessions[session_id]
                if not existing.info.closed:
                    return existing
                self._sessions.pop(session_id, None)
            runtime = self.runtime()
            if not runtime["enabled"]:
                raise PiRpcError("Pi is disabled")
            if runtime["status"] != "available":
                raise PiRpcError(runtime.get("message") or "Pi runtime is unavailable")
            if len(self._sessions) >= int(self._config("max_sessions", 3) or 3):
                raise PiRpcError("Pi session limit reached")
            root = self._root()
            default_cwd = root / "data" / "workspace"
            safe_cwd = self._allowed_root(cwd or str(default_cwd if default_cwd.is_dir() else root))
            safe_project = "".join(char for char in project_id if char.isalnum() or char in "-_ ")[:80].strip() or "default"
            for existing in self._sessions.values():
                if existing.info.project_id == safe_project and not existing.info.closed:
                    return existing
            saved = None if session_id else self._store.get(safe_project)
            session_key = session_id or (saved["session_id"] if saved and not saved["closed"] else uuid.uuid4().hex)
            configured_session_root = Path(str(self._config("session_root", "") or "data/workspace/pi-sessions"))
            session_root = configured_session_root if configured_session_root.is_absolute() else root / configured_session_root
            session_dir = session_root / safe_project
            agent_settings = self.settings()
            assistant_id = safe_project.removeprefix("agent-")
            assistant_settings = agent_settings["assistants"].get(assistant_id, {})
            llm_router = agent_settings.get("model_mode", "router") == "router"
            base_url = config.get("llm.router_url") if llm_router else config.get("llm.base_url")
            api_key = (config.get("llm.router_api_key") or "123") if llm_router else config.get("llm.api_key")
            if not llm_router:
                base_url = agent_settings.get("custom_base_url") or base_url
                api_key = agent_settings.get("custom_api_key") or api_key
                model = agent_settings.get("custom_model") or model
            selected_tools = self._tools(tools)
            read_blacklist = self._path_list([
                "backend/auth",
                *agent_settings.get("read_blacklist", []),
                *assistant_settings.get("read_blacklist", []),
            ])
            write_blacklist = self._path_list([
                "backend/auth",
                *agent_settings.get("write_blacklist", []),
                *assistant_settings.get("write_blacklist", []),
            ])
            base_documents = self._document_paths(agent_settings.get("base_docs_paths", []))
            assistant_docs = [assistant_settings.get("docs_path")] if assistant_settings.get("docs_path") else []
            if assistant_id == "general" and not assistant_docs:
                capability_index = root / "backend" / "config" / "agent" / "docs" / "capability-index.md"
                if capability_index.is_file():
                    assistant_docs.append(str(capability_index))
            if assistant_id == "installer" and not assistant_docs:
                installer_doc = root / "backend" / "config" / "agent" / "docs" / "skill-mcp-install.md"
                if installer_doc.is_file():
                    assistant_docs.append(str(installer_doc))
            assistant_documents = self._document_paths(assistant_docs)
            known = {str(path).lower() for path in base_documents}
            assistant_documents = [path for path in assistant_documents if str(path).lower() not in known]
            prompt_parts = [
                _DEFAULT_PERSONA,
                assistant_settings.get("persona") or system_prompt or "",
                "PROJECT_ROOT is the absolute root of this VideoLingoFlow checkout. Resolve every relative project path from PROJECT_ROOT.",
                "Path access is enforced by the runtime policy. Do not attempt to bypass it with shell commands.",
                self._document_context([*base_documents, *assistant_documents]),
                self._environment_summary(),
            ]
            env = {
                "OPENAI_BASE_URL": str(base_url or "").rstrip("/") + ("" if str(base_url or "").rstrip("/").endswith("/v1") else "/v1"),
                "OPENAI_API_KEY": str(api_key or ""),
                "NO_PROXY": "127.0.0.1,localhost",
                "VIDEOLINGO_PI_PATH_POLICY": json.dumps({"read_blacklist": read_blacklist, "write_blacklist": write_blacklist, "bash_enabled": "bash" in selected_tools}),
            }
            client = PiRpcClient(
                project_root=str(root),
                session_id=session_key,
                project_id=safe_project,
                cwd=str(safe_cwd),
                model=self._model(model),
                tools=selected_tools,
                system_prompt="\n\n".join(part for part in prompt_parts if part)[:32000],
                node_path=runtime["node_path"],
                cli_path=runtime["cli_path"],
                session_dir=str(session_dir),
                env=env,
                max_output_chars=int(self._config("max_output_chars", 12000) or 12000),
            )
            await client.start()
            if saved:
                client.info.messages = saved.get("messages", [])
                client.info.message_count = saved.get("message_count", 0)
            self._sessions[session_key] = client
            self._store.upsert(safe_project, session_key, str(safe_cwd), str(session_dir), client.info.created_at, client.info.last_activity, client.info.message_count, False, client.info.messages)
            client.subscribe(lambda event: self._persist_event(client, event))
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            return client

    async def workflow_session(
        self,
        system_prompt: str,
        cwd: str | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
    ) -> PiRpcClient:
        """Create a one-shot Pi session for a workflow node (not persisted, caller closes it).

        - Does NOT register into ``_sessions`` (no idle cleanup, no history persistence).
        - Builds env/path-policy exactly like ``create()`` (router or custom model settings).
        - The caller is responsible for closing the returned client after prompt completes.
        """
        runtime = self.runtime()
        if not runtime["enabled"]:
            raise PiRpcError("Pi is disabled")
        if runtime["status"] != "available":
            raise PiRpcError(runtime.get("message") or "Pi runtime is unavailable")
        root = self._root()
        default_cwd = root / "data" / "workspace"
        safe_cwd = self._allowed_root(cwd or str(default_cwd if default_cwd.is_dir() else root))
        agent_settings = self.settings()
        llm_router = agent_settings.get("model_mode", "router") == "router"
        base_url = config.get("llm.router_url") if llm_router else config.get("llm.base_url")
        api_key = (config.get("llm.router_api_key") or "123") if llm_router else config.get("llm.api_key")
        if not llm_router:
            base_url = agent_settings.get("custom_base_url") or base_url
            api_key = agent_settings.get("custom_api_key") or api_key
            model = agent_settings.get("custom_model") or model
        # 节点 agent 需要完整能力（含 Shell）以完成复杂任务，默认授予全部允许工具；
        # 若调用方显式传入 tools，则按传入列表执行。
        if tools:
            selected_tools = self._tools(tools)
        else:
            allowed_tools = set(self._config("allow_tools", ["read", "grep", "find", "ls", "write", "edit", "bash"]) or [])
            selected_tools = sorted(allowed_tools) or ["read"]
        read_blacklist = self._path_list([
            "backend/auth",
            *agent_settings.get("read_blacklist", []),
        ])
        write_blacklist = self._path_list([
            "backend/auth",
            *agent_settings.get("write_blacklist", []),
        ])
        session_key = f"wf-{uuid.uuid4().hex}"
        configured_session_root = Path(str(self._config("session_root", "") or "data/workspace/pi-sessions"))
        session_root = configured_session_root if configured_session_root.is_absolute() else root / configured_session_root
        session_dir = session_root / "workflow" / session_key
        env = {
            "OPENAI_BASE_URL": str(base_url or "").rstrip("/") + ("" if str(base_url or "").rstrip("/").endswith("/v1") else "/v1"),
            "OPENAI_API_KEY": str(api_key or ""),
            "NO_PROXY": "127.0.0.1,localhost",
            "VIDEOLINGO_PI_PATH_POLICY": json.dumps({"read_blacklist": read_blacklist, "write_blacklist": write_blacklist, "bash_enabled": "bash" in selected_tools}),
        }
        client = PiRpcClient(
            project_root=str(root),
            session_id=session_key,
            project_id="workflow",
            cwd=str(safe_cwd),
            model=self._model(model),
            tools=selected_tools,
            system_prompt=(system_prompt + "\n\n" + self._environment_summary())[:32000],
            node_path=runtime["node_path"],
            cli_path=runtime["cli_path"],
            session_dir=str(session_dir),
            env=env,
            max_output_chars=int(self._config("max_output_chars", 12000) or 12000),
        )
        await client.start()
        return client

    async def get(self, session_id: str) -> PiRpcClient:
        async with self._lock:
            client = self._sessions.get(session_id)
        if not client or client.info.closed:
            raise PiRpcError("Pi session not found or expired")
        return client

    async def close(self, session_id: str) -> None:
        async with self._lock:
            client = self._sessions.pop(session_id, None)
        if client:
            await client.close()
            self._store.mark_closed(client.info.project_id)

    async def end(self, session_id: str) -> None:
        await self.close(session_id)

    async def clear_context(self, session_id: str) -> PiRpcClient:
        client = await self.get(session_id)
        await client.command({"type": "new_session"}, timeout=10)
        client.info.messages = []
        client.info.message_count = 0
        self._store.clear_messages(client.info.project_id)
        return client

    async def restore_history(self, session_id: str, history_id: int) -> PiRpcClient:
        current = await self.get(session_id)
        history = next((item for item in self._store.history(current.info.project_id) if item["id"] == history_id), None)
        if not history:
            raise PiRpcError("History session not found")
        await self.close(session_id)
        client = await self.create(session_id=history["session_id"], project_id=current.info.project_id, cwd=history["cwd"], model=current.info.model)
        client.info.messages = history["messages"]
        return client

    async def _persist_event(self, client: PiRpcClient, event: dict[str, Any]) -> None:
        message = event.get("message")
        if event.get("type") == "message_end" and isinstance(message, dict):
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, list):
                text = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text")
                thinking = "".join(str(item.get("thinking", "")) for item in content if isinstance(item, dict) and item.get("type") == "thinking")
                if text or thinking:
                    entry: dict[str, str] = {"role": role, "text": text}
                    if thinking:
                        entry["thinking"] = thinking
                    client.info.messages = [*client.info.messages, entry][-100:]
        self._store.upsert(client.info.project_id, client.info.session_id, client.info.cwd, client._session_dir, client.info.created_at, client.info.last_activity, client.info.message_count, client.info.closed, client.info.messages)

    async def close_all(self) -> None:
        async with self._lock:
            clients = list(self._sessions.values())
            self._sessions.clear()
        await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        if self._cleanup_task:
            self._cleanup_task.cancel()

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            idle = float(self._config("idle_timeout", 1800) or 1800)
            now = time.time()
            async with self._lock:
                expired = [sid for sid, client in self._sessions.items() if now - client.info.last_activity > idle and not client.info.streaming]
            await asyncio.gather(*(self.close(sid) for sid in expired), return_exceptions=True)

    def status(self) -> dict[str, Any]:
        result = self.runtime()
        result["session_count"] = len(self._sessions)
        return result


_manager: PiSessionManager | None = None


def get_pi_manager() -> PiSessionManager:
    global _manager
    if _manager is None:
        _manager = PiSessionManager()
    return _manager
