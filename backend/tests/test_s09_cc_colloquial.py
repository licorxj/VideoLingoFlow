"""TTS 节点（s09_tts）指令克隆「口语化描述」的单元测试。

只覆盖不依赖外部环境的纯逻辑：``_parse_tts_config`` 读取新配置项，
以及 ``_build_voice_design_instruction`` 的 controllable_clone 分支前拼规则。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.steps.s09_tts import S09TTS  # noqa: E402


def _step() -> S09TTS:
    return S09TTS()


# --------------------------------------------------------------------------- #
# 配置解析
# --------------------------------------------------------------------------- #
def test_parse_tts_config_reads_colloquial_desc():
    step = _step()
    step._node_config = {"cc_colloquial_desc": "  用四川话说  "}
    cfg = step._parse_tts_config()
    assert cfg["cc_colloquial_desc"] == "用四川话说"


def test_parse_tts_config_defaults_to_empty():
    step = _step()
    step._node_config = {}
    cfg = step._parse_tts_config()
    assert cfg["cc_colloquial_desc"] == ""


# --------------------------------------------------------------------------- #
# controllable_clone 指令组装
# --------------------------------------------------------------------------- #
def _clone_cfg(desc: str) -> dict:
    return {"mode": "controllable_clone", "cc_colloquial_desc": desc}


def test_cc_prepends_colloquial_with_comma():
    step = _step()
    seg = {"read_tone_desc": "低沉沙哑"}
    assert step._build_voice_design_instruction(seg, _clone_cfg("用四川话说")) == "用四川话说，低沉沙哑"


def test_cc_desc_only_no_trailing_comma():
    step = _step()
    assert step._build_voice_design_instruction({}, _clone_cfg("用四川话说")) == "用四川话说"


def test_cc_tone_only_unchanged():
    step = _step()
    assert step._build_voice_design_instruction({"read_tone_desc": "低沉沙哑"}, _clone_cfg("")) == "低沉沙哑"


def test_cc_both_empty():
    step = _step()
    assert step._build_voice_design_instruction({}, _clone_cfg("")) == ""


def test_cc_whitespace_desc_treated_as_empty():
    step = _step()
    assert step._build_voice_design_instruction({"read_tone_desc": "温柔"}, _clone_cfg("   ")) == "温柔"


# --------------------------------------------------------------------------- #
# voice_design 模式不受影响
# --------------------------------------------------------------------------- #
def test_voice_design_mode_ignores_colloquial_desc():
    step = _step()
    seg = {"read_tone_desc": "低沉沙哑", "read_character_id": 0}
    cfg = {"mode": "voice_design", "voice_design_roles": ["低沉男声"], "cc_colloquial_desc": "用四川话说"}
    assert step._build_voice_design_instruction(seg, cfg) == "低沉男声，低沉沙哑"


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in funcs:
        fn()
        print(f"  [OK] {fn.__name__}")
    print(f"\nAll {len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
