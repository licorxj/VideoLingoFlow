"""s_hyperframes_cli: HyperFrames 工具调用节点。

把 HyperFrames CLI 的附属能力直接暴露成一个可编排节点：技能安装/检查、工程
初始化、网站抓取、Registry 组件安装、关键帧诊断、校验、升级、预览、渲染、
发布，以及自定义子命令。

节点不做语义编排，只负责在指定工作目录里执行一条 CLI 命令，把 stdout 落盘成
日志并作为文本输出。
"""
from pathlib import Path
from typing import Callable, Optional

from backend.steps.s_hyperframes_base import (
    HyperFramesBase,
    _config,
    _inputs,
    _node_id,
    _rel_or_abs,
)
from backend.utils import hyperframes as hf

#: 子命令 -> (展示名, 说明)
CLI_COMMANDS: dict[str, tuple[str, str]] = {
    "init": ("init 初始化工程", "在项目目录初始化 HyperFrames 工程"),
    "skills_update": ("skills update 安装技能", "安装/刷新指定工作流或领域技能，留空则只刷新核心集"),
    "skills_check": ("skills check 技能体检", "检查已安装技能是否过期或缺失"),
    "add": ("add 安装 Registry 组件", "安装一个 Registry 场景组件到当前工程"),
    "capture": ("capture 抓取网站", "用无头浏览器抓取站点截图与品牌资源"),
    "keyframes": ("keyframes 关键帧诊断", "检查合成里的关键帧是否可 seek"),
    "lint": ("lint 代码检查", "对合成做静态检查"),
    "validate": ("validate 结构校验", "校验合成结构是否合法"),
    "check": ("check 工程体检", "校验工程在已固定 CLI 版本上是否仍然通过"),
    "upgrade": ("upgrade 升级工程", "把工程固定的 CLI 版本升级到最新"),
    "doctor": ("doctor 环境诊断", "诊断本地渲染环境"),
    "preview": ("preview 启动预览", "启动本地预览服务"),
    "render": ("render 渲染成片", "对已有工程执行渲染"),
    "publish": ("publish 发布链接", "把成片发布到可分享的稳定链接"),
    "custom": ("custom 自定义命令", "直接填写子命令与参数"),
}

# 需要额外文本参数的子命令 -> 配置键
_COMMAND_ARG_KEYS = {
    "skills_update": "skill_names",
    "add": "block",
    "capture": "url",
}


def build_args(command: str, config: dict) -> list[str]:
    """按子命令拼装 CLI 参数（不含 cli/package 前缀）。"""
    extra = [item for item in str(config.get("args") or "").split() if item]
    block_value = str(config.get("block") or "").strip()
    url_value = str(config.get("url") or "").strip()
    names = [item for item in str(config.get("skill_names") or "").replace(",", " ").split() if item]

    if command == "custom":
        return [item for item in str(config.get("custom_args") or "").split() if item]
    if command == "init":
        return ["init", *extra]
    if command == "skills_update":
        return ["skills", "update", *names, *extra]
    if command == "skills_check":
        return ["skills", "check", *extra]
    if command == "add":
        if not block_value:
            raise ValueError("安装 Registry 组件需要填写组件名（block）")
        return ["add", block_value, *extra]
    if command == "capture":
        if not url_value:
            raise ValueError("抓取网站需要填写 URL")
        return ["capture", url_value, "-o", "./capture", *extra]
    if command == "upgrade":
        return ["upgrade", "--project", ".", *extra]
    if command in ("keyframes", "lint", "validate", "check", "doctor", "preview", "render", "publish"):
        return [command, *extra]
    raise ValueError(f"未知的子命令：{command}")


class S_HyperFramesCli(HyperFramesBase):
    step_id = "hyperframes_cli"
    step_name = "HyperFrames 工具"
    result_base = "hyperframes_cli"

    def validate_inputs(self, task_dir: str) -> bool:
        config, inputs = _config(self), _inputs(self)
        command = str(config.get("command") or "check")
        return command in CLI_COMMANDS

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config, inputs = _config(self), _inputs(self)
        node_id = _node_id(self)
        command = str(config.get("command") or "check")
        if command not in CLI_COMMANDS:
            raise ValueError(f"未知的子命令：{command}")

        # 抓取/初始化等命令允许直接落在任务缓存目录，无需既有工程
        project_dir = self._project_dir(task_dir, config, inputs, create=True)
        cli, package = self._cli_settings(config)
        args = build_args(command, config)
        timeout = self._as_int(config.get("timeout"), 1800)

        if callback:
            callback(3, f"工作目录：{project_dir}")

        stdout = hf.run_cli(
            args,
            cwd=project_dir,
            cli=cli,
            package=package,
            timeout=timeout,
            callback=callback,
            cancel_callback=cancel_callback,
            progress_range=(5, 95),
            label=f"hyperframes {args[0] if args else ''}".strip(),
        )

        log_path = Path(task_dir) / "cache" / f"hyperframes_cli_{node_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(stdout or "(无输出)", encoding="utf-8")

        self._write_result(task_dir, {
            "command": command,
            "args": args,
            "project_dir": str(project_dir),
            "log": str(log_path),
        })

        if callback:
            callback(100, f"完成：{CLI_COMMANDS[command][0]}")

        return {
            "artifacts": [_rel_or_abs(task_dir, log_path)],
            "outputs": {
                "output": _rel_or_abs(task_dir, log_path),
                "stdout": (stdout or "")[:8000],
            },
        }


StepHyperFramesCli = S_HyperFramesCli
