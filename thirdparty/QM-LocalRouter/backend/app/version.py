"""Version identification for LocalRouter.

Resolution order (first hit wins):
  1. PyInstaller one-file release: a bundled ``version.json`` written at build
     time (see .github/workflows/build-release.yml) carrying the git tag/commit.
  2. A live Git checkout: ``git describe --tags --always --dirty``.
  3. Environment overrides ``GIT_TAG`` / ``GIT_COMMIT`` (handy for containers).
  4. The static ``APP_VERSION`` from app config.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from app.config import BASE_DIR

try:  # APP_VERSION 可能是模块级常量，也可能是 Settings 类字段
    from app.config import APP_VERSION
except ImportError:  # pragma: no cover - 取决于 config.py 的组织方式
    from app.config import settings as _settings
    APP_VERSION = _settings.APP_VERSION

REPOSITORY_ROOT = BASE_DIR.parent


def _bundled_meta() -> dict | None:
    if not getattr(sys, "frozen", False):
        return None
    bases = [Path(sys.executable).resolve().parent]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(Path(meipass))
    for base in bases:
        cand = base / "version.json"
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _git_describe() -> dict | None:
    if not (REPOSITORY_ROOT / ".git").is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=str(REPOSITORY_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None

    desc = out.stdout.strip()
    dirty = desc.endswith("-dirty")
    if dirty:
        desc = desc[: -len("-dirty")]

    tag = None
    commit = desc
    if "-g" in desc:
        # Form: <tag>-<n>-g<hash>  -> we are ahead of a tag
        commit = desc.split("-g")[-1]
    else:
        commit = desc
        # A bare hash (no tag yet) is all hex; otherwise treat it as a tag.
        if not all(c in "0123456789abcdef" for c in desc):
            tag = desc
    return {"git_tag": tag, "git_commit": commit, "git_dirty": dirty}


def get_version_info() -> dict:
    info = {
        "version": APP_VERSION,
        "git_tag": None,
        "git_commit": None,
        "git_dirty": False,
        "build_type": "dev",
    }

    meta = _bundled_meta()
    if meta:
        info["build_type"] = "release"
        info["git_tag"] = meta.get("git_tag")
        info["git_commit"] = meta.get("git_commit")
        info["git_dirty"] = bool(meta.get("git_dirty", False))
    else:
        g = _git_describe()
        if g:
            info.update(g)

    if info["git_commit"] is None:
        info["git_commit"] = os.environ.get("GIT_COMMIT")
    if info["git_tag"] is None:
        info["git_tag"] = os.environ.get("GIT_TAG")

    # Prefer the git tag as the semantic version (strip a leading "v").
    if info["git_tag"]:
        stripped = info["git_tag"].lstrip("v")
        if stripped:
            info["version"] = stripped
    return info
