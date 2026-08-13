from __future__ import annotations

import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path


class CutiaUpdateError(Exception):
    pass


class CutiaUpdater:
    _lock = threading.Lock()
    _allowed_remotes = {
        "https://github.com/msgbyte/cutia.git",
        "git@github.com:msgbyte/cutia.git",
        "ssh://git@ssh.github.com:443/msgbyte/cutia.git",
    }

    def __init__(self) -> None:
        self.repository_path = Path(__file__).resolve().parents[2] / "thirdparty" / "cutia"

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repository_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CutiaUpdateError("未找到 Git，无法更新 Cutia。") from exc
        except subprocess.TimeoutExpired as exc:
            raise CutiaUpdateError("Git 操作超时，未执行更新。") from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise CutiaUpdateError(message or "Git 操作失败，未执行更新。")
        return result.stdout.strip()

    def update(self) -> dict[str, str | bool]:
        with self._lock:
            if not (self.repository_path / ".git").exists():
                raise CutiaUpdateError("未找到 Cutia Git 仓库。")

            remote = self._run("remote", "get-url", "origin")
            if remote not in self._allowed_remotes:
                raise CutiaUpdateError("Cutia 远端不是官方 msgbyte/cutia 仓库，已取消更新。")

            branch = self._run("branch", "--show-current")
            if branch != "main":
                raise CutiaUpdateError(f"当前分支为 {branch or 'detached HEAD'}，仅允许从 main 分支更新。")

            changes = self._run("status", "--porcelain")
            if changes:
                raise CutiaUpdateError("Cutia 存在未提交的本地改动。请先提交或备份集成补丁后再更新，系统未修改任何文件。")

            self._run("fetch", "--prune", "origin", "main")
            current_revision = self._run("rev-parse", "HEAD")
            remote_revision = self._run("rev-parse", "origin/main")
            if current_revision == remote_revision:
                return {
                    "success": True,
                    "updated": False,
                    "message": "Cutia 已是最新版本。",
                    "previous_revision": current_revision[:12],
                    "current_revision": current_revision[:12],
                    "backup_branch": "",
                }

            if subprocess.run(
                ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
                cwd=self.repository_path,
                capture_output=True,
                timeout=30,
                check=False,
            ).returncode != 0:
                raise CutiaUpdateError("本地历史无法快进到上游版本，已取消更新以保护本地版本。")

            backup_branch = f"videolingo-pre-update-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            if not re.fullmatch(r"videolingo-pre-update-\d{8}-\d{6}", backup_branch):
                raise CutiaUpdateError("无法生成安全备份分支名。")
            self._run("branch", backup_branch, current_revision)
            self._run("merge", "--ff-only", "origin/main")

            return {
                "success": True,
                "updated": True,
                "message": "Cutia 已安全更新。请重新构建并重启 Cutia 服务。",
                "previous_revision": current_revision[:12],
                "current_revision": remote_revision[:12],
                "backup_branch": backup_branch,
            }
