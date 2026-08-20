#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""venv312 重定位自愈脚本（分发包首次运行）。

把随包分发的 venv312 适配到当前机器：
  阶段 1（任意可用 Python 3.12 执行，仅标准库）：
    - 探测本机基础 Python（优先随包 python-base/，其次 py -3.12 / python）
    - 重写 pyvenv.cfg 的 home / executable / command
    - 重写 Scripts/activate.bat、activate 中的 VIRTUAL_ENV 绝对路径
    - 重写 Scripts 下脚本文件的 shebang
  阶段 2（用修好的 venv python 执行自身 --regenerate-launchers）：
    - 用 distlib ScriptMaker 重新生成全部控制台 .exe 启动器
  阶段 3：验证 pip 可用。

用法：
    python installer\\fix_venv_relocate.py            # 完整修复
    python installer\\fix_venv_relocate.py --regenerate-launchers   # 内部子步骤
"""
import os
import re
import shutil
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 分发包布局：脚本与 venv312 同级（分发包根目录内）；
# 开发机布局：脚本在 installer/ 下，venv312 在上两级的项目根。
if os.path.isdir(os.path.join(_SCRIPT_DIR, "venv312")):
    ROOT = _SCRIPT_DIR
else:
    ROOT = os.path.dirname(_SCRIPT_DIR)
VENV = os.path.join(ROOT, "venv312")
VENV_PY = os.path.join(VENV, "Scripts", "python.exe")
SCRIPTS = os.path.join(VENV, "Scripts")
# 随包 python-base 探测位置（按优先级）：
#   1. 项目根 python-base/         （开发机布局）
#   2. 项目根 Windows分发包-*/python-base/（分发包布局）
#   3. 脚本所在目录自身（分发包根目录内的独立副本）
BUNDLED_CANDIDATES = [os.path.join(ROOT, "python-base", "python.exe")]
for _d in sorted(os.listdir(ROOT)):
    if _d.startswith("Windows分发包"):
        BUNDLED_CANDIDATES.append(os.path.join(ROOT, _d, "python-base", "python.exe"))
BUNDLED_CANDIDATES.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "python-base", "python.exe"))


def log(msg: str) -> None:
    print(f"  [fix-venv] {msg}")


# ---------------------------------------------------------------------------
# 阶段 1
# ---------------------------------------------------------------------------
def find_base_python() -> str:
    """寻找本机可用的 Python 3.12 基础解释器（随包 python-base 优先）。"""
    candidates = [p for p in BUNDLED_CANDIDATES if os.path.isfile(p)]
    candidates += ["py", "python", "python3"]
    for cand in candidates:
        exe = cand if os.path.isfile(cand) else shutil.which(cand)
        if not exe:
            continue
        # 跳过 venv 自身的解释器（基础解释器必须在 venv 之外）
        if VENV.lower() in os.path.abspath(exe).lower():
            continue
        args = [exe, "-3.12", "--version"] if os.path.basename(exe).lower() == "py.exe" else [exe, "--version"]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=20)
            text = (out.stdout or out.stderr).strip()
            m = re.search(r"Python (\d+)\.(\d+)", text)
            if m and (int(m.group(1)), int(m.group(2))) == (3, 12):
                if os.path.basename(exe).lower() == "py.exe":
                    # py 启动器不是解释器本体，取其指向的真实路径
                    real = subprocess.run(
                        ["py", "-3.12", "-c", "import sys; print(sys.executable)"],
                        capture_output=True, text=True, timeout=20,
                    ).stdout.strip()
                    if real and os.path.isfile(real):
                        return real
                return os.path.abspath(exe)
        except Exception:
            continue
    raise SystemExit(
        "[错误] 未找到 Python 3.12 基础解释器。\n"
        "        请安装 Python 3.12（python.org 或 随包 python-base/），然后重新运行本脚本。"
    )


def rewrite_pyvenv_cfg(base_python: str) -> None:
    cfg = os.path.join(VENV, "pyvenv.cfg")
    home = os.path.dirname(base_python)
    lines = []
    with open(cfg, encoding="utf-8") as f:
        for line in f:
            key = line.split("=", 1)[0].strip()
            if key == "home":
                line = f"home = {home}\n"
            elif key == "executable":
                line = f"executable = {base_python}\n"
            elif key == "command":
                line = f'command = {base_python} -m venv --prompt="videoLingo312" {VENV}\n'
            lines.append(line)
    with open(cfg, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log(f"pyvenv.cfg -> home = {home}")


def rewrite_activate_scripts() -> None:
    new_env = VENV
    # activate.bat
    bat = os.path.join(SCRIPTS, "activate.bat")
    if os.path.isfile(bat):
        with open(bat, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"set VIRTUAL_ENV=.*", lambda m: f"set VIRTUAL_ENV={new_env}", text)
        with open(bat, "w", encoding="utf-8") as f:
            f.write(text)
    # activate (POSIX)
    sh = os.path.join(SCRIPTS, "activate")
    if os.path.isfile(sh):
        with open(sh, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r'cygpath "[^"]*venv312"', lambda m: f'cygpath "{new_env}"', text)
        text = re.sub(r'VIRTUAL_ENV="[^"]*venv312"', lambda m: f'VIRTUAL_ENV="{new_env}"', text)
        with open(sh, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    log("activate / activate.bat -> VIRTUAL_ENV 已重写")


def rewrite_shebangs() -> None:
    target = f"#!{VENV_PY}\n".encode("utf-8")
    fixed = 0
    for name in os.listdir(SCRIPTS):
        path = os.path.join(SCRIPTS, name)
        if not os.path.isfile(path) or name.lower().endswith((".exe", ".dll", ".pyd")):
            continue
        try:
            with open(path, "rb") as f:
                first = f.readline()
                rest = f.read()
        except OSError:
            continue
        if first.startswith(b"#!") and b"venv312" in first and b"python.exe" in first:
            if first.rstrip(b"\r\n") != target.rstrip(b"\n"):
                with open(path, "wb") as f:
                    f.write(target + rest)
                fixed += 1
    log(f"shebang 重写: {fixed} 个文件")


def verify_venv_python() -> None:
    r = subprocess.run([VENV_PY, "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True)
    if r.returncode != 0 or "venv312" not in r.stdout:
        raise SystemExit(f"[错误] venv python 仍不可用:\n{r.stdout}{r.stderr}")
    log(f"venv python OK: {r.stdout.strip()}")


# ---------------------------------------------------------------------------
# 阶段 2（由修复后的 venv python 执行）
# ---------------------------------------------------------------------------
def regenerate_launchers() -> None:
    try:
        from distlib.scripts import ScriptMaker
    except ImportError:
        from pip._vendor.distlib.scripts import ScriptMaker
    import importlib.metadata as imd

    existing = {
        os.path.splitext(f)[0] for f in os.listdir(SCRIPTS) if f.lower().endswith(".exe")
    } - {"python", "pythonw"}

    maker = ScriptMaker(None, SCRIPTS)
    maker.clobber = True
    maker.executable = VENV_PY  # 启动器内嵌新的解释器路径
    maker.set_mode = False

    count, failed = 0, []
    for dist in imd.distributions():
        try:
            eps = [ep for ep in dist.entry_points if ep.group == "console_scripts"]
        except Exception:
            continue
        for ep in eps:
            for name in (ep.name, ep.name + "3", ep.name + "3.12"):
                if name not in existing:
                    continue
                try:
                    maker.make(f"{name} = {ep.value}")
                    existing.discard(name)
                    count += 1
                except Exception as e:
                    failed.append(f"{name}: {e}")
    log(f"启动器重新生成: {count} 个")
    if failed:
        log(f"失败 {len(failed)} 个: " + "; ".join(failed[:5]))


# ---------------------------------------------------------------------------
def main() -> None:
    if "--regenerate-launchers" in sys.argv:
        regenerate_launchers()
        return

    print("=" * 56)
    print("  VideoLingoLc venv 重定位自愈")
    print("=" * 56)
    if not os.path.isfile(VENV_PY):
        raise SystemExit(f"[错误] 未找到 {VENV_PY}")

    base = find_base_python()
    log(f"基础 Python: {base}")
    rewrite_pyvenv_cfg(base)
    rewrite_activate_scripts()
    rewrite_shebangs()
    verify_venv_python()

    log("重新生成控制台启动器（venv python）...")
    r = subprocess.run([VENV_PY, os.path.abspath(__file__), "--regenerate-launchers"])
    if r.returncode != 0:
        raise SystemExit("[错误] 启动器重新生成失败")

    r = subprocess.run([VENV_PY, "-m", "pip", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[错误] pip 验证失败:\n{r.stdout}{r.stderr}")
    log(f"pip OK: {r.stdout.strip().splitlines()[0]}")
    print("\n[完成] venv312 已适配本机，可运行 start-prod.bat 启动。")


if __name__ == "__main__":
    main()
