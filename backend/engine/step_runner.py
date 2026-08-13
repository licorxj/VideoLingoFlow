"""Run a workflow step in a separate process (process isolation for heavy ML steps).

重型节点（ASR、音轨分离等）会在同一进程内加载模型并推理，长时间占用 GIL，
导致单进程 uvicorn 的事件循环线程被饿死，前端无法与后端通信。
本模块把这些步骤放到独立子进程中执行，从而彻底隔离。

Usage:
    python -m backend.engine.step_runner <ctx_json_path>

ctx.json fields:
    task_dir     : str  任务目录
    nid          : str  节点 id
    module       : str  步骤模块（如 backend.steps.s02_asr）
    class        : str  步骤类名（如 S02ASR）
    node_config  : dict 节点配置
    step_inputs  : dict 步骤输入
    output_file  : str  结果 JSON 写入路径
    cancel_file  : str  取消标记文件路径

Protocol:
- 进度：stdout 输出 `PROGRESS <json>` 行，json 为 {"p": int, "m": str}。
- 结果：写入 ctx["output_file"]，格式为
    {"ok": true,  "result": {...}}  或
    {"ok": false, "error": "..."}
- 取消：cancel_callback() 轮询 cancel_file 是否存在。
"""
import json
import os
import sys


def main():
    ctx_path = sys.argv[1]
    with open(ctx_path, "r", encoding="utf-8") as f:
        ctx = json.load(f)

    task_dir = ctx["task_dir"]
    nid = ctx["nid"]
    cancel_file = ctx["cancel_file"]
    output_file = ctx["output_file"]

    # 确保 backend 包可导入（项目根目录）
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    def callback(pct, message):
        print("PROGRESS " + json.dumps({"p": pct, "m": message}, ensure_ascii=False), flush=True)

    def cancel_callback():
        return os.path.exists(cancel_file)

    try:
        import importlib
        import inspect

        mod = importlib.import_module(ctx["module"])
        cls = getattr(mod, ctx["class"])
        step = cls()
        step._node_id = nid
        step._node_config = ctx.get("node_config", {}) or {}
        step._step_inputs = ctx.get("step_inputs", {}) or {}

        sig = inspect.signature(step.run)
        run_kwargs = {"callback": callback}
        if "cancel_callback" in sig.parameters:
            run_kwargs["cancel_callback"] = cancel_callback

        step_result = step.run(task_dir, **run_kwargs)
        if not isinstance(step_result, dict):
            step_result = {}
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "result": step_result}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump({"ok": False, "error": f"{type(e).__name__}: {e}"}, f, ensure_ascii=False)
        except Exception:
            pass
        print(f"[step_runner] ERROR: {e}", flush=True)
        raise


if __name__ == "__main__":
    main()
