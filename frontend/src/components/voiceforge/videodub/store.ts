import { create } from "zustand";
import { voiceForgeApi, VoiceForgeVoice } from "@/api/voiceforge";
import {
  AudioClip,
  SubtitlePair,
  TRACK_ORDER,
  TrackKind,
  VideoInfo,
  clamp,
  uid,
} from "./types";

const sortPairs = (pairs: SubtitlePair[]) =>
  [...pairs].sort((a, b) => a.start - b.start || a.end - b.end);

/** 轨道静音表：原音默认关闭（视频载入即静音），其余音轨默认开启。 */
const DEFAULT_MUTED: Record<TrackKind, boolean> = {
  subtitle: false,
  subtitle_translation: false,
  original_audio: true,
  dubbing: false,
  bgm: false,
  sfx: false,
};

type VideoDubState = {
  video: VideoInfo | null;
  /** 当前显示的轨道（有序），最多 TRACK_ORDER.length 条。 */
  tracks: TrackKind[];
  /** 字幕对：原文轨与译文轨共用同一份数据。 */
  pairs: SubtitlePair[];
  /** 各音频轨上的片段，键为轨道类型。 */
  clips: Record<TrackKind, AudioClip[]>;
  /** 时间指针位置（秒），与视频播放进度双向同步。 */
  currentTime: number;
  playing: boolean;
  /** 时间轴横向缩放（像素 / 秒）。 */
  pxPerSec: number;
  selectedPairId: string | null;
  /** 各轨道静音状态（仅音频轨道使用）。 */
  mutedTracks: Record<TrackKind, boolean>;
  /** 逐句配音使用的音色档案 id。 */
  dubVoiceId: string | null;
  /** 已保存工程的后端 id / 名称（null 表示尚未保存）。 */
  workspaceId: string | null;
  workspaceName: string | null;
  /** 最近一次保存时间（ISO），用于工具栏提示。 */
  savedAt: string | null;
  /** 运行时字段：当前视频的本地文件引用，保存工程时上传（不序列化）。 */
  videoFile: File | null;
  /** 配音模式：voice=音色档案 / clone=原文参考克隆 / tts_interface=接口原生音色。 */
  dubMode: "voice" | "clone" | "tts_interface";
  /** 克隆模式使用的 TTS 接口。 */
  cloneInterfaceId: string | null;
  /** 接口音色模式使用的 TTS 接口与其原生音色。 */
  ttsInterfaceId: string | null;
  ttsVoiceId: string | null;
  /** 音色库列表（音色配音模式使用，懒加载一次）。 */
  voices: VoiceForgeVoice[];
  voicesError: string;

  setVideo: (video: VideoInfo | null) => void;
  updateVideo: (patch: Partial<VideoInfo>) => void;
  /** 设置原音轨整段片段（视频加载完成后调用）；传 null 清空。 */
  setOriginalAudio: (clip: AudioClip | null) => void;
  seek: (time: number) => void;
  setPlaying: (playing: boolean) => void;
  setPxPerSec: (pxPerSec: number) => void;

  addPairs: (pairs: SubtitlePair[], replace: boolean) => void;
  updatePair: (id: string, patch: Partial<Omit<SubtitlePair, "id">>) => void;
  removePair: (id: string) => void;
  /** 在指定时间点插入一条空字幕并选中，返回新 id。 */
  insertPair: (start: number) => string;
  selectPair: (id: string | null) => void;

  removeTrack: (kind: TrackKind) => void;
  addTrack: (kind: TrackKind) => void;
  toggleTrackMute: (kind: TrackKind) => void;

  addClip: (kind: TrackKind, clip: Omit<AudioClip, "id">) => string;
  moveClip: (kind: TrackKind, clipId: string, start: number) => void;
  removeClip: (kind: TrackKind, clipId: string) => void;
  setDubVoiceId: (voiceId: string | null) => void;
  setWorkspace: (id: string | null, name: string | null) => void;
  setSavedAt: (savedAt: string | null) => void;
  attachClipMediaKey: (kind: TrackKind, clipId: string, mediaKey: string) => void;
  setDubConfig: (patch: Partial<Pick<VideoDubState, "dubMode" | "dubVoiceId" | "cloneInterfaceId" | "ttsInterfaceId" | "ttsVoiceId">>) => void;
  loadVoices: () => Promise<void>;
  /** 一键对齐：所有配音片段开头对齐其所属字幕的开头。 */
  alignDubToPairs: () => void;
  /** 音频对齐字幕：虚拟变速让配音长度贴合字幕时长。 */
  fitAudioToSubtitles: () => void;
  /** 字幕对齐音频：延长字幕结束时间覆盖音频真实时长。 */
  extendSubtitlesToAudio: () => void;
  /** 用 vlf 任务导入结果替换字幕与配音/原音片段（媒体由 /api/files/stream 提供）。 */
  applyVlfImport: (payload: {
    video: VideoInfo | null;
    pairs: SubtitlePair[];
    dubbing: AudioClip[];
    originalAudio: AudioClip[];
  }) => void;
  /** 整体载入后端工程（替换全部工作台状态）。 */
  loadWorkspaceState: (payload: {
    id: string;
    name: string;
    tracks: TrackKind[];
    mutedTracks: Record<TrackKind, boolean>;
    pxPerSec: number;
    dubVoiceId: string | null;
    dubMode: "voice" | "clone" | "tts_interface";
    cloneInterfaceId: string | null;
    ttsInterfaceId: string | null;
    ttsVoiceId: string | null;
    pairs: SubtitlePair[];
    clips: Partial<Record<TrackKind, AudioClip[]>>;
    video: VideoInfo | null;
  }) => void;
};

