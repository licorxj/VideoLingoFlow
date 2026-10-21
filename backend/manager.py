"""Backend process manager. Runs on port 18001, manages backend lifecycle.

Usage:
    python backend/manager.py          (default ports: manager=18001, backend=11001)
    python backend/manager.py 18001 11001
"""

import os
import sys
import json
import time
import signal
import socket
import threading
import subprocess
import shutil
import functools
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# 以 `python backend/manager.py` 脚本方式启动时，sys.path[0] 是 backend/ 目录而非项目
# 根目录，进程内 `from backend... import`（如 config_manager / celery_runtime / pi_rpc）
# 会 ModuleNotFoundError 被静默吞掉，导致 worker 并发回退默认值 4。此处引导项目根目录。
_PROJECT_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT_DIR)


def _argv_port(index: int, default: int) -> int:
    """解析命令行端口参数。

    本模块被主后端进程（uvicorn backend.main:app）import 时，sys.argv 是 uvicorn 的
    参数而非端口，直接 int() 会抛 ValueError，导致所有 in-process 调用失败。
    因此仅在参数为纯数字时才采用，否则回退默认值。
    """
    try:
        if len(sys.argv) > index:
            return int(sys.argv[index])
    except (TypeError, ValueError):
        pass
    return default


MANAGER_PORT = _argv_port(1, 18001)
BACKEND_PORT = _argv_port(2, 11001)
SOCIAL_BACKEND_PORT = 5409
SOCIAL_FRONTEND_PORT = 5173

# 控制面 worker 软停机：给在途任务留出完成时间，超时后再强杀（单位秒，可调）
CONTROL_PLANE_SOFT_SHUTDOWN_TIMEOUT = int(os.environ.get("CONTROL_PLANE_SOFT_SHUTDOWN_TIMEOUT", "300"))
SOCIAL_MCP_PORT = 5410
LLM_ROUTER_PORT = 8800
OPENCHATCUT_PORT = 5199
REDIS_PORT = 6379
REDIS_BIN_DIR = os.environ.get("VOICEFORGE_REDIS_BIN", r"C:\Program Files\Redis")
VOICEFORGE_REDIS_URL = os.environ.get("VOICEFORGE_REDIS_URL", f"redis://127.0.0.1:{REDIS_PORT}/2")
VOICEFORGE_CELERY_RESULT_URL = os.environ.get("VOICEFORGE_CELERY_RESULT_URL", f"redis://127.0.0.1:{REDIS_PORT}/3")
LOCAL_HOST = "127.0.0.1"
LAN_HOST = "0.0.0.0"
# 隐藏窗口创建标志：新进程无控制台窗口（区别于 CREATE_NEW_CONSOLE 的可见新窗口）
CREATE_HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
# 隐藏窗口 + 独立进程组：脱离 Manager 所在控制台，避免控制台 Ctrl+C 广播连带杀死
# （与 celery worker 的启动方式一致，见 start_voiceforge_worker）
CREATE_HIDDEN_GROUP = CREATE_HIDDEN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_backend_process: subprocess.Popen | None = None
_backend_start_time: float = 0
_social_backend_process: subprocess.Popen | None = None
_social_backend_start_time: float = 0
_social_frontend_process: subprocess.Popen | None = None
_social_frontend_start_time: float = 0
_social_mcp_process: subprocess.Popen | None = None
_social_mcp_start_time: float = 0
_llm_router_process: subprocess.Popen | None = None
_llm_router_start_time: float = 0
_openchatcut_process: subprocess.Popen | None = None
_openchatcut_start_time: float = 0
_voiceforge_worker_process: subprocess.Popen | None = None
_voiceforge_worker_start_time: float = 0
_control_plane_worker_process: subprocess.Popen | None = None
_control_plane_worker_start_time: float = 0
_gpu_service_process: subprocess.Popen | None = None
_gpu_service_start_time: float = 0
_redis_process: subprocess.Popen | None = None
_lock = threading.Lock()
# 运行时准备缓存：预检/迁移/孤儿清理只需执行一次，worker 启动复用结果
_runtime_prepared = False
_prepared_lock = threading.Lock()
# 操作级互斥：串行化所有 start/stop/restart 的实际执行（RLock 可重入，restart→stop→start 同线程复用）
_op_lock = threading.RLock()
# 健康监督：服务期望运行状态登记（True=期望运行，崩溃自动拉起；False=已主动停止，不干预）
_desired: dict[str, bool] = {}
_last_auto_restart: dict[str, float] = {}
# 连续自动重启失败计数：避免"启动即死"的服务被无限拉起刷屏
_auto_restart_failures: dict[str, int] = {}
_MAX_AUTO_RESTARTS = 5
# 稳定运行超过该时长视为健康，清零连续失败计数
_STABLE_UPTIME = 60.0
_shutting_down = threading.Event()
_manager_shutdown_callback = None
_AUTO_RESTART_COOLDOWN = 30.0
_WATCHDOG_INTERVAL = 10.0
# Windows Job Object 句柄：manager 退出时由 OS 级联终止全部子进程（孤儿兜底）
_job_handle = None


def _serialized(fn):
    """串行化公开的 start/stop/restart 操作，避免并发竞态。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _op_lock:
            return fn(*args, **kwargs)
    return wrapper


def _create_windows_job():
    """创建 kill-on-close Job Object：manager 进程退出时 OS 级联终止全部子进程，杜绝孤儿。
    任何失败都静默降级（保持原有行为），不影响执行架构。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

        class _BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC_LIMIT),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        print("[Manager] Windows Job Object enabled (kill-on-close orphan protection)")
        return job
    except Exception as exc:
        print(f"[Manager] Windows Job Object unavailable, skipped: {exc}")
        return None


def _assign_to_job(proc) -> bool:
    """将子进程加入全局 Job Object；失败静默降级，不改变原有行为。"""
    if os.name != "nt" or _job_handle is None or proc is None:
        return False
    try:
        import ctypes
        handle = getattr(proc, "_handle", None)
        if not handle:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        return bool(kernel32.AssignProcessToJobObject(_job_handle, int(handle)))
    except Exception:
        return False


def _cooldown_restart(name: str, starter):
    now = time.time()
    if now - _last_auto_restart.get(name, 0) < _AUTO_RESTART_COOLDOWN:
        return
    failures = _auto_restart_failures.get(name, 0)
    if failures >= _MAX_AUTO_RESTARTS:
        if failures == _MAX_AUTO_RESTARTS:
            print(f"[Manager] Watchdog gave up on {name}: 连续 {_MAX_AUTO_RESTARTS} 次自动重启均失败，停止拉起，需人工介入")
            _auto_restart_failures[name] = failures + 1
        return
    _last_auto_restart[name] = now
    _auto_restart_failures[name] = failures + 1
    print(f"[Manager] Watchdog restarting {name}... (attempt {failures + 1}/{_MAX_AUTO_RESTARTS})")
    starter()


def _watchdog_tick():
    """健康监督：仅对"期望运行但已崩溃"的服务自动拉起；主动停止的服务不干预。"""
    checks = [
        ("main_backend", _backend_process, start_backend, BACKEND_PORT, _backend_start_time),
        ("social_backend", _social_backend_process, start_social_backend, SOCIAL_BACKEND_PORT, _social_backend_start_time),
        ("social_frontend", _social_frontend_process, start_social_frontend, SOCIAL_FRONTEND_PORT, _social_frontend_start_time),
        ("social_mcp", _social_mcp_process, start_social_mcp, SOCIAL_MCP_PORT, _social_mcp_start_time),
        ("llm_router", _llm_router_process, start_llm_router, LLM_ROUTER_PORT, _llm_router_start_time),
        ("openchatcut", _openchatcut_process, start_openchatcut, None, _openchatcut_start_time),
        ("voiceforge_worker", _voiceforge_worker_process, start_voiceforge_worker, None, _voiceforge_worker_start_time),
        ("control_plane_worker", _control_plane_worker_process, start_control_plane_worker, None, _control_plane_worker_start_time),
        ("gpu_service", _gpu_service_process, start_gpu_service, None, _gpu_service_start_time),
    ]
    for name, proc, starter, port, started_at in checks:
        if _shutting_down.is_set():
            return
        with _lock:
            desired = _desired.get(name, False)
        if not desired:
            continue
        if proc is None:
            if port is not None and _check_port(port):
                continue  # 端口仍被占用：视为存活（外部或孙进程）
            _cooldown_restart(name, starter)
            continue
        if proc.poll() is not None:
            if port is not None and _check_port(port):
                continue  # 句柄退出但端口仍在监听：真实服务还活着
            _cooldown_restart(name, starter)
        elif started_at and (time.time() - started_at) > _STABLE_UPTIME:
            # 稳定运行足够久：视为健康，清空连续失败计数
            _auto_restart_failures.pop(name, None)


def _watchdog_loop():
    while not _shutting_down.wait(_WATCHDOG_INTERVAL):
        try:
            _watchdog_tick()
        except Exception as exc:
            print(f"[Manager] Watchdog tick error: {exc}")


def _load_local_runtime_env(project_root: str) -> dict[str, str]:
    path = os.path.join(project_root, ".runtime", "local_env.bat")
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line.lower().startswith("set "):
                    continue
                assignment = line[4:].strip().strip('"')
                if "=" not in assignment:
                    continue
                key, value = assignment.split("=", 1)
                values[key] = value
    except FileNotFoundError:
        pass
    return values


