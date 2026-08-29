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

MANAGER_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18001
BACKEND_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 11001
SOCIAL_BACKEND_PORT = 5409
SOCIAL_FRONTEND_PORT = 5173
SOCIAL_MCP_PORT = 5410
LLM_ROUTER_PORT = 8800
CUTIA_PORT = 4100
REDIS_PORT = 6379
REDIS_BIN_DIR = os.environ.get("VOICEFORGE_REDIS_BIN", r"C:\Program Files\Redis")
VOICEFORGE_REDIS_URL = os.environ.get("VOICEFORGE_REDIS_URL", f"redis://127.0.0.1:{REDIS_PORT}/2")
VOICEFORGE_CELERY_RESULT_URL = os.environ.get("VOICEFORGE_CELERY_RESULT_URL", f"redis://127.0.0.1:{REDIS_PORT}/3")
LOCAL_HOST = "127.0.0.1"
LAN_HOST = "0.0.0.0"
# 隐藏窗口创建标志：新进程无控制台窗口（区别于 CREATE_NEW_CONSOLE 的可见新窗口）
CREATE_HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

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
_cutia_process: subprocess.Popen | None = None
_cutia_start_time: float = 0
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
    _last_auto_restart[name] = now
    print(f"[Manager] Watchdog restarting {name}...")
    starter()


def _watchdog_tick():
    """健康监督：仅对"期望运行但已崩溃"的服务自动拉起；主动停止的服务不干预。"""
    checks = [
        ("main_backend", _backend_process, start_backend, BACKEND_PORT),
        ("social_backend", _social_backend_process, start_social_backend, SOCIAL_BACKEND_PORT),
        ("social_frontend", _social_frontend_process, start_social_frontend, SOCIAL_FRONTEND_PORT),
        ("social_mcp", _social_mcp_process, start_social_mcp, SOCIAL_MCP_PORT),
        ("llm_router", _llm_router_process, start_llm_router, LLM_ROUTER_PORT),
        ("cutia", _cutia_process, start_cutia, CUTIA_PORT),
        ("voiceforge_worker", _voiceforge_worker_process, start_voiceforge_worker, None),
        ("control_plane_worker", _control_plane_worker_process, start_control_plane_worker, None),
        ("gpu_service", _gpu_service_process, start_gpu_service, None),
    ]
    for name, proc, starter, port in checks:
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
        env=env,
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
        timeout=90,
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
        env=env,
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
                    cwd=project_root, env=env, timeout=120, capture_output=True, text=True,
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
            creationflags=CREATE_HIDDEN if os.name == "nt" else 0,
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
            capture_output=True, text=True, timeout=10,
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
                timeout=10,
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
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
                timeout=10,
            )
            return result.stdout.strip().lower().replace("/", "\\")
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=10,
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


@_serialized
def start_cutia():
    """Start the Cutia editor on port 4100."""
    global _cutia_process, _cutia_start_time

    with _lock:
        if _cutia_process is not None and _cutia_process.poll() is None:
            print("[Manager] Cutia already running, skipping start")
            return

    if _check_port(CUTIA_PORT):
        print("[Manager] Cutia port is already in use, skipping start")
        return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cutia_dir = os.path.join(project_root, "thirdparty", "cutia", "apps", "web")
    if not os.path.isdir(cutia_dir):
        print("[Manager] Cutia directory not found, skipping")
        return

    bun_cmd = os.environ.get("BUN_CMD", "bun")
    # Use 'dev:web' from monorepo root which uses turbo to run @cutia/web dev
    cutia_root = os.path.join(project_root, "thirdparty", "cutia")
    print(f"[Manager] Starting Cutia: bun run dev:web (port {CUTIA_PORT})")
    try:
        if os.name == "nt":
            # Windows: 隐藏窗口启动 cmd（bun dev:web 在前台运行，无可见控制台窗口）
            cmd = f'cmd /K "cd /d "{cutia_root}" && "{bun_cmd}" run dev:web"'
            proc = subprocess.Popen(
                cmd,
                cwd=cutia_root,
                env=os.environ.copy(),
                shell=True,
                creationflags=CREATE_HIDDEN,
            )
        else:
            # POSIX (Linux/macOS): 直接以 argv 列表启动, 无需 shell
            proc = subprocess.Popen(
                [bun_cmd, "run", "dev:web"],
                cwd=cutia_root,
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        _assign_to_job(proc)
        with _lock:
            _cutia_process = proc
            _cutia_start_time = time.time()
        _desired["cutia"] = True
        print(f"[Manager] Cutia started, PID={proc.pid}")
    except Exception as e:
        print(f"[Manager] Failed to start Cutia: {e}")


def _get_cutia_listener_pid() -> int | None:
    """返回监听 CUTIA_PORT 的进程 PID (跨平台)。"""
    try:
        if os.name == "nt":
            output = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].rsplit(":", 1)[-1] == str(CUTIA_PORT):
                    return int(parts[-1])
        else:
            # POSIX: 优先 lsof, 回退 ss
            for cmd in (
                ["lsof", "-iTCP", f":{CUTIA_PORT}", "-sTCP:LISTEN", "-t"],
                ["ss", "-ltnp", f"sport = :{CUTIA_PORT}"],
            ):
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    continue
                for token in result.stdout.split():
                    if token.isdigit():
                        return int(token)
    except Exception:
        return None
    return None


