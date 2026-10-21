# -*- coding: utf-8 -*-
"""视频工具公共部分：找 ffmpeg、跑命令（带进度）、读视频信息、输出路径、报错翻译、时间解析。

安全说明（准确描述实际做法）：
- 所有命令都用列表形式交给 subprocess（shell=False），不经过命令行外壳，不存在外壳注入。
- 用户给的视频/音乐路径作为独立的一个参数传给 ffmpeg（「-i 路径」）。
- 字幕文件路径、字体路径需要嵌进滤镜参数里：这两处先校验（文件存在、扩展名对），
  再用 esc_filter_value 按 libavfilter 的两层规则完整转义后拼入，见该函数说明。
- 水印文字不进命令行：先写进临时文本文件，再让 ffmpeg 用 textfile 读取，并关闭 % 展开。
- 每次运行前都会打印「将运行：<程序绝对路径> <参数>」，不隐藏实际执行的内容。
- 不保存任何配置：ffmpeg 位置每次都从系统 PATH / 受管安装目录查找，或由本次命令的 --ffmpeg 指定。
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading

IS_WINDOWS = sys.platform == "win32"
OUT_FOLDER = "处理后"
EXE = ".exe" if IS_WINDOWS else ""


class UserError(Exception):
    """给用户看的错误：两行，出错了 + 下一步。"""

    def __init__(self, what, next_step):
        super().__init__(what)
        self.what = what
        self.next_step = next_step


# ---------------- 找 ffmpeg ----------------
# 不持久化 ffmpeg 位置，也不扫描「下载」「桌面」、Scoop、WinGet 包目录这类用户可写目录：
# 只信任系统 PATH、管理员才能写的受管安装目录、以及用户在本次命令里用 --ffmpeg 明确指定的位置。

FF_NAMES = ("ffmpeg" + EXE, "ffprobe" + EXE)


def managed_dirs():
    """受管安装目录（Windows 下是 Program Files，普通用户写不进去）。"""
    if IS_WINDOWS:
        dirs = []
        for var, default in (("ProgramFiles", r"C:\Program Files"), ("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            base = os.environ.get(var, default)
            if base:
                dirs.append(os.path.join(base, "ffmpeg", "bin"))
        return dirs
    return ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/snap/bin"]


def valid_tool(path, which):
    """重新校验一个程序路径：是绝对路径、文件存在、文件名正好是 ffmpeg(.exe) / ffprobe(.exe)。"""
    return (bool(path) and os.path.isabs(path) and os.path.isfile(path)
            and os.path.basename(path).lower() == FF_NAMES[which].lower())


def _pair_in(folder):
    """folder 里同时有 ffmpeg 和 ffprobe 才算找到；返回两者的真实绝对路径。"""
    ff = os.path.realpath(os.path.join(folder, FF_NAMES[0]))
    fp = os.path.realpath(os.path.join(folder, FF_NAMES[1]))
    if valid_tool(ff, 0) and valid_tool(fp, 1):
        return ff, fp
    return None


def _resolve_user_path(p):
    """用户给的可能是 ffmpeg.exe 本身、bin 文件夹、或解压出来的总文件夹（里面有 bin）。

    不做环境变量 / ~ 展开，只去掉首尾空白和引号后取真实绝对路径（realpath）。
    """
    p = os.path.realpath(str(p).strip().strip('"'))
    if os.path.isfile(p):
        if os.path.basename(p).lower() not in [n.lower() for n in FF_NAMES]:
            return None
        p = os.path.dirname(p)
    for cand in (p, os.path.join(p, "bin")):
        r = _pair_in(cand)
        if r:
            return r
    return None


INSTALL_GUIDE = """还没找到视频处理工具 ffmpeg（免费、开源，处理视频都靠它）。请先装一下，二选一：

方法一（推荐，Windows 10/11）：
  1. 按键盘上的 Win 键，输入「终端」或「PowerShell」，打开它；
  2. 输入下面这一行，回车，等它提示安装完成：
       winget install Gyan.FFmpeg
  3. 关掉这个窗口，再回来跟我说「装好了」。

