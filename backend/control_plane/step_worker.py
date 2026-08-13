"""step_worker: 在独立子进程中执行单个节点步骤（方案 C 的子进程隔离）。

父线程（workflow_runtime._run_node_subprocess）通过以下方式调用：
    python -m backend.control_plane.step_worker <args.json>

args.json 内容：
    {
        "task_dir": str,       # 工作区绝对路径（产物读写目录）
        "node_type": str,      # 节点类型 id
        "node_id": str,        # 节点唯一 id
        "node_config": dict,   # 节点 data.config
        "step_inputs": dict,   # _resolve_step_inputs 产出的连线输入
        "result_path": str,    # 结果 pickle 回传路径
        "cancel_file": str,    # 取消标记文件（存在则协作取消）
    }

进度上报：步骤 callback 写 stdout 行 ``@PROGRESS@|<percent>|<message>``，父线程逐行解析。
协作取消：callback 检查 cancel_file 存在则抛 TaskCancelledError；阻塞不回调的步骤由父线程 kill 进程树兜底。
结果回传：step.run 返回 dict 以 pickle 写入 result_path；异常打印 traceback 到 stderr 并退出码 1。
"""
import json
import os
import pickle
import sys
import traceback


# 子进程 stdout 统一 UTF-8，保证进度中文不乱码（父线程按 UTF-8 解析行协议）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load_args(argv: list[str]) -> dict:
    with open(argv[1], "r", encoding="utf-8") as f:
        return json.load(f)


def _progress_callback(args: dict, percent, message) -> None:
    # 协作取消：取消标记文件存在即中断（由父线程在 request_cancel 时创建）
    if args.get("cancel_file") and os.path.exists(args["cancel_file"]):
        from backend.control_plane.runtime import TaskCancelledError
        raise TaskCancelledError("user_requested")
    msg = str(message or "").replace("\n", " ").replace("\r", " ")
    try:
        sys.stdout.write(f"@PROGRESS@|{int(percent)}|{msg}\n")
        sys.stdout.flush()
    except Exception:
        pass


def main(argv: list[str]) -> int:
    args = _load_args(argv)
    task_dir = args["task_dir"]
    node_type = args["node_type"]
    node_id = args["node_id"]
    result_path = args["result_path"]

    from backend.steps.step_registry import get_step_instance

    step = get_step_instance(node_type)
    if step is None:
        raise ValueError(f"未知工作流节点: {node_type}")
    step._node_id = node_id
    step._node_config = args.get("node_config", {}) or {}
    step._step_inputs = args.get("step_inputs", {}) or {}

    def callback(percent, message):
        _progress_callback(args, percent, message)

    result = step.run(task_dir, callback=callback)
    with open(result_path, "wb") as f:
        pickle.dump(result or {}, f)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
