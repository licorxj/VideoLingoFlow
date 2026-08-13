# -*- coding: utf-8 -*-
"""GitHub 项目更新（适配 Windows / Linux / macOS 多平台）。

流程：
1. 检测平台与 git 可执行文件（Windows 常见 Git 安装路径回退）。
2. 校验/初始化本地仓库，并将 remote origin 固定为项目 GitHub 地址。
3. `git fetch origin` 拉取远端引用，确定目标分支（本地当前分支优先，其次远端默认分支）。
4. 同步工作区到远端最新：
   - 常规（仓库已有提交）：`git reset --hard origin/<branch>`，仅覆盖被跟踪文件，
     未跟踪的本地文件（config.yaml / 接口 JSON / data 等已在 .gitignore）不受影响；
   - 引导（空仓库 / 全部文件未跟踪，reset 会因未跟踪冲突而失败）：退化为「临时克隆 +
     覆盖拷贝」，覆盖同名文件、保留本地额外文件，保证任意分发形态都能更新。
5. 调用项目根目录安装脚本（install.bat / install.sh）完成依赖与三方组件安装。
6. 全程进度写入共享状态，供 `/api/github-update/status` 轮询展示。
"""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

# 项目 GitHub 仓库地址（与前端 About 页一致）
REPO_URL = "https://github.com/licorxj/VideoLingoFlow.git"

# Windows 常见 Git 安装路径（shutil.which 找不到时回退）
_WINDOWS_GIT_PATHS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
    r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe",
)

# 共享进度状态（模块级单例，线程锁保护）
_status_lock = threading.Lock()
_status = {
    "status": "idle",          # idle | updating | success | error
    "message": "",
    "log": [],
    "updated_at": 0,
    "task_id": "",
}


def _project_root() -> Path:
    """backend/updater/github_updater.py 所在位置向上三级为项目根目录。"""
    return Path(__file__).resolve().parents[2]


def get_status() -> dict:
    with _status_lock:
        return {
            "status": _status["status"],
            "message": _status["message"],
            "log": list(_status["log"]),
            "updated_at": _status["updated_at"],
            "task_id": _status["task_id"],
        }


def _set_status(status: str, message: str) -> None:
    with _status_lock:
        _status["status"] = status
        _status["message"] = message
        _status["updated_at"] = time.time()
        _status["log"].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        # 日志只保留最近 300 行，避免无限增长
        _status["log"] = _status["log"][-300:]


def _reset_status() -> None:
    with _status_lock:
        _status["status"] = "idle"
        _status["message"] = ""
        _status["log"] = []
        _status["updated_at"] = time.time()
        _status["task_id"] = uuid.uuid4().hex[:12]


def _git_cmd() -> str:
    found = shutil.which("git")
    if found:
        return found
    if os.name == "nt":
        for path in _WINDOWS_GIT_PATHS:
            expanded = os.path.expandvars(path)
            if os.path.exists(expanded):
                return expanded
    raise FileNotFoundError("未找到 git 可执行文件，请先安装 Git（https://git-scm.com/）")


def _run(cmd: list, cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    """执行命令并返回结果（不抛异常，由调用方检查 returncode）。"""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        stdin=subprocess.DEVNULL,
    )


