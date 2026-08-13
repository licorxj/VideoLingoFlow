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
  4. cutia (bun 运行)            保证 bun 可用 + bun install（开发服务器模式，无需生产构建）
  5. pi (Node.js)                保证 node_modules 就绪（各包 dist 已随 git 上传，无需重建）

平台策略:
  - Windows:    优先使用 git 仓库内已提交的 dist 构建产物（无 node 环境的用户可直接使用）；
                产物缺失时用 npm 构建。
  - 非 Windows: 每次重新构建各项目前端（提交的 dist 为 Windows 产物，不做跨平台保证）。

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
        PROJECT_ROOT / "backend" / "venv312" / "Scripts" / "python.exe",
        PROJECT_ROOT / "backend" / "venv312" / "bin" / "python",
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
            fail(f"CloakBrowser 下载失败: {last_err}")
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
            fail(f"CloakBrowser 解压后未找到浏览器二进制: {target_bin}")
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
        warn(f"{label}: 未发现共享 venv（backend/venv312），跳过 pip 安装（启动管理器会自愈）")
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
def ensure_qm_router(force: bool) -> None:
    print("\n[3/4] QM-LocalRouter")
    base = THIRDPARTY / "QM-LocalRouter"
    if not base.exists():
        warn("目录不存在，跳过")
        return
    ensure_backend_pip(base / "backend" / "requirements.txt", "QM-LocalRouter 后端")
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
    found = os.environ.get("BUN_CMD") or find_exe(["bun.exe", "bun"])
    if found and not force:
        log(f"使用现有 bun: {found}")
        return found
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


def ensure_cutia(force: bool) -> None:
    print("\n[4/5] cutia（bun 运行）")
    base = THIRDPARTY / "cutia"
    if not base.exists():
        warn("目录不存在，跳过")
        return
    bun = ensure_bun(force)
    if not bun:
        warn("bun 不可用，跳过 cutia 依赖安装")
        return
    if not (base / "node_modules").exists() or force:
        log("执行 bun install（cutia 为 bun workspace）...")
        run([bun, "install"], cwd=str(base))
    # cutia 以开发服务器模式运行（bun run dev:web），无需生产构建
    ok("cutia 依赖就绪（开发服务器模式，无需构建产物）")


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
        ensure_cutia(args.force)
        results.append(("cutia", "OK"))
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
