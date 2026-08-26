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
        "result_path": str,    # 结果 JSON 回传路径（.json）
        "cancel_file": str,    # 取消标记文件（存在则协作取消）
    }

进度上报：步骤 callback 写 stdout 行 ``@PROGRESS@|<percent>|<message>``，父线程逐行解析。
协作取消：callback 检查 cancel_file 存在则抛 TaskCancelledError；阻塞不回调的步骤由父线程 kill 进程树兜底。
结果回传：step.run 返回 dict 以 JSON 写入 result_path（跨版本安全、无反序列化风险）；
          异常打印 traceback 到 stderr 并退出码 1。
"""
import json
import os
import sys
import traceback

# ── 最早期启动标记（在任何导入之前，确保父进程能看到子进程已启动）──
try:
    sys.stdout.write(f"[step_worker] BOOT pid={os.getpid()} argv={sys.argv}\n")
    sys.stdout.flush()
except Exception:
    pass

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


def _emit_log(message: str) -> None:
    """把普通日志行转发给父进程（@LOG@ 前缀），父线程会写入任务事件流。"""
    try:
        msg = str(message or "").replace("\n", " ").replace("\r", " ")
        sys.stdout.write(f"@LOG@|{msg}\n")
        sys.stdout.flush()
    except Exception:
        pass


class _LogForwardingStdout:
    """包装 stdout：@PROGRESS@ 行原样透传，其他行用 @LOG@ 前缀转发给父进程。

    这样步骤内部的 print() 调试输出也能在父线程/任务事件流中看到，
    对排查"无限等待"类问题至关重要。
    """

    def __init__(self, original):
        self._original = original
        self._buf = ""

    def write(self, data: str):
        if not data:
            return 0
        self._buf += data
        out_parts = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.startswith("@PROGRESS@|") or line.startswith("@LOG@|"):
                out_parts.append(line + "\n")
            elif line.strip():
                out_parts.append(f"@LOG@|{line}\n")
            else:
                out_parts.append("\n")
        return self._original.write("".join(out_parts))

    def flush(self):
        return self._original.flush()

    def reconfigure(self, *args, **kwargs):
        return self._original.reconfigure(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._original, name)


def main(argv: list[str]) -> int:
    args = _load_args(argv)
    task_dir = args["task_dir"]
    node_type = args["node_type"]
    node_id = args["node_id"]
    result_path = args["result_path"]

    # 安装 stdout 日志转发：步骤内部所有 print() 输出都会以 @LOG@ 前缀回传父进程
    sys.stdout = _LogForwardingStdout(sys.stdout)  # type: ignore[assignment]

    print(f"[step_worker] start node_type={node_type} node_id={node_id} pid={os.getpid()}")

    from backend.steps.step_registry import get_step_instance

    step = get_step_instance(node_type)
    if step is None:
        raise ValueError(f"未知工作流节点: {node_type}")
    print(f"[step_worker] step instance created: {type(step).__name__}")
    step._node_id = node_id
    step._node_config = args.get("node_config", {}) or {}
    step._step_inputs = args.get("step_inputs", {}) or {}
    print(f"[step_worker] step_inputs keys={list(step._step_inputs.keys())}")
    print(f"[step_worker] node_config keys={list(step._node_config.keys()) if step._node_config else '(empty)'}")

    def callback(percent, message):
        _progress_callback(args, percent, message)

    def cancel_callback():
        return bool(args.get("cancel_file") and os.path.exists(args["cancel_file"]))

    import inspect
    sig = inspect.signature(step.run)
    run_kwargs = {"callback": callback}
    # 忠实传递 cancel_callback：步骤签名声明了该参数才传入，避免不支持取消的步骤报错
    if "cancel_callback" in sig.parameters:
        run_kwargs["cancel_callback"] = cancel_callback

    print(f"[step_worker] calling step.run(task_dir={task_dir}, kwargs={list(run_kwargs.keys())})")
    result = step.run(task_dir, **run_kwargs)
    print(f"[step_worker] step.run returned, result keys={list((result or {}).keys())}")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result or {}, f, ensure_ascii=False, default=str)
    print(f"[step_worker] result written to {result_path}, exiting 0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
