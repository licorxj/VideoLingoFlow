"""图片宫格切割节点（s_image_grid_split）的单元测试。

只覆盖不依赖外部服务的纯切割逻辑：宫格数量、外框/内部收缩像素、
格式保持、产物命名与结果 JSON。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image  # noqa: E402

from backend.steps.s_image_grid_split import S_ImageGridSplit  # noqa: E402


def _step(node_id: str = "unit") -> S_ImageGridSplit:
    step = S_ImageGridSplit()
    step._node_id = node_id
    return step


def _make_image(tmp_path: Path, size=(300, 200), ext=".png") -> Path:
    path = tmp_path / f"src{ext}"
    Image.new("RGB", size, (255, 0, 0)).save(path)
    return path


def _run(tmp_path: Path, config: dict, src: Path, node_id: str = "unit") -> dict:
    task_dir = tmp_path / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    step = _step(node_id)
    step._node_config = config
    step._step_inputs = {"image": str(src)}
    return step.run(str(task_dir))


# --------------------------------------------------------------------------- #
# 基本切割
# --------------------------------------------------------------------------- #
def test_split_4_grid_default_shrink(tmp_path):
    src = _make_image(tmp_path, (300, 200))
    result = _run(tmp_path, {"grid": "4", "outer_shrink": 0, "inner_shrink": 5}, src)

    files = result["outputs"]["images"]
    assert len(files) == 4
    # 行优先命名 01..04，扩展名与输入一致
    assert [Path(f).name for f in files] == ["01.png", "02.png", "03.png", "04.png"]
    out_dir = tmp_path / "task" / "cache" / "image_grid_unit"
    for f in files:
        assert (tmp_path / "task" / f).is_file()
    # 内部切缝两侧各收 5px：300/2=150、200/2=100 → 每块 145x95
    sizes = {Image.open(out_dir / name).size for name in ("01.png", "02.png", "03.png", "04.png")}
    assert sizes == {(145, 95)}
    # 角块外侧不收缩：01 左上角仍贴 (0,0)，02 右下角贴 (300,200)
    assert Image.open(out_dir / "01.png").getpixel((0, 0)) is not None


def test_split_9_grid_no_shrink(tmp_path):
    src = _make_image(tmp_path, (300, 300))
    result = _run(tmp_path, {"grid": "9", "outer_shrink": 0, "inner_shrink": 0}, src)
    files = result["outputs"]["images"]
    assert len(files) == 9
    out_dir = tmp_path / "task" / "cache" / "image_grid_unit"
    assert {Image.open(out_dir / f"{i:02d}.png").size for i in range(1, 10)} == {(100, 100)}


def test_outer_shrink_crops_border(tmp_path):
    src = _make_image(tmp_path, (300, 200))
    _run(tmp_path, {"grid": "4", "outer_shrink": 10, "inner_shrink": 0}, src)
    out_dir = tmp_path / "task" / "cache" / "image_grid_unit"
    # 外框收缩后 280x180 → 每块 140x90
    assert Image.open(out_dir / "01.png").size == (140, 90)


def test_format_preserved_jpg(tmp_path):
    src = _make_image(tmp_path, (200, 200), ext=".jpg")
    result = _run(tmp_path, {"grid": "4", "outer_shrink": 0, "inner_shrink": 0}, src)
    assert all(f.endswith(".jpg") for f in result["outputs"]["images"])
    out_dir = tmp_path / "task" / "cache" / "image_grid_unit"
    assert Image.open(out_dir / "01.jpg").format == "JPEG"


# --------------------------------------------------------------------------- #
# 产物检测 / 清理 / 校验
# --------------------------------------------------------------------------- #
def test_check_artifact_and_rollback(tmp_path):
    src = _make_image(tmp_path, (300, 200))
    _run(tmp_path, {"grid": "4", "outer_shrink": 0, "inner_shrink": 5}, src)
    task_dir = str(tmp_path / "task")

    step = _step()
    assert step.check_artifact(task_dir) is True
    assert step.validate_inputs(task_dir) is False  # 未注入 _step_inputs

    step.rollback(task_dir)
    assert step.check_artifact(task_dir) is False
    assert not (tmp_path / "task" / "cache" / "image_grid_unit").exists()


def test_result_json_payload(tmp_path):
    src = _make_image(tmp_path, (300, 200))
    _run(tmp_path, {"grid": "4", "outer_shrink": 0, "inner_shrink": 5}, src)
    payload = json.loads(
        (tmp_path / "task" / "cache" / "image_grid_unit.json").read_text(encoding="utf-8")
    )
    assert payload["grid"] == 4
    assert payload["count"] == 4
    assert payload["size"] == [300, 200]
    assert payload["source"].endswith("src.png")


# --------------------------------------------------------------------------- #
# 异常路径
# --------------------------------------------------------------------------- #
def test_invalid_grid_raises(tmp_path):
    src = _make_image(tmp_path, (300, 200))
    try:
        _run(tmp_path, {"grid": "6", "outer_shrink": 0, "inner_shrink": 0}, src)
        assert False, "should raise"
    except ValueError as exc:
        assert "宫格" in str(exc)


def test_missing_image_raises(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir(parents=True)
    step = _step()
    step._node_config = {"grid": "4", "outer_shrink": 0, "inner_shrink": 5}
    step._step_inputs = {}
    try:
        step.run(str(task_dir))
        assert False, "should raise"
    except FileNotFoundError:
        pass


def test_oversize_inner_shrink_raises(tmp_path):
    src = _make_image(tmp_path, (20, 20))
    try:
        _run(tmp_path, {"grid": "4", "outer_shrink": 0, "inner_shrink": 15}, src)
        assert False, "should raise"
    except RuntimeError as exc:
        assert "收缩" in str(exc)


# --------------------------------------------------------------------------- #
# 注册
# --------------------------------------------------------------------------- #
def test_node_definition_and_registry(tmp_path=None):
    from backend.config.builtin_node_types import BUILTIN_NODE_TYPES
    from backend.steps.step_registry import get_step_instance

    node = next(n for n in BUILTIN_NODE_TYPES if n["id"] == "image_grid_split")
    assert node["category"] == "aigc"
    keys = {f["key"] for f in node["configFields"]}
    assert keys == {"grid", "outer_shrink", "inner_shrink"}
    assert set(node["defaultConfig"]) == keys
    assert [o["type"] for o in node["outputs"]] == ["list"]

    assert get_step_instance("image_grid_split") is not None
    assert get_step_instance("s_image_grid_split") is not None


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in funcs:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))
        print(f"  [OK] {fn.__name__}")
    print(f"\nAll {len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
