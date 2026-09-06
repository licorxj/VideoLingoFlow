import { videodubApi } from "@/api/videodub";
import { useVideoDubStore } from "./store";
import { AudioClip, SubtitlePair, TrackKind } from "./types";

/** 参与持久化的音频轨（字幕两条轨由 pairs 派生，原音轨由视频自动生成）。 */
const PERSISTED_AUDIO_KINDS: TrackKind[] = ["dubbing", "bgm", "sfx"];

type SerializedClip = {
  id: string;
  name: string;
  start: number;
  duration: number;
  mediaKey: string;
  speed?: number;
  originalDuration?: number;
  source?: { taskId: string; path: string };
};

function errorText(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/** 当前工作台状态 → 可持久化 JSON（剥离 file 等运行时字段）。 */
export function serializeState() {
  const state = useVideoDubStore.getState();
  const clips: Record<string, SerializedClip[]> = {};
  for (const kind of PERSISTED_AUDIO_KINDS) {
    clips[kind] = state.clips[kind]
      .filter((clip): clip is AudioClip & { mediaKey: string } => Boolean(clip.mediaKey))
      .map((clip) => {
        const base = { id: clip.id, name: clip.name, start: clip.start, duration: clip.duration, mediaKey: clip.mediaKey };
        if (clip.speed && clip.speed !== 1) (base as any).speed = clip.speed;
        if (clip.originalDuration && clip.originalDuration !== clip.duration) (base as any).originalDuration = clip.originalDuration;
        if (clip.source) (base as any).source = clip.source;
        return base;
      });
  }
  return {
    appVersion: 1,
    tracks: state.tracks,
    mutedTracks: state.mutedTracks,
    pxPerSec: state.pxPerSec,
    dubVoiceId: state.dubVoiceId,
    dubMode: state.dubMode,
    cloneInterfaceId: state.cloneInterfaceId,
    ttsInterfaceId: state.ttsInterfaceId,
    ttsVoiceId: state.ttsVoiceId,
    pairs: state.pairs.map((pair) => ({
      id: pair.id,
      start: pair.start,
      end: pair.end,
      text: pair.text,
      translation: pair.translation,
      dubClipId: pair.dubClipId,
      dubVoiceId: pair.dubVoiceId,
      dubDuration: pair.dubDuration,
      // 保存瞬间还在生成中的行按"被中断"处理
      dubStatus: pair.dubStatus === "generating" ? "error" : pair.dubStatus,
      dubError: pair.dubStatus === "generating" ? "保存时生成被中断，可重新生成" : pair.dubError,
      vlfIndex: pair.vlfIndex,
      characterId: pair.characterId,
      readCharacterId: pair.readCharacterId,
      toneDesc: pair.toneDesc,
      dialect: pair.dialect,
    })),
    clips,
  };
}

/** 保存工程：未保存过则先建工程（上传视频），再把本地音频片段上传，最后写状态。 */
export async function saveWorkspace(): Promise<{ ok: boolean; error?: string }> {
  try {
    const state = useVideoDubStore.getState();
    let workspaceId = state.workspaceId;
    if (!workspaceId) {
      const created = await videodubApi.create(state.videoFile, state.workspaceName || state.video?.name || "视频配音工程");
      workspaceId = created.data.id;
      useVideoDubStore.setState({ workspaceId, workspaceName: created.data.name });
    }
    if (!workspaceId) return { ok: false, error: "创建工程失败" };
    // 上传本地音频文件（还没有 mediaKey 的片段）
    for (const kind of PERSISTED_AUDIO_KINDS) {
      for (const clip of useVideoDubStore.getState().clips[kind]) {
        if (clip.mediaKey || !clip.file) continue;
        const uploaded = await videodubApi.uploadAudio(workspaceId, clip.file);
        useVideoDubStore.getState().attachClipMediaKey(kind, clip.id, uploaded.data.media_key);
      }
    }
    const current = useVideoDubStore.getState();
    await videodubApi.saveState(
      workspaceId,
      serializeState(),
      current.workspaceName || undefined,
      current.video?.duration || undefined,
    );
    useVideoDubStore.getState().setSavedAt(new Date().toISOString());
    return { ok: true };
  } catch (error) {
    return { ok: false, error: errorText(error, "保存失败，请确认主后端已启动") };
  }
}

/** 打开工程：拉取详情并整体替换工作台状态。 */
export async function loadWorkspace(id: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const detail = (await videodubApi.detail(id)).data;
    const state = (detail.state || {}) as Record<string, unknown>;
    const mediaUrl = (key: string) => videodubApi.mediaUrl(id, key);
    const pairs = (state.pairs || []) as SubtitlePair[];
    const clips: Partial<Record<TrackKind, AudioClip[]>> = {};
    const savedClips = (state.clips || {}) as Record<string, SerializedClipLike[]>;
    for (const kind of PERSISTED_AUDIO_KINDS) {
      clips[kind] = (savedClips[kind] || []).map((clip) => ({
        id: clip.id,
        name: clip.name,
        start: clip.start,
        duration: clip.duration,
        mediaKey: clip.mediaKey,
        url: clip.mediaKey ? mediaUrl(clip.mediaKey) : undefined,
        speed: (clip as any).speed,
        originalDuration: (clip as any).originalDuration,
        source: (clip as any).source,
      }));
    }
    useVideoDubStore.getState().loadWorkspaceState({
      id: detail.id,
      name: detail.name,
      tracks: (state.tracks || useVideoDubStore.getState().tracks) as TrackKind[],
      mutedTracks: { ...useVideoDubStore.getState().mutedTracks, ...((state.mutedTracks || {}) as Record<TrackKind, boolean>) },
      pxPerSec: (state.pxPerSec as number) || 60,
      dubVoiceId: (state.dubVoiceId as string | null) ?? null,
      dubMode: (state.dubMode as "voice" | "clone" | "tts_interface") || "voice",
      cloneInterfaceId: (state.cloneInterfaceId as string | null) ?? null,
      ttsInterfaceId: (state.ttsInterfaceId as string | null) ?? null,
      ttsVoiceId: (state.ttsVoiceId as string | null) ?? null,
      pairs,
      clips,
      video: detail.video_key
        ? { name: detail.video_name, url: mediaUrl(detail.video_key), duration: detail.duration || 0, width: 0, height: 0 }
        : null,
    });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: errorText(error, "打开工程失败，请确认主后端已启动") };
  }
}

type SerializedClipLike = { id: string; name: string; start: number; duration: number; mediaKey?: string };
