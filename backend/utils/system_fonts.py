"""系统字体枚举工具。

跨平台获取操作系统已安装（fontconfig / GDI 可识别）的字体族名称，
供前端字幕样式设置中的字体下拉框使用。
"""
import os
import sys

_FALLBACK_EXTS = (".ttf", ".otf", ".ttc", ".woff", ".woff2")


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result


def _fc_fonts() -> list[str]:
    """通过 fc-list 枚举（Linux / macOS 等装有 fontconfig 的平台）。"""
    import subprocess

    out = subprocess.run(
        ["fc-list", "--format=%{family}\\n"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    fonts: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # family 字段可能是逗号分隔的多个别名
        for part in line.split(","):
            part = part.strip()
            if part:
                fonts.append(part)
    return fonts


def _win_fonts() -> list[str]:
    """通过 GDI EnumFontFamiliesExW 枚举 Windows 系统字体。"""
    import ctypes
    from ctypes import POINTER, WINFUNCTYPE, Structure, byref, wintypes

    class LOGFONTW(Structure):
        _fields_ = [
            ("lfHeight", wintypes.LONG),
            ("lfWidth", wintypes.LONG),
            ("lfEscapement", wintypes.LONG),
            ("lfOrientation", wintypes.LONG),
            ("lfWeight", wintypes.LONG),
            ("lfItalic", wintypes.BYTE),
            ("lfUnderline", wintypes.BYTE),
            ("lfStrikeOut", wintypes.BYTE),
            ("lfCharSet", wintypes.BYTE),
            ("lfOutPrecision", wintypes.BYTE),
            ("lfClipPrecision", wintypes.BYTE),
            ("lfQuality", wintypes.BYTE),
            ("lfPitchAndFamily", wintypes.BYTE),
            ("lfFaceName", wintypes.WCHAR * 32),
        ]

    gdi32 = ctypes.windll.gdi32
    hdc = gdi32.CreateCompatibleDC(0)

    fonts: list[str] = []

    @WINFUNCTYPE(ctypes.c_int, POINTER(LOGFONTW), ctypes.c_void_p, wintypes.DWORD, wintypes.LPARAM)
    def _cb(lplf, _lptm, _fonttype, _lparam):  # noqa: ANN001
        name = lplf.contents.lfFaceName
        if name:
            fonts.append(name)
        return 1

    lf = LOGFONTW()
    lf.lfCharSet = 1  # DEFAULT_CHARSET
    gdi32.EnumFontFamiliesExW.argtypes = [
        wintypes.HDC,
        POINTER(LOGFONTW),
        ctypes.c_void_p,
        wintypes.LPARAM,
        wintypes.DWORD,
    ]
    gdi32.EnumFontFamiliesExW.restype = wintypes.INT
    gdi32.EnumFontFamiliesExW(hdc, byref(lf), _cb, 0, 0)
    gdi32.DeleteDC(hdc)
    return fonts


def _scan_fallback() -> list[str]:
    """fc-list / GDI 不可用时的兜底：扫描常见字体目录的文件名。"""
    if sys.platform.startswith("win"):
        dirs = [os.path.expandvars("%WINDIR%/Fonts")]
    else:
        dirs = [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
            os.path.expanduser("~/Library/Fonts"),
        ]
    fonts: list[str] = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith(_FALLBACK_EXTS):
                    fonts.append(os.path.splitext(f)[0])
    return fonts


def get_system_fonts() -> list[str]:
    """返回系统可用字体族名称列表（去重）。"""
    try:
        if sys.platform.startswith("win"):
            fonts = _win_fonts()
        else:
            fonts = _fc_fonts()
    except Exception:
        fonts = []

    if not fonts:
        try:
            fonts = _scan_fallback()
        except Exception:
            fonts = []

    return sorted(_dedupe(fonts))
