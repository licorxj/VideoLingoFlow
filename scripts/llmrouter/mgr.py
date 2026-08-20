#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LocalRouter 第三方项目管理脚本 (VideoLingoFlow)

本脚本位于 VideoLingoFlow 自身仓库 (scripts/llmrouter), 不修改第三方项目文件,
因此第三方项目的 git pull / git update 永远不会破坏本管理逻辑。

运行方式与主项目管理器 (backend/manager.py) 完全对齐:
    - 后端环境: 复用主项目共享 venv (venv312), 不创建独立虚拟环境
    - 后端端口: 8800 (与主项目 LLM_ROUTER_PORT 一致)
    - 后端进程: 复用 manager._setup_env() 构造环境 (CUDA/模型缓存/venv 路径)

系统会自动识别 Windows / Linux / macOS 并使用相应的分支代码。

子命令:
    start    启动 LocalRouter (后端 + 前端)
    update   更新第三方项目 (git pull -> 增量迁移数据库 -> 重装依赖)
    status   显示服务运行状态
    stop     停止所有服务

数据库策略:
    - 初始化与更新均调用第三方自带的 app.database.init_db(),
      其内部使用 create_all + _add_missing_columns 做 "增量迁移",
      只会补齐缺失的表和列, 永远不会清空或覆盖已有数据。
    - 数据文件 backend/data/app.db 始终保留, 不受 git 更新影响。
"""

import os
import sys
import json
import shutil
import signal
import socket
import subprocess
import platform
import webbrowser
from pathlib import Path

# 主项目 backend 包路径, 用于复用其环境构造 (_setup_env / _get_python)
PROJECT_ROOT_STR = None  # 在下方常量段赋值
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ---------- 路径解析 ----------
# SCRIPT_DIR = scripts/llmrouter
SCRIPT_DIR = Path(__file__).resolve().parent
# PROJECT_ROOT = VideoLingoFlow 仓库根
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PROJECT_ROOT_STR = str(PROJECT_ROOT)
# THIRD_PARTY = VideoLingoFlow/thirdparty/QM-LocalRouter
THIRD_PARTY = PROJECT_ROOT / "thirdparty" / "QM-LocalRouter"
BACKEND_DIR = THIRD_PARTY / "backend"
FRONTEND_DIR = THIRD_PARTY / "frontend"
DATA_DIR = BACKEND_DIR / "data"
DB_FILE = DATA_DIR / "app.db"
# 共享主项目 venv (与主项目 manager.py 一致, 避免双环境)
VENV_DIR = PROJECT_ROOT / "venv312"
RUN_DIR = SCRIPT_DIR / "run"

# 端口对齐主项目管理器 (manager.py 中 LLM_ROUTER_PORT = 8800)
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8800"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "12001"))

# ---------- 系统识别 ----------
SYSTEM = platform.system().lower()  # "windows" / "linux" / "darwin"
IS_WINDOWS = SYSTEM == "windows"

PID_FILES = {
    "backend": RUN_DIR / "backend.pid",
    "frontend": RUN_DIR / "frontend.pid",
}


def log(msg: str):
    print(f"  >> {msg}")


def step(title: str):
    print(f"\n[ {title} ]")


# ---------- 跨平台命令构造 ----------
def venv_python() -> str:
    """返回共享主项目 venv (venv312) 中的 python 解释器路径。"""
    if IS_WINDOWS:
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def venv_python_exists() -> bool:
    return Path(venv_python()).is_file()


def manager_helpers():
    """动态导入主项目 manager 的环境/解释器助手 (保护 sys.argv, 避免顶层端口解析崩溃)。"""
    import importlib.util

    saved_argv = sys.argv[:]
    try:
        sys.argv = ["manager.py"]  # 避免 int(sys.argv[1]) 崩溃
        spec = importlib.util.spec_from_file_location(
            "main_manager",
            os.path.join(str(PROJECT_ROOT), "backend", "manager.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._setup_env, mod._get_python
    finally:
        sys.argv = saved_argv


def port_in_use(port: int) -> bool:
    """检测端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_cmd(pid: int) -> list:
    if IS_WINDOWS:
        return ["taskkill", "/F", "/PID", str(pid)]
    return ["kill", "-9", str(pid)]


