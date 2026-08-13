#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VideoLingoFlow 跨平台安装主程序（Windows / Linux / macOS）
由根目录 install.bat（Windows）/ install.sh（Linux/macOS）调用。

流程:
  1. Python 环境:   复用 backend/venv312 → 系统 Python(>=3.10) 创建 venv →
                    Windows 自动下载 Python 3.12 静默安装；Linux/macOS 输出包管理器指引
  2. git 检查:      缺失时尝试 winget/apt/brew 自动安装；失败打印官方下载地址
  3. FFmpeg 检查:   缺失时尝试自动安装（视频/音频处理必需）；失败打印下载地址
  4. CUDA 检查:     CUDA < 12.8 时提示安装 CUDA 12.8.2（提供官方链接）并重启安装程序
  5. 后端依赖:      运行 backend/installer.py（按 CUDA 版本装对应 PyTorch 三件套 + 其余依赖）
  6. Node.js 检查:  可选（前端构建/部分第三方项目用）；缺失仅告警（dist 已随仓库分发）
  7. 第三方扩展:    调用 thirdparty/install_thirdparty.py（CloakBrowser + 三个项目 + pi）
  8. 配置引导:      补齐 backend/config/config.yaml、.runtime/local_env.bat
  9. 汇总与下一步指引

用法:
    python installer/install.py                 # 全量安装
    python installer/install.py --skip-backend  # 跳过后端依赖（PyTorch 等）
    python installer/install.py --skip-thirdparty
    python installer/install.py --force-thirdparty   # 强制重下第三方扩展
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / "backend" / "venv312"
TEMP_DIR = ROOT / "temp"

# 国内镜像（与项目既有约定一致；可被环境变量覆盖）
PY_MIRROR = "https://registry.npmmirror.com/-/binary/python"
NODE_MIRROR = "https://registry.npmmirror.com/-/binary/node"
PY_VERSION = "3.12.0"
NODE_VERSION = "v20.11.0"
PYTHON_MIN = (3, 10)


def is_windows() -> bool:
    return os.name == "nt"


