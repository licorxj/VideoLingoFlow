"""HyperFrames 系列节点的测试。

只覆盖不依赖外部环境的纯逻辑：CLI 参数拼装、BRIEF.md 路由解析、验收 JSON 解析、
项目目录/产物定位，以及创意节点的「加载已有简报」路径与节点/Step 注册。
需要 Node.js 或小 Pi 运行时的路径不在本文件覆盖范围内。

Run directly:
    python backend/tests/test_hyperframes_nodes.py
Or, once pytest is available:
    python -m pytest backend/tests/test_hyperframes_nodes.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.steps.s_hyperframes_cli import CLI_COMMANDS, build_args  # noqa: E402
from backend.utils import hyperframes as hf  # noqa: E402


def assert_raises(exc_type, func, *args, **kwargs):
    """无 pytest 依赖的异常断言。"""
    try:
        func(*args, **kwargs)
    except exc_type:
        return
    except Exception as exc:  # noqa: BLE001 - 报告实际抛出的异常便于定位
        raise AssertionError(f"期望 {exc_type.__name__}，实际抛出 {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"期望 {exc_type.__name__}，但没有抛出异常")


# --------------------------------------------------------------------------- #
# CLI 参数拼装
# --------------------------------------------------------------------------- #
def test_build_cli_command():
    assert hf.build_cli_command(["skills", "update"]) == ["npx", "hyperframes@latest", "skills", "update"]
    assert hf.build_cli_command(["check"], cli="node", package="") == ["node", "check"]
    assert hf.build_cli_command(["check", ""], cli="npx", package="hyperframes") == ["npx", "hyperframes", "check"]


def test_build_args_simple_commands():
    cases = {
        "init": ["init"],
        "skills_check": ["skills", "check"],
        "upgrade": ["upgrade", "--project", "."],
        "render": ["render"],
        "publish": ["publish"],
        "doctor": ["doctor"],
        "preview": ["preview"],
        "lint": ["lint"],
        "validate": ["validate"],
        "check": ["check"],
        "keyframes": ["keyframes"],
    }
    for command, expected in cases.items():
        assert build_args(command, {}) == expected, command


def test_build_args_skills_update_with_names():
    assert build_args("skills_update", {"skill_names": "pr-to-video, figma"}) == [
        "skills", "update", "pr-to-video", "figma",
    ]
    assert build_args("skills_update", {}) == ["skills", "update"]


def test_build_args_add_requires_block():
    assert_raises(ValueError, build_args, "add", {})
    assert build_args("add", {"block": "data-chart"}) == ["add", "data-chart"]


def test_build_args_capture_requires_url():
    assert_raises(ValueError, build_args, "capture", {})
    assert build_args("capture", {"url": "https://example.com"}) == [
        "capture", "https://example.com", "-o", "./capture",
    ]


def test_build_args_custom_and_extra():
    assert build_args("custom", {"custom_args": "skills update figma"}) == ["skills", "update", "figma"]
    assert build_args("check", {"args": "--json"}) == ["check", "--json"]


def test_build_args_unknown_command():
    assert_raises(ValueError, build_args, "nope", {})


def test_every_cli_command_is_buildable():
    payload = {"skill_names": "x", "block": "x", "url": "https://x.dev", "custom_args": "check"}
    for command in CLI_COMMANDS:
        args = build_args(command, payload)
        assert args and all(isinstance(item, str) for item in args), command


# --------------------------------------------------------------------------- #
# BRIEF.md 解析与装载
# --------------------------------------------------------------------------- #
def test_read_brief_route_frontmatter(tmp_path):
    brief = tmp_path / "BRIEF.md"
    brief.write_text(
        "---\nworkflow: product-launch-video\n---\n\n# 简报\n讲清楚产品价值。\n",
        encoding="utf-8",
    )
    assert hf.read_brief_route(brief) == "product-launch-video"


def test_read_brief_route_markdown_row(tmp_path):
    brief = tmp_path / "BRIEF.md"
    brief.write_text("| 项目 | 值 |\n| --- | --- |\n| workflow | `/music-to-video` |\n", encoding="utf-8")
    assert hf.read_brief_route(brief) == "music-to-video"


def test_read_brief_route_plain_mention(tmp_path):
    brief = tmp_path / "BRIEF.md"
    brief.write_text("# 简报\n按 /faceless-explainer 路由执行。\n", encoding="utf-8")
    assert hf.read_brief_route(brief) == "faceless-explainer"


def test_read_brief_route_unknown_or_missing(tmp_path):
    brief = tmp_path / "BRIEF.md"
    brief.write_text("# 简报\n没有写明路由。\n", encoding="utf-8")
    assert hf.read_brief_route(brief) == ""
    assert hf.read_brief_route(tmp_path / "nope.md") == ""


def test_install_brief_into_project(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("workflow: slideshow\n", encoding="utf-8")
    project = tmp_path / "project"
    target = hf.install_brief_into_project(source, project)
    assert target == project / "BRIEF.md"
    assert target.read_text(encoding="utf-8") == "workflow: slideshow\n"
    # 同文件重复装载不应报错
    assert hf.install_brief_into_project(target, project) == target


# --------------------------------------------------------------------------- #
# 验收 JSON 解析
# --------------------------------------------------------------------------- #
def test_parse_done_payload():
    text = f"做完了\n{hf.DONE_MARKER}\n" + json.dumps({"status": "success", "video": "out/a.mp4"})
    assert hf.parse_done_payload(text) == {"status": "success", "video": "out/a.mp4"}


def test_parse_done_payload_missing_marker():
    assert hf.parse_done_payload("没有结束标识") is None
    assert hf.parse_done_payload(f"{hf.DONE_MARKER}\n不是 JSON") is None


def test_require_done_payload_raises_with_tail():
    assert_raises(RuntimeError, hf.require_done_payload, "随便输出了一些内容")


# --------------------------------------------------------------------------- #
# 路径与产物
# --------------------------------------------------------------------------- #
def test_resolve_project_dir_defaults_to_cache(tmp_path):
    path = hf.resolve_project_dir(str(tmp_path), {}, "n1")
    assert path == (tmp_path / "cache" / "hyperframes_n1").resolve()
    assert path.is_dir()


def test_resolve_project_dir_honours_config(tmp_path):
    path = hf.resolve_project_dir(str(tmp_path), {"project_dir": "my/video"}, "n1", create=False)
    assert path == (tmp_path / "my" / "video").resolve()

    absolute = str(tmp_path / "abs")
    assert hf.resolve_project_dir(str(tmp_path), {"project_dir": absolute}, "n1") == Path(absolute).resolve()


def test_first_value_handles_lists():
    assert hf.first_value(["a", "b"]) == "a"
    assert hf.first_value([]) == ""
    assert hf.first_value(None) == ""
    assert hf.first_value(["", "b"]) == "b"


def test_locate_render_output_prefers_configured(tmp_path):
    (tmp_path / "out").mkdir()
    configured = tmp_path / "out" / "final.mp4"
    configured.write_bytes(b"0")
    assert hf.locate_render_output(tmp_path, "out/final.mp4") == configured.resolve()


def test_locate_render_output_picks_newest(tmp_path):
    (tmp_path / "dist").mkdir()
    older = tmp_path / "dist" / "old.mp4"
    newer = tmp_path / "dist" / "new.mp4"
    older.write_bytes(b"0")
    newer.write_bytes(b"0")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    assert hf.locate_render_output(tmp_path) == newer.resolve()


def test_locate_render_output_returns_none(tmp_path):
    assert hf.locate_render_output(tmp_path) is None


# --------------------------------------------------------------------------- #
# 技能目录
# --------------------------------------------------------------------------- #
def test_skill_dir_contains_entry_and_routes():
    assert hf.skill_dir().is_dir()
    assert hf.skill_entry().is_file()
    assert hf.route_reference("pr-to-video").is_file()
    assert hf.route_reference("not-a-route") is None


def test_every_route_has_reference():
    for route in hf.WORKFLOW_ROUTES:
        assert hf.route_reference(route).is_file(), route


# --------------------------------------------------------------------------- #
# 提示词拼装
# --------------------------------------------------------------------------- #
def test_prompts_mention_skill_entry_and_marker(tmp_path):
    creative = hf.build_creative_prompt(
        project_dir=tmp_path, route="pr-to-video", subject="讲这个 PR",
        run_mode="autonomous", style_preset="", aspect="16:9", language="zh",
        materials={"source": "https://github.com/a/b/pull/1"},
    )
    assert str(tmp_path) in creative
    assert "pr-to-video" in creative
    assert hf.DONE_MARKER in creative

    brief = tmp_path / "BRIEF.md"
    brief.write_text("# 简报\n", encoding="utf-8")
    render = hf.build_render_prompt(
        project_dir=tmp_path, brief_path=brief, route="pr-to-video",
        stage="build_and_render", output_name="out.mp4", publish=True,
    )
    assert str(brief) in render
    assert "out.mp4" in render
    assert hf.DONE_MARKER in render


# --------------------------------------------------------------------------- #
# 创意节点：加载已有简报（不调用大模型）
# --------------------------------------------------------------------------- #
def _creative_step():
    from backend.steps.s_hyperframes_creative import S_HyperFramesCreative

    step = S_HyperFramesCreative()
    step._node_id = "unit"
    return step


def test_creative_load_mode_reuses_existing_brief(tmp_path):
    task_dir = tmp_path / "task"
    (task_dir / "cache").mkdir(parents=True)
    brief_source = tmp_path / "BRIEF.md"
    brief_source.write_text("---\nworkflow: pr-to-video\n---\n\n# 简报\n讲这个 PR。\n", encoding="utf-8")

    step = _creative_step()
    step._node_config = {"mode": "load", "brief_path": str(brief_source), "project_dir": ""}
    step._step_inputs = {}

    result = step.run(str(task_dir))
    outputs = result["outputs"]

    project_dir = task_dir / "cache" / "hyperframes_unit"
    assert (project_dir / "BRIEF.md").is_file()
    assert Path(task_dir / outputs["brief"]).is_file()
    assert outputs["project_dir"] == "cache/hyperframes_unit"
    assert "pr-to-video" in outputs["summary"]

    payload = json.loads((task_dir / "cache" / "hyperframes_brief_unit.json").read_text(encoding="utf-8"))
    assert payload["workflow"] == "pr-to-video"
    assert step.check_artifact(str(task_dir)) is True


def test_creative_load_mode_reads_brief_from_input_port(tmp_path):
    task_dir = tmp_path / "task"
    (task_dir / "cache").mkdir(parents=True)
    brief_source = tmp_path / "BRIEF.md"
    brief_source.write_text("workflow: motion-graphics\n", encoding="utf-8")

    step = _creative_step()
    step._node_config = {"mode": "load", "project_dir": ""}
    step._step_inputs = {"brief": str(brief_source)}

    outputs = step.run(str(task_dir))["outputs"]
    assert "motion-graphics" in outputs["summary"]


def test_creative_load_mode_without_brief_raises(tmp_path):
    task_dir = tmp_path / "task"
    (task_dir / "cache").mkdir(parents=True)

    step = _creative_step()
    step._node_config = {"mode": "load", "project_dir": ""}
    step._step_inputs = {}

    assert_raises(FileNotFoundError, step.run, str(task_dir))


def test_creative_validate_inputs(tmp_path):
    step = _creative_step()

    step._node_config = {"mode": "load"}
    step._step_inputs = {}
    assert step.validate_inputs(str(tmp_path)) is True

    step._node_config = {"mode": "create", "subject": ""}
    assert step.validate_inputs(str(tmp_path)) is False

    step._node_config = {"mode": "create", "subject": "讲一下 DNS"}
    assert step.validate_inputs(str(tmp_path)) is True


# --------------------------------------------------------------------------- #
# 渲染 / 工具 / 智能体节点的前置校验
# --------------------------------------------------------------------------- #
def test_render_requires_brief(tmp_path):
    from backend.steps.s_hyperframes_render import S_HyperFramesRender

    step = S_HyperFramesRender()
    step._node_id = "unit"
    step._node_config = {"project_dir": ""}
    step._step_inputs = {}

    assert step.validate_inputs(str(tmp_path)) is False
    assert_raises(FileNotFoundError, step.run, str(tmp_path))


def test_cli_rejects_unknown_command(tmp_path):
    from backend.steps.s_hyperframes_cli import S_HyperFramesCli

    step = S_HyperFramesCli()
    step._node_id = "unit"
    step._node_config = {"command": "nope", "project_dir": ""}
    step._step_inputs = {}

    assert step.validate_inputs(str(tmp_path)) is False
    assert_raises(ValueError, step.run, str(tmp_path))


def test_agent_rejects_unknown_span(tmp_path):
    from backend.steps.s_hyperframes_agent import S_HyperFramesAgent

    step = S_HyperFramesAgent()
    step._node_id = "unit"
    step._node_config = {"span": "nope", "project_dir": ""}
    step._step_inputs = {}

    assert_raises(ValueError, step.run, str(tmp_path))


# --------------------------------------------------------------------------- #
# 注册
# --------------------------------------------------------------------------- #
def test_builtin_node_types_define_hyperframes_group():
    from backend.config.builtin_node_types import BUILTIN_NODE_TYPES

    nodes = {node["id"]: node for node in BUILTIN_NODE_TYPES if node.get("category") == "hyperframes"}
    assert set(nodes) == {
        "hyperframes_creative", "hyperframes_render", "hyperframes_cli", "hyperframes_agent",
    }
    for node in nodes.values():
        assert node["name"] and node["description"]
        # 端口 id 在同侧不重复且三要素齐全（输入/输出允许同名，与既有节点一致）
        for side in ("inputs", "outputs"):
            ids = [port["id"] for port in node[side]]
            assert len(ids) == len(set(ids)), f"{node['id']}: {side} 端口 id 重复"
            for port in node[side]:
                assert port["id"] and port["label"] and port["type"]
        # 每个默认值都要有对应的设置项；dependsOn 必须指向已声明的字段
        keys = [field["key"] for field in node["configFields"]]
        assert len(keys) == len(set(keys)), f"{node['id']}: 设置项 key 重复"
        for key in node["defaultConfig"]:
            assert key in keys, f"{node['id']}: 默认值 {key} 缺少对应设置项"
        for field in node["configFields"]:
            if field.get("dependsOn"):
                assert field["dependsOn"] in keys, f"{node['id']}: dependsOn 指向未声明的字段"


def test_hyperframes_category_is_allowed():
    from backend.config.node_schema import ALLOWED_NODE_CATEGORIES

    assert "hyperframes" in ALLOWED_NODE_CATEGORIES


def test_steps_registered():
    try:
        from backend.steps.step_registry import get_step_instance
    except Exception as exc:  # pragma: no cover - 依赖缺失时跳过
        print(f"  [SKIP] step_registry 导入失败：{exc}")
        return

    for node_id in ("hyperframes_creative", "hyperframes_render", "hyperframes_cli", "hyperframes_agent"):
        assert get_step_instance(node_id) is not None, node_id
        assert get_step_instance(f"s_{node_id}") is not None, node_id


# --------------------------------------------------------------------------- #
# 直接运行入口
# --------------------------------------------------------------------------- #
def _run_all():
    tmp_root = Path(tempfile.mkdtemp(prefix="hf-nodes-test-"))
    with_tmp = [
        test_read_brief_route_frontmatter, test_read_brief_route_markdown_row,
        test_read_brief_route_plain_mention, test_read_brief_route_unknown_or_missing,
        test_install_brief_into_project, test_resolve_project_dir_defaults_to_cache,
        test_resolve_project_dir_honours_config, test_locate_render_output_prefers_configured,
        test_locate_render_output_picks_newest, test_locate_render_output_returns_none,
        test_prompts_mention_skill_entry_and_marker, test_creative_load_mode_reuses_existing_brief,
        test_creative_load_mode_reads_brief_from_input_port, test_creative_load_mode_without_brief_raises,
        test_creative_validate_inputs, test_render_requires_brief, test_cli_rejects_unknown_command,
        test_agent_rejects_unknown_span,
    ]
    without_tmp = [
        test_build_cli_command, test_build_args_simple_commands,
        test_build_args_skills_update_with_names, test_build_args_add_requires_block,
        test_build_args_capture_requires_url, test_build_args_custom_and_extra,
        test_build_args_unknown_command, test_every_cli_command_is_buildable,
        test_parse_done_payload, test_parse_done_payload_missing_marker,
        test_require_done_payload_raises_with_tail, test_first_value_handles_lists,
        test_skill_dir_contains_entry_and_routes, test_every_route_has_reference,
        test_builtin_node_types_define_hyperframes_group, test_hyperframes_category_is_allowed,
        test_steps_registered,
    ]
    try:
        for index, func in enumerate(without_tmp, start=1):
            print(f"[{index:02d}] {func.__name__}")
            func()
        for index, func in enumerate(with_tmp, start=len(without_tmp) + 1):
            print(f"[{index:02d}] {func.__name__}")
            case_dir = tmp_root / func.__name__
            case_dir.mkdir(parents=True, exist_ok=True)
            func(case_dir)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    print(f"\nAll tests passed. ({len(without_tmp) + len(with_tmp)} cases)")


if __name__ == "__main__":
    _run_all()