def _lan_mode_enabled(env: dict[str, str]) -> bool:
    return env.get("VIDEOLINGO_LAN_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _listener_host(env: dict[str, str]) -> str:
    return LAN_HOST if _lan_mode_enabled(env) else LOCAL_HOST


def _venv_has_bundled_cuda(venv_root: str) -> bool:
    """检测 venv 是否自带 CUDA 运行时（本机特殊构建：CUDA 运行时打进 venv\\Library）。

    存在 nvcc 或 cudart64_*.dll 即视为自带；否则视为通用构建，使用用户的系统 CUDA。
    """
    lib_bin = os.path.join(venv_root, "Library", "bin")
    if not os.path.isdir(lib_bin):
        return False
    if os.path.isfile(os.path.join(lib_bin, "nvcc.exe")):
        return True
    try:
        for name in os.listdir(lib_bin):
            if name.lower().startswith("cudart64_"):
                return True
    except OSError:
        pass
    return False


def _setup_env() -> dict[str, str]:
    """Build the environment for the backend process.

    - 本机特殊构建（venv 自带 CUDA 运行时）：屏蔽系统 CUDA、PATH 最小化、CUDA 指向 venv\\Library。
    - 通用构建（git 源码从头构建）：保留用户系统 CUDA 与 PATH，仅前置 venv 与 torch lib。
    """
    env = os.environ.copy()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for key, value in _load_local_runtime_env(project_root).items():
        env[key] = value
    sysroot = os.environ.get("SystemRoot", "C:\\Windows")

    venv_root = os.path.join(project_root, "venv312")
    torch_lib = os.path.join(venv_root, "Lib", "site-packages", "torch", "lib")
    bundled_cuda = _venv_has_bundled_cuda(venv_root)

    if bundled_cuda:
        # -- Block system CUDA / cuDNN (本机特殊构建) --
        env.pop("CUDA_HOME", None)
        env.pop("CUDA_PATH", None)
        env.pop("CUDA_PATH_V12_6", None)
        env.pop("CUDNN_PATH", None)
        # -- Minimal PATH --
        env["PATH"] = (
            sysroot + "\\system32;"
            + sysroot + ";"
            + sysroot + "\\System32\\Wbem;"
            + sysroot + "\\System32\\WindowsPowerShell\\v1.0\\"
        )
        # -- Local CUDA + torch DLL paths (来自 venv\Library) --
        env["CUDA_PATH"] = os.path.join(venv_root, "Library")
        env["CUDA_HOME"] = os.path.join(venv_root, "Library")
        env["TORCH_LIB"] = torch_lib
        # Prepend torch lib and venv bin to PATH
        env["PATH"] = (
            f"{torch_lib};"
            f"{os.path.join(venv_root, 'Library', 'bin')};"
            f"{os.path.join(venv_root, 'Scripts')};"
            f"{env['PATH']}"
        )
    else:
        # -- 通用构建：使用用户的系统 CUDA 与 PATH，仅前置 venv 与 torch lib --
        env.setdefault("CUDA_PATH", "")
        env.setdefault("CUDA_HOME", "")
        env["TORCH_LIB"] = torch_lib
        env["PATH"] = f"{torch_lib};{os.path.join(venv_root, 'Scripts')};{env['PATH']}"

    # -- Model cache --
    # Anchor all model downloads (HuggingFace / ModelScope / torch.hub) inside the
    # project's _model_cache directory so nothing leaks to the user home cache.
    model_cache_dir = os.path.join(project_root, "_model_cache")
    os.makedirs(model_cache_dir, exist_ok=True)
    env["HF_HOME"] = model_cache_dir
    env["TORCH_HOME"] = model_cache_dir
    env["MODELSCOPE_CACHE"] = model_cache_dir
    env["TFHUB_CACHE_DIR"] = model_cache_dir
    env["MODEL_DIRECTORY"] = os.path.join(model_cache_dir, "spleeter")
    # Disable modelscope file lock to prevent stale lock files from blocking threads
    env["MODELSCOPE_HUB_FILE_LOCK"] = "false"
    # Skip torchcodec DLL loading (pyannote falls back to torchaudio)
    env["TORCHCODEC_DISABLE"] = "1"
    # Use HuggingFace mirror when an endpoint was not explicitly provided
    if not env.get("HF_ENDPOINT"):
        env["HF_ENDPOINT"] = "https://hf-mirror.com"

    # Python from venv
    env["VENV_ROOT"] = venv_root
    env["VIRTUAL_ENV"] = venv_root
    env["PATH"] = f"{os.path.join(venv_root, 'Scripts')};{env['PATH']}"
    if os.path.isfile(os.path.join(REDIS_BIN_DIR, "redis-server.exe")):
        env["PATH"] = f"{REDIS_BIN_DIR};{env['PATH']}"
    # -- Node.js runtime (小π Agent depends on it; the startup wrapper already detected it) --
    node_exe = shutil.which("node") or ""
    if not node_exe and os.name == "nt":
        for candidate in (
            r"X:\nodejs\node.exe",
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs", "node.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "nodejs", "node.exe"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvm", "node.exe"),
        ):
            if os.path.isfile(candidate):
                node_exe = candidate
                break
    if node_exe and os.path.isfile(node_exe):
        node_dir = os.path.dirname(os.path.abspath(node_exe))
        if node_dir and node_dir not in env["PATH"].split(os.pathsep):
            env["PATH"] = f"{node_dir};{env['PATH']}"
        env["VIDEOLINGO_PI_NODE_PATH"] = os.path.abspath(node_exe)
    env.pop("CONTROL_PLANE_DATABASE_URL", None)
    env.pop("MINIO_ENDPOINT", None)
    env.pop("MINIO_ROOT_USER", None)
    env.pop("MINIO_ROOT_PASSWORD", None)
    env.pop("MINIO_BUCKET", None)
    env.pop("MINIO_SECURE", None)
    env["CONTROL_PLANE_DATA_ROOT"] = os.path.join(project_root, "data")
    env["CONTROL_PLANE_DATABASE_PATH"] = os.path.join(project_root, "data", "control-plane.db")
    env["VOICEFORGE_REDIS_URL"] = VOICEFORGE_REDIS_URL
    env["VOICEFORGE_CELERY_RESULT_URL"] = VOICEFORGE_CELERY_RESULT_URL

    return env


def _get_python() -> str:
    """Get the venv python executable."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(project_root, "venv312", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _local_runtime_dirs(project_root: str) -> tuple[Path, ...]:
    data_root = Path(project_root) / "data"
    return (
        data_root,
        data_root / "assets",
        data_root / "workspace",
        data_root / "checkpoints",
        data_root / "backups",
        Path(project_root) / "logs",
    )


def _python_ready(python_exe: str, env: dict[str, str]) -> bool:
    check = subprocess.run(
        [python_exe, "-c", "import sqlite3, alembic, celery, redis, sqlalchemy"],
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8", errors="replace",
    )
    if check.returncode == 0:
        return True
    detail = (check.stderr or check.stdout).strip().splitlines()
    print(f"[Manager] Python dependencies are unavailable: {detail[-1] if detail else 'unknown error'}")
    return False


def _redis_ready(python_exe: str, env: dict[str, str]) -> bool:
    check = subprocess.run(
        [python_exe, "-c", "import os, redis; redis.Redis.from_url(os.environ['VOICEFORGE_REDIS_URL'], socket_connect_timeout=1, socket_timeout=1).ping()"],
        capture_output=True,
        timeout=5,
        env=env,
    )
    return check.returncode == 0


def _start_redis(python_exe: str, env: dict[str, str]) -> bool:
    global _redis_process
    if _redis_ready(python_exe, env):
        return True
    if _check_port(REDIS_PORT):
        print(f"[Manager] Port {REDIS_PORT} is occupied but does not respond as Redis")
        return False
    redis_server = shutil.which("redis-server", path=env.get("PATH"))
    if not redis_server:
        candidate = os.path.join(REDIS_BIN_DIR, "redis-server.exe")
        redis_server = candidate if os.path.isfile(candidate) else None
    if not redis_server:
        print("[Manager] Redis is required but redis-server was not found")
        return False
    try:
        _redis_process = subprocess.Popen(
            [redis_server, "--bind", LOCAL_HOST, "--port", str(REDIS_PORT)],
            cwd=_project_root(),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        _assign_to_job(_redis_process)
    except Exception as exc:
        print(f"[Manager] Failed to start Redis: {exc}")
        return False
    for _ in range(20):
        if _redis_ready(python_exe, env):
            print(f"[Manager] Redis started PID={_redis_process.pid}")
            return True
        time.sleep(0.25)
    print("[Manager] Redis did not become ready")
    _kill_existing_process(_redis_process)
    _redis_process = None
    return False


def _migrate_sqlite(python_exe: str, env: dict[str, str], project_root: str) -> bool:
    command = (
        "from alembic import command; from alembic.config import Config; "
        "from backend.voiceforge import initialize_database; "
        "command.upgrade(Config('alembic.ini'), 'head'); initialize_database()"
    )
    result = subprocess.run(
        [python_exe, "-c", command],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90, encoding="utf-8", errors="replace",
    )
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout).strip().splitlines()
    print(f"[Manager] SQLite migration failed: {detail[-1] if detail else 'unknown error'}")
    return False


def _worker_available(python_exe: str, env: dict[str, str], project_root: str, queues: set[str], app_module: str) -> bool:
    command = (
        f"from {app_module} import celery_app; "
        "inspect = celery_app.control.inspect() if celery_app else None; "
        "active = inspect.active_queues() if inspect else {}; "
        f"target = {sorted(queues)!r}; "
        "print(any(set(item['name'] for item in worker_queues) >= set(target) for worker_queues in active.values()))"
    )
    check = subprocess.run(
        [python_exe, "-c", command],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=project_root,
        env=env, encoding="utf-8", errors="replace",
    )
    return check.returncode == 0 and check.stdout.strip() == "True"


def _prepare_local_runtime() -> tuple[str, dict[str, str]] | None:
    """准备本地运行时（依赖预检 → SQLite 迁移 → 孤儿工作区清理 → Redis）。

    预检/迁移/孤儿清理在 Manager 生命周期内只需执行一次：后续 worker 启动复用
    结果（_runtime_prepared 缓存），仅保留 Redis 存活探测以便崩溃后重新拉起。
    """
    global _runtime_prepared
    project_root = _project_root()
    python_exe = _get_python()
    env = _setup_env()
    for path in _local_runtime_dirs(project_root):
        path.mkdir(parents=True, exist_ok=True)
    with _prepared_lock:
        if not _runtime_prepared:
            if not _python_ready(python_exe, env):
                return None
            if not _migrate_sqlite(python_exe, env, project_root):
                return None
            # 迁移已完成：标记传递给子进程，主后端 startup 据此跳过重复迁移
            os.environ["VIDEOLINGO_MIGRATION_DONE"] = "1"
            # 清理孤儿任务文件夹：DB 中已不存在的工作区残留（删除失败/历史遗留），避免磁盘堆积
            try:
                cleanup = subprocess.run(
                    [python_exe, "-c",
                     "from backend.control_plane.workflow_runtime import cleanup_orphan_workspaces; cleanup_orphan_workspaces()"],
                    cwd=project_root, env=env, timeout=120, capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                if cleanup.stdout.strip():
                    print(f"[Manager] {cleanup.stdout.strip().splitlines()[-1]}")
            except Exception as exc:
                print(f"[Manager] 孤儿工作区清理跳过: {exc}")
            _runtime_prepared = True
    if not _start_redis(python_exe, env):
        return None
    return python_exe, env


def _kill_existing_process(proc):
    """Safely terminate a process and its children."""
    if proc is None:
        return
    try:
        # On Windows, use taskkill to kill the process tree
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    except Exception as e:
        print(f"[Manager] Failed to kill process {proc.pid}: {e}")


@_serialized
def start_backend():
    """Start the backend process."""
    global _backend_process, _backend_start_time

    with _lock:
        if _backend_process is not None and _backend_process.poll() is None:
            print("[Manager] Backend already running, skipping start")
            return
        if _check_port(BACKEND_PORT):
            detached_pid = next((pid for pid in _get_listener_pids(BACKEND_PORT) if _is_main_backend_process(pid)), None)
            if detached_pid is not None:
                print(f"[Manager] Backend already running outside manager handle, PID={detached_pid}, skipping start")
                _desired["main_backend"] = True
                return
            print(f"[Manager] Backend port {BACKEND_PORT} is already in use, skipping start")
            return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = _get_python()
    env = _setup_env()

    listener_host = _listener_host(env)
    cmd = [
        python_exe, "-m", "uvicorn", "backend.main:app",
        "--host", listener_host,
        "--port", str(BACKEND_PORT),
        "--log-level", "warning",
    ]

    print(f"[Manager] Starting backend: {' '.join(cmd)}")
    if _lan_mode_enabled(env):
        print("[Manager] WARNING: LAN mode is enabled without authentication or TLS. Use only on a trusted LAN.")
    print(f"[Manager] Python: {python_exe}")
    print(f"[Manager] CUDA_PATH: {env.get('CUDA_PATH', 'N/A')}")

    try:
        # 生产模式（start-prod.* 设置 VIDEOLINGO_PROD_MODE=1）：主后端也隐藏窗口，
        # 仅保留 Manager 一个窗口（worker 输出在当前窗口）；否则主后端可见新窗口（dev 形态）
        prod_mode = os.environ.get("VIDEOLINGO_PROD_MODE", "").strip().lower() in {"1", "true", "yes"}
        if os.name == "nt":
            creationflags = CREATE_HIDDEN if prod_mode else subprocess.CREATE_NEW_CONSOLE
        else:
            creationflags = 0
        proc = subprocess.Popen(
            cmd,
            cwd=project_root,
            env=env,
            creationflags=creationflags,
        )
        _assign_to_job(proc)
        with _lock:
            _backend_process = proc
            _backend_start_time = time.time()
        _desired["main_backend"] = True
        print(f"[Manager] Backend started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start backend: {e}")


@_serialized
def stop_backend():
    """Stop the backend process."""
    global _backend_process, _backend_start_time
    _desired["main_backend"] = False

    with _lock:
        proc = _backend_process
        _backend_process = None
        _backend_start_time = 0

    if proc is None:
        if _check_port(BACKEND_PORT) and _stop_external_backend():
            for _ in range(20):
                if _check_port(BACKEND_PORT):
                    time.sleep(0.5)
                else:
                    break
            print("[Manager] Detached backend stopped")
            return
        print("[Manager] No backend process to stop")
        return

    pid = proc.pid
    print(f"[Manager] Stopping backend PID={pid}...")
    _kill_existing_process(proc)

    # Wait for port to free up
    for _ in range(20):
        if _check_port(BACKEND_PORT):
            time.sleep(0.5)
        else:
            break
    print(f"[Manager] Backend stopped")


@_serialized
def start_social_backend():
    """Start the social-auto-upload-web-ui backend (Flask + Waitress on port 5409)."""
    global _social_backend_process, _social_backend_start_time

    with _lock:
        if _social_backend_process is not None and _social_backend_process.poll() is None:
            print("[Manager] Social backend already running, skipping start")
            return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = _get_python()
    env = _setup_env()

    # Clear proxy
    for k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)

    # CloakBrowser built-in path
    cloak_path = os.path.join(project_root, "thirdparty", "cloakbrowser", "chrome.exe")
    if os.path.exists(cloak_path):
        env["CLOAKBROWSER_BINARY_PATH"] = cloak_path

    social_dir = os.path.join(project_root, "thirdparty", "social-auto-upload-web-ui", "backend")
    data_dir = os.path.join(project_root, "thirdparty", "social-auto-upload-web-ui", "data")
    env["SAU_DATA_DIR"] = data_dir
    env["SAU_PORT"] = str(SOCIAL_BACKEND_PORT)

    cmd = [python_exe, "app.py"]

    print(f"[Manager] Starting social backend: {' '.join(cmd)}")
    print(f"[Manager] Python:   {python_exe}")
    print(f"[Manager] Work dir: {social_dir}")
    print(f"[Manager] Data dir: {data_dir}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=social_dir,
            env=env,
            creationflags=CREATE_HIDDEN if os.name == "nt" else 0,
        )
        _assign_to_job(proc)
        with _lock:
            _social_backend_process = proc
            _social_backend_start_time = time.time()
        _desired["social_backend"] = True
        print(f"[Manager] Social backend started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start social backend: {e}")


@_serialized
def stop_social_backend():
    """Stop the social backend process."""
    global _social_backend_process, _social_backend_start_time
    _desired["social_backend"] = False

    with _lock:
        proc = _social_backend_process
        _social_backend_process = None
        _social_backend_start_time = 0

    if proc is None:
        print("[Manager] No social backend process to stop")
        return

    pid = proc.pid
    print(f"[Manager] Stopping social backend PID={pid}...")
    _kill_existing_process(proc)

    for _ in range(20):
        if _check_port(SOCIAL_BACKEND_PORT):
            time.sleep(0.5)
        else:
            break
    print(f"[Manager] Social backend stopped")


@_serialized
def start_social_mcp():
    """Start the social MCP server (npm start on port 5410)."""
    global _social_mcp_process, _social_mcp_start_time

    with _lock:
        if _social_mcp_process is not None and _social_mcp_process.poll() is None:
            print("[Manager] Social MCP already running, skipping start")
            return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mcp_dir = os.path.join(project_root, "thirdparty", "social-auto-upload-web-ui", "backend-mcp")
    if not os.path.isdir(mcp_dir):
        print("[Manager] Social MCP directory not found, skipping")
        return

    env = os.environ.copy()
    npm_cmd = env.get("NPM_CMD", "npm")

    print(f"[Manager] Starting social MCP in {mcp_dir}")
    try:
        proc = subprocess.Popen(
            f'"{npm_cmd}" start',
            cwd=mcp_dir,
            env=env,
            shell=True,
            # 独立进程组：否则会跟随 Manager 控制台收到 Ctrl+C 广播而被误杀，
            # 看门狗随即拉起，形成"启动→被杀→重启"的死循环
            creationflags=CREATE_HIDDEN_GROUP if os.name == "nt" else 0,
        )
        _assign_to_job(proc)
        with _lock:
            _social_mcp_process = proc
            _social_mcp_start_time = time.time()
        _desired["social_mcp"] = True
        print(f"[Manager] Social MCP started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start social MCP: {e}")


@_serialized
def stop_social_mcp():
    """Stop the social MCP process."""
    global _social_mcp_process, _social_mcp_start_time
    _desired["social_mcp"] = False

    with _lock:
        proc = _social_mcp_process
        _social_mcp_process = None
        _social_mcp_start_time = 0

    if proc is not None:
        print(f"[Manager] Stopping social MCP PID={proc.pid}...")
        _kill_existing_process(proc)

    # Fallback: npm start 的 shell 句柄失真，孙进程可能仍占用 5410，按端口兜底清理
    if _check_port(SOCIAL_MCP_PORT):
        _kill_port_process(SOCIAL_MCP_PORT)

    for _ in range(20):
        if _check_port(SOCIAL_MCP_PORT):
            time.sleep(0.5)
        else:
            break
    print(f"[Manager] Social MCP stopped")


def _find_npm() -> str:
    """Find npm executable, preferring npm.cmd on Windows."""
    import shutil
    if os.name == "nt":
        for name in ("npm.cmd", "npm.exe", "npm"):
            found = shutil.which(name)
            if found:
                return found
        # Fallback: common Node.js install paths
        for p in [
            os.path.expandvars(r"%ProgramFiles%\nodejs\npm.cmd"),
            os.path.expandvars(r"%ProgramFiles(x86)%\nodejs\npm.cmd"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\npm.cmd"),
        ]:
            if os.path.exists(p):
                return p
    return "npm"


@_serialized
def start_social_frontend():
    """Start the social frontend as a static server (serve built dist on port 5173).

    静态模式下不再运行 Vite dev server：dist 缺失时先执行一次 npm run build，
    然后由 backend/social_frontend_server.py 托管 dist。后续代码更新时，
    由更新流程重新执行构建（见 backend/api/publish.py 的更新任务）。
    """
    global _social_frontend_process, _social_frontend_start_time

    with _lock:
        if _social_frontend_process is not None and _social_frontend_process.poll() is None:
            print("[Manager] Social frontend already running, skipping start")
            return
        if _check_port(SOCIAL_FRONTEND_PORT):
            print(f"[Manager] Port {SOCIAL_FRONTEND_PORT} already in use, skipping social frontend start")
            return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(project_root, "thirdparty", "social-auto-upload-web-ui", "frontend")
    if not os.path.isdir(frontend_dir):
        print("[Manager] Social frontend directory not found, skipping")
        return

    dist_dir = os.path.join(frontend_dir, "dist")
    if not os.path.isfile(os.path.join(dist_dir, "index.html")):
        node_modules = os.path.join(frontend_dir, "node_modules")
        if not os.path.isdir(node_modules):
            print(f"[Manager] node_modules not found in {frontend_dir}, installing deps first...")
            npm_cmd = _find_npm()
            try:
                subprocess.run(
                    [npm_cmd, "install", "--prefer-offline", "--registry=https://registry.npmmirror.com"],
                    cwd=frontend_dir,
                    shell=os.name == "nt",
                    timeout=300,
                    capture_output=True,
                )
            except Exception as e:
                print(f"[Manager] npm install failed: {e}")

        npm_cmd = _find_npm()
        print("[Manager] Building social frontend (dist missing, first run)...")
        try:
            res = subprocess.run(
                [npm_cmd, "run", "build"],
                cwd=frontend_dir,
                shell=os.name == "nt",
                timeout=600,
                capture_output=True,
            )
            if res.returncode != 0:
                print(f"[Manager] npm run build failed: {(res.stdout or res.stderr)[:2000]}")
        except Exception as e:
            print(f"[Manager] npm run build failed: {e}")

        if not os.path.isfile(os.path.join(dist_dir, "index.html")):
            print("[Manager] Social frontend build output missing, skipping start")
            return

    server_script = os.path.join(project_root, "backend", "social_frontend_server.py")
    python_exe = _get_python()
    cmd = [
        python_exe, server_script,
        "--dist", dist_dir,
        "--host", "127.0.0.1",
        "--port", str(SOCIAL_FRONTEND_PORT),
        "--backend-port", str(SOCIAL_BACKEND_PORT),
    ]

    print(f"[Manager] Starting social frontend static server: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            env=os.environ.copy(),
            creationflags=CREATE_HIDDEN if os.name == "nt" else 0,
        )
        _assign_to_job(proc)
        with _lock:
            _social_frontend_process = proc
            _social_frontend_start_time = time.time()
        _desired["social_frontend"] = True
        print(f"[Manager] Social frontend static server started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start social frontend: {e}")


def _kill_port_process(port: int):
    """按端口清理游离监听进程；绝不清理 manager 自身进程。"""
    if os.name != "nt":
        return
    if port == MANAGER_PORT:
        print(f"[Manager] Refusing to kill process listening on manager port {port}")
        return
    try:
        output = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
        ).stdout
        pids: set[int] = set()
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].endswith("TCP") and parts[1].rsplit(":", 1)[-1] == str(port) and parts[3] == "LISTENING":
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
        for pid in sorted(pids):
            if pid == os.getpid():
                print(f"[Manager] Skip killing own process PID={pid} on port {port}")
                continue
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
    except Exception as e:
        print(f"[Manager] Failed to kill process listening on port {port}: {e}")


def _get_listener_pids(port: int) -> list[int]:
    """返回监听指定 TCP 端口的 PID 列表。"""
    pids: set[int] = set()
    try:
        if os.name == "nt":
            output = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=10, encoding="utf-8", errors="replace",
            ).stdout
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].endswith("TCP") and parts[1].rsplit(":", 1)[-1] == str(port) and parts[3] == "LISTENING":
                    try:
                        pids.add(int(parts[-1]))
                    except ValueError:
                        pass
        else:
            for cmd in (
                ["lsof", "-iTCP", f":{port}", "-sTCP:LISTEN", "-t"],
                ["ss", "-ltnp", f"sport = :{port}"],
            ):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
                if result.returncode != 0:
                    continue
                for token in result.stdout.replace(",", " ").split():
                    if token.isdigit():
                        pids.add(int(token))
    except Exception:
        return []
    return sorted(pids)


def _get_process_command_line(pid: int | None) -> str:
    """返回指定 PID 的命令行，小写；失败返回空串。"""
    if pid is None:
        return ""
    try:
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=10, encoding="utf-8", errors="replace",
            )
            return result.stdout.strip().lower().replace("/", "\\")
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=10, encoding="utf-8", errors="replace",
        )
        return result.stdout.strip().lower()
    except Exception:
        return ""


def _is_main_backend_process(pid: int | None) -> bool:
    """判断 PID 是否为当前项目的主后端进程。"""
    if pid is None:
        return False
    command_line = _get_process_command_line(pid)
    if not command_line:
        return False
    project_root = _project_root().lower().replace("/", "\\")
    markers = (
        "backend.main:app",
        "backend\\main.py",
        "backend/main.py",
    )
    return project_root in command_line and any(marker in command_line for marker in markers)


def _stop_external_backend() -> bool:
    """尝试停止监听 11001 但未被当前 manager 句柄记录的本项目主后端。"""
    stopped = False
    for pid in _get_listener_pids(BACKEND_PORT):
        if pid == os.getpid():
            continue
        if not _is_main_backend_process(pid):
            continue
        try:
            print(f"[Manager] Reclaiming detached backend PID={pid} on port {BACKEND_PORT}...")
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            stopped = True
        except Exception as exc:
            print(f"[Manager] Failed to stop detached backend PID={pid}: {exc}")
    return stopped


@_serialized
def stop_social_frontend():
    """Stop the social frontend process."""
    global _social_frontend_process, _social_frontend_start_time
    _desired["social_frontend"] = False

    with _lock:
        proc = _social_frontend_process
        _social_frontend_process = None
        _social_frontend_start_time = 0

    if proc is not None:
        print(f"[Manager] Stopping social frontend PID={proc.pid}...")
        _kill_existing_process(proc)

    if _check_port(SOCIAL_FRONTEND_PORT):
        _kill_port_process(SOCIAL_FRONTEND_PORT)

    for _ in range(20):
        if _check_port(SOCIAL_FRONTEND_PORT):
            time.sleep(0.5)
        else:
            break
    print(f"[Manager] Social frontend stopped")


@_serialized
def start_llm_router():
    """Start the QM-LocalRouter backend (FastAPI on port 8800)."""
    global _llm_router_process, _llm_router_start_time

    with _lock:
        if _llm_router_process is not None and _llm_router_process.poll() is None:
            print("[Manager] LLM Router already running, skipping start")
            return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = _setup_env()

    llm_router_dir = os.path.join(project_root, "thirdparty", "QM-LocalRouter", "backend")
    if not os.path.isdir(llm_router_dir):
        print("[Manager] LLM Router directory not found, skipping")
        return

    # 优先使用 QM-LocalRouter 的独立虚拟环境，避免依赖污染主 venv312
    python_exe = _get_python()
    qm_venv_py = os.path.join(
        llm_router_dir, "venv",
        "Scripts/python.exe" if os.name == "nt" else "bin/python",
    )
    if os.path.isfile(qm_venv_py):
        python_exe = qm_venv_py

    cmd = [
        python_exe, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1",
        "--port", str(LLM_ROUTER_PORT),
    ]

    print(f"[Manager] Starting LLM Router: {' '.join(cmd)}")
    print(f"[Manager] Python:   {python_exe}")
    print(f"[Manager] Work dir: {llm_router_dir}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=llm_router_dir,
            env=env,
            creationflags=CREATE_HIDDEN if os.name == "nt" else 0,
        )
        _assign_to_job(proc)
        with _lock:
            _llm_router_process = proc
            _llm_router_start_time = time.time()
        _desired["llm_router"] = True
        print(f"[Manager] LLM Router started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start LLM Router: {e}")


@_serialized
def stop_llm_router():
    """Stop the LLM Router process."""
    global _llm_router_process, _llm_router_start_time
    _desired["llm_router"] = False

    with _lock:
        proc = _llm_router_process
        _llm_router_process = None
        _llm_router_start_time = 0

    if proc is None:
        print("[Manager] No LLM Router process to stop")
        return

    pid = proc.pid
    print(f"[Manager] Stopping LLM Router PID={pid}...")
    _kill_existing_process(proc)

    for _ in range(20):
        if _check_port(LLM_ROUTER_PORT):
            time.sleep(0.5)
        else:
            break
    print(f"[Manager] LLM Router stopped")


def _resolve_node_exe() -> str | None:
    """优先用 start.bat 注入的 NODE_EXE，否则回退到 PATH 探测。"""
    node = os.environ.get("NODE_EXE")
    if node and os.path.isfile(node):
        return node
    for cand in ("node", "node.exe"):
        p = shutil.which(cand)
        if p:
            return p
    return None


def _node_version_at_least(node_exe: str, major: int, minor: int = 0) -> bool:
    try:
        out = subprocess.run(
            [node_exe, "--version"], capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
        ).stdout.strip().lstrip("v")
        parts = out.split(".")
        if len(parts) < 2:
            return False
        return (int(parts[0]), int(parts[1])) >= (major, minor)
    except Exception:
        return False




# --------------------------------------------------------------------------- #
# OpenChatCut（AI剪辑台，thirdparty/openchatcut，AGPL 独立进程，不改源码）
# --------------------------------------------------------------------------- #


def _openchatcut_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "thirdparty", "openchatcut",
    )


def _openchatcut_settings() -> tuple[int, bool]:
    """读取「AI剪辑台」设置：(端口, 是否启用)。

    manager 是独立进程，直读 config.yaml；读取失败时回退默认值 5199 / 启用。
    环境变量 OPENCHATCUT_DISABLED=1 可强制关闭自动启动。
    """
    port = OPENCHATCUT_PORT
    enabled = True
    try:
        from backend.config.config_manager import config as _config

        value = _config.get("openchatcut.port", port)
        try:
            port = int(value)
        except (TypeError, ValueError):
            pass
        enabled = bool(_config.get("openchatcut.enabled", True))
    except Exception:
        pass
    if os.environ.get("OPENCHATCUT_DISABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        enabled = False
    return port, enabled


def _openchatcut_npm() -> str:
    """解析 npm：优先 node 同目录的 npm(.cmd)，回退 PATH 探测。"""
    node_exe = _resolve_node_exe()
    if node_exe:
        sibling = os.path.join(
            os.path.dirname(node_exe), "npm.cmd" if os.name == "nt" else "npm"
        )
        if os.path.isfile(sibling):
            return sibling
    found = shutil.which("npm") or shutil.which("npm.cmd")
    return found or "npm"


@_serialized
def start_openchatcut():
    """启动 OpenChatCut 编辑器（npm run dev，默认 5199）。

    合规边界：不修改其源码，运行参数来自其官方 .env.local（由主项目
    「AI剪辑台」设置页注入）。node_modules 缺失（未安装依赖）时跳过并提示。
    """
    global _openchatcut_process, _openchatcut_start_time

    port, enabled = _openchatcut_settings()
    if not enabled:
        return

    with _lock:
        if _openchatcut_process is not None and _openchatcut_process.poll() is None:
            print("[Manager] OpenChatCut already running, skipping start")
            return

    if _check_port(port):
        print("[Manager] OpenChatCut port is already in use, skipping start")
        return

    occ_dir = _openchatcut_dir()
    if not os.path.isdir(occ_dir):
        print("[Manager] OpenChatCut directory not found, skipping")
        return
    if not os.path.isdir(os.path.join(occ_dir, "node_modules")):
        print("[Manager] OpenChatCut 依赖未安装（thirdparty/openchatcut/node_modules 缺失），跳过启动；"
              "请先在 thirdparty/openchatcut 下执行 npm install")
        return

    npm_cmd = _openchatcut_npm()
    # isolated-dev 模式下 profile 的 settings.env 一旦存在，上游 vite 不再读取
    # .env.local，进程 env 是该模式官方设计的注入通道；此处把「AI剪辑台」设置
    # 生成的同一组变量注入子进程（.env.local 仍会写入，供 dev:shared / 桌面端使用）。
    child_env = os.environ.copy()
    try:
        from backend.config.config_manager import config as _occ_cfg
        from backend.config.openchatcut_settings import merge_defaults as _occ_merge
        from backend.config.openchatcut_settings import resolved_env_pairs as _occ_pairs

        _occ_stored = _occ_cfg.get("openchatcut", {}) or {}
        for _key, _value in _occ_pairs(_occ_merge(_occ_stored)).items():
            child_env[_key] = _value
    except Exception as exc:
        print(f"[Manager] OpenChatCut env 注入跳过（将仅依赖 .env.local）: {exc}")

    # 启动模式：优先跑构建产物（dist/，安装时已 npm run build），
    # 复用上游官方生产服务（desktop/embedded-server.ts，含全部服务端能力：
    # /api、/llm、外部 MCP 等），不修改其源码，仅新增启动器 thirdparty/openchatcut_prod_server.mts。
    # dist 缺失（未构建 / 构建失败）时回退 dev server，保证「装完依赖也能用」。
    dist_index = os.path.join(occ_dir, "dist", "index.html")
    runner = os.path.join(os.path.dirname(occ_dir), "openchatcut_prod_server.mts")
    tsx_cli = os.path.join(occ_dir, "node_modules", "tsx", "dist", "cli.mjs")
    use_build = os.path.isfile(dist_index) and os.path.isfile(runner) and os.path.isfile(tsx_cli)

    if use_build:
        node_exe = _resolve_node_exe() or "node"
        print(f"[Manager] Starting OpenChatCut: 生产模式（dist 构建产物, port {port}）")
        try:
            if os.name == "nt":
                cmd = f'cmd /c "cd /d "{occ_dir}" && "{node_exe}" "{tsx_cli}" "{runner}" "{occ_dir}""'
                proc = subprocess.Popen(
                    cmd,
                    cwd=occ_dir,
                    env=child_env,
                    shell=True,
                    creationflags=CREATE_HIDDEN,
                )
            else:
                proc = subprocess.Popen(
                    [node_exe, tsx_cli, runner, occ_dir],
                    cwd=occ_dir,
                    env=child_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        except Exception as e:
            print(f"[Manager] Failed to start OpenChatCut (prod): {e}")
            return
    else:
        # 上游 vite 未配置 server.host，默认绑 localhost（本机解析到 ::1），与主项目
        # 全站 127.0.0.1 约定（反代/端口探测）不符；经 CLI 参数绑定 127.0.0.1（不改其源码）。
        print(f"[Manager] Starting OpenChatCut: dev 模式（dist 缺失, npm run dev, port {port}）")
        try:
            if os.name == "nt":
                cmd = f'cmd /c "cd /d "{occ_dir}" && "{npm_cmd}" run dev -- --host 127.0.0.1"'
                proc = subprocess.Popen(
                    cmd,
                    cwd=occ_dir,
                    env=child_env,
                    shell=True,
                    creationflags=CREATE_HIDDEN,
                )
            else:
                proc = subprocess.Popen(
                    [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1"],
                    cwd=occ_dir,
                    env=child_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        except Exception as e:
            print(f"[Manager] Failed to start OpenChatCut (dev): {e}")
            return

    try:
        _assign_to_job(proc)
        with _lock:
            _openchatcut_process = proc
            _openchatcut_start_time = time.time()
        _desired["openchatcut"] = True
        print(f"[Manager] OpenChatCut started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start OpenChatCut: {e}")


@_serialized
def _kill_orphan_openchatcut(port: int):
    """清理未纳入跟踪的 OpenChatCut 实例（手工启动、或 manager 重启后遗留的子进程）。

    没有它的话，"重启剪辑台" 会对这类实例空操作（stop 找不到进程、start 又因端口
    占用跳过），导致 .env.local 的新配置永远不生效。命令行不含 openchatcut 的
    监听进程一律不杀，避免误伤占用同端口的其他程序。
    """
    for pid in _get_listener_pids(port):
        cmdline = ""
        try:
            probe = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
            )
            cmdline = (probe.stdout or "").strip()
        except Exception as e:
            print(f"[Manager] Failed to inspect PID={pid}: {e}")
        if "openchatcut" not in cmdline.lower():
            print(f"[Manager] Port {port} held by unrelated process PID={pid}, skip killing")
            continue
        print(f"[Manager] Stopping orphan OpenChatCut PID={pid} on port {port}...")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=15)


def stop_openchatcut():
    """Stop the OpenChatCut dev process managed by this manager."""
    global _openchatcut_process, _openchatcut_start_time
    _desired["openchatcut"] = False

    with _lock:
        proc = _openchatcut_process
        _openchatcut_process = None
        _openchatcut_start_time = 0

    port, _enabled = _openchatcut_settings()

    if proc is None:
        print("[Manager] No tracked OpenChatCut process, falling back to port cleanup")
        _kill_orphan_openchatcut(port)
        for _ in range(20):
            if _check_port(port):
                time.sleep(0.5)
            else:
                break
        return

    print(f"[Manager] Stopping OpenChatCut PID={proc.pid}...")
    _kill_existing_process(proc)
    for _ in range(20):
        if _check_port(port):
            time.sleep(0.5)
        else:
            break
    print("[Manager] OpenChatCut stopped")


@_serialized
def restart_openchatcut_only():
    """Restart only the OpenChatCut editor."""
    print("[Manager] Restarting OpenChatCut...")
    stop_openchatcut()
    time.sleep(1)
    start_openchatcut()


@_serialized
def start_voiceforge_worker():
    global _voiceforge_worker_process, _voiceforge_worker_start_time
    with _lock:
        if _voiceforge_worker_process is not None and _voiceforge_worker_process.poll() is None:
            print("[Manager] VoiceForge worker already running, skipping start")
            return
    prepared = _prepare_local_runtime()
    if prepared is None:
        return
    python_exe, env = prepared
    project_root = _project_root()
    concurrency = _voiceforge_worker_concurrency(env)
    if _worker_available(
        python_exe,
        env,
        project_root,
        VOICEFORGE_WORKER_QUEUES,
        "backend.voiceforge.tasks.celery_app",
    ):
        # 残留 worker 的 --concurrency 是启动时冻结的旧值，不会随设置变更
        # （历史上硬编码 5，与 voiceforge.synthesis.concurrency 脱节）；也可能残留
        # 多个 worker 使实际总并发翻倍。只要并发度与配置不一致或 worker 数量超过
        # 1 个，就软停全部并拉起单个新 worker，确保投递层与执行层口径一致。
        existing = _existing_voiceforge_concurrency()
        if existing and (any(v != concurrency for v in existing) or len(existing) > 1):
            print(
                f"[Manager] Existing VoiceForge worker(s) concurrency={existing} "
                f"!= expected [{concurrency}], recycling worker(s) to apply config"
            )
            if not _recycle_voiceforge_workers(python_exe, env, project_root):
                print("[Manager] VoiceForge worker 回收超时，仍按新并发拉起（旧 worker 可能仍在运行）")
        else:
            print("[Manager] VoiceForge worker queues already have a consumer, skipping start")
            return
    cmd = [
        python_exe, "-m", "celery", "-A", "backend.voiceforge.tasks.celery_app.celery_app",
        "worker", "--loglevel=INFO", "--hostname=voiceforge@%h", "--pool=threads", f"--concurrency={concurrency}", "--queues=voiceforge_synthesis,voiceforge_voice,voiceforge_export",
    ]
    try:
        proc = subprocess.Popen(cmd, cwd=project_root, env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        _assign_to_job(proc)
        with _lock:
            _voiceforge_worker_process = proc
            _voiceforge_worker_start_time = time.time()
        _desired["voiceforge_worker"] = True
        print(f"[Manager] VoiceForge worker started PID={proc.pid}")
    except Exception as exc:
        print(f"[Manager] Failed to start VoiceForge worker: {exc}")


def _celery_warm_shutdown(timeout: int = 30, hostname_prefix: str = "control-plane@") -> bool:
    """通过 Celery control 协议请求 worker 暖停机（完成在途任务后退出）。

    必须定向广播（destination）：control-plane 与 voiceforge worker 共用同一 broker，
    无差别的 `celery control shutdown` 会把 voiceforge worker 也一并杀掉（表现为
    一键重启后 voiceforge 掉线、被看门狗重新拉起）。
    另外 shutdown 是"收到即退"，worker 不会回复，因此不走会等回复的 CLI（其必然
    报 "No nodes replied within time constraint"），直接用 broadcast API 下发。

    hostname_prefix 限定目标 worker 节点名前缀（control-plane@ / voiceforge@），
    对跨会话残留进程同样有效（按节点名寻址，不依赖 manager 持有的进程句柄）。

    返回 True 表示指令已成功下发；失败（broker 不可达、无存活节点等）返回 False。
    """
    try:
        python_exe = _get_python()
        env = _setup_env()
        warm_shutdown_code = (
            "from backend.control_plane.celery_runtime import celery_app as app\n"
            "ping = app.control.inspect(timeout=10).ping() or {}\n"
            f"targets = [n for n in ping if str(n).startswith({hostname_prefix!r})]\n"
            "print('warm-shutdown targets:', targets)\n"
            "if not targets:\n"
            "    raise SystemExit(2)\n"
            "app.control.broadcast('shutdown', destination=targets)\n"
        )
        result = subprocess.run(
            [python_exe, "-c", warm_shutdown_code],
            cwd=_project_root(),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"[Manager] Celery 暖停机指令返回非零: {(result.stderr or result.stdout).strip()[:200]}")
            return False
        return True
    except Exception as exc:
        print(f"[Manager] Celery 暖停机指令失败（将回退为信号方式）: {exc}")
        return False


def _soft_signal_shutdown(proc) -> None:
    """向进程组发送软停机信号：Windows 用 Ctrl+C，POSIX 用 SIGTERM，触发 Celery 暖停机。"""
    try:
        if os.name == "nt":
            # worker 以 CREATE_NEW_PROCESS_GROUP 启动，属于独立进程组，可直接发送 Ctrl+C
            os.kill(proc.pid, signal.CTRL_C_EVENT)
        else:
            os.kill(proc.pid, signal.SIGTERM)
    except Exception as exc:
        print(f"[Manager] 发送软停机信号失败: {exc}")


def _wait_for_exit(proc, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(1)
    return proc.poll() is not None


VOICEFORGE_WORKER_QUEUES = {"voiceforge_synthesis", "voiceforge_voice", "voiceforge_export"}
# VoiceForge worker 软停机等待在途任务完成的超时（秒，可调）
VOICEFORGE_SOFT_SHUTDOWN_TIMEOUT = int(os.environ.get("VOICEFORGE_SOFT_SHUTDOWN_TIMEOUT", "300"))


def _voiceforge_worker_concurrency(env: dict[str, str]) -> int:
    """从配置读取 VoiceForge worker 并发数（voiceforge.synthesis.concurrency）。

    与任务泵 pump_pending_tasks / 本地线程池共用同一配置与钳制范围，保证
    投递层与执行层口径一致；读取失败时回退到环境变量或默认 3。
    """
    try:
        from backend.voiceforge.task_defaults import synthesis_concurrency

        return synthesis_concurrency()
    except Exception as exc:
        # 不再静默吞异常：读取失败时打印原因，避免冷启动 worker 并发悄悄回退默认值
        print(f"[Manager] Failed to read voiceforge.synthesis.concurrency: {exc!r}, falling back")
    try:
        return max(1, int(env.get("VOICEFORGE_CONCURRENCY", "3")))
    except (ValueError, TypeError):
        return 3


def _existing_voiceforge_concurrency() -> list[int]:
    """查询当前在跑的 VoiceForge worker 实际并发度（--concurrency）；查询失败返回空列表。

    用于冷启动时核对"残留 worker"的并发是否与 voiceforge.synthesis.concurrency 一致：
    worker 的并发是启动时冻结的旧值，残留进程不会感知配置变更，需回收重启才能生效。
    """
    try:
        from backend.voiceforge.tasks.celery_app import celery_app

        if celery_app is None:
            return []
        # 注意：voiceforge 与 control-plane worker 复用同一 Celery app 与 broker，
        # inspect().stats() 会一并返回，必须先按 active_queues 过滤出消费
        # 配音谷队列的 worker，再取其并发度。
        target = VOICEFORGE_WORKER_QUEUES
        inspect = celery_app.control.inspect(timeout=3)
        stats = inspect.stats() or {}
        active_queues = inspect.active_queues() or {}
        consumers = {
            name
            for name, worker_queues in active_queues.items()
            if {item.get("name") for item in worker_queues} >= target
        }
        values: list[int] = []
        for name in consumers:
            info = stats.get(name)
            pool = info.get("pool") if isinstance(info, dict) else None
            mc = pool.get("max-concurrency") if isinstance(pool, dict) else None
            if mc is None:
                continue
            try:
                values.append(int(mc))
            except (ValueError, TypeError):
                continue
        return values
    except Exception:
        return []


def _recycle_voiceforge_workers(python_exe: str, env: dict[str, str], project_root: str, timeout: float = 120) -> bool:
    """软停机全部消费配音谷队列的 worker（含跨会话残留进程），等待其退出。

    返回 True 表示已无残留消费者，调用方可安全拉起新 worker；False 表示超时
    仍有 worker 在运行（调用方需决定是否强行拉起）。
    """
    # 自己拉起的 worker：软停机（等待在途 TTS 任务完成）
    stop_voiceforge_worker(soft=True)
    # 跨会话残留进程：按节点名广播暖停机（尽力而为，失败也不影响下面的轮询判定）
    _celery_warm_shutdown(hostname_prefix="voiceforge@")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _worker_available(python_exe, env, project_root, VOICEFORGE_WORKER_QUEUES, "backend.voiceforge.tasks.celery_app"):
            return True
        time.sleep(2)
    return False


def _existing_control_plane_concurrency() -> list[int]:
    """查询当前在跑的 control-plane worker 实际并发度（--concurrency）；查询失败返回空列表。

    用于冷启动时核对"残留 worker"的并发是否与配置一致：worker 的并发是启动时
    冻结的旧值，残留进程不会感知配置变更，需回收重启才能生效。
    """
    try:
        from backend.control_plane.celery_runtime import celery_app

        if celery_app is None:
            return []
        # 注意：voiceforge worker 复用同一 Celery app，inspect().stats() 会一并返回，
        # 必须先按 active_queues 过滤出消费 control-plane 队列的 worker，再取其并发度。
        target = {"videolingo_cpu", "videolingo_gpu", "videolingo_llm", "videolingo_tts", "videolingo_io"}
        inspect = celery_app.control.inspect(timeout=3)
        stats = inspect.stats() or {}
        active_queues = inspect.active_queues() or {}
        consumers = {
            name
            for name, worker_queues in active_queues.items()
            if {item.get("name") for item in worker_queues} >= target
        }
        values: list[int] = []
        for name in consumers:
            info = stats.get(name)
            pool = info.get("pool") if isinstance(info, dict) else None
            mc = pool.get("max-concurrency") if isinstance(pool, dict) else None
            if mc is None:
                continue
            try:
                values.append(int(mc))
            except (TypeError, ValueError):
                continue
        return values
    except Exception:
        return []


@_serialized
def start_control_plane_worker():
    global _control_plane_worker_process, _control_plane_worker_start_time
    with _lock:
        if _control_plane_worker_process is not None and _control_plane_worker_process.poll() is None:
            print("[Manager] Control-plane worker already running, skipping start")
            return
    prepared = _prepare_local_runtime()
    if prepared is None:
        return
    python_exe, env = prepared
    project_root = _project_root()
    concurrency = _control_plane_concurrency(env)
    if _worker_available(
        python_exe,
        env,
        project_root,
        {"videolingo_cpu", "videolingo_gpu", "videolingo_llm", "videolingo_tts", "videolingo_io"},
        "backend.control_plane.celery_runtime",
    ):
        # 已有 worker 在消费队列（常见为上一会话残留进程，其 --concurrency 是启动时
        # 冻结的旧值；也可能残留多个 worker 使实际总并发翻倍）。只要并发度与配置不一致
        # 或 worker 数量超过 1 个，就软停全部并拉起单个新 worker，确保启动阶段严格
        # 应用 batch.max_concurrent_tasks；一致则跳过。
        existing = _existing_control_plane_concurrency()
        if existing and (any(v != concurrency for v in existing) or len(existing) > 1):
            print(
                f"[Manager] Existing control-plane worker(s) concurrency={existing} "
                f"!= expected [{concurrency}], recycling worker(s) to apply config"
            )
            stop_control_plane_worker(soft=True)
        else:
            print("[Manager] Control-plane worker queues already have a consumer, skipping start")
            return
    cmd = [python_exe, "-m", "celery", "-A", "backend.control_plane.celery_runtime:celery_app", "worker", "--loglevel=INFO", "--hostname=control-plane@%h", "--pool=threads", f"--concurrency={concurrency}", "--queues=videolingo_cpu,videolingo_gpu,videolingo_llm,videolingo_tts,videolingo_io"]
    try:
        proc = subprocess.Popen(cmd, cwd=project_root, env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        _assign_to_job(proc)
        with _lock:
            _control_plane_worker_process = proc
            _control_plane_worker_start_time = time.time()
        _desired["control_plane_worker"] = True
        print(f"[Manager] Control-plane worker started PID={proc.pid}")
    except Exception as exc:
        print(f"[Manager] Failed to start control-plane worker: {exc}")


@_serialized
def stop_control_plane_worker(soft: bool = False):
    global _control_plane_worker_process, _control_plane_worker_start_time
    _desired["control_plane_worker"] = False
    with _lock:
        proc = _control_plane_worker_process
        _control_plane_worker_process = None
        _control_plane_worker_start_time = 0
    if proc is None or proc.poll() is not None:
        return
    if soft:
        print("[Manager] 软停机 control-plane worker（等待在途任务完成）...")
        # 优先用 Celery control 协议请求暖停机；失败再回退为 OS 信号
        if not _celery_warm_shutdown():
            _soft_signal_shutdown(proc)
        if _wait_for_exit(proc, timeout=CONTROL_PLANE_SOFT_SHUTDOWN_TIMEOUT):
            print("[Manager] control-plane worker 已软停机")
            return
        print("[Manager] 软停机超时，回退为强杀")
    _kill_existing_process(proc)
    print("[Manager] Control-plane worker stopped")


@_serialized
def restart_control_plane_worker(soft: bool = True):
    # 软停机：先让在途任务完成再退出，避免强杀中断任务
    stop_control_plane_worker(soft=soft)
    # stop 已阻塞至进程退出（或已强杀），无需额外 sleep，直接拉起新 worker
    start_control_plane_worker()


def _gpu_service_enabled_in(env: dict[str, str]) -> bool:
    return env.get("GPU_SERVICE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _control_plane_concurrency(env: dict[str, str]) -> int:
    """从 config.yaml 的 batch.max_concurrent_tasks 读取 worker 并发数；异常时回退到环境变量或默认 4。"""
    try:
        from backend.config.config_manager import config as _cfg

        value = _cfg.get("batch.max_concurrent_tasks", 4)
        return max(1, int(value))
    except Exception as exc:
        # 不再静默吞异常：读取失败时打印原因（历史上曾因脚本模式 sys.path 缺项目根
        # 目录而 ModuleNotFoundError，导致冷启动 worker 并发始终回退默认 4）
        print(f"[Manager] Failed to read batch.max_concurrent_tasks from config.yaml: {exc!r}, falling back")
    try:
        return max(1, int(env.get("CELERY_CONTROL_PLANE_CONCURRENCY", "4")))
    except (ValueError, TypeError):
        return 4


@_serialized
def start_gpu_service():
    """启动 GPU 服务层（显存监测 + lane 调度）。未启用 GPU_SERVICE_ENABLED 时跳过。"""
    global _gpu_service_process, _gpu_service_start_time
    with _lock:
        if _gpu_service_process is not None and _gpu_service_process.poll() is None:
            print("[Manager] GPU service already running, skipping start")
            return
    prepared = _prepare_local_runtime()
    if prepared is None:
        return
    python_exe, env = prepared
    project_root = _project_root()
    if not _gpu_service_enabled_in(env):
        print("[Manager] GPU service disabled (GPU_SERVICE_ENABLED not set), skipping start")
        return
    cmd = [python_exe, "-m", "backend.gpu_service.manager"]
    try:
        proc = subprocess.Popen(cmd, cwd=project_root, env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        _assign_to_job(proc)
        with _lock:
            _gpu_service_process = proc
            _gpu_service_start_time = time.time()
        _desired["gpu_service"] = True
        print(f"[Manager] GPU service started PID={proc.pid}")
    except Exception as exc:
        print(f"[Manager] Failed to start GPU service: {exc}")


@_serialized
def stop_gpu_service():
    global _gpu_service_process, _gpu_service_start_time
    _desired["gpu_service"] = False
    with _lock:
        proc = _gpu_service_process
        _gpu_service_process = None
        _gpu_service_start_time = 0
    if proc is not None:
        _kill_existing_process(proc)
        print("[Manager] GPU service stopped")


@_serialized
def restart_gpu_service():
    stop_gpu_service()
    time.sleep(1)
    start_gpu_service()


@_serialized
def stop_voiceforge_worker(soft: bool = False):
    global _voiceforge_worker_process, _voiceforge_worker_start_time
    _desired["voiceforge_worker"] = False
    with _lock:
        proc = _voiceforge_worker_process
        _voiceforge_worker_process = None
        _voiceforge_worker_start_time = 0
    if proc is None or proc.poll() is not None:
        return
    if soft:
        print("[Manager] 软停机 VoiceForge worker（等待在途任务完成）...")
        # 优先用 Celery control 协议请求暖停机；失败再回退为 OS 信号
        if not _celery_warm_shutdown(hostname_prefix="voiceforge@"):
            _soft_signal_shutdown(proc)
        if _wait_for_exit(proc, timeout=VOICEFORGE_SOFT_SHUTDOWN_TIMEOUT):
            print("[Manager] VoiceForge worker 已软停机")
            return
        print("[Manager] 软停机超时，回退为强杀")
    _kill_existing_process(proc)
    print("[Manager] VoiceForge worker stopped")


@_serialized
def restart_voiceforge_worker(soft: bool = True):
    # 软停机：先让在途 TTS 任务完成再退出，避免强杀中断合成
    stop_voiceforge_worker(soft=soft)
    # stop 已阻塞至进程退出（或已强杀），无需额外 sleep，直接拉起新 worker
    start_voiceforge_worker()


@_serialized
def restart_llm_router_only():
    """Restart only the LLM Router."""
    print("[Manager] Restarting LLM Router...")
    stop_llm_router()
    time.sleep(1)
    start_llm_router()


@_serialized
def stop_all():
    """Stop all managed processes."""
    stop_backend()
    stop_social_backend()
    stop_social_frontend()
    stop_social_mcp()
    stop_llm_router()
    stop_openchatcut()
    stop_voiceforge_worker()
    stop_control_plane_worker()
    stop_gpu_service()
    global _redis_process
    if _redis_process is not None:
        _kill_existing_process(_redis_process)
        _redis_process = None


@_serialized
def restart_backend():
    """Restart all backend processes."""
    print("[Manager] Restarting all backends...")
    stop_all()
    time.sleep(1)
    start_backend()
    start_social_backend()
    start_social_frontend()
    start_llm_router()
    start_voiceforge_worker()
    start_control_plane_worker()


def request_manager_shutdown(source: str = "api"):
    """停止所有托管进程并退出 manager 自身。"""
    callback = _manager_shutdown_callback
    if callback is not None:
        callback(source)
        return
    print(f"[Manager] Shutdown callback unavailable, stop_all only (source={source})")
    _shutting_down.set()
    stop_all()


@_serialized
def restart_main_backend():
    """Restart only the main backend."""
    print("[Manager] Restarting main backend...")
    stop_backend()
    time.sleep(1)
    start_backend()


@_serialized
def restart_social_backend_only():
    """Restart only the social backend."""
    print("[Manager] Restarting social backend...")
    stop_social_backend()
    time.sleep(1)
    start_social_backend()


@_serialized
def restart_social_frontend_only():
    """Restart only the social frontend."""
    print("[Manager] Restarting social frontend...")
    stop_social_frontend()
    time.sleep(1)
    start_social_frontend()


@_serialized
def restart_social_mcp_only():
    """Restart only the social MCP."""
    print("[Manager] Restarting social MCP...")
    stop_social_mcp()
    time.sleep(1)
    start_social_mcp()


def _proc_status(proc, start_time, port=None):
    """统一进程状态判定：包装进程存活 / 已退出但端口仍在监听（如 npm→vite）。"""
    if proc is None:
        if port is not None and _check_port(port):
            return {"status": "running", "pid": None, "uptime": 0, "managed": False}
        return {"status": "stopped", "pid": None, "uptime": 0}
    poll = proc.poll()
    if poll is None:
        uptime = time.time() - start_time if start_time else 0
        return {"status": "running", "pid": proc.pid, "uptime": round(uptime, 1), "managed": True}
    else:
        # Process wrapper exited, but the actual server may still be running (e.g. npm→vite)
        if port is not None and _check_port(port):
            return {"status": "running", "pid": proc.pid, "uptime": round(time.time() - start_time, 1) if start_time else 0, "managed": True}
        return {"status": "stopped", "pid": proc.pid, "exitCode": poll, "uptime": 0}


def get_status() -> dict:
    """Get all backend statuses."""
    with _lock:
        main_proc = _backend_process
        social_proc = _social_backend_process
        social_fe_proc = _social_frontend_process
        mcp_proc = _social_mcp_process
        llm_router_proc = _llm_router_process
        openchatcut_proc = _openchatcut_process
        voiceforge_worker_proc = _voiceforge_worker_process
        control_plane_worker_proc = _control_plane_worker_process
        gpu_service_proc = _gpu_service_process

    try:
        import sys as _sys
        _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)
        from backend.pi_rpc import get_pi_manager
        pi_status = get_pi_manager().status()
    except Exception as exc:
        pi_status = {"status": "unavailable", "error": str(exc)[:200], "session_count": 0}

    return {
        "main_backend": {**_proc_status(main_proc, _backend_start_time, BACKEND_PORT), "port": BACKEND_PORT},
        "social_backend": {**_proc_status(social_proc, _social_backend_start_time, SOCIAL_BACKEND_PORT), "port": SOCIAL_BACKEND_PORT},
        "social_frontend": {**_proc_status(social_fe_proc, _social_frontend_start_time, SOCIAL_FRONTEND_PORT), "port": SOCIAL_FRONTEND_PORT},
        "social_mcp": {**_proc_status(mcp_proc, _social_mcp_start_time, SOCIAL_MCP_PORT), "port": SOCIAL_MCP_PORT},
        "llm_router": {**_proc_status(llm_router_proc, _llm_router_start_time, LLM_ROUTER_PORT), "port": LLM_ROUTER_PORT},
        "openchatcut": _openchatcut_status(openchatcut_proc, _openchatcut_start_time),
        "voiceforge_redis": {
            "status": "running" if _check_port(REDIS_PORT) else "stopped",
            "port": REDIS_PORT,
            "managed": False,
            "url": VOICEFORGE_REDIS_URL.rsplit("/", 1)[0],
        },
        "voiceforge_worker": {**_proc_status(voiceforge_worker_proc, _voiceforge_worker_start_time), "port": None},
        "control_plane_worker": {**_proc_status(control_plane_worker_proc, _control_plane_worker_start_time), "port": None},
        "gpu_service": {**_proc_status(gpu_service_proc, _gpu_service_start_time), "port": None},
        "pi_agent": pi_status,
    }


def _openchatcut_status(proc, start_time: float) -> dict:
    """OpenChatCut 状态：端口来自「AI剪辑台」设置，兼容外部启动的实例。"""
    port, enabled = _openchatcut_settings()
    status = _proc_status(proc, start_time)
    if status.get("status") != "running" and _check_port(port):
        status = {"status": "running", "pid": None, "uptime": 0, "managed": False}
    status["port"] = port
    status["enabled"] = enabled
    status["deps"] = os.path.isdir(os.path.join(_openchatcut_dir(), "node_modules"))
    return status


def _check_port(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is in use."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


class ManagerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the manager."""

    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data: dict, status: int = 200):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/manager/status" or self.path == "/api/manager/status":
            self._send_json(get_status())
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path == "/manager/restart" or self.path == "/api/manager/restart":
            self._send_json({"status": "restarting"})
            # Run restart in a thread so we can respond immediately
            threading.Thread(target=restart_backend, daemon=True).start()
        elif self.path == "/manager/restart-main":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_main_backend, daemon=True).start()
        elif self.path == "/manager/restart-social":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_social_backend_only, daemon=True).start()
        elif self.path == "/manager/restart-social-frontend":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_social_frontend_only, daemon=True).start()
        elif self.path == "/manager/restart-mcp":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_social_mcp_only, daemon=True).start()
        elif self.path == "/manager/restart-llm-router":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_llm_router_only, daemon=True).start()
        elif self.path == "/manager/restart-voiceforge-worker":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_voiceforge_worker, daemon=True).start()
        elif self.path == "/manager/restart-control-plane-worker":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_control_plane_worker, daemon=True).start()
        elif self.path == "/manager/start" or self.path == "/api/manager/start":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_backend, daemon=True).start()
        elif self.path == "/manager/start-mcp":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_social_mcp, daemon=True).start()
        elif self.path == "/manager/start-main":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_backend, daemon=True).start()
        elif self.path == "/manager/start-social":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_social_backend, daemon=True).start()
        elif self.path == "/manager/start-social-frontend":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_social_frontend, daemon=True).start()
        elif self.path == "/manager/start-llm-router":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_llm_router, daemon=True).start()
        elif self.path == "/manager/start-openchatcut":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_openchatcut, daemon=True).start()
        elif self.path == "/manager/restart-openchatcut":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_openchatcut_only, daemon=True).start()
        elif self.path == "/manager/stop-openchatcut":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_openchatcut, daemon=True).start()
        elif self.path == "/manager/start-voiceforge-worker":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_voiceforge_worker, daemon=True).start()
        elif self.path == "/manager/start-control-plane-worker":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_control_plane_worker, daemon=True).start()
        elif self.path == "/manager/restart-gpu-service":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_gpu_service, daemon=True).start()
        elif self.path == "/manager/start-gpu-service":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_gpu_service, daemon=True).start()
        elif self.path == "/manager/stop-gpu-service":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_gpu_service, daemon=True).start()
        elif self.path == "/manager/stop" or self.path == "/api/manager/stop":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_backend, daemon=True).start()
        elif self.path == "/manager/stop-main":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_backend, daemon=True).start()
        elif self.path == "/manager/stop-social":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_social_backend, daemon=True).start()
        elif self.path == "/manager/stop-social-frontend":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_social_frontend, daemon=True).start()
        elif self.path == "/manager/stop-mcp":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_social_mcp, daemon=True).start()
        elif self.path == "/manager/stop-llm-router":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_llm_router, daemon=True).start()
        elif self.path == "/manager/stop-voiceforge-worker":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_voiceforge_worker, daemon=True).start()
        elif self.path == "/manager/stop-control-plane-worker":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_control_plane_worker, daemon=True).start()
        elif self.path == "/manager/shutdown-all" or self.path == "/api/manager/shutdown-all":
            self._send_json({"status": "shutting_down"})
            threading.Thread(target=request_manager_shutdown, args=("api",), daemon=True).start()
        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


