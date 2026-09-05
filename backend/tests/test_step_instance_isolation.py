"""Regression tests for step-instance isolation under concurrent node execution.

背景：worker 以线程池同进程并行执行多个批量任务，而注册表 ``_STEPS`` 中的步骤是
进程级单例。``_run_node`` 执行前会把 ``_node_id`` / ``_node_config`` / ``_step_inputs``
写到步骤实例上，部分步骤（text_editor / subtitle_gen / dub_task / sentence_split 等）
还会在 run 中途回读这些属性——两个任务并发跑同一节点类型时共用单例会互相覆盖任务态，
导致配置/输入串台、产物污染。

修复约定：线程域节点每次执行必须持独立实例（``new_step_instance``）。

覆盖点：
  * ``new_step_instance`` 对所有注册节点类型都返回独立实例，注入任务态不泄漏到单例；
  * 未知节点类型返回 None；构造失败回退单例（退化契约）；
  * 共享同一实例的旧模式在并发注入下必然互相污染（文档化缺陷）；
  * 每次执行持独立实例时，并发执行同一节点类型各自读到自己的任务态，产物互不污染。

Run directly:
    python backend/tests/test_step_instance_isolation.py
Or, once pytest is available:
    python -m pytest backend/tests/test_step_instance_isolation.py
"""
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

# Allow running directly from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.steps.step_registry import (  # noqa: E402
    _STEPS,
    get_step_instance,
    new_step_instance,
)

# 产物污染高发的线程域节点类型（修复前会共用单例互相覆盖）
CORE_THREAD_TYPES = [
    "sentence_split",
    "subtitle_gen",
    "dub_task",
    "asr_result_validate",
    "sentence_preprocess",
    "text_editor",
    "json_editor",
    "llm_request",
]


def test_new_step_instance_returns_independent_instance_for_every_registered_type():
    """所有注册节点类型：新实例 ≠ 注册表单例，且互相独立。"""
    for step_id in _STEPS:
        singleton = get_step_instance(step_id)
        fresh = new_step_instance(step_id)
        assert fresh is not None, f"new_step_instance({step_id!r}) 返回 None"
        assert fresh is not singleton, (
            f"节点 {step_id!r} 构造失败回退到了单例："
            f"{type(singleton).__name__} 必须支持零参构造（见 step_registry.new_step_instance docstring）"
        )


def test_injected_state_does_not_leak_to_singleton():
    """在独立实例上注入任务态，注册表单例不受影响。"""
    for step_id in CORE_THREAD_TYPES:
        sentinel_cfg = {"__sentinel__": True}
        sentinel_inputs = {"__sentinel__": True}
        singleton = get_step_instance(step_id)
        old_cfg = getattr(singleton, "_node_config", None)
        old_inputs = getattr(singleton, "_step_inputs", None)
        try:
            singleton._node_config = sentinel_cfg
            singleton._step_inputs = sentinel_inputs

            fresh = new_step_instance(step_id)
            fresh._node_id = "node_fresh"
            fresh._node_config = {"key": "task-A"}
            fresh._step_inputs = {"text": "task-A"}

            assert getattr(singleton, "_node_id", None) != "node_fresh"
            assert singleton._node_config is sentinel_cfg
            assert singleton._step_inputs is sentinel_inputs
        finally:
            if old_cfg is None:
                singleton.__dict__.pop("_node_config", None)
            else:
                singleton._node_config = old_cfg
            if old_inputs is None:
                singleton.__dict__.pop("_step_inputs", None)
            else:
                singleton._step_inputs = old_inputs


def test_unknown_type_returns_none():
    assert new_step_instance("no_such_step_type") is None


def test_construction_failure_falls_back_to_singleton():
    """构造失败时回退单例（退化为不隔离但不报错）——锁定 new_step_instance 的契约。"""

    class _Broken:
        def __init__(self):
            raise RuntimeError("not zero-arg constructible")

    # object.__new__ 绕过 __init__ 拿到实例，模拟"注册表里存在一个无法零参重建的实例"
    broken_instance = object.__new__(_Broken)
    _STEPS["__test_broken__"] = broken_instance
    try:
        assert new_step_instance("__test_broken__") is broken_instance
    finally:
        _STEPS.pop("__test_broken__", None)


def test_shared_instance_cross_contaminates():
    """文档化旧模式的缺陷：多个执行共享同一实例时，后注入者覆盖先注入者，
    两次执行读到相同的任务态（即用户看到的"产物互相污染"）。"""

    class _Step:
        def run(self, task_dir, callback=None):
            # 模拟步骤 run 开头回读注入态
            return {
                "cfg": getattr(self, "_node_config", {}),
                "inputs": getattr(self, "_step_inputs", {}),
            }

    shared = _Step()
    barrier = threading.Barrier(2)
    results = {}

    def worker(tag):
        shared._node_config = {"owner": tag}
        shared._step_inputs = {"text": tag}
        barrier.wait(timeout=5)  # 确保两次注入都完成后才开始执行
        results[tag] = shared.run("unused")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, ["A", "B"]))

    assert results["A"] == results["B"], "共享实例未被覆盖，说明 Barrier 语义失效"


def test_concurrent_execution_with_fresh_instances_is_isolated():
    """并发执行同一节点类型（真实线程域步骤 S_TextEditor）：每次执行持独立实例，
    各任务读到自己的 _node_config/_step_inputs，产物互不污染。"""
    n_tasks = 8
    barrier = threading.Barrier(n_tasks)
    with tempfile.TemporaryDirectory(prefix="step_iso_") as tmp_root:
        task_dirs = [os.path.join(tmp_root, f"task_{i}") for i in range(n_tasks)]

        def worker(i: int) -> None:
            task_dir = task_dirs[i]
            os.makedirs(task_dir, exist_ok=True)
            # 复刻 _run_node 的执行方式：独立实例 + 注入任务态
            step = new_step_instance("text_editor")
            assert step is not get_step_instance("text_editor")
            step._node_id = f"text_edit_task{i}"
            step._node_config = {"edited_text": f"edited-by-task-{i}", "enable_copy": True}
            step._step_inputs = {"text": f"raw-text-of-task-{i}"}
            barrier.wait(timeout=30)  # 全部注入完成后同时执行，最大化交错
            result = step.run(task_dir)
            out_rel = result["outputs"]["text"]
            with open(os.path.join(task_dir, out_rel.replace("/", os.sep)), "r", encoding="utf-8") as f:
                content = f.read()

            assert content == f"edited-by-task-{i}", (
                f"task_{i} 读到了别的任务的配置（产物污染）：{content!r}"
            )

        with ThreadPoolExecutor(max_workers=n_tasks) as pool:
            list(pool.map(worker, range(n_tasks)))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = []
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed.append((fn.__name__, exc))
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        sys.exit(1)
    print(f"\n{len(fns)} tests passed")
