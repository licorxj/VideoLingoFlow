#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thirdparty 第三方扩展安装脚本（由主安装程序调用，任意 Python 3 可运行，仅用标准库）

用法:
    python thirdparty/install_thirdparty.py               # 正常安装
    python thirdparty/install_thirdparty.py --force       # 强制重新下载/构建

职责（按顺序）:
  1. CloakBrowser                下载隐匿浏览器二进制 → thirdparty/cloakbrowser/
  2. social-auto-upload-web-ui   前端构建产物 + backend-mcp(node) + backend(pip)
  3. QM-LocalRouter              后端 pip 依赖 + 前端构建
  4. cutia (standalone 部署)      Windows/整合包用已提交的 apps/web/standalone（免构建）；
                                   非 Windows 重新构建（bun install + build:web 产出原生 standalone）
  5. pi (Node.js)                保证 node_modules 就绪（各包 dist 已随 git 上传，无需重建）

平台策略:
  - Windows:    优先使用 git 仓库内已提交的 dist 构建产物（无 node 环境的用户可直接使用）；
                产物缺失时用 npm 构建。
  - 非 Windows: 每次重新构建各项目前端（提交的 dist 为 Windows 产物，不做跨平台保证）。
  - cutia:     Windows/整合包用户直接使用 git 已提交的 apps/web/standalone（免构建）；
               非 Windows 用户重新构建产出本平台原生 standalone。

下载源:
  - CloakBrowser: GitHub Releases (CloakHQ/CloakBrowser) 主源 + cloakbrowser.dev 兜底
  - bun:          GitHub Releases (oven-sh/bun)