export const useVideoDubStore = create<VideoDubState>((set) => ({
  video: null,
  tracks: [...TRACK_ORDER],
  pairs: [],
  clips: { subtitle: [], subtitle_translation: [], original_audio: [], dubbing: [], bgm: [], sfx: [] },
  currentTime: 0,
  playing: false,
  pxPerSec: 60,
  selectedPairId: null,
  mutedTracks: { ...DEFAULT_MUTED },
  dubVoiceId: null,
  workspaceId: null,
  workspaceName: null,
  savedAt: null,
  videoFile: null,
  dubMode: "voice",
  cloneInterfaceId: null,
  ttsInterfaceId: null,
  ttsVoiceId: null,
  voices: [],
  voicesError: "",

  setVideo: (video) =>
    set((state) => {
      if (state.video?.url && state.video.url !== video?.url) {
        URL.revokeObjectURL(state.video.url);
      }
      return { video, currentTime: 0, playing: false, clips: { ...state.clips, original_audio: [] } };
    }),
  updateVideo: (patch) =>
    set((state) => (state.video ? { video: { ...state.video, ...patch } } : {})),
  setOriginalAudio: (clip) =>
    set((state) => ({ clips: { ...state.clips, original_audio: clip ? [clip] : [] } })),
  seek: (time) =>
    set((state) => ({ currentTime: Math.max(0, time) })),
  setPlaying: (playing) => set({ playing }),
  setPxPerSec: (pxPerSec) => set({ pxPerSec: clamp(pxPerSec, 2, 600) }),

  addPairs: (pairs, replace) =>
    set((state) => ({ pairs: sortPairs(replace ? pairs : [...state.pairs, ...pairs]), selectedPairId: null })),
  updatePair: (id, patch) =>
    set((state) => {
      const pair = state.pairs.find((item) => item.id === id);
      const pairs = sortPairs(state.pairs.map((item) => (item.id === id ? { ...item, ...patch } : item)));
      let dubbing = state.clips.dubbing;
      // 文本改动同步配音片段标签；时间改动让配音片段跟随对齐
      if (pair?.dubClipId) {
        const nextPair = pairs.find((item) => item.id === id);
        const nextText = patch.text;
        if (nextPair && nextText !== undefined) {
          dubbing = dubbing.map((clip) => (clip.id === pair.dubClipId ? { ...clip, name: nextText } : clip));
        }
        if (nextPair && (patch.start !== undefined || patch.end !== undefined)) {
          dubbing = dubbing.map((clip) => (clip.id === pair.dubClipId ? { ...clip, start: nextPair.start } : clip));
        }
      }
      return { pairs, clips: { ...state.clips, dubbing } };
    }),
  removePair: (id) =>
    set((state) => {
      const pair = state.pairs.find((item) => item.id === id);
      const dubbing = pair?.dubClipId
        ? state.clips.dubbing.filter((clip) => clip.id !== pair.dubClipId)
        : state.clips.dubbing;
      return {
        pairs: state.pairs.filter((item) => item.id !== id),
        clips: { ...state.clips, dubbing },
        selectedPairId: state.selectedPairId === id ? null : state.selectedPairId,
      };
    }),
  insertPair: (start) => {
    const id = uid();
    const pair: SubtitlePair = { id, start, end: start + 2, text: "", translation: "" };
    set((state) => ({ pairs: sortPairs([...state.pairs, pair]), selectedPairId: id }));
    return id;
  },
  selectPair: (id) => set({ selectedPairId: id }),

  removeTrack: (kind) =>
    set((state) => (state.tracks.length > 1 ? { tracks: state.tracks.filter((item) => item !== kind) } : {})),
  addTrack: (kind) =>
    set((state) =>
      state.tracks.includes(kind) || state.tracks.length >= TRACK_ORDER.length
        ? {}
        : { tracks: TRACK_ORDER.filter((item) => state.tracks.includes(item) || item === kind) },
    ),
  toggleTrackMute: (kind) =>
    set((state) => ({ mutedTracks: { ...state.mutedTracks, [kind]: !state.mutedTracks[kind] } })),
  setWorkspace: (id, name) => set({ workspaceId: id, workspaceName: name }),
  setSavedAt: (savedAt) => set({ savedAt }),
  attachClipMediaKey: (kind, clipId, mediaKey) =>
    set((state) => ({
      clips: { ...state.clips, [kind]: state.clips[kind].map((clip) => (clip.id === clipId ? { ...clip, mediaKey } : clip)) },
    })),
  setDubConfig: (patch) => set(patch),
  loadVoices: async () => {
    if (useVideoDubStore.getState().voices.length) return;
    try {
      const result = await voiceForgeApi.voices();
      set({ voices: result.data.voices || [], voicesError: "" });
    } catch {
      set({ voicesError: "音色列表加载失败，请确认主后端已启动" });
    }
  },
  alignDubToPairs: () =>
    set((state) => ({
      clips: {
        ...state.clips,
        dubbing: state.clips.dubbing.map((clip) => {
          const pair = state.pairs.find((item) => item.dubClipId === clip.id);
          return pair ? { ...clip, start: pair.start } : clip;
        }),
      },
    })),
  fitAudioToSubtitles: () =>
    set((state) => ({
      clips: {
        ...state.clips,
        dubbing: state.clips.dubbing.map((clip) => {
          const pair = state.pairs.find((item) => item.dubClipId === clip.id);
          if (!pair) return clip;
          const aligned = Math.max(0.1, pair.end - pair.start);
          const original = clip.originalDuration && clip.originalDuration > 0.05 ? clip.originalDuration : clip.duration;
          if (original <= 0.05 || aligned <= 0.05) return clip;
          return { ...clip, duration: aligned, originalDuration: original, speed: original / aligned };
        }),
      },
    })),
  extendSubtitlesToAudio: () =>
    set((state) => ({
      pairs: sortPairs(
        state.pairs.map((pair) => {
          const clip = pair.dubClipId ? state.clips.dubbing.find((item) => item.id === pair.dubClipId) : null;
          if (!clip) return pair;
          const real = clip.originalDuration && clip.originalDuration > 0.05 ? clip.originalDuration : clip.duration;
          if (real <= pair.end - pair.start) return pair;
          return { ...pair, end: pair.start + real };
        }),
      ),
    })),
  applyVlfImport: ({ video, pairs, dubbing, originalAudio }) =>
    set((state) => {
      if (state.video?.url?.startsWith("blob:")) URL.revokeObjectURL(state.video.url);
      for (const kind of TRACK_ORDER) {
        for (const clip of state.clips[kind]) {
          if (clip.url?.startsWith("blob:")) URL.revokeObjectURL(clip.url);
        }
      }
      return {
        video,
        videoFile: null,
        // 导入任务内容视为新的未保存工程
        workspaceId: null,
        workspaceName: null,
        savedAt: null,
        pairs: sortPairs(pairs),
        clips: { ...state.clips, dubbing, original_audio: originalAudio },
        currentTime: 0,
        playing: false,
        selectedPairId: null,
      };
    }),
  loadWorkspaceState: ({ id, name, tracks, mutedTracks, pxPerSec, dubVoiceId, dubMode, cloneInterfaceId, ttsInterfaceId, ttsVoiceId, pairs, clips, video }) =>
    set((state) => {
      // 释放旧视频/音频的 blob 引用（后端媒体 URL 不需要 revoke）
      for (const kind of TRACK_ORDER) {
        for (const clip of state.clips[kind]) {
          if (clip.url?.startsWith("blob:")) URL.revokeObjectURL(clip.url);
        }
      }
      if (state.video?.url?.startsWith("blob:")) URL.revokeObjectURL(state.video.url);
      const nextClips = { subtitle: [], subtitle_translation: [], original_audio: [], dubbing: [], bgm: [], sfx: [] } as Record<TrackKind, AudioClip[]>;
      for (const kind of TRACK_ORDER) {
        if (kind === "subtitle" || kind === "subtitle_translation") continue;
        nextClips[kind] = (clips[kind] || []).map((clip) => ({ ...clip, file: undefined }));
      }
      return {
        workspaceId: id,
        workspaceName: name,
        savedAt: null,
        video,
        videoFile: null,
        tracks,
        mutedTracks,
        pxPerSec,
        dubVoiceId,
        dubMode,
        cloneInterfaceId,
        ttsInterfaceId,
        ttsVoiceId,
        pairs: sortPairs(pairs),
        clips: nextClips,
        currentTime: 0,
        playing: false,
        selectedPairId: null,
      };
    }),

  addClip: (kind, clip) => {
    const id = uid();
    set((state) => ({ clips: { ...state.clips, [kind]: [...state.clips[kind], { ...clip, id }] } }));
    return id;
  },
  moveClip: (kind, clipId, start) =>
    set((state) => ({
      clips: { ...state.clips, [kind]: state.clips[kind].map((clip) => (clip.id === clipId ? { ...clip, start: Math.max(0, start) } : clip)) },
    })),
  removeClip: (kind, clipId) =>
    set((state) => ({ clips: { ...state.clips, [kind]: state.clips[kind].filter((clip) => clip.id !== clipId) } })),
  setDubVoiceId: (voiceId) => set({ dubVoiceId: voiceId }),
}));

/** 时间轴总时长：视频时长 / 各片段末尾 / 字幕末尾的最大值，至少 60 秒保证空态可用。 */
export function timelineDuration(state: Pick<VideoDubState, "video" | "pairs" | "clips">) {
  let duration = state.video?.duration || 0;
  for (const kind of TRACK_ORDER) {
    for (const clip of state.clips[kind]) {
      duration = Math.max(duration, clip.start + clip.duration);
    }
  }
  for (const pair of state.pairs) {
    duration = Math.max(duration, pair.end);
  }
  return Math.max(60, duration);
}

/** 当前播放位置命中的字幕（用于预览叠字幕与列表高亮）。 */
export function activePairAt(pairs: SubtitlePair[], time: number) {
  return pairs.find((pair) => time >= pair.start && time <= pair.end) || null;
}

// 调试 / 自动化测试入口：可在控制台直接驱动工作台状态
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__videoDubStore = useVideoDubStore;
}
