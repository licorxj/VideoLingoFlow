from abc import ABC, abstractmethod
from typing import Callable, Optional


def find_artifact(directory: str, base_name: str) -> Optional[str]:
    """按基础名在目录中匹配产物文件（忽略节点 id 后缀）。

    约定：步骤输出文件名为 ``{base}_{node_id}{ext}``（如 asr_result_abc123.json）。
    匹配时忽略 ``_<node_id>`` 部分：`asr_result_abc123.json` 可匹配 `asr_result.json`。
    匹配到多个时返回排序后的第一个（无 node_id 后缀的优先）。返回绝对路径，无匹配返回 None。
    """
    import os
    if not os.path.isdir(directory):
        return None
    base, ext = os.path.splitext(base_name)
    candidates = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(ext):
            continue
        stem = name[: -len(ext)] if ext else name
        if stem == base or stem.startswith(base + "_"):
            candidates.append(os.path.join(directory, name))
    return candidates[0] if candidates else None


def step_check_cancel(cancel_callback: Optional[Callable]) -> None:
    """协作取消检查点：thread 域步骤在批处理迭代边界主动查询取消。

    thread 域步骤跑在 worker 线程内、无法被强杀，只能靠步骤主动查询取消状态退出。
    框架已在每次 callback() 时检查取消（``_run_node`` 的 progress 闭包 /
    step_worker 的行协议回调），本检查点覆盖「两次 callback 之间的长耗时引擎
    调用」间隙：命中后抛 ``TaskCancelledError``，不再启动下一轮迭代；已启动的
    引擎调用返回后由 callback 抛出终止。

    ``cancel_callback`` 为 None（步骤未声明该参数 / 框架未注入）时静默跳过；
    探针自身异常不冒充取消、不中断主流程。
    """
    if cancel_callback is None:
        return
    try:
        cancelled = bool(cancel_callback())
    except Exception:  # noqa: BLE001 - 检查点自身异常不应中断主流程
        return
    if cancelled:
        from backend.control_plane.runtime import TaskCancelledError

        raise TaskCancelledError("user_requested")


class BaseStep(ABC):
    """Abstract base class for pipeline steps. Each step has fixed inputs, outputs, and artifacts."""

    step_id: str = ""
    step_name: str = ""
    dependencies: list = []
    artifacts: list = []  # files this step produces (relative to task_dir)

    @abstractmethod
    def check_artifact(self, task_dir: str) -> bool:
        """Check if all output artifacts exist and are valid."""
        ...

    @abstractmethod
    def validate_inputs(self, task_dir: str) -> bool:
        """Check if all required input artifacts exist."""
        ...

    @abstractmethod
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        """
        Execute the step.
        callback(percent: int, message: str) for progress reporting.
        cancel_callback() -> bool: returns True if cancellation has been requested.
        Returns dict with artifact paths.
        """
        ...

    def rollback(self, task_dir: str):
        """Remove this step artifacts to allow re-execution."""
        import os
        for artifact in self.artifacts:
            path = os.path.join(task_dir, artifact)
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                import shutil
                shutil.rmtree(path, ignore_errors=True)

    def clear_artifact(self, task_dir: str) -> None:
        """清理本节点产物（重跑前调用）。

        删除 ``artifacts`` 中声明的文件/目录（路径相对 task_dir，含 ``_node_id`` 后缀）。
        等价于 rollback，供运行时「单节点重跑 / 往后执行」等场景复用。
        """
        self.rollback(task_dir)

    def _all_exist(self, task_dir: str, files: list) -> bool:
        import os
        return all(os.path.exists(os.path.join(task_dir, f)) for f in files)
