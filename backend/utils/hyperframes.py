"""HyperFrames 工作流节点的公共支撑层。

HyperFrames 用 HTML 描述合成、用 ``npx hyperframes`` 渲染成片。本项目把它包装成
工作流节点，核心链路是「创意 → 渲染」两步：

1. **创意（creative）**：按意图访谈锁定工作流路由与风格，产出 ``BRIEF.md``；
   或加载一份已有的 ``BRIEF.md``，稳定复用既有工作流。
2. **渲染（render）**：读取 ``BRIEF.md``，按路由构建合成并渲染成片。

两步都由小 Pi（piagent 框架）驱动 HyperFrames CLI 完成。本模块只封装它们的公共
部分：技能定位、CLI 调用、Pi 会话编排与产物查找，不含任何节点业务逻辑。
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# 约定的任务结束标识：Pi 会话最终回复须包含该标记，后跟验收 JSON
DONE_MARKER = "[HF_DONE]"

# HyperFrames 工作流路由（与技能 references/routes/<route>.md 一一对应）
WORKFLOW_ROUTES: dict[str, str] = {
    "general-video": "通用视频：其它所有自定义合成、长片、静态循环",
    "product-launch-video": "产品发布片：从 URL / 脚本做产品宣传片",
    "faceless-explainer": "无脸讲解：从文本讲解一个主题，视觉全部 LLM 构思",
    "pr-to-video": "PR 讲解：把 GitHub PR / 代码改动讲成视频",
    "embedded-captions": "嵌入字幕：给现成口播素材加字幕，不改画面",
    "talking-head-recut": "口播精编：给现成口播素材加设计感图文浮层",
    "motion-graphics": "动态图形：10 秒内无旁白的短动效",
    "music-to-video": "音乐视频：按节拍网格驱动的卡点视频",
    "slideshow": "演示文稿：可导航的 deck，产出不是 MP4",
    "remotion-to-hyperframes": "Remotion 迁移：把已有 Remotion 合成移植过来",
}

# 画幅与语言默认值
ASPECT_CHOICES = ("auto", "16:9", "9:16", "1:1", "4:3", "21:9")

# CLI 默认调用方式：npx hyperframes@latest ...
DEFAULT_CLI = "npx"
DEFAULT_PACKAGE = "hyperframes@latest"

# 渲染产物可能被写到的目录（按优先级排序）
_RENDER_OUTPUT_DIRS = ("out", "dist", "render", "output", "build", ".")
_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv")


# --------------------------------------------------------------------------- #
# 路径与技能定位
# --------------------------------------------------------------------------- #
def project_root() -> Path:
    """项目根目录（backend 的上一级）。"""
    return Path(__file__).resolve().parents[2]


def skill_dir() -> Path:
    """HyperFrames 技能目录（随仓库分发，Pi 可直接以项目技能方式加载）。"""
    return project_root() / "backend" / "config" / "agent" / "skills" / "hyperframes"


def skill_entry() -> Path:
    """技能入口 SKILL.md。"""
    return skill_dir() / "SKILL.md"


def route_reference(route: str) -> Optional[Path]:
    """工作流路由说明文档；未知路由返回 None。"""
    if not route or route not in WORKFLOW_ROUTES:
        return None
    return skill_dir() / "references" / "routes" / f"{route}.md"


def resolve_project_dir(task_dir: str, config: dict, node_id: str, create: bool = True) -> Path:
    """确定 HyperFrames 项目目录。

    优先级：节点配置 ``project_dir`` → 任务缓存下的 ``hyperframes_{node_id}``。
    配置值可以是绝对路径，也可以是相对任务目录的路径。
    """
    configured = str(config.get("project_dir") or "").strip()
    base = configured or os.path.join("cache", f"hyperframes_{node_id}")
    path = Path(base)
    if not path.is_absolute():
        path = Path(task_dir) / path
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def first_value(raw: Any) -> str:
    """取值：``_step_inputs`` 的值可能是字符串或列表，统一取第一个非空项。"""
    if isinstance(raw, (list, tuple)):
        for item in raw:
            text = first_value(item)
            if text:
                return text
        return ""
    if raw is None:
        return ""
    return str(raw).strip()


def resolve_input_path(task_dir: str, raw: Any) -> Optional[Path]:
    """把连线输入解析为存在的文件/目录绝对路径。"""
    text = first_value(raw)
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = Path(task_dir) / path
    return path.resolve() if path.exists() else None


# --------------------------------------------------------------------------- #
# CLI 调用
# --------------------------------------------------------------------------- #
def build_cli_command(args: Iterable[Any], cli: str = DEFAULT_CLI, package: str = DEFAULT_PACKAGE) -> list[str]:
    """拼装 CLI 命令行：``<cli> <package> <args...>``。"""
    command = [cli]
    if str(package or "").strip():
        command.append(str(package).strip())
    command.extend(str(item) for item in args if str(item) != "")
    return command


def run_cli(
    args: Iterable[Any],
    cwd: str | Path,
    cli: str = DEFAULT_CLI,
    package: str = DEFAULT_PACKAGE,
    timeout: int = 600,
    callback: Optional[Callable] = None,
    cancel_callback: Optional[Callable] = None,
    progress_range: tuple[int, int] = (5, 95),
    label: str = "hyperframes",
) -> str:
    """执行一条 HyperFrames CLI 命令，逐行回传日志，返回合并后的 stdout。

    超时或用户取消时终止子进程并抛错。非 0 退出码抛出带日志尾部的 RuntimeError。
    """
    command = build_cli_command(args, cli=cli, package=package)
    low, high = progress_range
    if callback:
        callback(low, f"执行 {' '.join(command[:4])}")

    popen_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        # 隐藏控制台窗口；shell=True 让 npx.cmd 这类批处理可被解析
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        popen_kwargs["shell"] = True
    try:
        process = subprocess.Popen(command, **popen_kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"未找到 CLI 执行程序 {command[0]!r}，请确认已安装 Node.js 并将其加入 PATH，"
            f"或在节点设置里指定可执行的 CLI 命令。"
        ) from exc

    lines: list[str] = []
    stream: "queue.Queue[Optional[str]]" = queue.Queue()

    def _reader() -> None:
        try:
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ""):
                stream.put(line)
        except Exception:  # pragma: no cover - 读取线程异常不应挂起主流程
            pass
        finally:
            stream.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    deadline = time.time() + max(1, int(timeout))
    finished = False
    while True:
        try:
            line = stream.get(timeout=1.0)
        except queue.Empty:
            line = ""
        if line is None:
            finished = True
            break
        if line:
            text = line.rstrip("\r\n")
            lines.append(text)
            if callback and text.strip():
                callback(low, f"[{label}] {text.strip()[:200]}")
        if process.poll() is not None and stream.empty():
            # 进程已退出且队列空：再给一次机会取结束哨兵
            time.sleep(0.05)
            continue
        if time.time() > deadline:
            _terminate(process)
            raise RuntimeError(f"{label} 执行超时（{timeout} 秒）：{' '.join(command)}")
        if cancel_callback and cancel_callback():
            _terminate(process)
            raise RuntimeError(f"{label} 已被用户取消")

    if not finished:  # 理论上不可达，保险处理
        process.wait(timeout=10)

    try:
        process.stdout.close()  # type: ignore[union-attr]
    except Exception:
        pass
    returncode = process.wait(timeout=30)
    output = "\n".join(lines).strip()
    if returncode != 0:
        tail = output[-1500:] if output else "(无输出)"
        raise RuntimeError(
            f"{label} 命令失败（退出码 {returncode}）：{' '.join(command)}\n{tail}\n"
            f"提示：若在 Windows 下首次运行，请先手动执行 `npx hyperframes --help` 完成安装。"
        )
    if callback:
        callback(high, f"{label} 完成")
    return output


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def ensure_workflow_skills(
    route: str,
    cwd: str | Path,
    cli: str = DEFAULT_CLI,
    package: str = DEFAULT_PACKAGE,
    timeout: int = 600,
    callback: Optional[Callable] = None,
    cancel_callback: Optional[Callable] = None,
) -> None:
    """保证目标工作流的技能已安装（``npx hyperframes skills update <route>``）。

    ``route`` 为 auto / 空值时只刷新核心技能集，不安装具体工作流。
    """
    names = [route] if route in WORKFLOW_ROUTES else []
    run_cli(
        ["skills", "update", *names],
        cwd=cwd,
        cli=cli,
        package=package,
        timeout=timeout,
        callback=callback,
        cancel_callback=cancel_callback,
        progress_range=(5, 30),
        label="skills update",
    )


# --------------------------------------------------------------------------- #
# 小 Pi（piagent 框架）会话编排
# --------------------------------------------------------------------------- #
def run_pi_task(
    system_prompt: str,
    instruction: str,
    cwd: str | Path,
    callback: Optional[Callable] = None,
    cancel_callback: Optional[Callable] = None,
    settle_timeout: int = 1800,
    progress_range: tuple[int, int] = (10, 90),
) -> str:
    """发起一次性小 Pi 会话执行任务，返回助手最终文本。

    复用 ``pi_rpc`` 的 ``workflow_session``：会话不进入全局会话表，调用方负责关闭。
    """
    async def _execute() -> str:
        from backend.pi_rpc import get_pi_manager

        manager = get_pi_manager()
        client = None
        low, high = progress_range
        chunks: list[str] = []
        last_message: dict[str, Any] = {}

        def progress(percent: int, message: str) -> None:
            if callback:
                try:
                    callback(percent, message)
                except Exception:
                    pass

        try:
            if cancel_callback and cancel_callback():
                raise RuntimeError("任务已取消")
            progress(low, "正在启动小 Pi 会话")
            client = await manager.workflow_session(system_prompt=system_prompt, cwd=str(cwd))
            if cancel_callback and cancel_callback():
                raise RuntimeError("任务已取消")
            progress(low + 5, "小 Pi 会话已就绪")

            async def _on_event(event: dict[str, Any]) -> None:
                nonlocal last_message
                etype = event.get("type", "")
                delta = event.get("assistantMessageEvent") or {}
                dtype = delta.get("type", "")
                if dtype == "thinking_delta" and delta.get("delta"):
                    progress(low + 15, f"思考中: {str(delta['delta'])[:60]}")
                elif dtype == "text_delta" and delta.get("delta"):
                    chunks.append(str(delta["delta"]))
                    progress(min(high - 5, low + 20 + (len(chunks) % 40)), f"生成: {str(delta['delta'])[-50:]}")
                elif etype == "message_end":
                    message = event.get("message") or {}
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        last_message = message
                elif etype == "agent_end":
                    for message in event.get("messages") or []:
                        if isinstance(message, dict) and message.get("role") == "assistant":
                            last_message = message
                elif etype == "tool_execution_end":
                    progress(min(high - 10, low + 30), f"调用工具: {event.get('toolName', '')}")

            client.subscribe(_on_event)

            settled = asyncio.Event()

            async def _on_terminal(event: dict[str, Any]) -> None:
                if event.get("type") in ("agent_settled", "agent_end", "pi_closed"):
                    settled.set()

            client.subscribe(_on_terminal)
            # Pi 的 prompt 在 preflight 通过时即返回，LLM 生成是异步的，
            # 必须等到终止事件后再验收，否则最终文本尚未收集完成。
            await client.prompt(instruction, "steer", 300)
            if cancel_callback and cancel_callback():
                raise RuntimeError("任务已取消")
            try:
                await asyncio.wait_for(settled.wait(), timeout=settle_timeout)
            except asyncio.TimeoutError:
                pass

            full_text = "".join(chunks)
            if not full_text and last_message:
                content = last_message.get("content") or []
                full_text = "".join(
                    str(item.get("text", ""))
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            progress(high, "小 Pi 会话结束")
            return full_text
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_execute())
    # 极少数情况下调用方已持有事件循环：在新线程里另起一个循环执行
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _execute()).result()


def parse_done_payload(text: str, marker: str = DONE_MARKER) -> Optional[dict[str, Any]]:
    """从最终回复中解析结束标识后的验收 JSON。"""
    if marker not in text:
        return None
    after = text.split(marker, 1)[1].strip()
    match = re.search(r"\{.*\}", after, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def require_done_payload(text: str, marker: str = DONE_MARKER) -> dict[str, Any]:
    """解析验收 JSON 并兜底报错，附带 Pi 实际输出尾部便于排查。"""
    payload = parse_done_payload(text, marker=marker)
    if payload is None:
        snippet = (text or "").strip()[-800:] or "(empty)"
        raise RuntimeError(
            f"小 Pi 未返回约定的结束标识 {marker}，请检查其输出。"
            f"实际输出尾部：{snippet}"
        )
    return payload


# --------------------------------------------------------------------------- #
# BRIEF.md 读写
# --------------------------------------------------------------------------- #
_BRIEF_ROUTE_KEYS = ("workflow", "route", "工作流", "路由")


def read_brief_route(brief_path: Path) -> str:
    """从 BRIEF.md 中解析已锁定的工作流路由，解析不到返回空串。

    同时兼容 YAML 风格（``workflow: xxx``）与 Markdown 表格/标题中的反引号引用。
    """
    try:
        content = brief_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = content.splitlines()
    in_frontmatter = lines[:1] == ["---"]
    for index, line in enumerate(lines):
        if in_frontmatter and index > 0:
            if line.strip() == "---":
                in_frontmatter = False
            continue
        stripped = line.strip().lstrip("-*|").strip()
        for key in _BRIEF_ROUTE_KEYS:
            match = re.match(rf"^{re.escape(key)}\s*[:：]\s*(.+)$", stripped, re.IGNORECASE)
            if not match:
                continue
            value = re.sub(r"[`*\"'\[\]()]", "", match.group(1)).strip().rstrip("|").strip()
            if value in WORKFLOW_ROUTES:
                return value
            # 形如 `/product-launch-video` 的斜杠写法
            candidate = value.lstrip("/").strip()
            if candidate in WORKFLOW_ROUTES:
                return candidate
    for route in WORKFLOW_ROUTES:
        if f"`/{route}`" in content or f"/{route}" in content:
            return route
    return ""


def install_brief_into_project(source: Path, project_dir: Path) -> Path:
    """把已有的 BRIEF.md 复制到项目目录（已是同文件则原样返回）。"""
    project_dir.mkdir(parents=True, exist_ok=True)
    target = project_dir / "BRIEF.md"
    try:
        if source.resolve() == target.resolve():
            return target
    except OSError:
        pass
    shutil.copy2(source, target)
    return target


def find_brief(project_dir: Path) -> Optional[Path]:
    """在项目目录中查找 BRIEF.md。"""
    candidate = project_dir / "BRIEF.md"
    return candidate if candidate.is_file() else None


# --------------------------------------------------------------------------- #
# 渲染产物查找
# --------------------------------------------------------------------------- #
def locate_render_output(project_dir: Path, configured: str = "") -> Optional[Path]:
    """定位渲染成片：优先用配置路径，否则在常见输出目录里找最新的视频文件。"""
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = project_dir / path
        if path.is_file():
            return path.resolve()

    candidates: list[Path] = []
    for folder in _RENDER_OUTPUT_DIRS:
        directory = project_dir / folder
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in _VIDEO_EXTS:
                candidates.append(entry)
    # 递归兜底：HyperFrames 可能按合成名建子目录
    for entry in project_dir.rglob("*"):
        if entry.is_file() and entry.suffix.lower() in _VIDEO_EXTS and "node_modules" not in entry.parts:
            candidates.append(entry)
    if not candidates:
        return None
    return max(set(candidates), key=lambda item: item.stat().st_mtime).resolve()


# --------------------------------------------------------------------------- #
# 提示词拼装
# --------------------------------------------------------------------------- #
def _prompt_skill_block(route: str, extra_references: Iterable[Path] = ()) -> list[str]:
    parts = [
        "## HyperFrames 技能入口",
        f"- 入口文档（必须先读）：{skill_entry()}",
        f"- 能力总表：{skill_dir() / 'references' / 'capability-menu.md'}",
        f"- 意图访谈规则：{skill_dir() / 'references' / 'intent-interview.md'}",
        f"- 技能生命周期：{skill_dir() / 'references' / 'skill-lifecycle.md'}",
    ]
    reference = route_reference(route)
    if reference:
        parts.append(f"- 本次工作流路由契约：{reference}")
    for path in extra_references:
        parts.append(f"- 附加参考：{path}")
    return parts


def build_creative_prompt(
    project_dir: Path,
    route: str,
    subject: str,
    run_mode: str,
    style_preset: str,
    aspect: str,
    language: str,
    materials: dict[str, str],
    extra_instruction: str = "",
) -> str:
    """拼装「创意」阶段的 Pi 系统提示。"""
    route_text = WORKFLOW_ROUTES.get(route, "未指定，由你按意图路由决定")
    parts = [
        "你是 HyperFrames 的创意总监，负责把用户的原始输入收敛成一份可执行的创意简报。",
        "HyperFrames 用 HTML 描述合成、用 `npx hyperframes` 渲染成片；你只负责创意与简报，不要渲染。",
        *_prompt_skill_block(route),
        "## 本次任务",
        f"- 项目目录：{project_dir}",
        f"- 工作流路由：{route or 'auto'}（{route_text}）",
        f"- 协作模式：{run_mode}（collaborative=先确认再落盘；autonomous=自行决断，不再追问）",
        f"- 风格预设：{style_preset or '由你按内容挑选，或直接采用工作流默认'}",
        f"- 画幅：{aspect}（auto 表示按投放平台推断：社交信息流 1:1、短视频 9:16、其它 16:9）",
        f"- 旁白/字幕语言：{language or '跟随用户语言'}",
        "## 输入材料",
        json.dumps(materials, ensure_ascii=False, indent=2),
        "## 创作主题",
        subject or "（未指定，请先向用户确认视频到底要讲什么，再开始写简报）",
    ]
    if extra_instruction:
        parts.append(f"## 用户补充要求\n{extra_instruction}")
    parts.extend(
        [
            "## 执行与回报规则",
            "1. 先读技能入口文档与本次路由契约，按其中的访谈流程收敛输入、主题与必选项。",
            "2. 路由为 auto 时，先阅读 `references/routes/` 下各路由契约再决定，并把决定写进简报。",
            "3. 把最终简报写入项目目录下的 `BRIEF.md`，至少包含：主题、工作流路由、目标受众与投放平台、"
            "时长与画幅、旁白语言、风格预设、创意方向与分镜要点、所需素材清单。",
            "4. 若已有 `BRIEF.md`，在其基础上迭代而不是推倒重写。",
            f"5. 完成后在最终回复最后单独一行输出结束标识 {DONE_MARKER}，并在其后输出验收 JSON（不要用代码块包裹）：",
            '   {"status": "success" | "failed", "message": "简要说明", "brief": "BRIEF.md", "workflow": "<最终路由>", "summary": "一句话创意摘要"}',
            "6. 若信息不足且协作模式为 collaborative，可先只输出一个提问，待下一轮补充后再写简报；"
            "autonomous 模式下必须自行补全假设并直接产出简报。",
        ]
    )
    return "\n\n".join(parts)


def build_render_prompt(
    project_dir: Path,
    brief_path: Path,
    route: str,
    stage: str,
    output_name: str,
    extra_instruction: str = "",
    publish: bool = False,
) -> str:
    """拼装「渲染」阶段的 Pi 系统提示。"""
    stage_text = {
        "build_and_render": "构建合成并渲染成片",
        "build": "只构建合成（HTML/工程产物），不渲染",
        "render": "只对已有合成执行渲染",
        "validate": "只做校验（lint / check / validate），不渲染",
    }.get(stage, "构建合成并渲染成片")
    parts = [
        "你是 HyperFrames 的制作执行者，负责把创意简报落地为可播放的成片。",
        "HyperFrames 用 HTML 描述合成、用 `npx hyperframes` 渲染成片；CLI 是你唯一的生产工具。",
        *_prompt_skill_block(
            route,
            extra_references=[skill_dir() / "references" / "route-briefs.md"],
        ),
        "## 本次任务",
        f"- 项目目录：{project_dir}",
        f"- 创意简报：{brief_path}（先完整读一遍，简报里的 workflow 字段即工作流路由）",
        f"- 执行阶段：{stage}（{stage_text}）",
        f"- 成片文件名：{output_name}",
        f"- 是否需要发布：{'是，渲染完成后执行 publish 并把链接回报出来' if publish else '否'}",
    ]
    if extra_instruction:
        parts.append(f"## 用户补充要求\n{extra_instruction}")
    parts.extend(
        [
            "## 执行与回报规则",
            "1. 工作目录必须是上面的项目目录；CLI 一律用 `npx hyperframes@latest <子命令>` 调用。",
            "2. 恢复既有工程时先按 `references/skill-lifecycle.md` 做一次 CLI 版本探针（"
            "`npx hyperframes@latest upgrade --project . --check`），落后则先升级再 `npx hyperframes check`。",
            "3. 按路由契约推进：设计规格 → 分镜规划 → 先排版后动效 → 构建合成 → 校验 → 渲染。",
            "4. 渲染前至少跑一次 `npx hyperframes check`（必要时 `lint` / `validate`），失败必须修好再渲染。",
            "5. 成片输出到项目目录内，文件名用上面给定的成片文件名。",
            "6. 领域能力（动画、关键帧、媒体、音频、Registry 组件、Figma）按需调用 `npx hyperframes skills update <name>` 后加载对应技能。",
            f"7. 完成后在最终回复最后单独一行输出结束标识 {DONE_MARKER}，并在其后输出验收 JSON（不要用代码块包裹）：",
            '   {"status": "success" | "failed", "message": "简要说明", "video": "<成片相对项目目录的路径>", "url": "<publish 链接，未发布填空串>"}',
            "8. 若失败，同样输出结束标识并置 status 为 failed，message 写清原因。",
        ]
    )
    return "\n\n".join(parts)