方法二（手动下载）：
  1. 浏览器打开 ffmpeg 官网 https://ffmpeg.org/download.html ，选 Windows 版本下载压缩包；
  2. 解压到一个好找的地方，比如 D:\\ffmpeg；
  3. 把解压后的文件夹位置告诉我（例如「ffmpeg 在 D:\\ffmpeg」），之后每次处理我都会带上这个位置
     （本工具不会把它保存到电脑上）。

苹果电脑：在「终端」里输入 brew install ffmpeg 。
我不会自动帮你下载或安装任何软件。"""


def find_ffmpeg(user_path=None):
    """返回 (ffmpeg, ffprobe) 的真实绝对路径；找不到抛 UserError（附安装指引）。

    查找顺序：本次命令 --ffmpeg 指定的位置 → 系统 PATH → 受管安装目录。不读也不写任何配置文件。
    """
    if user_path:
        r = _resolve_user_path(user_path)
        if not r:
            raise UserError(f"你给的位置里没找到 ffmpeg 和 ffprobe 这两个程序：{user_path}",
                            "请确认是解压后的文件夹（里面有 bin 文件夹，bin 里有 ffmpeg 和 ffprobe），再把那个位置告诉我。")
        return r
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ff and fp:
        ff, fp = os.path.realpath(ff), os.path.realpath(fp)
        if valid_tool(ff, 0) and valid_tool(fp, 1):
            return ff, fp
    for d in managed_dirs():
        r = _pair_in(d)
        if r:
            return r
    raise UserError("这台电脑上还没有视频处理工具 ffmpeg。\n" + INSTALL_GUIDE,
                    "装好后跟我说「装好了」；或者把 ffmpeg 解压后的文件夹位置告诉我。")


# ---------------- 时间 / 大小 ----------------

def parse_time(text):
    """把 1:23、01:02:03、90、90秒、1分30秒、1小时2分、2.5 等转成秒。"""
    if text is None:
        return None
    t = str(text).strip().replace("：", ":").replace(" ", "")
    if not t:
        return None
    if re.fullmatch(r"\d+(\.\d+)?[sS]?", t):
        return float(t.rstrip("sS"))
    if re.fullmatch(r"\d+(:\d{1,2}){1,2}(\.\d+)?", t):
        parts = [float(x) for x in t.split(":")]
        sec = 0.0
        for p in parts:
            sec = sec * 60 + p
        return sec
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)(?:小时|时|h|H))?(?:(\d+(?:\.\d+)?)(?:分钟|分|m|M))?(?:(\d+(?:\.\d+)?)(?:秒钟|秒|s|S)?)?", t)
    if m and any(m.groups()):
        h, mi, s = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + s
    raise UserError(f"看不懂这个时间：{text}",
                    "请用「1分30秒」「1:30」「01:02:03」或「90」（秒）这样的写法再说一次。")


def fmt_dur(sec):
    sec = max(0.0, float(sec or 0))
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    frac = sec - int(sec)
    s_txt = f"{s + frac:04.1f}" if frac >= 0.05 else f"{s:02d}"
    return f"{h}:{m:02d}:{s_txt}" if h else f"{m:02d}:{s_txt}"


def fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_ts_arg(sec):
    """内部用：秒数转成工具认的时间文本（固定格式，不含用户原文）。"""
    return f"{max(0.0, sec):.3f}"


# ---------------- 输入 / 输出路径 ----------------

def check_input(path):
    if re.match(r"^\s*(https?|rtmp|rtsp|ftp)://", str(path), re.I):
        raise UserError("这是一个网址。这个技能不下载网上的视频。",
                        "请先把你自己有权处理的视频保存到电脑上，再告诉我文件在哪。")
    p = os.path.realpath(str(path).strip().strip('"'))
    if not os.path.isfile(p):
        raise UserError(f"找不到这个文件：{p}",
                        "请在文件上按住 Shift 点右键，选「复制文件地址」，再粘贴给我。")
    return p


def _protected_dirs():
    """不允许把新文件写进去的系统目录。"""
    if IS_WINDOWS:
        out = []
        for var, default in (("SystemRoot", r"C:\Windows"), ("windir", r"C:\Windows"),
                             ("ProgramFiles", r"C:\Program Files"), ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             ("ProgramW6432", r"C:\Program Files")):
            out += [os.environ.get(var) or default, default]
        return out
    return ["/bin", "/sbin", "/usr", "/etc", "/boot", "/lib", "/lib64", "/opt", "/System", "/Library",
            "/Applications", "/private/etc"]


def _under(path, parent):
    try:
        a = os.path.normcase(os.path.realpath(path))
        b = os.path.normcase(os.path.realpath(parent))
        return os.path.commonpath([a, b]) == b
    except ValueError:      # 不在同一个盘
        return False


def check_out_dir(d):
    """校验 --out-dir：取真实绝对路径，拒绝系统目录（Windows 目录、Program Files 等）和同名的普通文件。"""
    if not d:
        return None
    p = os.path.realpath(str(d).strip().strip('"'))
    for bad in _protected_dirs():
        if _under(p, bad):
            raise UserError(f"不能把新文件放进系统文件夹：{p}",
                            "请换一个自己的文件夹，比如桌面、文档，或者视频所在的文件夹。")
    if os.path.exists(p) and not os.path.isdir(p):
        raise UserError(f"这个位置是一个文件，不是文件夹：{p}", "请换一个文件夹位置。")
    return p


def unique_path(base_dir, stem, ext, avoid=None):
    """在 base_dir 里起一个还不存在的名字：先试 stem+ext，重名就依次试 stem_1、stem_2……

    ext 为空字符串时得到的是文件夹名。avoid 是绝不能等于的路径（原视频）。
    """
    def taken(c):
        return os.path.exists(c) or bool(
            avoid and os.path.normcase(os.path.abspath(c)) == os.path.normcase(os.path.abspath(avoid)))
    cand = os.path.join(base_dir, f"{stem}{ext}")
    i = 1
    while taken(cand):
        cand = os.path.join(base_dir, f"{stem}_{i}{ext}")
        i += 1
    return cand


def _base_dir(src, out_dir):
    base = check_out_dir(out_dir) or os.path.join(os.path.dirname(os.path.abspath(src)), OUT_FOLDER)
    os.makedirs(base, exist_ok=True)
    return base


def out_path(src, tag, ext=None, out_dir=None):
    """在原视频旁边的「处理后」文件夹（或校验过的 --out-dir）里起一个不重名的新文件名，绝不等于原文件。"""
    stem, old_ext = os.path.splitext(os.path.basename(src))
    ext = ext or old_ext or ".mp4"
    if not ext.startswith("."):
        ext = "." + ext
    return unique_path(_base_dir(src, out_dir), f"{stem}_{tag}", ext, avoid=src)


def out_folder(src, tag, out_dir=None):
    """新建一个不重名的文件夹（每隔几秒截图用），重复运行不会写进旧文件夹、不会覆盖旧截图。"""
    stem = os.path.splitext(os.path.basename(src))[0]
    folder = unique_path(_base_dir(src, out_dir), f"{stem}_{tag}", "")
    os.makedirs(folder)
    return folder


# ---------------- 读视频信息 ----------------

def probe(ffprobe, path):
    cmd = [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path]
    show_cmd(cmd)
    r = subprocess.run(cmd, capture_output=True, **_popen_kw())
    if r.returncode != 0:
        raise UserError(translate_error(r.stderr.decode("utf-8", "replace"))[0],
                        "请确认这是一个能正常播放的视频文件。")
    data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    fmt = data.get("format", {})
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    info = {
        "path": path,
        "duration": float(fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0),
        "size": int(fmt.get("size") or os.path.getsize(path)),
        "bitrate": int(fmt.get("bit_rate") or 0),
        "format": fmt.get("format_name", ""),
        "has_video": v is not None,
        "has_audio": a is not None,
    }
    if v:
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        if not rot and (v.get("tags") or {}).get("rotate"):
            rot = int(v["tags"]["rotate"])
        if abs(rot) % 180 == 90:
            w, h = h, w        # 手机竖拍：显示时是竖的
        fps = 0.0
        rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"
        try:
            n, d = rate.split("/")
            fps = float(n) / float(d) if float(d) else 0.0
        except Exception:
            pass
        info.update(width=w, height=h, fps=fps, vcodec=v.get("codec_name", ""),
                    pix_fmt=v.get("pix_fmt", ""), vbitrate=int(v.get("bit_rate") or 0),
                    rotation=rot)
    if a:
        info.update(acodec=a.get("codec_name", ""), sample_rate=int(a.get("sample_rate") or 0),
                    channels=int(a.get("channels") or 0), abitrate=int(a.get("bit_rate") or 0))
    return info


# ---------------- 跑命令 + 进度 ----------------

def _popen_kw():
    kw = {}
    if IS_WINDOWS:
        # 只是不额外弹出黑色控制台窗口；实际运行的程序和参数会先用 show_cmd 打印出来，并非隐藏执行。
        kw["creationflags"] = 0x08000000
    return kw


def show_cmd(cmd):
    """运行前打印「将运行：<程序绝对路径> <参数>」，让用户知道实际执行了什么。"""
    text = subprocess.list2cmdline(cmd) if IS_WINDOWS else " ".join(shlex.quote(c) for c in cmd)
    print(f"将运行：{text}", flush=True)


def progress_percent(line, duration):
    """解析一行进度输出，返回 0-100 的整数；不是进度行返回 None。"""
    line = line.strip()
    if line == "progress=end":
        return 100
    if not duration or duration <= 0:
        return None
    sec = None
    m = re.match(r"out_time_(?:us|ms)=(-?\d+)$", line)   # 两个字段的单位其实都是微秒
    if m:
        sec = int(m.group(1)) / 1_000_000
    else:
        m = re.match(r"out_time=(-?)(\d+):(\d+):(\d+(?:\.\d+)?)$", line)
        if m:
            sec = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + float(m.group(4))
            if m.group(1):
                sec = 0
    if sec is None:
        return None
    return max(0, min(99, int(sec / duration * 100)))


def run_ff(ffmpeg, args, duration=None, label="处理中", cwd=None, quiet=False):
    """跑一次 ffmpeg，边跑边打印进度百分比。失败抛 UserError（已翻译成大白话）。

    用 -n：输出文件已存在时 ffmpeg 直接放弃，绝不覆盖（正常情况下输出名已由 out_path 避开重名）。
    日志级别用 warning，警告也会被收集，出错时一并用于判断原因。
    """
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-n", "-progress", "pipe:1", "-nostats", "-loglevel", "warning"] + list(args)
    show_cmd(cmd)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, **_popen_kw())
    err_lines = []

    def _drain():
        for raw in proc.stderr:
            err_lines.append(raw.decode("utf-8", "replace").rstrip())
            if len(err_lines) > 300:
                del err_lines[:100]

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    last = -10
    for raw in proc.stdout:
        pct = progress_percent(raw.decode("utf-8", "replace"), duration)
        if pct is None or quiet:
            continue
        if pct >= last + 10 or (pct == 100 and last != 100):
            print(f"{label}：{pct}%", flush=True)
            last = pct
    proc.wait()
    t.join(timeout=5)
    err = "\n".join(err_lines)
    # 新版 ffmpeg 遇到 -n 拒绝覆盖时退出码可能仍是 0，所以还要看输出里有没有这句
    if proc.returncode != 0 or re.search(r"already exists\. Exiting", err):
        what, nxt = translate_error(err)
        raise UserError(what, nxt)
    return "\n".join(err_lines)


ERROR_MAP = [
    (r"already exists\. Exiting|Not overwriting", "要写的新文件已经存在，为了不覆盖它，这次没有处理。",
     "再说一次同样的要求就行，会自动换一个新文件名。"),
    (r"No such file or directory", "找不到要处理的文件，或者文件名里有电脑认不出的字符。",
     "请把文件地址重新复制给我；如果文件名特别长或有表情符号，先改个简单的名字。"),
    (r"Permission denied|Access is denied", "文件被别的程序占用了，或者这个文件夹不让写入。",
     "先关掉正在播放或编辑这个视频的软件，再试一次；还不行就把视频复制到桌面再处理。"),
    (r"No space left on device|There is not enough space", "硬盘空间不够了，新文件写不下。",
     "先清理一下硬盘（或换一个空间大的盘），再试一次。"),
    (r"moov atom not found", "这个视频没有录完整（比如录到一半断电、或者传输中断），打不开。",
     "换一份完整的视频再试；手机录的可以重新从手机导出一次。"),
    (r"Invalid data found when processing input|could not find codec parameters|Invalid argument.*input",
     "这个文件打不开：可能已经损坏，或者根本不是视频/音频文件。",
     "先用播放器试试能不能正常播放；能播放的话把文件复制一份再试。"),
    (r"matches no streams|does not contain any stream|Stream specifier .* matches no streams|Output file .* does not contain",
     "这个视频里没有需要的内容（比如要提取声音，但视频本来就是无声的）。",
     "先用「查看视频信息」看看这个视频有没有声音/画面。"),
    (r"Unknown encoder|Encoder not found|Unrecognized option|Option not found",
     "你电脑上的 ffmpeg 版本太旧或者是精简版，缺少需要的功能。",
     "建议按安装说明重新装一个完整版（Windows 用 winget install Gyan.FFmpeg）。"),
    (r"Unable to open .*\.(srt|ass)|Unable to parse|Error initializing filter 'subtitles'|subtitles.*(Error|error)",
     "字幕文件读不出来。", "请确认字幕是 .srt 格式、能用记事本打开看到正常文字。"),
    (r"Cannot load font|Could not load font|font.*not found|Cannot find a valid font",
     "找不到写文字要用的字体。", "可以换一个字体文件再试，或者告诉我电脑里有哪些字体。"),
    (r"Invalid duration|Invalid time", "时间写得不对。", "请用「1分30秒」或「1:30」这样的写法。"),
    (r"Conversion failed|Error while opening encoder|Could not open encoder",
     "转换没成功：视频的某些参数这个格式不支持。", "换成「转成 MP4」再试，或者把视频信息发给我看看。"),
]


def translate_error(stderr):
    for pat, what, nxt in ERROR_MAP:
        if re.search(pat, stderr or "", re.I):
            return what, nxt
    return ("处理没成功，视频工具报告了一个不常见的错误。",
            "先用「查看视频信息」确认视频能正常读取；还不行就把视频复制到桌面、改个简单的文件名再试。")


# ---------------- 滤镜里的路径 ----------------

# 第一层（滤镜选项值）里有特殊含义的字符：反斜杠、单引号、冒号（选项分隔）；
# = 和 % 在这一层不强制转义，但多转义一次无害（反斜杠会被去掉），一并转义更稳妥。
_LEVEL1_SPECIAL = "\\':=%"
# 第二层（滤镜图）里有特殊含义的字符：反斜杠、单引号、方括号（标签）、逗号（滤镜分隔）、分号（链分隔）。
_LEVEL2_SPECIAL = "\\'[],;"


def _bs_escape(text, special):
    return "".join("\\" + c if c in special else c for c in text)


def esc_filter_value(text):
    """把一个值（文件路径或固定的样式文字）安全地放进 -vf 滤镜参数里。

    libavfilter 解析 -vf 字符串时有两层：
      1. 滤镜图层：按 , ; [ ] 切分滤镜，并去掉一层反斜杠转义和引号；
      2. 选项层：按 : 切分「键=值」，再去掉一层反斜杠转义和引号。
    所以先按选项层转义，再对结果按滤镜图层转义，顺序不能反。
    Windows 路径里的反斜杠原样保留，并被正确转义（不再先换成正斜杠）。
    换行、回车、空字符在滤镜参数里无法安全表达，直接拒绝（正常文件名里也不会有）。
    """
    v = str(text)
    if any(c in v for c in "\n\r\0"):
        raise UserError("文件名里有换行等特殊字符，视频工具没法安全处理。", "请先把文件改个简单的名字再试。")
    return _bs_escape(_bs_escape(v, _LEVEL1_SPECIAL), _LEVEL2_SPECIAL)


def esc_image_pattern(path):
    """图片序列的输出名里 % 有特殊含义（%04d 是编号），路径本身带的 % 要写成 %%。"""
    return str(path).replace("%", "%%")


def temp_dir():
    return tempfile.mkdtemp(prefix="vtools_")


def rm_tree(d):
    shutil.rmtree(d, ignore_errors=True)


def remove_quiet(p):
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except OSError:
        pass