def venv_python() -> Path:
    if is_windows():
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def log(msg: str) -> None:
    print(f"  [INFO] {msg}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise SystemExit(1)


def manual_install(title: str, url: str, steps: list[str]) -> None:
    """自动安装失败时，打印手动安装方法 + 下载地址，引导用户操作后重跑安装流程。"""
    print()
    print("  ============================================================")
    print(f"  {title} 无法自动安装，请手动操作：")
    print(f"    下载地址: {url}")
    for step in steps:
        print(f"      - {step}")
    print("  安装完成后，重新运行本安装程序即可继续。")
    print("  ============================================================")


def run(cmd, cwd=None, check=True):
    print(f"  [执行] {' '.join(str(c) for c in cmd)}")
    try:
        result = subprocess.run(
            cmd, cwd=cwd, check=check, text=True, encoding="utf-8", errors="replace",
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            fail(f"命令失败（退出码 {e.returncode}）: {e}")
        return e


def download(url: str, dest: Path) -> None:
    print(f"  [下载] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "VideoLingoFlow-installer/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                print(f"\r    下载进度: {downloaded * 100 // total}%", end="", flush=True)
    print()


def python_version(exe) -> tuple[int, int] | None:
    """返回 (major, minor) 或 None。"""
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=20)
        text = (out.stdout or out.stderr).strip()
        # Python 3.12.0
        ver = text.split("Python ", 1)[-1].split()
        parts = ver[0].split(".")
        return int(parts[0]), int(parts[1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 步骤 1: Python 环境
# ---------------------------------------------------------------------------
def ensure_python() -> Path:
    print("\n[1/7] Python 环境")
    vp = venv_python()
    if vp.exists():
        ver = python_version(vp)
        ok(f"复用虚拟环境 backend/venv312（Python {'.'.join(map(str, ver)) if ver else '?'}）")
        return vp

    # 系统 Python
    for cand in (["python3", "python"] if not is_windows() else ["python", "py"]):
        exe = shutil.which(cand)
        if not exe:
            continue
        if cand == "py":
            exe = "py"  # py 启动器需要 -3 前缀
            args = ["py", "-3", "--version"]
            try:
                subprocess.run(args, capture_output=True, text=True, timeout=20)
            except Exception:
                continue
        ver = python_version(exe)
        if ver and ver >= PYTHON_MIN:
            log(f"使用系统 Python {exe}（{'.'.join(map(str, ver))}），创建虚拟环境...")
            run([exe, "-m", "venv", str(VENV)])
            if not vp.exists():
                fail("虚拟环境创建失败")
            ver = python_version(vp)
            ok(f"虚拟环境创建完成 backend/venv312（Python {'.'.join(map(str, ver))}）")
            return vp

    # 无可用 Python
    if is_windows():
        return install_python_windows()
    print()
    print("  [提示] 未找到 Python。请按平台安装 Python 3.12 后重跑：")
    if platform.system() == "Linux":
        print("    Ubuntu/Debian: sudo apt install python3.12 python3.12-venv python3-pip")
        print("    或使用 pyenv:  pyenv install 3.12 && pyenv local 3.12")
    else:
        print("    macOS: brew install python@3.12")
    print("    官方下载: https://www.python.org/downloads/")
    print("    安装完成后重新运行本安装程序。")
    raise SystemExit(1)


def install_python_windows() -> Path:
    """Windows 无 Python 时自动下载并静默安装 Python 3.12（仅当前用户）。"""
    warn("未找到 Python，自动下载 Python 3.12.0 并静默安装...")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    installer = TEMP_DIR / f"python-{PY_VERSION}-amd64.exe"
    try:
        download(f"{PY_MIRROR}/{PY_VERSION}/python-{PY_VERSION}-amd64.exe", installer)
    except Exception as e:
        warn(f"镜像下载失败（{e}），改用 python.org...")
        try:
            download(f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-amd64.exe", installer)
        except Exception as e2:
            manual_install("Python", "https://www.python.org/downloads/", [
                "下载 Windows installer (64-bit) 并双击运行",
                "勾选 Add python.exe to PATH，点击 Install Now",
            ])
            fail(f"Python 下载失败（{e2}），请按上方指引手动安装后重跑")
    result = run([str(installer), "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0"], check=False)
    # 用户级安装的默认路径
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    major_minor = PY_VERSION.split(".")[0] + PY_VERSION.split(".")[1]
    cand = local / f"Python{major_minor}" / "python.exe"
    if result.returncode not in (0, 3010) or not cand.exists():
        manual_install("Python", "https://www.python.org/downloads/", [
            "下载 Windows installer (64-bit) 并双击运行",
            "勾选 Add python.exe to PATH，点击 Install Now",
        ])
        fail(f"Python 静默安装失败（安装器退出码 {result.returncode}），请按上方指引手动安装后重跑")
    log("创建虚拟环境...")
    run([str(cand), "-m", "venv", str(VENV)])
    if not venv_python().exists():
        manual_install("Python", "https://www.python.org/downloads/", [
            "下载 Windows installer (64-bit) 并双击运行",
            "勾选 Add python.exe to PATH，点击 Install Now",
        ])
        fail("虚拟环境创建失败，请按上方指引重新安装 Python 后重跑")
    ok("Python 安装 + 虚拟环境创建完成（需重新打开终端使 PATH 生效）")
    return venv_python()


# ---------------------------------------------------------------------------
# 步骤 2: git 检查（第三方项目更新功能依赖）
# ---------------------------------------------------------------------------
GIT_DOWNLOAD_URL = "https://git-scm.com/downloads"


def ensure_git() -> None:
    print("\n[2/9] git 检查")
    git = shutil.which("git")
    if git:
        ok(f"已检测到 git: {git}")
        return
    warn("未检测到 git —— 第三方项目（social / QM-LocalRouter）的更新功能依赖 git，建议安装。")
    if is_windows():
        winget = shutil.which("winget")
        if winget:
            warn("尝试使用 winget 自动安装 git...")
            result = run(
                [winget, "install", "--id", "Git.Git", "-e", "--source", "winget",
                 "--accept-package-agreements", "--accept-source-agreements", "--silent"],
                check=False,
            )
            if result.returncode == 0 and shutil.which("git"):
                ok("git 安装完成（需重新打开终端使 PATH 生效）")
                return
        manual_install("git", GIT_DOWNLOAD_URL, [
            "下载 64-bit Windows 安装包（Git for Windows）并运行",
            "安装向导保持默认选项即可",
        ])
        warn("git 自动安装失败，请按上方指引手动安装后重新运行本安装程序。")
    else:
        print("  [提示] 请按平台安装 git 后重跑：")
        if platform.system() == "Linux":
            print("    Ubuntu/Debian: sudo apt install git")
            print("    Fedora/RHEL:   sudo dnf install git")
        else:
            print("    macOS: brew install git（或 xcode-select --install）")
        print(f"    官方下载: {GIT_DOWNLOAD_URL}")


# ---------------------------------------------------------------------------
# 步骤 3: FFmpeg 检查（视频/音频处理必需）
# ---------------------------------------------------------------------------
FFMPEG_WIN_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/"


def ensure_ffmpeg() -> None:
    print("\n[3/9] FFmpeg 检查")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        ok(f"已检测到 ffmpeg: {ffmpeg}")
        return
    warn("未检测到 ffmpeg —— 视频/音频处理节点必需，尝试自动安装...")
    if is_windows():
        winget = shutil.which("winget")
        if winget:
            warn("尝试使用 winget 自动安装 ffmpeg...")
            result = run(
                [winget, "install", "--id", "Gyan.FFmpeg", "-e", "--source", "winget",
                 "--accept-package-agreements", "--accept-source-agreements", "--silent"],
                check=False,
            )
            if result.returncode == 0 and shutil.which("ffmpeg"):
                ok("ffmpeg 安装完成（需重新打开终端使 PATH 生效）")
                return
        manual_install("FFmpeg", FFMPEG_WIN_DOWNLOAD_URL, [
            "下载 ffmpeg-release-essentials.zip（gyan.dev 官方 Windows 构建）",
            "解压后把其中的 bin 目录（含 ffmpeg.exe）加入系统 PATH",
            "或在命令行执行: winget install Gyan.FFmpeg",
        ])
        warn("ffmpeg 自动安装失败，请按上方指引手动安装后重新运行本安装程序。")
    else:
        print("  [提示] 请按平台安装 ffmpeg 后重跑：")
        if platform.system() == "Linux":
            print("    Ubuntu/Debian: sudo apt install ffmpeg")
            print("    Fedora/RHEL:   sudo dnf install ffmpeg")
        else:
            print("    macOS: brew install ffmpeg")
        print(f"    官方下载: https://ffmpeg.org/download.html")


# ---------------------------------------------------------------------------
# 步骤 4: CUDA 检查（版本 < 12.8 时提示升级）
# ---------------------------------------------------------------------------
CUDA_REQUIRED = (12, 8)
CUDA_DOWNLOAD_URL = "https://developer.nvidia.com/cuda-12-8-2-download-archive"


def detect_cuda_version() -> tuple[int, int] | None:
    """检测 CUDA 版本，返回 (major, minor) 或 None（nvidia-smi → nvcc → CUDA_PATH）。"""
    # 1. nvidia-smi
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=15)
        m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    # 2. nvcc --version
    try:
        out = subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=15)
        m = re.search(r"release (\d+)\.(\d+)", out.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    # 3. CUDA_PATH/version.txt
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        try:
            text = Path(cuda_path, "version.txt").read_text(encoding="utf-8", errors="replace")
            m = re.search(r"CUDA Version (\d+)\.(\d+)", text)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    return None


def check_cuda() -> None:
    """CUDA 存在但版本 < 12.8 时，提示用户安装 12.8.2 并重启安装程序。"""
    print("\n[4/9] CUDA 检查")
    ver = detect_cuda_version()
    if ver is None:
        ok("未检测到 CUDA，将安装 CPU 版 PyTorch")
        return
    ok(f"检测到 CUDA {ver[0]}.{ver[1]}")
    if ver < CUDA_REQUIRED:
        print()
        print("  ============================================================")
        print(f"  检测到 CUDA {ver[0]}.{ver[1]}，低于推荐版本 {CUDA_REQUIRED[0]}.{CUDA_REQUIRED[1]}")
        print(f"  请前往以下地址安装 CUDA {CUDA_REQUIRED[0]}.{CUDA_REQUIRED[1]}:")
        print(f"    {CUDA_DOWNLOAD_URL}")
        print("  安装完成后，请重新运行本安装程序，即可安装对应 CUDA 版本的 PyTorch。")
        print("  ============================================================")
        try:
            ans = input("  是否仍以当前 CUDA 版本继续安装（不推荐）？[y/N]: ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            fail(f"请先安装 CUDA {CUDA_REQUIRED[0]}.{CUDA_REQUIRED[1]}，再重新运行安装程序")
        warn(f"继续使用 CUDA {ver[0]}.{ver[1]} 安装（PyTorch 将选择兼容版本）")


# ---------------------------------------------------------------------------
# 步骤 3: 后端依赖（PyTorch 三件套 + 其余）
# ---------------------------------------------------------------------------
def install_backend(py: Path) -> None:
    print("\n[5/9] 后端依赖（PyTorch 三件套 + 其余依赖）")
    run([str(py), "backend/installer.py"], cwd=str(ROOT))
    ok("后端依赖安装完成")


# ---------------------------------------------------------------------------
# 步骤 6: Node.js 检查（可选）
# ---------------------------------------------------------------------------
def ensure_node() -> None:
    print("\n[6/9] Node.js 检查")
    node = shutil.which("node")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if node:
        ok(f"已检测到 Node.js: {node}")
        if not npm:
            warn("未找到 npm（Node 安装不完整），第三方项目构建可能失败")
        return
    warn("未检测到 Node.js —— 前端构建/部分第三方项目需要；dist 已随仓库分发，运行不受影响。")
    if is_windows():
        warn("自动下载 Node.js 20 LTS 并静默安装...")
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        msi = TEMP_DIR / f"node-{NODE_VERSION}-x64.msi"
        try:
            download(f"{NODE_MIRROR}/{NODE_VERSION}/node-{NODE_VERSION}-x64.msi", msi)
        except Exception as e:
            warn(f"镜像下载失败（{e}），改用 nodejs.org...")
            try:
                download(f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-x64.msi", msi)
            except Exception as e2:
                manual_install("Node.js", "https://nodejs.org/en/download", [
                    "下载 Windows Installer (.msi)（LTS 版）并双击运行",
                    "安装时保持默认选项即可",
                ])
                fail(f"Node.js 下载失败（{e2}），请按上方指引手动安装后重跑")
        result = run(["msiexec", "/i", str(msi), "/quiet", "/norestart"], check=False)
        if result.returncode not in (0, 3010):
            manual_install("Node.js", "https://nodejs.org/en/download", [
                "下载 Windows Installer (.msi)（LTS 版）并双击运行",
                "安装时保持默认选项即可",
            ])
            fail(f"Node.js 静默安装失败（msiexec 退出码 {result.returncode}），请按上方指引手动安装后重跑")
        warn("Node.js 安装完成，需重新打开终端（PATH 生效）后，第三方项目的前端构建才能使用 npm。")
    else:
        if platform.system() == "Linux":
            print("    Ubuntu/Debian: sudo apt install nodejs npm")
        else:
            print("    macOS: brew install node")
        print("    或使用 nvm: https://github.com/nvm-sh/nvm")
        print("    官方下载: https://nodejs.org/en/download")
        print("    安装完成后重新运行本安装程序即可继续。")


# ---------------------------------------------------------------------------
# 步骤 7: 第三方扩展
# ---------------------------------------------------------------------------
def install_thirdparty(py: Path, force: bool) -> None:
    print("\n[7/9] 第三方扩展（CloakBrowser + 三个项目 + pi）")
    cmd = [str(py), "thirdparty/install_thirdparty.py"]
    if force:
        cmd.append("--force")
    run(cmd, cwd=str(ROOT))
    ok("第三方扩展安装完成")


# ---------------------------------------------------------------------------
# 步骤 8: 配置引导
# ---------------------------------------------------------------------------
def bootstrap_config() -> None:
    print("\n[8/9] 配置引导")
    # 运行时配置文件（可能含密钥）：正式文件缺失时，从 git 分发的脱敏版 *.temp 还原为正式文件名
    for target, temp_src in [
        (ROOT / "backend" / "config" / "config.yaml", ROOT / "backend" / "config" / "config.yaml.temp"),
        (ROOT / "backend" / "config" / "asr_interfaces.json", ROOT / "backend" / "config" / "asr_interfaces.json.temp"),
        (ROOT / "backend" / "config" / "tts_interfaces.json", ROOT / "backend" / "config" / "tts_interfaces.json.temp"),
        (ROOT / "backend" / "config" / "imagegen_interfaces.json", ROOT / "backend" / "config" / "imagegen_interfaces.json.temp"),
    ]:
        if not target.exists() and temp_src.exists():
            shutil.copy2(temp_src, target)
            ok(f"已从脱敏版本 {temp_src.name} 还原为 {target.name}")

    runtime = ROOT / ".runtime"
    local_env = runtime / "local_env.bat"
    if not local_env.exists():
        tpl = runtime / "local_env.bat.template"
        if tpl.exists():
            runtime.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tpl, local_env)
            ok("已从模板生成 .runtime/local_env.bat")
        else:
            warn(".runtime/local_env.bat 缺失且无模板（管理器会自动使用内置默认值）")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="VideoLingoFlow 跨平台安装")
    parser.add_argument("--skip-backend", action="store_true", help="跳过后端依赖（PyTorch 等）")
    parser.add_argument("--skip-thirdparty", action="store_true", help="跳过第三方扩展安装")
    parser.add_argument("--skip-config", action="store_true", help="跳过配置引导")
    parser.add_argument("--force-thirdparty", action="store_true", help="强制重新下载/构建第三方扩展")
    args = parser.parse_args()

    print("=" * 60)
    print("  VideoLingoFlow 安装程序")
    print(f"  平台: {platform.system()} {platform.machine()}")
    print("=" * 60)
    print()
    print("  [提示] 安装过程需要下载大量依赖（Python / Node / PyTorch / 第三方扩展），")
    print("         建议先开启全局网络（VPN / 代理）后再安装，可显著加快下载速度、")
    print("         并避免部分海外源下载失败。")
    print()

    py = ensure_python()
    ensure_git()
    ensure_ffmpeg()

    if not args.skip_backend:
        check_cuda()
        install_backend(py)
    else:
        log("跳过后端依赖安装（--skip-backend）")

    ensure_node()

    if not args.skip_thirdparty:
        install_thirdparty(py, args.force_thirdparty)
    else:
        log("跳过第三方扩展安装（--skip-thirdparty）")

    if not args.skip_config:
        bootstrap_config()
    else:
        log("跳过配置引导（--skip-config）")

    print()
    print("=" * 60)
    print("  安装完成")
    print("=" * 60)
    if is_windows():
        print("  启动: 双击 start.bat")
    else:
        print("  启动: 运行 bash start.sh")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
