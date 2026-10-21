# -*- coding: utf-8 -*-
"""视频小工具：压缩、剪切、合并、提取音频、转格式、转 GIF、截图、改分辨率、调速、
去声音/换背景音乐、加文字、烧字幕、旋转翻转、查看信息。

用法：python video_tools.py <子命令> <视频> [选项]
输出一律另存到原视频旁边的「处理后」文件夹，绝不覆盖原视频。不联网。
"""
import argparse
import math
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vt_core import (UserError, check_input, check_out_dir, esc_filter_value, esc_image_pattern,  # noqa: E402
                     find_ffmpeg, fmt_dur, fmt_size, fmt_ts_arg, out_folder, out_path, parse_time, probe,
                     remove_quiet, rm_tree, run_ff, temp_dir)

X264 = ["-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "160k"]
FASTSTART = ["-movflags", "+faststart"]
CRF = {"高": 20, "中": 24, "低": 28}
QUALITY_ALIASES = {"高": "高", "high": "高", "清晰": "高", "好": "高",
                   "中": "中", "medium": "中", "一般": "中", "默认": "中",
                   "低": "低", "low": "低", "小": "低", "最小": "低"}

VCODEC_NAMES = {"h264": "H.264（兼容性最好，几乎所有设备都能放）",
                "hevc": "HEVC / H.265（苹果手机常见，老电脑和部分软件打不开）",
                "av1": "AV1（新格式，老设备放不了）", "vp9": "VP9（网页视频常见）",
                "mpeg4": "MPEG-4（老格式）", "prores": "ProRes（专业剪辑格式，文件很大）"}


class Ctx:
    def __init__(self, args):
        self.ffmpeg, self.ffprobe = find_ffmpeg(getattr(args, "ffmpeg", None))
        self.out_dir = check_out_dir(getattr(args, "out_dir", None))     # 先校验，系统目录直接拒绝

    def info(self, path):
        return probe(self.ffprobe, path)

    def out(self, src, tag, ext=None):
        return out_path(src, tag, ext, self.out_dir)


def done(dst, extra=""):
    size = os.path.getsize(dst) if os.path.isfile(dst) else 0
    print(f"完成！新文件：{dst}")
    if size:
        print(f"大小：{fmt_size(size)}")
    if extra:
        print(extra)
    print("原视频没有动过。")


def run_to(ctx, dst, args, duration, label="处理中", cwd=None):
    """跑命令写到 dst；失败就删掉半成品。

    ffmpeg 的 -n 对图片输出（jpg 等）不生效，所以这里自己再查一次：dst 已存在就不跑，绝不覆盖。
    """
    if os.path.exists(dst):
        raise UserError(f"要写的新文件已经存在，为了不覆盖它，这次没有处理：{dst}",
                        "再说一次同样的要求就行，会自动换一个新文件名。")
    try:
        run_ff(ctx.ffmpeg, args + [dst], duration, label, cwd=cwd)
    except UserError as e:
        if "不覆盖" not in e.what:       # 因为文件已存在而放弃时，那个文件不是我们的，不能删
            remove_quiet(dst)
        raise
    except BaseException:
        remove_quiet(dst)
        raise
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        remove_quiet(dst)
        raise UserError("处理结束了，但没有生成新文件。", "请把视频复制到桌面、改个简单的文件名再试一次。")


def need_video(info):
    if not info.get("has_video"):
        raise UserError("这个文件里没有画面（可能是纯音频文件）。", "请换一个视频文件。")


def quality(q):
    if q is None:
        return "中"
    k = QUALITY_ALIASES.get(str(q).strip().lower()) or QUALITY_ALIASES.get(str(q).strip())
    if not k:
        raise UserError(f"画质档位只有 高 / 中 / 低，没有「{q}」。", "请说「高」「中」或「低」。")
    return k


def window(info, start, end, length=None):
    """把开始/结束时间换算成 (开始秒, 时长秒)，并检查范围。"""
    dur = info["duration"]
    s = parse_time(start) or 0.0
    e = parse_time(end) if end not in (None, "") else None
    if length not in (None, ""):
        e = s + parse_time(length)
    if e is None:
        e = dur
    if dur and s >= dur:
        raise UserError(f"开始时间 {fmt_dur(s)} 已经超过视频总长 {fmt_dur(dur)}。", "请换一个在视频长度以内的开始时间。")
    if dur and e > dur:
        e = dur
    if e <= s:
        raise UserError(f"结束时间 {fmt_dur(e)} 要比开始时间 {fmt_dur(s)} 晚。", "请重新说一下从哪到哪。")
    return s, e - s


# ======================= 各个功能 =======================

def cmd_check(args):
    ff, fp = find_ffmpeg(args.ffmpeg)
    print(f"已找到视频处理工具：{ff}")
    print(f"配套的信息读取工具：{fp}")
    if args.ffmpeg:
        print("这个位置不会被保存到电脑上；之后每次处理都要带上同一个位置。")


def cmd_info(args):
    ctx = Ctx(args)
    p = check_input(args.input)
    i = ctx.info(p)
    print(f"文件：{p}")
    print(f"大小：{fmt_size(i['size'])}")
    print(f"时长：{fmt_dur(i['duration'])}")
    if i["has_video"]:
        orient = "竖屏" if i["height"] > i["width"] else ("横屏" if i["width"] > i["height"] else "方形")
        label = res_label(i["width"], i["height"])
        print(f"分辨率：{i['width']} × {i['height']}（{orient}{('，' + label) if label else ''}）")
        if i["fps"]:
            print(f"帧率：每秒 {i['fps']:.0f} 帧")
        print(f"视频编码：{VCODEC_NAMES.get(i['vcodec'], i['vcodec'])}")
    else:
        print("画面：没有（这是纯音频）")
    if i["bitrate"]:
        print(f"整体码率：{i['bitrate'] / 1000:.0f} kbps（每秒数据量，越大越清晰、文件越大）")
    print("声音：" + (f"有（{i['channels']} 声道）" if i["has_audio"] else "没有"))
    if i["duration"] and i["size"]:
        print(f"每分钟大约占 {fmt_size(i['size'] / i['duration'] * 60)}")


def res_label(w, h):
    short = min(w, h)
    for n, name in ((2160, "4K"), (1440, "2K"), (1080, "1080P"), (720, "720P"), (480, "480P"), (360, "360P")):
        if short >= n * 0.95:
            return name
    return ""


def cmd_compress(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    dur = info["duration"]
    if args.size_mb:
        target = float(args.size_mb) * 1024 * 1024
        if info["size"] <= target and not args.force:
            print(f"这个视频现在是 {fmt_size(info['size'])}，已经比 {args.size_mb} MB 小了，不用压缩。")
            print("如果还想压得更小，说一个更小的大小就行。")
            return
        if not dur:
            raise UserError("读不到这个视频的时长，没法按大小压缩。", "改成按画质压缩（说「中等画质压缩」）试试。")
        total_kbps = target * 8 * 0.96 / dur / 1000          # 留 4% 给文件头等开销
        a_kbps = 0
        if info["has_audio"]:
            a_kbps = 128 if total_kbps > 1000 else (96 if total_kbps > 400 else 64)
        v_kbps = int(total_kbps - a_kbps)
        if v_kbps < 80:
            mins = math.ceil((80 + a_kbps) * dur * 1000 / 8 / 0.96 / 1024 / 1024)
            raise UserError(f"视频有 {fmt_dur(dur)} 长，压到 {args.size_mb} MB 画面会糊得看不清。",
                            f"至少给 {mins} MB；或者先把视频剪短（剪切功能）再压。")
        vf = []
        short = min(info["width"], info["height"])
        cap = 1080 if v_kbps < 2500 else None
        cap = 720 if v_kbps < 900 else cap
        cap = 480 if v_kbps < 350 else cap
        if cap and short > cap:
            vf = ["-vf", scale_short_side(info, cap)]
        dst = ctx.out(src, f"压到{args.size_mb:g}MB", ".mp4")
        td = temp_dir()
        try:
            common = ["-i", src] + vf + X264 + ["-b:v", f"{v_kbps}k", "-passlogfile", "passlog"]
            null_out = "NUL" if os.name == "nt" else "/dev/null"
            print("第 1 遍：分析画面（两遍法，大小更准）")
            run_ff(ctx.ffmpeg, common + ["-pass", "1", "-an", "-f", "null", null_out], dur, "第 1 遍", cwd=td)
            print("第 2 遍：正式压缩")
            audio = (["-c:a", "aac", "-b:a", f"{a_kbps}k"] if info["has_audio"] else ["-an"])
            run_to(ctx, dst, common + ["-pass", "2"] + audio + FASTSTART, dur, "第 2 遍", cwd=td)
        finally:
            rm_tree(td)
        size = os.path.getsize(dst)
        note = f"原来 {fmt_size(info['size'])} → 现在 {fmt_size(size)}（目标 {args.size_mb:g} MB）"
        if vf:
            note += f"\n为了在这个大小下保持清楚，画面缩小到了 {cap}P。"
        if size > target:
            note += "\n比目标稍大一点，如果卡着上限传不上去，就把目标再说小 5 MB 重来一次。"
        done(dst, note)
    else:
        q = quality(args.quality)
        dst = ctx.out(src, f"压缩{q}画质", ".mp4")
        audio = AAC if info["has_audio"] else ["-an"]
        run_to(ctx, dst, ["-i", src] + X264 + ["-crf", str(CRF[q])] + audio + FASTSTART, dur, "压缩中")
        done(dst, f"原来 {fmt_size(info['size'])} → 现在 {fmt_size(os.path.getsize(dst))}（{q}画质）")


def scale_short_side(info, short):
    """按短边缩放：横屏控制高度，竖屏控制宽度；另一边自动按比例且保证是偶数。"""
    if info["width"] >= info["height"]:
        return f"scale=-2:{int(short)}:flags=lanczos"
    return f"scale={int(short)}:-2:flags=lanczos"


def cmd_cut(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    s, d = window(info, args.start, args.end, args.length)
    ext = os.path.splitext(src)[1] or ".mp4"
    if args.precise:
        dst = ctx.out(src, f"剪切{fmt_dur(s).replace(':', '.')}起", ".mp4")
        audio = AAC if info["has_audio"] else ["-an"]
        run_to(ctx, dst, ["-ss", fmt_ts_arg(s), "-i", src, "-t", fmt_ts_arg(d)] + X264 + ["-crf", "18"]
               + audio + FASTSTART, d, "剪切中")
        done(dst, f"精确模式：从 {fmt_dur(s)} 到 {fmt_dur(s + d)}，共 {fmt_dur(d)}，切点准确到每一帧。")
    else:
        dst = ctx.out(src, f"剪切{fmt_dur(s).replace(':', '.')}起", ext)
        run_to(ctx, dst, ["-ss", fmt_ts_arg(s), "-i", src, "-t", fmt_ts_arg(d), "-map", "0:v?", "-map", "0:a?",
                          "-c", "copy", "-avoid_negative_ts", "make_zero"], d, "剪切中")
        done(dst, f"快速模式：从 {fmt_dur(s)} 到 {fmt_dur(s + d)}，几秒就好、画质完全不变；"
                  "但开头可能会比你说的时间早一点点（差零点几秒到两三秒）。要卡准到每一帧，就用精确模式。")


def cmd_merge(args):
    ctx = Ctx(args)
    srcs = [check_input(p) for p in args.inputs]
    if len(srcs) < 2:
        raise UserError("合并至少需要两个视频。", "请把要合并的视频按顺序一个个告诉我。")
    infos = [ctx.info(p) for p in srcs]
    for i in infos:
        need_video(i)
    total = sum(i["duration"] for i in infos)
    first = srcs[0]
    keys = [(i["vcodec"], i["width"], i["height"], round(i["fps"], 2), i["pix_fmt"], i["has_audio"],
             i.get("acodec"), i.get("sample_rate"), i.get("channels"), os.path.splitext(p)[1].lower())
            for i, p in zip(infos, srcs)]
    same = all(k == keys[0] for k in keys) and not args.reencode
    td = temp_dir()
    try:
        if same:
            ext = os.path.splitext(first)[1] or ".mp4"
            dst = ctx.out(first, f"合并{len(srcs)}个", ext)
            lst = os.path.join(td, "list.txt")
            # 列表里每一项都是用户给出、已经 check_input 校验存在、并转成真实绝对路径的视频文件，
            # 这里再确认一遍；concat 默认拒绝绝对路径，所以只在这种情况下才用 -safe 0。
            with open(lst, "w", encoding="utf-8") as f:
                for p in srcs:
                    if not (os.path.isabs(p) and os.path.isfile(p)) or "\n" in p or "\r" in p:
                        raise UserError(f"这个文件不能用来合并：{p}", "请确认每个视频都存在，文件名里没有换行等特殊字符。")
                    f.write("file '" + p.replace("\\", "/").replace("'", "'\\''") + "'\n")
            run_to(ctx, dst, ["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy"], total, "合并中")
            done(dst, f"{len(srcs)} 个视频格式一样，直接首尾相接，画质不变，总长 {fmt_dur(total)}。")
        else:
            w, h = infos[0]["width"], infos[0]["height"]
            w, h = w - w % 2, h - h % 2
            fps = round(infos[0]["fps"] or 30, 3)
            if fps > 60:
                fps = 60
            inputs, parts = [], []
            n = len(srcs)
            for p in srcs:
                inputs += ["-i", p]
            any_audio = any(i["has_audio"] for i in infos)
            extra = n
            for k, i in enumerate(infos):
                parts.append(f"[{k}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p[v{k}]")
                if not any_audio:
                    continue
                if i["has_audio"]:
                    parts.append(f"[{k}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{k}]")
                else:   # 无声片段补一段等长静音，保证声音和画面对得上
                    inputs += ["-f", "lavfi", "-t", fmt_ts_arg(i["duration"]), "-i",
                               "anullsrc=channel_layout=stereo:sample_rate=48000"]
                    parts.append(f"[{extra}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a{k}]")
                    extra += 1
            if any_audio:
                seq = "".join(f"[v{k}][a{k}]" for k in range(n))
                parts.append(f"{seq}concat=n={n}:v=1:a=1[v][a]")
                maps = ["-map", "[v]", "-map", "[a]"] + AAC
            else:
                seq = "".join(f"[v{k}]" for k in range(n))
                parts.append(f"{seq}concat=n={n}:v=1:a=0[v]")
                maps = ["-map", "[v]", "-an"]
            dst = ctx.out(first, f"合并{len(srcs)}个", ".mp4")
            run_to(ctx, dst, inputs + ["-filter_complex", ";".join(parts)] + maps + X264 + ["-crf", "20", "-r", str(fps)]
                   + FASTSTART, total, "合并中")
            done(dst, f"{len(srcs)} 个视频格式不一样，已先统一成 {w}×{h} 再合并，总长 {fmt_dur(total)}；"
                      "尺寸不同的片段会加黑边，不会被拉变形。")
    finally:
        rm_tree(td)


def cmd_audio(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    if not info["has_audio"]:
        raise UserError("这个视频没有声音，提取不出音频。", "先用「查看视频信息」确认一下；或者换一个有声音的视频。")
    q = quality(args.quality)
    br = {"高": "320k", "中": "192k", "低": "96k"}[q]
    dst = ctx.out(src, "音频", ".mp3")
    extra = ["-ac", "1"] if q == "低" else []
    run_to(ctx, dst, ["-i", src, "-vn", "-c:a", "libmp3lame", "-b:a", br] + extra, info["duration"], "提取中")
    done(dst, f"已转成 MP3（{q}音质），时长 {fmt_dur(info['duration'])}，手机、电脑、车载都能放。")


def cmd_convert(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    fmt = (args.to or "mp4").lower().lstrip(".")
    if fmt not in ("mp4", "mov", "mkv"):
        raise UserError(f"暂时只能转成 MP4、MOV、MKV，不支持「{fmt}」。", "大多数情况转成 MP4 就行，兼容性最好。")
    a_ok = (not info["has_audio"]) or info.get("acodec") in ("aac", "mp3")
    copy_ok = info["vcodec"] == "h264" and info["pix_fmt"] in ("yuv420p", "yuvj420p") and a_ok and not args.reencode
    dst = ctx.out(src, "转换", "." + fmt)
    faststart = FASTSTART if fmt in ("mp4", "mov") else []
    if copy_ok:
        run_to(ctx, dst, ["-i", src, "-map", "0:v:0", "-map", "0:a?", "-c", "copy"] + faststart, info["duration"], "转换中")
        done(dst, "原视频本来就是通用编码，只换了个「外壳」，几秒完成，画质不变。")
    else:
        audio = AAC if info["has_audio"] else ["-an"]
        vf = []
        if (info.get("pix_fmt") or "").find("10") >= 0 or info["vcodec"] == "hevc":
            vf = ["-vf", "format=yuv420p"]
        run_to(ctx, dst, ["-i", src, "-map", "0:v:0", "-map", "0:a?"] + vf + X264 + ["-crf", "20"] + audio + faststart,
               info["duration"], "转换中")
        old = VCODEC_NAMES.get(info["vcodec"], info["vcodec"]).split("（")[0]
        done(dst, f"已从 {old} 转成 H.264，老电脑、微信、各种播放器和剪辑软件都能打开。"
                  + ("\n提示：苹果手机拍的 HDR 视频转完颜色可能会稍微淡一点，这是正常的。" if info["vcodec"] == "hevc" else ""))


def cmd_gif(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    length = args.length
    if args.end in (None, "") and length in (None, "") and info["duration"] - (parse_time(args.start) or 0) > 10:
        length = "10"
        print("没说要多长，默认取 10 秒（GIF 太长文件会很大）。")
    s, d = window(info, args.start, args.end, length)
    width = int(args.width or 480)
    fps = int(args.fps or 12)
    if not (100 <= width <= 1920):
        raise UserError("GIF 宽度请在 100 到 1920 之间。", "一般聊天用 320～480，清楚一点用 640。")
    if not (2 <= fps <= 30):
        raise UserError("GIF 每秒帧数请在 2 到 30 之间。", "一般 10～15 就够流畅。")
    td = temp_dir()
    dst = ctx.out(src, "动图", ".gif")
    try:
        pal = os.path.join(td, "palette.png")
        base = f"fps={fps},scale={width}:-1:flags=lanczos"
        print("第 1 步：挑颜色")
        run_ff(ctx.ffmpeg, ["-ss", fmt_ts_arg(s), "-t", fmt_ts_arg(d), "-i", src, "-vf",
                            base + ",palettegen=stats_mode=diff", pal], d, "挑颜色")
        print("第 2 步：生成动图")
        run_to(ctx, dst, ["-ss", fmt_ts_arg(s), "-t", fmt_ts_arg(d), "-i", src, "-i", pal, "-lavfi",
                          base + "[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", "-loop", "0"],
               d, "生成中")
    finally:
        rm_tree(td)
    note = f"{fmt_dur(d)} 长，宽 {width} 像素，每秒 {fps} 帧。"
    if os.path.getsize(dst) > 10 * 1024 * 1024:
        note += "\n文件超过 10 MB，有的聊天软件发不出去；可以缩短时长、把宽度改成 320 或每秒帧数改成 8。"
    done(dst, note)


def cmd_snapshot(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    dur = info["duration"]
    if args.every:
        every = parse_time(args.every)
        if not every or every <= 0:
            raise UserError("间隔要大于 0 秒。", "比如说「每 5 秒截一张」。")
        count = int(dur / every) + 1 if dur else 0
        if count > 1000:
            raise UserError(f"每 {every:g} 秒截一张，会有 {count} 张图，太多了。", "把间隔调大一点，比如每 10 秒或每 30 秒。")
        stem = os.path.splitext(os.path.basename(src))[0]
        folder = out_folder(src, f"每{every:g}秒截图", ctx.out_dir)      # 每次都新建不重名的文件夹，不覆盖旧截图
        pattern = os.path.join(esc_image_pattern(folder), esc_image_pattern(stem) + "_%04d.jpg")
        run_ff(ctx.ffmpeg, ["-i", src, "-vf", f"fps=1/{every:g}", "-q:v", "2", pattern], dur, "截图中")
        n = len([f for f in os.listdir(folder) if f.lower().endswith(".jpg")])
        print(f"完成！一共截了 {n} 张图，都在：{folder}")
        print("原视频没有动过。")
        return
    if args.at not in (None, ""):
        t = parse_time(args.at)
        if dur and t >= dur:
            raise UserError(f"{fmt_dur(t)} 已经超过视频总长 {fmt_dur(dur)}。", "请换一个视频长度以内的时间点。")
        tag = f"截图{fmt_dur(t).replace(':', '.')}"
    else:
        t = min(1.0, dur / 2) if dur < 10 else dur * 0.1      # 封面：默认取十分之一处，避开黑屏片头
        tag = "封面"
    dst = ctx.out(src, tag, ".jpg")
    run_to(ctx, dst, ["-ss", fmt_ts_arg(t), "-i", src, "-frames:v", "1", "-q:v", "2", "-update", "1"], None, "截图中")
    done(dst, f"截的是 {fmt_dur(t)} 这一刻的画面（{info['width']}×{info['height']}）。")


RES_WORDS = {"4k": 2160, "2160p": 2160, "2k": 1440, "1440p": 1440, "1080p": 1080, "1080": 1080, "全高清": 1080,
             "720p": 720, "720": 720, "高清": 720, "480p": 480, "480": 480, "标清": 480, "360p": 360, "360": 360}


def cmd_resize(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    key = str(args.to).strip().lower().replace(" ", "")
    target = RES_WORDS.get(key) or RES_WORDS.get(key.upper().lower())
    if not target:
        try:
            target = int(key.rstrip("p"))
        except ValueError:
            raise UserError(f"看不懂「{args.to}」这个分辨率。", "请说 4K、1080P、720P、480P 之一。")
    short = min(info["width"], info["height"])
    if target >= short and not args.allow_upscale:
        raise UserError(f"这个视频本来就是 {info['width']}×{info['height']}，不比 {target}P 大。",
                        "放大不会变清楚，只会让文件变大，所以没处理。想压小文件请用「压缩」。")
    dst = ctx.out(src, f"{target}P", ".mp4")
    audio = ["-c:a", "copy"] if info.get("acodec") in ("aac", "mp3") else (AAC if info["has_audio"] else ["-an"])
    run_to(ctx, dst, ["-i", src, "-vf", scale_short_side(info, target)] + X264 + ["-crf", "20"] + audio + FASTSTART,
           info["duration"], "转换中")
    ni = ctx.info(dst)
    done(dst, f"{info['width']}×{info['height']} → {ni['width']}×{ni['height']}，比例不变不会拉伸。")


def atempo_chain(r):
    """音频变速：每一级限制在 0.5～2 倍，超出就串联几级。"""
    steps = []
    while r > 2.0:
        steps.append(2.0)
        r /= 2.0
    while r < 0.5:
        steps.append(0.5)
        r /= 0.5
    steps.append(r)
    return ",".join(f"atempo={s:.6g}" for s in steps)


def cmd_speed(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    try:
        r = float(str(args.rate).replace("倍", "").replace("x", "").replace("X", ""))
    except ValueError:
        raise UserError(f"看不懂「{args.rate}」这个速度。", "请说一个 0.5 到 4 之间的倍数，比如 1.5 倍、2 倍、0.5 倍。")
    if not (0.5 <= r <= 4):
        raise UserError("速度只能在 0.5 倍（慢放）到 4 倍（快进）之间。", "请换一个这个范围里的倍数。")
    if abs(r - 1) < 1e-6:
        raise UserError("1 倍就是原速，不用处理。", "想快放就说 1.5 倍、2 倍；想慢放就说 0.5 倍。")
    new_dur = info["duration"] / r
    dst = ctx.out(src, f"{r:g}倍速", ".mp4")
    if info["has_audio"]:
        fc = f"[0:v]setpts=PTS/{r:.6g}[v];[0:a]{atempo_chain(r)}[a]"
        maps = ["-map", "[v]", "-map", "[a]"] + AAC
    else:
        fc = f"[0:v]setpts=PTS/{r:.6g}[v]"
        maps = ["-map", "[v]", "-an"]
    run_to(ctx, dst, ["-i", src, "-filter_complex", fc] + maps + X264 + ["-crf", "20"] + FASTSTART, new_dur, "调速中")
    done(dst, f"{r:g} 倍速：{fmt_dur(info['duration'])} → {fmt_dur(new_dur)}，声音跟着变速但音调不变。")


def cmd_mute(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    ext = os.path.splitext(src)[1] or ".mp4"
    dst = ctx.out(src, "无声", ext)
    run_to(ctx, dst, ["-i", src, "-map", "0:v:0", "-c:v", "copy", "-an"], info["duration"], "处理中")
    done(dst, "声音已经去掉，画面没有重新压缩，画质不变。")


def cmd_bgm(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    music = check_input(args.music)
    info = ctx.info(src)
    need_video(info)
    minfo = ctx.info(music)
    if not minfo["has_audio"]:
        raise UserError("这个音乐文件里没有声音。", "请换一个 MP3、M4A 或 WAV 音乐文件。")
    vol = float(args.music_volume if args.music_volume is not None else (30 if args.keep_voice else 100)) / 100
    if not (0 < vol <= 2):
        raise UserError("音乐音量请在 1% 到 200% 之间。", "保留人声时一般 20%～40% 比较合适。")
    dur = info["duration"]
    loop = [] if args.no_loop else ["-stream_loop", "-1"]
    vcopy = ["-c:v", "copy"] if info["vcodec"] == "h264" else X264 + ["-crf", "20"]
    dst = ctx.out(src, "配乐", ".mp4")
    fade = f"afade=t=out:st={max(0, dur - 2):.3f}:d=2" if dur > 4 else "anull"
    if args.keep_voice and info["has_audio"]:
        fc = (f"[1:a]volume={vol:.3f},aresample=48000[m];[0:a]aresample=48000[o];"
              f"[o][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,{fade}[a]")
        note = f"原声保留，背景音乐音量 {vol * 100:.0f}%。"
    else:
        fc = f"[1:a]volume={vol:.3f},{fade}[a]"
        note = "原声已换成背景音乐。"
    run_to(ctx, dst, ["-i", src] + loop + ["-i", music, "-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"]
           + vcopy + AAC + ["-t", fmt_ts_arg(dur)] + FASTSTART, dur, "配乐中")
    if minfo["duration"] < dur and not args.no_loop:
        note += "\n音乐比视频短，已自动从头循环播放；结尾 2 秒淡出。"
    done(dst, note + "\n请只用你有权使用的音乐（自己的、已购买授权的或免版权的）。")


POSITIONS = {
    "右下": ("w-tw-{m}", "h-th-{m}"), "左下": ("{m}", "h-th-{m}"), "右上": ("w-tw-{m}", "{m}"),
    "左上": ("{m}", "{m}"), "中间": ("(w-tw)/2", "(h-th)/2"), "正中": ("(w-tw)/2", "(h-th)/2"),
    "底部": ("(w-tw)/2", "h-th-{m}"), "下方": ("(w-tw)/2", "h-th-{m}"), "顶部": ("(w-tw)/2", "{m}"),
}

FONT_CANDIDATES = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf", r"C:\Windows\Fonts\simhei.ttf",
                   r"C:\Windows\Fonts\simsun.ttc", "/System/Library/Fonts/PingFang.ttc",
                   "/System/Library/Fonts/STHeiti Medium.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]


def cmd_text(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    text = (args.text or "").strip()
    if not text:
        raise UserError("没有要加的文字。", "请告诉我要在视频上写什么，比如「@我的店铺」。")
    if len(text) > 60:
        raise UserError("文字太长了（超过 60 个字），画面放不下。", "请缩短一点，比如只写名字或账号。")
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise UserError("文字里有换行或看不见的控制字符。", "请只写一行普通文字。")
    pos = POSITIONS.get(args.pos or "右下")
    if not pos:
        raise UserError(f"位置只能是 右下/左下/右上/左上/中间/底部/顶部，没有「{args.pos}」。", "请换一个位置再说一次。")
    if args.font:
        font = os.path.realpath(args.font.strip().strip('"'))
        if not os.path.isfile(font) or os.path.splitext(font)[1].lower() not in (".ttf", ".ttc", ".otf"):
            raise UserError(f"这个字体文件用不了：{font}", "请给一个存在的 .ttf / .ttc / .otf 字体文件。")
    else:
        font = next((f for f in FONT_CANDIDATES if os.path.isfile(f)), None)
    if not font:
        raise UserError("电脑里没找到能显示中文的字体。", "请告诉我一个字体文件的位置（比如 C:\\Windows\\Fonts 里的 .ttf 文件）。")
    td = temp_dir()
    try:
        tf = os.path.join(td, "text.txt")
        with open(tf, "w", encoding="utf-8") as f:
            f.write(text)                       # 文字写进文件再让工具去读，不放进命令里；expansion=none 关掉 % 展开
        size_ratio = {"大": 12, "中": 20, "小": 30}.get(args.size or "中", 20)
        short = min(info["width"], info["height"])
        fs = max(12, int(short / size_ratio))
        m = max(8, int(short / 40))
        x, y = (p.format(m=m) for p in pos)
        alpha = max(0.1, min(1.0, float(args.opacity if args.opacity is not None else 80) / 100))
        vf = (f"drawtext=fontfile={esc_filter_value(font)}:textfile={esc_filter_value(tf)}:"
              f"fontsize={fs}:fontcolor=white@{alpha:.2f}:shadowcolor=black@{alpha * 0.6:.2f}:shadowx=2:shadowy=2:"
              f"x={x}:y={y}:expansion=none")
        dst = ctx.out(src, "加文字", ".mp4")
        audio = ["-c:a", "copy"] if info.get("acodec") in ("aac", "mp3") else (AAC if info["has_audio"] else ["-an"])
        run_to(ctx, dst, ["-i", src, "-vf", vf] + X264 + ["-crf", "20"] + audio + FASTSTART, info["duration"], "加文字中")
    finally:
        rm_tree(td)
    done(dst, f"已在{args.pos or '右下'}加上文字：{text}")


def _srt_charenc(path):
    data = open(path, "rb").read()
    if data.startswith(b"\xef\xbb\xbf"):
        return None
    for enc in ("utf-8", "utf-16"):
        try:
            data.decode(enc)
            return None if enc == "utf-8" else "UTF-16"
        except UnicodeDecodeError:
            pass
    try:
        data.decode("gb18030")
        return "GB18030"
    except UnicodeDecodeError:
        return None


def cmd_subtitle(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    srt = check_input(args.srt)
    if os.path.splitext(srt)[1].lower() not in (".srt", ".ass", ".ssa"):
        raise UserError("字幕文件要是 .srt（或 .ass）格式。", "如果是 .txt 等别的格式，需要先转成 .srt。")
    info = ctx.info(src)
    need_video(info)
    short = min(info["width"], info["height"])
    fs = {"大": 26, "中": 20, "小": 15}.get(args.size or "中", 20)
    # 字幕路径：上面已确认文件存在、扩展名是 .srt/.ass/.ssa，再经两层完整转义后才拼进滤镜参数
    vf = f"subtitles=filename={esc_filter_value(srt)}"
    enc = _srt_charenc(srt)
    if enc:
        vf += f":charenc={enc}"
    if os.path.splitext(srt)[1].lower() == ".srt":
        style = f"FontName=Microsoft YaHei,FontSize={fs},Outline=1,Shadow=1,MarginV={20 if short >= 720 else 12}"
        vf += f":force_style={esc_filter_value(style)}"
    dst = ctx.out(src, "带字幕", ".mp4")
    audio = ["-c:a", "copy"] if info.get("acodec") in ("aac", "mp3") else (AAC if info["has_audio"] else ["-an"])
    run_to(ctx, dst, ["-i", src, "-vf", vf] + X264 + ["-crf", "20"] + audio + FASTSTART, info["duration"], "烧字幕中")
    done(dst, "字幕已经「印」进画面里，任何播放器都能看到，也关不掉。" + ("（字幕文件是 GBK 编码，已自动识别）" if enc else ""))


ROTATE = {"右转90": ("transpose=1", "向右转 90 度"), "顺时针90": ("transpose=1", "向右转 90 度"),
          "左转90": ("transpose=2", "向左转 90 度"), "逆时针90": ("transpose=2", "向左转 90 度"),
          "180": ("hflip,vflip", "转 180 度（倒过来）"), "倒过来": ("hflip,vflip", "转 180 度（倒过来）"),
          "水平翻转": ("hflip", "左右镜像翻转"), "镜像": ("hflip", "左右镜像翻转"), "左右翻转": ("hflip", "左右镜像翻转"),
          "垂直翻转": ("vflip", "上下翻转"), "上下翻转": ("vflip", "上下翻转")}


def cmd_rotate(args):
    ctx = Ctx(args)
    src = check_input(args.input)
    info = ctx.info(src)
    need_video(info)
    key = str(args.how).replace("度", "").replace(" ", "")
    if key not in ROTATE:
        raise UserError(f"看不懂「{args.how}」。", "可以说：右转90、左转90、180、水平翻转（镜像）、垂直翻转。")
    vf, desc = ROTATE[key]
    dst = ctx.out(src, "旋转" if "transpose" in vf or vf == "hflip,vflip" else "翻转", ".mp4")
    audio = ["-c:a", "copy"] if info.get("acodec") in ("aac", "mp3") else (AAC if info["has_audio"] else ["-an"])
    run_to(ctx, dst, ["-i", src, "-vf", vf, "-metadata:s:v:0", "rotate=0"] + X264 + ["-crf", "20"] + audio + FASTSTART,
           info["duration"], "处理中")
    done(dst, f"已{desc}。")


# ======================= 命令行 =======================

def build_parser():
    p = argparse.ArgumentParser(description="视频小工具（结果另存到原视频旁边的「处理后」文件夹）")
    p.add_argument("--ffmpeg", help="ffmpeg 所在文件夹（用户在本次明确告诉的位置，不会被保存）")
    p.add_argument("--out-dir", help="新文件放哪（默认原视频旁边的「处理后」文件夹；不能是系统文件夹）")
    sub = p.add_subparsers(dest="cmd")

    def add(name, fn, *, inp=True):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        if inp:
            sp.add_argument("input")
        sp.add_argument("--ffmpeg", default=argparse.SUPPRESS)
        sp.add_argument("--out-dir", default=argparse.SUPPRESS)
        return sp

    add("check", cmd_check, inp=False)
    add("info", cmd_info)
    sp = add("compress", cmd_compress)
    sp.add_argument("--size-mb", type=float)
    sp.add_argument("--quality")
    sp.add_argument("--force", action="store_true")
    sp = add("cut", cmd_cut)
    sp.add_argument("--start", default="0")
    sp.add_argument("--end")
    sp.add_argument("--length")
    sp.add_argument("--precise", action="store_true")
    sp = sub.add_parser("merge")
    sp.set_defaults(fn=cmd_merge)
    sp.add_argument("inputs", nargs="+")
    sp.add_argument("--reencode", action="store_true")
    sp.add_argument("--ffmpeg", default=argparse.SUPPRESS)
    sp.add_argument("--out-dir", default=argparse.SUPPRESS)
    sp = add("audio", cmd_audio)
    sp.add_argument("--quality")
    sp = add("convert", cmd_convert)
    sp.add_argument("--to", default="mp4")
    sp.add_argument("--reencode", action="store_true")
    sp = add("gif", cmd_gif)
    sp.add_argument("--start", default="0")
    sp.add_argument("--end")
    sp.add_argument("--length")
    sp.add_argument("--width", type=int)
    sp.add_argument("--fps", type=int)
    sp = add("snapshot", cmd_snapshot)
    sp.add_argument("--at")
    sp.add_argument("--every")
    sp = add("resize", cmd_resize)
    sp.add_argument("--to", required=True)
    sp.add_argument("--allow-upscale", action="store_true")
    sp = add("speed", cmd_speed)
    sp.add_argument("--rate", required=True)
    add("mute", cmd_mute)
    sp = add("bgm", cmd_bgm)
    sp.add_argument("--music", required=True)
    sp.add_argument("--keep-voice", action="store_true")
    sp.add_argument("--music-volume", type=float)
    sp.add_argument("--no-loop", action="store_true")
    sp = add("text", cmd_text)
    sp.add_argument("--text", required=True)
    sp.add_argument("--pos")
    sp.add_argument("--size")
    sp.add_argument("--opacity", type=float)
    sp.add_argument("--font")
    sp = add("subtitle", cmd_subtitle)
    sp.add_argument("--srt", required=True)
    sp.add_argument("--size")
    sp = add("rotate", cmd_rotate)
    sp.add_argument("--how", required=True)
    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    try:
        args.fn(args)
        return 0
    except UserError as e:
        print(f"出错了：{e.what}")
        print(f"下一步：{e.next_step}")
        return 1
    except KeyboardInterrupt:
        print("出错了：处理被中途停止了，没完成的文件已删掉。")
        print("下一步：需要的话再说一次，我重新开始。")
        return 1
    except Exception as e:  # 兜底：不把技术细节甩给用户
        print("出错了：处理时遇到了意外情况。")
        print(f"下一步：把视频复制到桌面、改个简单的文件名再试；还不行就把这句话发给我：{type(e).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