def is_pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        # tasklist 返回退出码 0 表示存在
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return str(pid) in r.stdout.decode(errors="ignore")
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def npm_run(args: list, cwd: str, **kwargs):
    """跨平台运行 npm 命令 (Windows 上 npm 是 npm.cmd, 需 shell=True)。"""
    return subprocess.run(
        ["npm"] + args,
        cwd=cwd,
        shell=IS_WINDOWS,
        **kwargs,
    )


# ---------- PID 管理 ----------
def read_pid(name: str):
    p = PID_FILES.get(name)
    if not p or not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except Exception:
        return None


def write_pid(name: str, pid: int):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILES[name].write_text(str(pid))


def cleanup_pid(name: str):
    p = PID_FILES.get(name)
    if p and p.exists():
        p.unlink()


def is_running(name: str) -> bool:
    pid = read_pid(name)
    if pid is None:
        return False
    if is_pid_alive(pid):
        return True
    cleanup_pid(name)
    return False


def stop_process(name: str):
    pid = read_pid(name)
    if pid and is_pid_alive(pid):
        log(f"Stopping {name} (PID: {pid})...")
        subprocess.run(kill_cmd(pid), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cleanup_pid(name)


# ---------- 环境检查 / 初始化 ----------
def check_venv_and_deps() -> bool:
    """确保共享主项目 venv (venv312) 存在且依赖已安装。返回 True 表示就绪。"""
    step("环境检查")
    if not THIRD_PARTY.exists():
        log(f"第三方项目目录不存在: {THIRD_PARTY}")
        log("请先通过 git 克隆 QM-LocalRouter 到 thirdparty/QM-LocalRouter")
        return False

    # 共享主项目 venv 必须已存在 (由主项目初始化创建); 不在此创建独立 venv
    if not venv_python_exists():
        log(f"未检测到主项目共享 venv: {venv_python()}")
        log("请先启动主项目后端 (start.bat) 完成 venv312 的创建与初始化。")
        return False

    # 安装/更新后端依赖 (装进共享 venv, 与主项目一致)
    req = BACKEND_DIR / "requirements.txt"
    if req.exists():
        log("检查后端依赖 (缺失时安装到共享 venv)...")
        pip = str(VENV_DIR / ("Scripts/pip.exe" if IS_WINDOWS else "bin/pip"))
        subprocess.run([pip, "install", "-r", str(req), "-q"], check=False)

    # 兜底: 第三方 requirements.txt 可能遗漏运行时依赖 (如 Pillow 被 icons 路由使用,
    # python-multipart 被文件上传路由使用)。此步骤保证即使上游依赖清单不全, 服务也能启动。
    EXTRA_DEPS = [
        ("PIL", "Pillow"),
        ("multipart", "python-multipart"),
    ]
    log("检查缺失的运行时依赖...")
    pip = str(VENV_DIR / ("Scripts/pip.exe" if IS_WINDOWS else "bin/pip"))
    for import_name, pkg_name in EXTRA_DEPS:
        try:
            subprocess.run([venv_python(), "-c", f"import {import_name}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError:
            log(f"补装 {pkg_name} ...")
            subprocess.run([pip, "install", pkg_name, "-q"], check=True)
    return True


def ensure_env_file():
    env = BACKEND_DIR / ".env"
    if env.exists():
        return
    log("创建默认 .env 文件...")
    env.write_text(
        "APP_NAME=LLM API Router\n"
        "APP_VERSION=1.0.0\n"
        "HOST=127.0.0.1\n"
        f"BACKEND_PORT={BACKEND_PORT}\n"
        f"DATABASE_URL=sqlite+aiosqlite:///{DATA_DIR / 'app.db'}\n"
        "LOG_RETENTION_DAYS=30\n"
        "DEFAULT_TIMEOUT=120\n"
        "DEFAULT_RETRY_COUNT=2\n",
        encoding="utf-8",
    )


def ensure_data_dirs():
    for d in (DATA_DIR, DATA_DIR / "backups", DATA_DIR / "icons"):
        d.mkdir(parents=True, exist_ok=True)


def need_db_init() -> bool:
    """数据库是否需要初始化: 文件不存在即需要。"""
    return not DB_FILE.exists()


def init_db(incremental: bool = True):
    """
    调用第三方自带的 app.database.init_db() 做增量迁移。
    incremental=True 时仅当数据库文件不存在才创建 (保留已有数据);
    更新流程中始终以 incremental=True 调用, 安全补齐新列。
    """
    step("数据库初始化 / 增量迁移")
    if not incremental and DB_FILE.exists():
        log("增量模式下跳过已有数据库, 保留原始数据。")
        return

    if DB_FILE.exists():
        log(f"数据库已存在: {DB_FILE}")
        log("执行增量迁移 (补齐缺失的表/列, 不清除数据)...")
    else:
        log("数据库不存在, 首次初始化...")

    env = os.environ.copy()
    env.setdefault("BACKEND_PORT", str(BACKEND_PORT))
    env.setdefault("HOST", "127.0.0.1")

    # 用临时脚本文件执行, 支持多行 async 语法 (跨平台一致)
    tmp_script = RUN_DIR / "_init_db_tmp.py"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    backend_path = str(BACKEND_DIR).replace("\\", "\\\\")
    tmp_script.write_text(
        "import asyncio, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "from app.database import init_db, engine\n"
        "async def _main():\n"
        "    await init_db()\n"
        "    await engine.dispose()\n"
        "asyncio.run(_main())\n" % backend_path,
        encoding="utf-8",
    )
    try:
        subprocess.run([venv_python(), str(tmp_script)], cwd=str(BACKEND_DIR),
                       env=env, check=True)
    finally:
        if tmp_script.exists():
            tmp_script.unlink()
    log("数据库就绪。")


# ---------- 服务启动 / 停止 ----------
def start_backend():
    if is_running("backend"):
        log(f"Backend 已在运行 (PID: {read_pid('backend')})")
        return
    # 端口若已被占用 (如主项目 manager 已启动 LLM Router), 视为已在运行
    if port_in_use(BACKEND_PORT):
        log(f"端口 {BACKEND_PORT} 已被占用, Backend 可能已由主项目启动, 跳过独立启动。")
        return
    log(f"启动 Backend (uvicorn) 端口 {BACKEND_PORT} (共享 venv)...")
    try:
        setup_env, get_python = manager_helpers()
        py_exe = get_python()
        env = setup_env()
    except Exception as e:
        log(f"无法加载主项目 manager 环境配置: {e}")
        py_exe = venv_python()
        env = os.environ.copy()
    env["BACKEND_PORT"] = str(BACKEND_PORT)
    p = subprocess.Popen(
        [py_exe, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=(RUN_DIR / "backend.log").open("a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=(subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0),
    )
    write_pid("backend", p.pid)
    log(f"Backend 已启动 (PID: {p.pid})")


def start_frontend():
    if is_running("frontend"):
        log(f"Frontend 已在运行 (PID: {read_pid('frontend')})")
        return
    if not (FRONTEND_DIR / "node_modules").exists():
        log("前端依赖未安装, 正在 npm install...")
        npm_run(["install"], cwd=str(FRONTEND_DIR), check=True)
    log(f"启动 Frontend (Vite) 端口 {FRONTEND_PORT}...")
    env = os.environ.copy()
    env["FRONTEND_PORT"] = str(FRONTEND_PORT)
    if IS_WINDOWS:
        p = subprocess.Popen(
            ["cmd", "/c", f"set FRONTEND_PORT={FRONTEND_PORT} && npm run dev"],
            cwd=str(FRONTEND_DIR),
            stdout=(RUN_DIR / "frontend.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
    else:
        p = subprocess.Popen(
            [npm_cmd(), "run", "dev"],
            cwd=str(FRONTEND_DIR),
            env=env,
            stdout=(RUN_DIR / "frontend.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
    write_pid("frontend", p.pid)
    log(f"Frontend 已启动 (PID: {p.pid})")


def stop_all():
    step("停止所有服务")
    stop_process("frontend")
    stop_process("backend")
    log("全部已停止。")


# ---------- 子命令实现 ----------
def cmd_start():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if not check_venv_and_deps():
        sys.exit(1)
    ensure_data_dirs()
    ensure_env_file()
    if need_db_init():
        init_db(incremental=True)
    else:
        # 已存在也执行一次增量迁移, 保证结构最新 (不清除数据)
        init_db(incremental=True)

    start_backend()
    start_frontend()

    print("\n" + "=" * 50)
    print("  LocalRouter 已启动 (共享主项目 venv)")
    print(f"  Frontend: http://localhost:{FRONTEND_PORT}")
    print(f"  Backend:  http://localhost:{BACKEND_PORT}")
    print(f"  Docs:     http://localhost:{BACKEND_PORT}/docs")
    print("=" * 50)
    try:
        webbrowser.open(f"http://localhost:{FRONTEND_PORT}")
    except Exception:
        pass


def cmd_update():
    step("更新第三方项目 (QM-LocalRouter)")
    if not THIRD_PARTY.exists():
        log(f"第三方项目目录不存在: {THIRD_PARTY}")
        sys.exit(1)

    # 0. 分发版：释放随仓库携带的 git 归档（若子项目缺 .git），保证可 git 更新
    if not (THIRD_PARTY / ".git").is_dir():
        try:
            subprocess.run([sys.executable, str(THIRD_PARTY.parent / "git_restore.py")], check=True)
        except Exception as e:
            log(f"git 元数据释放失败（继续走全新初始化）: {e}")

    # 1. git 拉取 (保留本地数据, 因为 app.db 在 data/ 下通常不被 git 跟踪)
    log("执行 git pull (保留本地数据)...")
    try:
        subprocess.run(["git", "-C", str(THIRD_PARTY), "pull", "--ff-only"], check=True)
    except subprocess.CalledProcessError:
        log("git pull 失败 (可能是本地改动冲突), 尝试普通 pull...")
        subprocess.run(["git", "-C", str(THIRD_PARTY), "pull"], check=True)

    # 2. 确保环境/依赖最新
    if not check_venv_and_deps():
        sys.exit(1)

    # 3. 增量迁移数据库 (关键: 不覆盖已有数据)
    ensure_data_dirs()
    ensure_env_file()
    init_db(incremental=True)

    # 4. 同步前端依赖 (更新可能改动 package.json)
    if (FRONTEND_DIR / "package.json").exists():
        log("同步前端依赖...")
        npm_run(["install"], cwd=str(FRONTEND_DIR), check=True)

    print("\n" + "=" * 50)
    print("  更新完成")
    print("  数据库已增量迁移, 原始数据已保留。")
    print("  如需生效, 请重启服务: 先 stop 再 start。")
    print("=" * 50)


def cmd_status():
    step("服务状态")
    for name in ("backend", "frontend"):
        if is_running(name):
            print(f"  {name:10s} RUNNING (PID: {read_pid(name)})")
        else:
            print(f"  {name:10s} STOPPED")
    if port_in_use(BACKEND_PORT):
        print(f"  {'backend':10s} (端口 {BACKEND_PORT} 被外部进程占用)")


def cmd_stop():
    stop_all()


def main():
    if len(sys.argv) < 2:
        print("用法: mgr.py {start|update|status|stop}")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "start":
        cmd_start()
    elif cmd == "update":
        cmd_update()
    elif cmd == "status":
        cmd_status()
    elif cmd == "stop":
        cmd_stop()
    else:
        print(f"未知命令: {cmd}")
        print("用法: mgr.py {start|update|status|stop}")
        sys.exit(1)


if __name__ == "__main__":
    main()
