"""File operation utilities."""
import os
import shutil
from typing import Optional


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def copy_file(src: str, dst: str):
    ensure_dir(os.path.dirname(dst))
    shutil.copy2(src, dst)


def safe_remove(path: str):
    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    except Exception:
        pass


def find_files(directory: str, extensions: tuple) -> list:
    """Find files with given extensions in directory."""
    results = []
    if not os.path.isdir(directory):
        return results
    for f in os.listdir(directory):
        if f.lower().endswith(extensions):
            results.append(os.path.join(directory, f))
    return results
