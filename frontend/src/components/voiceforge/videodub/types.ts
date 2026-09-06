/**
 * 视频配音工作台的类型与轨道常量。
 *
 * 轨道采用「一种类型一条轨」的模型：6 种轨道即 6 条轨道的上限，
 * 删除只是从显示列表移除，可通过「添加轨道」按类型恢复。
 */

export type TrackKind =
  | "subtitle"
  | "subtitle_translation"
  | "original_audio"
  | "dubbing"
  | "bgm"
  | "sfx";

/** 一条字幕（原文 + 可选译文），原文轨与译文轨的片段都由它派生。 */
export type SubtitlePair = {
  id: string;
  start: number;
  end: number;
  text: string;
  translation: string;
  /** 配音轨上对应片段的 id（TTS 生成后回填）。 */
  dubClipId?: string;
  /** 生成配音时使用的音色档案 id。 */
  dubVoiceId?: string;
  /** 配音音频时长（秒）。 */
  dubDuration?: number;
  dubStatus?: "idle" | "generating" | "done" | "error";
  dubError?: string;
  /** vlf 任务导入附带的配音指导信息（可选）。 */
  vlfIndex?: number;
  characterId?: number | string;
  readCharacterId?: number | string;
  toneDesc?: string;
  dialect?: string;
};

export type AudioClip = {
  id: string;
  name: string;
  start: number;
  duration: number;
  /** 播放地址(blob: 本地文件 或 后端媒体接口 URL)。 */
  url?: string;
  /** 持久化媒体键:vf: = voiceforge 存储,ws: = 工程存储(保存后由后端回填)。 */
  mediaKey?: string;
  /** 运行时字段:来源本地文件,保存工程时上传(不序列化)。 */
  file?: File;
  /** 音频对齐字幕后的虚拟变速倍率(原始时长 / 对齐后时长,>1 加速)。 */
  speed?: number;
  /** 变速前的真实音频时长(秒)。 */
  originalDuration?: number;
  /** 来源任务媒体(vlf 导入的片段),克隆模式用作参考音频。 */
  source?: { taskId: string; path: string };
};

export type VideoInfo = {
  name: string;
  url: string;
  duration: number;
  width: number;
  height: number;
};

export const TRACK_ORDER: TrackKind[] = [
  "subtitle",
  "subtitle_translation",
  "original_audio",
  "dubbing",
  "bgm",
  "sfx",
];

/** 带声音输出、需要喇叭开关的四条轨道。 */
export const AUDIO_TRACK_KINDS: TrackKind[] = ["original_audio", "dubbing", "bgm", "sfx"];

export const TRACK_NAMES: Record<TrackKind, string> = {
  subtitle: "字幕",
  subtitle_translation: "翻译字幕",
  original_audio: "原音音频",
  dubbing: "配音音频",
  bgm: "背景音乐",
  sfx: "音效轨",
};

export const TRACK_COLORS: Record<TrackKind, { dot: string; clip: string }> = {
  subtitle: {
    dot: "bg-violet-500",
    clip: "bg-violet-500/15 border-violet-500/40 text-violet-700 dark:text-violet-200",
  },
  subtitle_translation: {
    dot: "bg-sky-500",
    clip: "bg-sky-500/15 border-sky-500/40 text-sky-700 dark:text-sky-200",
  },
  original_audio: {
    dot: "bg-slate-400",
    clip: "bg-slate-400/20 border-slate-400/50 text-slate-700 dark:text-slate-200",
  },
  dubbing: {
    dot: "bg-emerald-500",
    clip: "bg-emerald-500/15 border-emerald-500/40 text-emerald-700 dark:text-emerald-200",
  },
  bgm: {
    dot: "bg-amber-500",
    clip: "bg-amber-500/15 border-amber-500/40 text-amber-700 dark:text-amber-200",
  },
  sfx: {
    dot: "bg-rose-500",
    clip: "bg-rose-500/15 border-rose-500/40 text-rose-700 dark:text-rose-200",
  },
};

export function isAudioTrack(kind: TrackKind) {
  return kind !== "subtitle" && kind !== "subtitle_translation";
}

export function uid() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