def _default_branch(git: str, root: Path) -> str:
    """通过 ls-remote 探测远端默认分支；失败时回退常见分支名。"""
    try:
        out = subprocess.run(
            [git, "ls-remote", "--symref", REPO_URL, "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=60,
        ).stdout
        for line in out.splitlines():
            if line.startswith("ref:"):
                ref = line.split()[1]
                if "/" in ref:
                    return ref.rsplit("/", 1)[-1]
    except Exception:
        pass
    for candidate in ("main", "master", "dev"):
        try:
            check = subprocess.run(
                [git, "ls-remote", "--heads", REPO_URL, candidate],
                cwd=str(root), capture_output=True, text=True, timeout=60,
            ).stdout
            if candidate in check:
                return candidate
        except Exception:
            pass
    return "main"


def _sync_worktree(git: str, root: Path) -> tuple[str, str]:
    """同步工作区到远端最新，返回 (branch, method)。"""
    if not (root / ".git").exists():
        _set_status("updating", "未检测到本地 .git，正在初始化仓库...")
        result = _run([git, "init"], root, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"git init 失败: {(result.stderr or result.stdout)[-800:]}")

    remotes = _run([git, "remote"], root, timeout=30).stdout.split()
    if "origin" not in remotes:
        result = _run([git, "remote", "add", "origin", REPO_URL], root, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"git remote add 失败: {(result.stderr or result.stdout)[-800:]}")
    # 始终将 origin 固定为项目仓库地址，防止被改动
    _run([git, "remote", "set-url", "origin", REPO_URL], root, timeout=30)

    _set_status("updating", "正在从 GitHub 拉取最新代码...")
    result = _run([git, "fetch", "--tags", "--force", "origin"], root, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"git fetch 失败（请检查网络连接）: {(result.stderr or result.stdout)[-800:]}")

    local_head = _run([git, "rev-parse", "--abbrev-ref", "HEAD"], root, timeout=30).stdout.strip()
    branch = local_head if local_head and local_head != "HEAD" else _default_branch(git, root)

    # 常规路径：reset --hard 覆盖被跟踪文件
    reset = _run([git, "reset", "--hard", f"origin/{branch}"], root, timeout=300)
    if reset.returncode == 0:
        return branch, "git reset --hard"

    # 引导路径：空仓库/全未跟踪工作区，reset 会因未跟踪冲突失败，
    # 改用「临时克隆 + 覆盖拷贝」：覆盖同名文件、保留本地额外文件。
    _set_status("updating", "检测到工作区无提交记录，改用克隆覆盖方式同步...")
    temp_dir = Path(tempfile.mkdtemp(prefix="vlf-update-"))
    try:
        clone = _run([git, "clone", "--depth", "1", "--branch", branch, REPO_URL, str(temp_dir)], root, timeout=600)
        if clone.returncode != 0:
            # 指定分支不存在时回退远端默认分支
            clone = _run([git, "clone", "--depth", "1", REPO_URL, str(temp_dir)], root, timeout=600)
        if clone.returncode != 0:
            raise RuntimeError(f"git clone 失败（请检查网络连接）: {(clone.stderr or clone.stdout)[-800:]}")
        _set_status("updating", "正在将最新代码覆盖到工作目录...")
        _copy_over(temp_dir, root)
        return branch, "git clone + copy"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _copy_over(src: Path, dst: Path) -> None:
    """把 src 顶层内容覆盖到 dst（保留 dst 中不存在于 src 的额外文件）。"""
    for entry in src.iterdir():
        if entry.name in (".git",):
            continue
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def _install_script(root: Path) -> subprocess.CompletedProcess:
    """调用项目根目录安装脚本（Windows: install.bat，POSIX: install.sh）。"""
    if os.name == "nt":
        script = root / "install.bat"
        if not script.exists():
            raise FileNotFoundError("未找到项目根目录安装脚本 install.bat")
        _set_status("updating", "正在执行安装脚本 install.bat（安装依赖，可能需要较长时间）...")
        return _run(["cmd", "/c", str(script)], root, timeout=3600)
    script = root / "install.sh"
    if not script.exists():
        raise FileNotFoundError("未找到项目根目录安装脚本 install.sh")
    shell = shutil.which("bash") or "sh"
    _set_status("updating", "正在执行安装脚本 install.sh（安装依赖，可能需要较长时间）...")
    return _run([shell, str(script)], root, timeout=3600)


def _run_update_worker() -> None:
    root = _project_root()
    try:
        _set_status("updating", "正在检测平台与 git 环境...")
        git = _git_cmd()
        _set_status("updating", f"检测到 git：{git}")

        branch, method = _sync_worktree(git, root)
        _set_status("updating", f"代码同步完成（{method}），当前分支：{branch}")

        result = _install_script(root)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-1500:]
            raise RuntimeError(f"安装脚本执行失败，退出码 {result.returncode}：{tail}")

        _set_status("success", "更新完成！新代码已拉取并完成安装，请重启应用使新版本生效。")
    except FileNotFoundError as exc:
        _set_status("error", f"更新失败：{exc}")
    except Exception as exc:
        _set_status("error", f"更新失败：{exc}")


def run_update() -> dict:
    """启动后台更新任务（幂等：已有更新任务进行中则拒绝）。"""
    with _status_lock:
        if _status["status"] == "updating":
            return {"ok": False, "message": "更新正在进行中，请稍候"}
        _reset_status()
    thread = threading.Thread(target=_run_update_worker, daemon=True, name="github-update")
    thread.start()
    return {"ok": True, "message": "更新任务已启动，请稍候查看进度"}