def _is_cutia_process(pid: int | None) -> bool:
    """判断 PID 是否为 cutia (apps/web, 含 next) 进程 (跨平台)。"""
    if pid is None:
        return False
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
                timeout=10,
            )
            command_line = result.stdout.strip().lower().replace("/", "\\")
        else:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "args="],
                capture_output=True,
                text=True,
                timeout=10,
            )
            command_line = result.stdout.strip().lower()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).lower()
        cutia_dir = os.path.join(project_root, "thirdparty", "cutia", "apps", "web").lower()
        return cutia_dir in command_line and "next" in command_line
    except Exception:
        return False


def _stop_external_cutia() -> bool:
    pid = _get_cutia_listener_pid()
    if not _is_cutia_process(pid):
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


@_serialized
def stop_cutia():
    """Stop the Cutia process managed by this manager."""
    global _cutia_process, _cutia_start_time
    _desired["cutia"] = False

    with _lock:
        proc = _cutia_process
        _cutia_process = None
        _cutia_start_time = 0

    if proc is None:
        if not _stop_external_cutia():
            print("[Manager] No controllable Cutia process to stop")
            return
    else:
        print(f"[Manager] Stopping Cutia PID={proc.pid}...")
        _kill_existing_process(proc)
    for _ in range(20):
        if _check_port(CUTIA_PORT):
            time.sleep(0.5)
        else:
            break
    print("[Manager] Cutia stopped")


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
    try:
        if _worker_available(
            python_exe,
            env,
            project_root,
            {"voiceforge_synthesis", "voiceforge_voice", "voiceforge_export"},
            "backend.voiceforge.tasks.celery_app",
        ):
            print("[Manager] VoiceForge worker queues already have a consumer, skipping start")
            return
        cmd = [
            python_exe, "-m", "celery", "-A", "backend.voiceforge.tasks.celery_app.celery_app",
            "worker", "--loglevel=INFO", "--hostname=voiceforge@%h", "--pool=threads", "--concurrency=5", "--queues=voiceforge_synthesis,voiceforge_voice,voiceforge_export",
        ]
        proc = subprocess.Popen(cmd, cwd=project_root, env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        _assign_to_job(proc)
        with _lock:
            _voiceforge_worker_process = proc
            _voiceforge_worker_start_time = time.time()
        _desired["voiceforge_worker"] = True
        print(f"[Manager] VoiceForge worker started PID={proc.pid}")
    except Exception as exc:
        print(f"[Manager] Failed to start VoiceForge worker: {exc}")


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
    if _worker_available(
        python_exe,
        env,
        project_root,
        {"videolingo_cpu", "videolingo_gpu", "videolingo_llm", "videolingo_tts", "videolingo_io"},
        "backend.control_plane.celery_runtime",
    ):
        print("[Manager] Control-plane worker queues already have a consumer, skipping start")
        return
    concurrency = env.get("CELERY_CONTROL_PLANE_CONCURRENCY", "4")
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
def stop_control_plane_worker():
    global _control_plane_worker_process, _control_plane_worker_start_time
    _desired["control_plane_worker"] = False
    with _lock:
        proc = _control_plane_worker_process
        _control_plane_worker_process = None
        _control_plane_worker_start_time = 0
    if proc is not None:
        _kill_existing_process(proc)
        print("[Manager] Control-plane worker stopped")


@_serialized
def restart_control_plane_worker():
    stop_control_plane_worker()
    time.sleep(1)
    start_control_plane_worker()


def _gpu_service_enabled_in(env: dict[str, str]) -> bool:
    return env.get("GPU_SERVICE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


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
def stop_voiceforge_worker():
    global _voiceforge_worker_process, _voiceforge_worker_start_time
    _desired["voiceforge_worker"] = False
    with _lock:
        proc = _voiceforge_worker_process
        _voiceforge_worker_process = None
        _voiceforge_worker_start_time = 0
    if proc is not None:
        _kill_existing_process(proc)
        print("[Manager] VoiceForge worker stopped")


@_serialized
def restart_voiceforge_worker():
    stop_voiceforge_worker()
    time.sleep(1)
    start_voiceforge_worker()


@_serialized
def restart_cutia_only():
    """Restart only the Cutia editor."""
    print("[Manager] Restarting Cutia...")
    stop_cutia()
    time.sleep(1)
    start_cutia()


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
    stop_cutia()
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
    start_cutia()
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


def get_status() -> dict:
    """Get all backend statuses."""
    with _lock:
        main_proc = _backend_process
        social_proc = _social_backend_process
        social_fe_proc = _social_frontend_process
        mcp_proc = _social_mcp_process
        llm_router_proc = _llm_router_process
        cutia_proc = _cutia_process
        voiceforge_worker_proc = _voiceforge_worker_process
        control_plane_worker_proc = _control_plane_worker_process
        gpu_service_proc = _gpu_service_process

    def _proc_status(proc, start_time, port=None):
        if proc is None:
            if port is not None and _check_port(port):
                pid = _get_cutia_listener_pid() if port == CUTIA_PORT else None
                return {
                    "status": "running",
                    "pid": pid,
                    "uptime": 0,
                    "managed": port == CUTIA_PORT and _is_cutia_process(pid),
                }
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
        "cutia": {**_proc_status(cutia_proc, _cutia_start_time, CUTIA_PORT), "port": CUTIA_PORT},
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
        elif self.path == "/manager/restart-cutia":
            self._send_json({"status": "restarting"})
            threading.Thread(target=restart_cutia_only, daemon=True).start()
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
        elif self.path == "/manager/start-cutia":
            self._send_json({"status": "starting"})
            threading.Thread(target=start_cutia, daemon=True).start()
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
        elif self.path == "/manager/stop-cutia":
            self._send_json({"status": "stopping"})
            threading.Thread(target=stop_cutia, daemon=True).start()
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
        start_cutia,
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
    print(f"  Cutia        : {CUTIA_PORT}")
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
