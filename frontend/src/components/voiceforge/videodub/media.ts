import SubtitleParser from "srt-parser-2";

/** 解析出的一条字幕 cue（秒制时间）。 */
export type ParsedCue = { start: number; end: number; text: string };

/** 解析 SRT 文本；解析失败时返回空数组。 */
export function parseSrt(text: string): ParsedCue[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  try {
    const cues = new SubtitleParser().fromSrt(trimmed) as Array<{
      startSeconds?: number;
      endSeconds?: number;
      text?: string;
    }>;
    return cues
      .map((cue) => {
        const start = Number(cue.startSeconds) || 0;
        const end = Math.max(Number(cue.endSeconds) || 0, start + 0.05);
        return { start, end, text: String(cue.text || "").replace(/\r/g, "").trim() };
      })
      .filter((cue) => cue.text)
      .sort((a, b) => a.start - b.start);
  } catch {
    return [];
  }
}

/** 把一个双语 cue 拆成「原文 + 译文」。swap 表示译文在第一行。 */
export function splitBilingualCue(
  cue: ParsedCue,
  swap: boolean,
): { start: number; end: number; text: string; translation: string } {
  const lines = cue.text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) return { start: cue.start, end: cue.end, text: "", translation: "" };
  if (lines.length === 1) return { start: cue.start, end: cue.end, text: lines[0], translation: "" };
  return swap
    ? { start: cue.start, end: cue.end, text: lines[lines.length - 1], translation: lines.slice(0, -1).join(" ") }
    : { start: cue.start, end: cue.end, text: lines[0], translation: lines.slice(1).join(" ") };
}

/** 秒 → "MM:SS.cc"（超过 1 小时为 "H:MM:SS.cc"），用于时间输入框与刻度。 */
export function formatTimecode(seconds: number, decimals = 2) {
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total - h * 3600 - m * 60;
  const secText = sec.toFixed(decimals).padStart(decimals > 0 ? 3 + decimals : 2, "0");
  const mm = String(m).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${secText}` : `${mm}:${secText}`;
}

/**
 * 解析用户输入的时间：支持 "83.4"（秒）、"1:23.4"（分:秒）、"1:02:03.4"（时:分:秒）。
 * 非法输入返回 null。
 */
export function parseTimeInput(raw: string): number | null {
  const text = raw.trim();
  if (!text) return null;
  const parts = text.split(":");
  if (parts.length > 3) return null;
  let seconds = 0;
  for (const part of parts) {
    const value = Number(part);
    if (!Number.isFinite(value) || value < 0) return null;
    seconds = seconds * 60 + value;
  }
  return seconds;
}

/**
 * 读取字幕文件文本：先按 UTF-8 解码，出现乱码标记时依次回退 GBK / Big5，
 * 兼容中文场景常见的 ANSI 编码 SRT。
 */
export async function readTextSmart(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const utf8 = new TextDecoder("utf-8").decode(buffer);
  if (!utf8.includes("\uFFFD")) return utf8;
  for (const encoding of ["gbk", "big5"]) {
    try {
      const decoded = new TextDecoder(encoding).decode(buffer);
      if (!decoded.includes("\uFFFD")) return decoded;
    } catch {
      /* 当前环境不支持该编码，继续尝试下一种 */
    }
  }
  return utf8;
}

/** 探测音频 / 视频 URL 的时长（秒）；加载失败返回 0。 */
export function mediaDuration(url: string): Promise<number> {
  return new Promise((resolve) => {
    const media = document.createElement("audio");
    media.preload = "metadata";
    media.onloadedmetadata = () => resolve(Number.isFinite(media.duration) ? media.duration : 0);
    media.onerror = () => resolve(0);
    media.src = url;
  });
}