"""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

THIRDPARTY = Path(__file__).resolve().parent
PROJECT_ROOT = THIRDPARTY.parent

# 输出实时刷新：即使 stdout 被管道/重定向（非 TTY），进度也能即时可见
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# ---------------------------------------------------------------------------
# 平台探测
# ---------------------------------------------------------------------------
def is_windows() -> bool:
    return os.name == "nt"


def platform_tag() -> str:
    """返回 cloakbrowser/bun 使用的平台标签，如 windows-x64 / linux-x64 / darwin-arm64。"""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "windows-x64"
    if system == "Linux":
        return "linux-arm64" if machine in ("aarch64", "arm64") else "linux-x64"
    if system == "Darwin":
        return "darwin-arm64" if machine in ("arm64", "aarch64") else "darwin-x64"
    raise RuntimeError(f"不支持的平台: {system} {machine}")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def log(msg: str, prefix: str = "[INFO]") -> None:
    print(f"  {prefix} {msg}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise SystemExit(1)


def run(cmd, cwd=None, check=True, capture=False):
    """运行命令；check=True 时失败即退出。"""
    print(f"  [执行] {' '.join(str(c) for c in cmd)}")
    try:
        result = subprocess.run(
            cmd, cwd=cwd, check=check, capture_output=capture, text=True,
            encoding="utf-8", errors="replace",
        )
        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(f"  [输出] {e.stderr.strip()[-2000:]}")
        if check:
            fail(f"命令失败: {e}")
        return e


def find_exe(names):
    """在 PATH 中查找可执行文件。"""
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    return None


def venv_python() -> str | None:
    """返回共享 venv 的 python（存在时），否则 None。"""
    for p in (
        PROJECT_ROOT / "venv312" / "Scripts" / "python.exe",
        PROJECT_ROOT / "venv312" / "bin" / "python",
    ):
        if p.exists():
            return str(p)
    return None


def download(url: str, dest: Path) -> None:
    """下载文件到 dest，带进度提示。"""
    log(f"下载: {url}")
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
                pct = int(downloaded * 100 / total)
                print(f"\r    下载进度: {pct}% ({downloaded // (1024*1024)}/{total // (1024*1024)} MB)", end="", flush=True)
    print()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(archive: Path, base_url: str, archive_name: str) -> bool:
    """从同一源抓取 SHA256SUMS 校验归档（尽力而为，失败仅告警）。"""
    try:
        req = urllib.request.Request(f"{base_url}/SHA256SUMS", headers={"User-Agent": "VideoLingoFlow-installer/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        expected = None
        for line in text.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].lower() == sha256_of(archive).lower():
                expected = parts[0]
                break
            if len(parts) == 2 and parts[1].lstrip("*") == archive_name and len(parts[0]) == 64:
                expected = parts[0]
                break
        if not expected:
            warn("SHA256SUMS 中未找到对应条目，跳过校验（HTTPS 传输兜底）")
            return True
        actual = sha256_of(archive)
        if actual.lower() != expected.lower():
            warn(f"SHA256 校验失败 (期望 {expected}, 实际 {actual})，继续前请确认下载源可信")
            return False
        ok("SHA256 校验通过")
        return True
    except Exception as e:
        warn(f"无法获取 SHA256SUMS（{e}），跳过校验")
        return True


def _safe_member(path: str) -> bool:
    """拒绝绝对路径与 .. 穿越。"""
    p = path.replace("\\", "/")
    if p.startswith("/") or ".." in p.split("/"):
        return False
    return True


def extract_archive(archive: Path, dest: Path) -> None:
    """解压 zip/tar.gz 到 dest，做路径穿越防护。"""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if not _safe_member(info.filename):
                    raise RuntimeError(f"归档包含非法路径: {info.filename}")
            zf.extractall(dest)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            members = []
            for m in tf.getmembers():
                if not _safe_member(m.name):
                    raise RuntimeError(f"归档包含非法路径: {m.name}")
                members.append(m)
            tf.extractall(dest, members=members)
    # 若解压出单个子目录则上移一层（保持 chrome.exe / chrome 直接在目标目录）
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and not entries[0].name.endswith(".app"):
        sub = entries[0]
        for item in sub.iterdir():
            shutil.move(str(item), str(dest / item.name))
        sub.rmdir()


# ---------------------------------------------------------------------------
# 1. CloakBrowser
# ---------------------------------------------------------------------------
# 各平台 Chromium 版本（与 cloakbrowser 包 config 保持一致）
CB_VERSIONS = {
    "windows-x64": "146.0.7680.177.5",
    "linux-x64": "146.0.7680.177.5",
    "linux-arm64": "146.0.7680.177.3",
    "darwin-arm64": "145.0.7632.109.2",
    "darwin-x64": "145.0.7632.109.2",
}
CB_GITHUB_RELEASES = "https://github.com/CloakHQ/CloakBrowser/releases/download"
CB_DEV = "https://cloakbrowser.dev"


def _cb_archive_name(tag: str) -> str:
    ext = ".zip" if tag == "windows-x64" else ".tar.gz"
    return f"cloakbrowser-{tag}{ext}"


def _cb_version_latest() -> str | None:
    """尝试从 GitHub API 取最新 chromium-v* 版本号。"""
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/CloakHQ/CloakBrowser/releases/latest",
            headers={"User-Agent": "VideoLingoFlow-installer/1.0", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            tag = json.load(resp).get("tag_name", "")
        if tag.startswith("chromium-v"):
            return tag[len("chromium-v"):]
    except Exception:
        pass
    return None


def _cb_binary_name(tag: str) -> str:
    if tag == "windows-x64":
        return "chrome.exe"
    if tag.startswith("darwin"):
        return "Chromium.app/Contents/MacOS/Chromium"
    return "chrome"


def ensure_cloakbrowser(force: bool) -> Path | None:
    """下载 CloakBrowser → thirdparty/cloakbrowser/，返回浏览器可执行文件路径。"""
    print("\n[1/4] CloakBrowser 隐匿浏览器")
    tag = platform_tag()
    binary_name = _cb_binary_name(tag)
    target_dir = THIRDPARTY / "cloakbrowser"
    target_bin = target_dir / binary_name

    if not force and target_bin.exists():
        ok(f"已存在: {target_bin}")
        return target_bin

    if tag.startswith("darwin"):
        # macOS 无官方自动下载包：优先使用用户提供的离线包
        candidates = list(THIRDPARTY.glob(f"cloakbrowser-darwin-*")) + list(THIRDPARTY.glob("cloakbrowser-macos-*"))
        if candidates:
            warn("macOS 使用用户提供的离线包: " + str(candidates[0]))
        else:
            warn("macOS 无官方自动下载包，请手动放置 chrome 二进制到 " + str(target_dir))
            return None

    version = _cb_version_latest() or CB_VERSIONS[tag]
    archive_name = _cb_archive_name(tag)
    urls = [
        f"{CB_GITHUB_RELEASES}/chromium-v{version}/{archive_name}",
        f"{CB_DEV}/chromium-v{version}/{archive_name}",
    ]
    tmp_dir = Path(tempfile.mkdtemp(prefix="vl-cb-"))
    try:
        archive = tmp_dir / archive_name
        last_err = None
        for url in urls:
            try:
                download(url, archive)
                last_err = None
                break
            except Exception as e:
                last_err = e
                warn(f"下载失败（{url}）: {e}")
        if last_err:
            warn(f"CloakBrowser 下载失败: {last_err}")
            warn("跳过 CloakBrowser：不影响主程序安装，相关节点运行时会提示缺少浏览器")
            return None
        verify_sha256(archive, urls[0].rsplit("/", 1)[0], archive_name)
        extract_archive(archive, target_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not target_bin.exists():
        # 归档内结构未知时尽力查找
        found = list(target_dir.rglob("chrome.exe")) + list(target_dir.rglob("chrome"))
        if found:
            target_bin = found[0]
        else:
            warn(f"CloakBrowser 解压后未找到浏览器二进制: {target_bin}")
            return None
    if not is_windows():
        os.chmod(target_bin, 0o755)
    ok(f"CloakBrowser 就绪: {target_bin}")
    return target_bin


# ---------------------------------------------------------------------------
# 通用：前端构建 / npm 依赖 / pip 依赖
# ---------------------------------------------------------------------------
def ensure_npm_frontend(fe_dir: Path, force: bool, label: str) -> None:
    """前端构建：Windows 且已有 dist 则跳过；否则 npm install + build。"""
    dist_ok = (fe_dir / "dist" / "index.html").exists() or (fe_dir / "dist").exists()
    need_build = force or (not is_windows()) or (not dist_ok)
    if not need_build:
        ok(f"{label}: 使用已提交的 dist 产物（Windows）")
        return
    npm = find_exe(["npm.cmd", "npm"])
    if not npm:
        warn(f"{label}: 未找到 npm，跳过前端构建（需手动安装 Node.js）")
        return
    if not (fe_dir / "node_modules").exists() or force:
        run([npm, "install", "--prefer-offline"], cwd=str(fe_dir))
    run([npm, "run", "build"], cwd=str(fe_dir))
    ok(f"{label}: 前端构建完成")


def ensure_backend_pip(req_path: Path, label: str) -> None:
    """后端 pip 依赖：venv 存在则安装，否则提示（后端启动管理器启动时会自愈）。"""
    py = venv_python()
    if not py:
        warn(f"{label}: 未发现共享 venv（venv312），跳过 pip 安装（启动管理器会自愈）")
        return
    run([py, "-m", "pip", "install", "-r", str(req_path), "-q"], check=False)
    ok(f"{label}: 后端依赖已安装（venv）")


def ensure_npm_deps(proj_dir: Path, force: bool, label: str, build: bool = False) -> None:
    """npm 依赖安装（node_modules 缺失或 --force 时执行）；可选执行 npm run build。"""
    npm = find_exe(["npm.cmd", "npm"])
    if not npm:
        warn(f"{label}: 未找到 npm，跳过依赖安装")
        return
    if not (proj_dir / "node_modules").exists() or force:
        run([npm, "install", "--prefer-offline"], cwd=str(proj_dir))
        if build:
            run([npm, "run", "build"], cwd=str(proj_dir))
    ok(f"{label}: 依赖就绪")


# ---------------------------------------------------------------------------
# 2. social-auto-upload-web-ui
# ---------------------------------------------------------------------------
def ensure_social(force: bool) -> None:
    print("\n[2/4] social-auto-upload-web-ui")
    base = THIRDPARTY / "social-auto-upload-web-ui"
    if not base.exists():
        warn("目录不存在，跳过（请先 git 拉取完整源码）")
        return
    ensure_npm_frontend(base / "frontend", force, "social 前端")
    ensure_npm_deps(base / "backend-mcp", force, "social backend-mcp", build=True)
    ensure_backend_pip(base / "backend" / "requirements.txt", "social 后端")


# ---------------------------------------------------------------------------
# 3. QM-LocalRouter
# ---------------------------------------------------------------------------
def _qm_venv_python():
    """QM-LocalRouter 独立虚拟环境的 python（不存在则返回 None）。"""
    qm_venv = THIRDPARTY / "QM-LocalRouter" / "backend" / "venv"
    for p in (qm_venv / "Scripts" / "python.exe", qm_venv / "bin" / "python"):
        if p.exists():
            return p
    return None


def ensure_qm_router(force: bool) -> None:
    """QM-LocalRouter：使用独立虚拟环境（不污染主 venv312），并完成数据库初始化。"""
    print("\n[3/4] QM-LocalRouter")
    base = THIRDPARTY / "QM-LocalRouter"
    if not base.exists():
        warn("目录不存在，跳过")
        return
    backend_dir = base / "backend"
    qm_venv = backend_dir / "venv"
    venv_py = qm_venv / ("Scripts/python.exe" if is_windows() else "bin/python")

    # 1. 创建独立虚拟环境（用共享 venv / 当前 python 引导）
    if not venv_py.exists():
        bootstrap = venv_python() or sys.executable
        log("为 QM-LocalRouter 创建独立虚拟环境（避免污染主 venv312）...")
        run([bootstrap, "-m", "venv", str(qm_venv)], check=False)

    if venv_py.exists():
        # 2. 依赖装入独立环境
        pip_exe = qm_venv / ("Scripts/pip.exe" if is_windows() else "bin/pip")
        req = backend_dir / "requirements.txt"
        if req.exists():
            run([str(pip_exe), "install", "-r", str(req), "-q"], check=False)
            ok("QM-LocalRouter 后端依赖已安装（独立 venv）")
        # 3. 数据库初始化（复用上游脚本，用独立环境执行）
        init_script = base / "scripts" / "init_db.py"
        if init_script.exists():
            log("初始化 QM-LocalRouter 数据库...")
            run([str(venv_py), str(init_script)], cwd=str(base), check=False)
            ok("QM-LocalRouter 数据库初始化完成")
        else:
            warn("未找到 scripts/init_db.py，跳过数据库初始化")
    else:
        warn("独立虚拟环境创建失败，回退共享 venv（依赖将装入主环境）")
        ensure_backend_pip(backend_dir / "requirements.txt", "QM-LocalRouter 后端")

    ensure_npm_frontend(base / "frontend", force, "QM-LocalRouter 前端")


# ---------------------------------------------------------------------------
# 4. cutia（bun 运行）
# ---------------------------------------------------------------------------
BUN_URLS = {
    "windows-x64": "https://github.com/oven-sh/bun/releases/latest/download/bun-windows-x64.zip",
    "linux-x64": "https://github.com/oven-sh/bun/releases/latest/download/bun-linux-x64.zip",
    "linux-arm64": "https://github.com/oven-sh/bun/releases/latest/download/bun-linux-aarch64.zip",
    "darwin-arm64": "https://github.com/oven-sh/bun/releases/latest/download/bun-darwin-aarch64.zip",
    "darwin-x64": "https://github.com/oven-sh/bun/releases/latest/download/bun-darwin-x64.zip",
}


def ensure_bun(force: bool) -> str | None:
    """保证 bun 可用：PATH 优先；否则下载便携 bun 到 thirdparty/bun/ 并同步 ~/.bun/bin/。
    ~/.bun/bin 是 后端启动管理器.bat 已探测的 fallback 路径，确保 manager 能发现 bun。"""
    # 优先使用系统 PATH 已有的 bun（不下载）；否则复用已下载到 thirdparty/bun 的便携 bun（不重复下载）。
    # force 不再强制重新下载 bun——bun 是构建工具，PATH 可用或已下载即用，无需重复拉取。
    found = os.environ.get("BUN_CMD") or find_exe(["bun.exe", "bun"])
    if found:
        log(f"使用现有 bun: {found}")
        return found
    bun_exe = THIRDPARTY / "bun" / ("bun.exe" if is_windows() else "bun")
    if bun_exe.is_file():
        log(f"使用已下载的 bun: {bun_exe}")
        return str(bun_exe)
    tag = platform_tag()
    url = BUN_URLS.get(tag)
    if not url:
        warn(f"不支持下载 bun 的平台: {tag}")
        return None
    bun_dir = THIRDPARTY / "bun"
    bun_exe = bun_dir / ("bun.exe" if is_windows() else "bun")
    tmp_dir = Path(tempfile.mkdtemp(prefix="vl-bun-"))
    try:
        archive = tmp_dir / "bun.zip"
        download(url, archive)
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if not _safe_member(info.filename):
                    raise RuntimeError(f"归档包含非法路径: {info.filename}")
            zf.extractall(tmp_dir)
        src = None
        for p in tmp_dir.rglob("bun.exe" if is_windows() else "bun"):
            src = p
            break
        if not src:
            fail("bun 归档中未找到 bun 可执行文件")
        bun_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(bun_exe))
        if not is_windows():
            os.chmod(bun_exe, 0o755)
        # 同步到 ~/.bun/bin/（后端启动管理器.bat 的 fallback 探测路径）
        home_bun = Path.home() / ".bun" / "bin"
        home_bun.mkdir(parents=True, exist_ok=True)
        home_exe = home_bun / bun_exe.name
        shutil.copy2(str(bun_exe), str(home_exe))
        if not is_windows():
            os.chmod(home_exe, 0o755)
    except Exception as e:
        warn(f"bun 自动安装失败: {e}")
        print()
        print("  请手动安装 bun 后重新运行本安装程序：")
        print("    官网: https://bun.sh/docs/installation")
        if is_windows():
            print("    PowerShell: irm bun.sh/install.ps1 | iex")
            print("    或 npm:      npm install -g bun")
        else:
            print("    macOS/Linux: curl -fsSL https://bun.sh/install | bash")
            print("    或 npm:       npm install -g bun")
        print("  安装完成后重新运行本安装程序即可继续（本次跳过 cutia 依赖安装）。")
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    ok(f"bun 就绪: {bun_exe}（已同步 {Path.home() / '.bun' / 'bin'}）")
    return str(bun_exe)


def _copytree_into(src: Path, dst: Path) -> None:
    """把 src 目录内容合并拷贝进 dst（dst 可不存在）。"""
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(src), str(dst), symlinks=True, dirs_exist_ok=True,
                   ignore_dangling_symlinks=True)


def prepare_standalone(base: Path) -> bool:
    """把 next build 产生的 .next/standalone 整理为自包含部署目录 apps/web/standalone：
    拷贝 static / public / public/locales，使其可直接用 node 运行（无需完整 node_modules）。

    该目录会随 git 分发；Windows 原生产物供 Windows / 整合包用户免构建直接使用；
    非 Windows 用户重新构建后产出的是本平台原生产物（覆盖即可）。"""
    src = base / "apps" / "web" / ".next" / "standalone"
    # Next 将 outputFileTracingRoot 推断为仓库根（VideoLingoLc），所以 standalone 内 web
    # 路径带 thirdparty/cutia 前缀（而非 apps/web）。以此定位 server.js 与合并目标目录。
    ws_src = src / "thirdparty" / "cutia" / "apps" / "web"
    if not (ws_src / "server.js").exists():
        warn("cutia: 未找到 .next/standalone 产物，跳过 standalone 整理")
        return False
    dst = base / "apps" / "web" / "standalone"
    ws_dst = dst / "thirdparty" / "cutia" / "apps" / "web"
    log("整理 cutia standalone 部署产物 → apps/web/standalone ...")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(str(src), str(dst), symlinks=True, dirs_exist_ok=True,
                   ignore_dangling_symlinks=True)
    web = base / "apps" / "web"
    static_src = web / ".next" / "static"
    if static_src.is_dir():
        _copytree_into(static_src, ws_dst / ".next" / "static")
    public_src = web / "public"
    if public_src.is_dir():
        _copytree_into(public_src, ws_dst / "public")
        locales = public_src / "locales"
        if locales.is_dir():
            _copytree_into(locales, ws_dst / "public" / "locales")
    ok(f"cutia standalone 已就绪（可提交到 git）: {dst}")
    return True


def _link_workspace_libs(base: Path) -> None:
    """Windows 上 bun 无法用 symlink/hardlink 链接 workspace 包到 node_modules（EPERM），
    改为把 packages/* 下的 workspace 库包源码复制到 node_modules/@cutia/<name>。
    这些包 exports 指向 src/*.ts，由 next.config 的 transpilePackages 编译，无需 build dist。"""
    import json
    nm = base / "node_modules"
    root_pkg = base / "package.json"
    if not root_pkg.exists():
        return
    try:
        data = json.loads(root_pkg.read_text(encoding="utf-8"))
    except Exception:
        return
    ws = data.get("workspaces") or {}
    patterns = ws.get("packages") if isinstance(ws, dict) else (ws or [])
    for pat in patterns:
        if not str(pat).startswith("packages"):
            continue
        for src in base.glob(str(pat)):
            if not src.is_dir():
                continue
            pj = src / "package.json"
            if not pj.exists():
                continue
            try:
                name = json.loads(pj.read_text(encoding="utf-8")).get("name")
            except Exception:
                continue
            if not name or not name.startswith("@cutia/"):
                continue
            dst = nm / name
            if dst.exists():
                shutil.rmtree(str(dst))
            log(f"复制 workspace 包 {name} -> node_modules（规避 Windows symlink EPERM）")
            shutil.copytree(str(src), str(dst))


def ensure_cutia(force: bool) -> bool:
    """cutia 部署策略：
    - Windows / 整合包用户：优先使用已提交（Windows 构建）的 apps/web/standalone 产物，
      跳过 bun 安装与构建（运行时用 node 直接跑 standalone，无需完整 node_modules）。
    - 非 Windows 用户：standalone 为平台相关产物，必须重新构建
      （bun install 下载依赖 + bun run build:web 产出本平台原生 standalone）。
    """
    print("\n[4/5] cutia（运行时：Windows 用已提交 standalone / 非 Windows 重新构建）")
    base = THIRDPARTY / "cutia"
    if not base.exists():
        warn("cutia 目录不存在（上游未提供该 workspace），跳过")
        return False
    standalone_dir = base / "apps" / "web" / "standalone"
    has_committed = (standalone_dir / "apps" / "web" / "server.js").exists()

    if is_windows():
        if has_committed and not force:
            ok("cutia: 使用已提交的 standalone 产物（Windows 原生），跳过 bun 安装与构建")
            return True
        if not has_committed and not force:
            warn("cutia: 未找到已提交的 standalone 产物（apps/web/standalone）。"
                 "Windows 用户需先在 Windows 上构建并提交该产物；本次跳过 cutia 部署。")
            return False
        log("cutia: 按 --force / 缺失重建，执行 bun install + build:web ...")
    else:
        # 非 Windows：提交的 standalone 为 Windows 产物，跨平台不保证，始终重新构建
        if has_committed and not force:
            log("cutia: 检测到已提交的（Windows）standalone，但非 Windows 需本平台原生构建，将重新构建...")
        else:
            log("cutia: 非 Windows 平台，执行 bun install + build:web 以产出原生 standalone ...")

    bun = ensure_bun(force)
    if not bun:
        warn("bun 不可用，跳过 cutia 构建")
        return False
    # 仅当依赖缺失（或不完整）时安装；以 build 必需的关键可执行 turbo 是否存在作为完整性判据，
    # 避免 EPERM 残留的不完整 node_modules 被误判为已就绪而导致 build 报 MODULE_NOT_FOUND。
    # force 只用于「重新 build standalone 产物」，不再触发全量重装。
    nm = base / "node_modules"
    turbo_bin = nm / "turbo" / "bin" / "turbo"
    import json

    def _read_ver(p):
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("version", "")
        except Exception:
            return ""

    # cutia 源码使用 Zod 3 API（如 z.record(z.string()) 单参），但 bun 可能将 bun.lock 解析到
    # zod 4，导致 next build 的 TS 类型检查失败。通过 overrides 强制回退到 zod 3.x（不删 lock，避免其他依赖漂移）。
    _zver = _read_ver(nm / "zod" / "package.json")
    # next 双版本（apps/web 与根不一致）会使 withBotId(nextConfig) 类型冲突，需统一。
    _nv_web = _read_ver(nm / "apps" / "web" / "node_modules" / "next" / "package.json")
    _nv_root = _read_ver(nm / "next" / "package.json")

    _need_reinstall = False
    if _zver.startswith("4."):
        log(f"检测到 zod {_zver}（cutia 源码需 Zod 3 API），将通过 overrides 回退到 zod 3.x")
        _need_reinstall = True
    if _nv_web and _nv_root and _nv_web != _nv_root:
        log(f"检测到 next 双版本 (apps/web {_nv_web} vs root {_nv_root})，将通过 overrides 统一")
        _need_reinstall = True

    # force 时也要跑 bun install，以应用 overrides 等 package.json 变更（增量安装，非全量）
    if not nm.is_dir() or not turbo_bin.is_file() or _need_reinstall or force:
        log("执行 bun install（cutia 为 bun workspace）...")
        # Windows 上 bun 将 workspace 本地包(@cutia/env/ui/web)物理链接到 node_modules 时常因
        # 符号链接/硬链接权限(EPERM)失败。临时注入 [install] linkWorkspacePackages=false 跳过
        # workspace 物理链接（bun/turbo/next 仍通过 workspace 协议解析源码），配合 --backend=copyfile
        # 复制普通依赖，从而规避链接权限问题。装完即还原，不污染 cutia 源码。
        bunfig = base / "bunfig.toml"
        bak = None
        if bunfig.exists():
            bak = base / "bunfig.toml.bak"
            shutil.move(str(bunfig), str(bak))
        bunfig.write_text("[install]\nlinkWorkspacePackages = false\n")
        try:
            result = run([bun, "install", "--backend=copyfile"], cwd=str(base), check=False)
        finally:
            bunfig.unlink(missing_ok=True)
            if bak is not None:
                shutil.move(str(bak), str(bunfig))
        if result.returncode != 0:
            warn("cutia 依赖安装失败，标记为跳过")
            return False
    # Windows 上 bun 无法用 symlink 链接 workspace 包（EPERM），改为复制源码到 node_modules。
    # 这些包 exports 指向 src/*.ts，由 next.config 的 transpilePackages 编译（无需 build dist）。
    _link_workspace_libs(base)
    log("执行 bun run build:web --force（强制重建，确保 .next/standalone 产物生成）...")
    result = run([bun, "run", "build:web", "--", "--force"], cwd=str(base), check=False)
    if result.returncode != 0:
        warn("cutia 构建失败，标记为跳过")
        return False
    prepared = prepare_standalone(base)
    return prepared


# ---------------------------------------------------------------------------
# 5. pi 智能体（Node.js）
# ---------------------------------------------------------------------------
def ensure_pi(force: bool) -> None:
    """pi 智能体：后端用 `node cli.js` 启动（backend/pi_rpc/client.py），
    必须依赖 Node.js（engines >= 22.19）。各包 dist 已随 git 上传，无需重建；
    本步骤只需保证 pi root 的 node_modules（npm workspaces）存在。"""
    print("\n[5/5] pi 智能体（Node.js）")
    base = THIRDPARTY / "pi"
    if not base.exists():
        warn("目录不存在，跳过")
        return
    cli = base / "packages" / "coding-agent" / "dist" / "cli.js"
    if not cli.exists():
        warn("pi 的 dist 构建产物缺失（git 仓库应已上传 packages/*/dist）；跳过依赖安装")
        return
    node = find_exe(["node.exe", "node"])
    if not node:
        warn("未找到 node（pi 需要 Node.js >= 22.19），跳过依赖安装")
        return
    npm = find_exe(["npm.cmd", "npm"])
    if not npm:
        warn("未找到 npm，跳过 pi 依赖安装")
        return
    if not (base / "node_modules").exists() or force:
        log("执行 npm install（pi 为 npm workspaces 仓库，忽略生命周期脚本）...")
        run([npm, "install", "--ignore-scripts", "--prefer-offline"], cwd=str(base))
    ok("pi 依赖就绪（node_modules；dist 使用 git 已提交产物）")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="thirdparty 第三方扩展安装")
    parser.add_argument("--force", action="store_true", help="强制重新下载/构建")
    parser.add_argument("--skip-cloakbrowser", action="store_true")
    parser.add_argument("--skip-social", action="store_true")
    parser.add_argument("--skip-qm", action="store_true")
    parser.add_argument("--skip-cutia", action="store_true")
    parser.add_argument("--skip-pi", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  VideoLingoFlow 第三方扩展安装")
    print(f"  平台: {platform_tag()}   强制模式: {args.force}")
    print("=" * 60)

    # 0. 释放子项目 git 元数据（分发版 .git 以归档携带；缺失时解压还原，保证各项目可 git 更新）
    try:
        import git_restore
        git_restore.main()
    except Exception as e:
        warn(f"git 信息释放跳过: {e}")

    results = []
    if not args.skip_cloakbrowser:
        cb = ensure_cloakbrowser(args.force)
        results.append(("CloakBrowser", "OK" if cb else "跳过"))
    if not args.skip_social:
        ensure_social(args.force)
        results.append(("social-auto-upload-web-ui", "OK"))
    if not args.skip_qm:
        ensure_qm_router(args.force)
        results.append(("QM-LocalRouter", "OK"))
    if not args.skip_cutia:
        cutia_ok = ensure_cutia(args.force)
        results.append(("cutia", "OK" if cutia_ok else "跳过"))
    if not args.skip_pi:
        ensure_pi(args.force)
        results.append(("pi", "OK"))

    print("\n" + "=" * 60)
    print("  安装结果汇总")
    print("=" * 60)
    for name, status in results:
        print(f"  - {name:<28} {status}")
    print()
    ok("第三方扩展安装流程执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
