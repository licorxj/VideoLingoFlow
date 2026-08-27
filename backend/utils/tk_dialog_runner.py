"""
Standalone dialog runner invoked by the backend as a subprocess.

Running tkinter in a separate process (on its main thread) avoids two problems:
1. tkinter is not thread-safe; creating dialogs from a daemon thread can crash/hang.
2. A crash during dialog initialization is isolated to this subprocess and will not
   take down the main backend.
"""
import json
import os
import sys
from pathlib import Path


def _normalize_filetypes(filetypes):
    """Convert frontend filetypes to tkinter (display_name, pattern) tuples."""
    if not filetypes:
        return [("All files", "*.*")]

    out = []
    for ft in filetypes:
        if isinstance(ft, dict):
            name = ft.get("name", "Files")
            exts = ft.get("extensions", ["*"])
            patterns = []
            for ext in exts:
                ext = str(ext).strip().lstrip(".")
                if not ext or ext == "*":
                    patterns.append("*.*")
                else:
                    patterns.append(f"*.{ext}")
            out.append((name, " ".join(patterns)))
        elif isinstance(ft, (list, tuple)) and len(ft) >= 2:
            out.append((ft[0], ft[1]))
        else:
            out.append((str(ft), "*.*"))
    return out


def _initial_dir(default_dir):
    if not default_dir:
        return None
    p = Path(os.path.expanduser(str(default_dir)))
    if p.is_file():
        p = p.parent
    if p.is_dir():
        return str(p)
    # Fallback: return the parent if it exists, otherwise the path as-is.
    if p.parent.is_dir():
        return str(p.parent)
    return str(p)


def main():
    try:
        req = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except Exception as exc:
        print(json.dumps({"error": f"invalid request: {exc}"}), flush=True)
        return 1

    dialog_type = req.get("type") or req.get("dialog_type", "file")
    title = req.get("title") or "Select"
    default_dir = _initial_dir(req.get("default_dir"))
    filetypes = _normalize_filetypes(req.get("filetypes"))
    multiple = bool(req.get("multiple", False))
    default_name = req.get("default_name") or ""

    # Delay tkinter import so that JSON parsing errors do not initialize Tcl.
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    try:
        if dialog_type == "folder":
            selected = filedialog.askdirectory(parent=root, title=title, mustexist=True)
            paths = [selected] if selected else []
        elif dialog_type in ("file", "files"):
            if multiple:
                selected = filedialog.askopenfilenames(
                    parent=root,
                    title=title,
                    initialdir=default_dir,
                    filetypes=filetypes,
                )
                paths = list(selected)
            else:
                selected = filedialog.askopenfilename(
                    parent=root,
                    title=title,
                    initialdir=default_dir,
                    filetypes=filetypes,
                )
                paths = [selected] if selected else []
        elif dialog_type == "save":
            selected = filedialog.asksaveasfilename(
                parent=root,
                title=title,
                initialdir=default_dir,
                initialfile=default_name,
                filetypes=filetypes,
            )
            paths = [selected] if selected else []
        else:
            print(json.dumps({"error": f"unsupported dialog_type: {dialog_type}"}), flush=True)
            return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        return 1
    finally:
        root.destroy()

    print(json.dumps({"paths": paths}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
