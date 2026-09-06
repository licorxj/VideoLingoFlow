import { useCallback, useState } from "react";
import { voiceForgeApi, VoiceForgeVoice } from "@/api/voiceforge";
import { videodubApi } from "@/api/videodub";
import { useVideoDubStore } from "./store";
import { AudioClip, SubtitlePair } from "./types";

function errorText(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/** 用音色档案拼出 TTS 试听接口的请求参数。 */
function buildVoiceProfilePayload(pair: SubtitlePair, voice: VoiceForgeVoice) {
  const mode = voice.mode || "preset_voice";
  return {
    interface_id: voice.interface_id || "",
    mode,
    text: pair.text,
    voice_id: voice.voice_id || undefined,
    speed: 1,
    reference_storage_key: ["clone", "controllable_clone"].includes(mode) ? voice.reference_storage_key || undefined : undefined,
    voice_design: mode === "voice_design" ? voice.design_text || undefined : undefined,
  };
}

/** 克隆模式：取该句原文音频片段（原音轨上起点对齐的片段）转成参考音频。 */
async function resolveReferenceStorageKey(pair: SubtitlePair): Promise<string | null> {
  const state = useVideoDubStore.getState();
  const original = state.clips.original_audio.find((clip) => Math.abs(clip.start - pair.start) < 0.05);
  if (!original) return null;
  if (original.file) {
    const uploaded = await voiceForgeApi.uploadVoiceReference(original.file);
    return uploaded.data.storage_key as string;
  }
  if (original.source) {
    const created = await videodubApi.referenceFromTask(original.source);
    return created.data.storage_key as string;
  }
  return null;
}

/**
 * 逐句 TTS 配音。按工作台当前配音模式分支：
 *   voice         音色档案（原逻辑）
 *   clone         用该句原文音频作为参考音频克隆音色
 *   tts_interface 直接用 TTS 接口自带音色
 * 生成的音频以片段形式落到配音轨（起点对齐字幕）。
 */
export function useDubbing() {
  const [batch, setBatch] = useState<{ running: boolean; done: number; total: number }>({ running: false, done: 0, total: 0 });

  const generateOne = useCallback(async (pair: SubtitlePair) => {
    const store = useVideoDubStore.getState();
    if (!pair.text.trim()) return;
    store.updatePair(pair.id, { dubStatus: "generating", dubError: undefined });

    try {
      let requestPayload: Record<string, unknown>;
      const mode = store.dubMode || "voice";
      if (mode === "clone") {
        if (!store.cloneInterfaceId) throw new Error("请先在「配音模式」中选择克隆用 TTS 接口");
        const referenceKey = await resolveReferenceStorageKey(pair);
        if (!referenceKey) throw new Error("该句没有可用的原文音频片段作为参考音频");
        requestPayload = {
          interface_id: store.cloneInterfaceId,
          mode: "clone",
          text: pair.text,
          reference_storage_key: referenceKey,
          speed: 1,
        };
      } else if (mode === "tts_interface") {
        if (!store.ttsInterfaceId) throw new Error("请先在「配音模式」中选择 TTS 接口");
        requestPayload = {
          interface_id: store.ttsInterfaceId,
          mode: "preset_voice",
          text: pair.text,
          voice_id: store.ttsVoiceId || undefined,
          speed: 1,
        };
      } else {
        const voice = store.voices.find((item) => item.id === store.dubVoiceId);
        if (!voice) throw new Error("请先选择配音音色");
        requestPayload = buildVoiceProfilePayload(pair, voice);
      }

      const result = await voiceForgeApi.previewVoice(requestPayload);
      const { storage_key: storageKey, duration } = result.data as { storage_key?: string; duration?: number };
      if (!storageKey) throw new Error("接口未返回音频");
      const next = useVideoDubStore.getState();
      const current = next.pairs.find((item) => item.id === pair.id);
      if (!current) return;
      if (current.dubClipId) next.removeClip("dubbing", current.dubClipId);
      const audioDuration = duration && duration > 0 ? duration : Math.max(1, current.end - current.start);
      const clipId = next.addClip("dubbing", {
        name: current.text,
        start: current.start,
        duration: audioDuration,
        url: voiceForgeApi.voicePreviewUrl(storageKey),
        mediaKey: `vf:${storageKey}`,
        originalDuration: audioDuration,
      });
      next.updatePair(pair.id, {
        dubClipId: clipId,
        dubDuration: audioDuration,
        dubVoiceId: mode === "voice" ? store.dubVoiceId || undefined : undefined,
        dubStatus: "done",
      });
    } catch (error) {
      useVideoDubStore.getState().updatePair(pair.id, {
        dubStatus: "error",
        dubError: errorText(error, "配音生成失败"),
      });
    }
  }, []);

  const generateBatch = useCallback(
    async (pairs: SubtitlePair[]) => {
      const targets = pairs.filter((pair) => pair.text.trim() && pair.dubStatus !== "generating");
      if (!targets.length) return;
      setBatch({ running: true, done: 0, total: targets.length });
      const queue = [...targets];
      const worker = async () => {
        while (queue.length) {
          const next = queue.shift();
          if (!next) break;
          await generateOne(next);
          setBatch((state) => ({ ...state, done: state.done + 1 }));
        }
      };
      await Promise.all([worker(), worker()]);
      setBatch((state) => ({ ...state, running: false }));
    },
    [generateOne],
  );

  return { generateOne, generateBatch, batch };
}