def _start_all_services():
    """并行拉起全部托管服务（main 启动路径专用）。

    各服务相互独立，直接执行未加操作锁的原始函数（functools.wraps 保留的 __wrapped__）：
    启动路径由 main 单线程触发，无并发竞态；API/watchdog 等并发入口仍走带锁版本。
    """
    starters = (
        start_backend,
        start_social_backend,
        start_social_frontend,
        start_llm_router,
        start_openchatcut,
        start_voiceforge_worker,
        start_control_plane_worker,
        start_gpu_service,
    )
    threads = []
    for starter in starters:
        target = getattr(starter, "__wrapped__", starter)
        thread = threading.Thread(target=target, name=f"manager-start-{starter.__name__}", daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


def main():
    global _job_handle, _manager_shutdown_callback
    if _check_port(MANAGER_PORT):
        print(f"[Manager] Port {MANAGER_PORT} is already in use; another Manager may be running")
        return 1

    # 孤儿兜底：先建 kill-on-close Job Object（失败自动降级为原有行为）
    _job_handle = _create_windows_job()

    # 统一线程异常钩子：后台管理代码出错只记录日志，不影响端口管理
    def _thread_excepthook(args):
        thread_name = getattr(args.thread, "name", "?")
        print(f"[Manager] Unhandled exception in thread {thread_name}: {args.exc_type.__name__}: {args.exc_value}")
    threading.excepthook = _thread_excepthook

    if _prepare_local_runtime() is None:
        return 1

    env = _setup_env()
    listener_host = _listener_host(env)
    print("=" * 50)
    print("  VideoLingoFlow Manager")
    print(f"  Manager port : {MANAGER_PORT}")
    print(f"  Backend port : {BACKEND_PORT}")
    print(f"  API listener : {listener_host}:{BACKEND_PORT}")
    print(f"  Manager listener : {LOCAL_HOST}:{MANAGER_PORT}")
    print(f"  LLM Router   : {LLM_ROUTER_PORT}")
    print(f"  OpenChatCut  : {_openchatcut_settings()[0]}")
    print(f"  VoiceForge Redis : {VOICEFORGE_REDIS_URL}")
    if _lan_mode_enabled(env):
        print("  WARNING: LAN mode has no authentication or TLS; trusted LAN only.")
    print("=" * 50)

    server = HTTPServer((LOCAL_HOST, MANAGER_PORT), ManagerHandler)
    print(f"[Manager] Listening on http://{LOCAL_HOST}:{MANAGER_PORT}")

    # Start backends on launch (social_mcp is not started by default and can be started manually from frontend)
    _start_all_services()

    # 健康监督：期望运行却崩溃的服务自动拉起（每 10s 探测，30s 冷却防重启风暴）
    threading.Thread(target=_watchdog_loop, name="manager-watchdog", daemon=True).start()

    shutdown_started = threading.Event()

    def _shutdown(source: str):
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        _shutting_down.set()
        print(f"\n[Manager] Shutting down (source={source})...")
        stop_all()
        server.shutdown()

    _manager_shutdown_callback = _shutdown

    def _handle_signal(signum, _frame):
        source = signal.Signals(signum).name
        threading.Thread(target=_shutdown, args=(source,), daemon=True).start()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _shutdown("KeyboardInterrupt")
    finally:
        _manager_shutdown_callback = None


if __name__ == "__main__":
    raise SystemExit(main() or 0)
