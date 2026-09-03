import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useParams } from "react-router-dom";
import {
  voiceForgeApi,
  VoiceForgeProject,
  VoiceForgeSentence,
  VoiceForgeVoice,
  VoiceForgeTask,
  VoiceForgeExport,
  VoiceForgeCapability,
  VoiceForgeEmotionTag,
  VoiceForgeProjectProgress,
  VoiceForgeProgressMessage,
} from "@/api/voiceforge";
import { getWebSocketUrl } from "@/api/ws";

/* ── Types ─────────────────────────────────────────────────────────── */

export interface Chapter {
  id: string;
  title: string;
  parent_id?: string | null;
  level: number;
  order_index: number;
  sentence_count?: number;
  char_count?: number;
  children?: Chapter[];
}

export interface Character {
  id: string;
  name: string;
  character_type?: string;
  voice_profile_id?: string | null;
  language?: string;
  note?: string;
}

export interface DubbingState {
  project: VoiceForgeProject | null;
  chapters: Chapter[];
  characters: Character[];
  voices: VoiceForgeVoice[];
  sentences: VoiceForgeSentence[];
  tasks: VoiceForgeTask[];
  exports: VoiceForgeExport[];
  capabilities: VoiceForgeCapability[];
  emotionTags: VoiceForgeEmotionTag[];
  selectedChapterId: string | null;
  selectedIds: Set<string>;
  engine: string;
  voiceControlMode: "clone" | "instruct";
  defaultGap: number;
  busy: string;
  error: string;
  projectProgress: VoiceForgeProjectProgress | null;
}

export type DubbingAction =
  | { type: "SET_ALL"; payload: Partial<DubbingState> }
  | { type: "SET_CHAPTER"; payload: string | null }
  | { type: "SET_SELECTED"; payload: Set<string> }
  | { type: "TOGGLE_SELECT"; payload: string }
  | { type: "SELECT_ALL"; payload: string[] }
  | { type: "CLEAR_SELECTION" }
  | { type: "SET_ENGINE"; payload: string }
  | { type: "SET_MODE"; payload: "clone" | "instruct" }
  | { type: "SET_GAP"; payload: number }
  | { type: "SET_BUSY"; payload: string }
  | { type: "SET_ERROR"; payload: string }
  | { type: "UPDATE_SENTENCE_LOCAL"; payload: { id: string; changes: Partial<VoiceForgeSentence> } }
  | { type: "PATCH_SENTENCES"; payload: Array<Partial<VoiceForgeSentence> & { id: string }> }
  | { type: "SET_PROJECT_PROGRESS"; payload: VoiceForgeProjectProgress };

/* ── Reducer ───────────────────────────────────────────────────────── */

const initialState: DubbingState = {
  project: null,
  chapters: [],
  characters: [],
  voices: [],
  sentences: [],
  tasks: [],
  exports: [],
  capabilities: [],
  emotionTags: [],
  projectProgress: null,
  selectedChapterId: null,
  selectedIds: new Set<string>(),
  engine: "",
  voiceControlMode: "clone",
  defaultGap: 0.3,
  busy: "",
  error: "",
};

function reducer(state: DubbingState, action: DubbingAction): DubbingState {
  switch (action.type) {
    case "SET_ALL":
      return { ...state, ...action.payload };

    case "SET_CHAPTER":
      return {
        ...state,
        selectedChapterId: action.payload,
        selectedIds: new Set<string>(),
      };

    case "SET_SELECTED":
      return { ...state, selectedIds: action.payload };

    case "TOGGLE_SELECT": {
      const next = new Set(state.selectedIds);
      if (next.has(action.payload)) {
        next.delete(action.payload);
      } else {
        next.add(action.payload);
      }
      return { ...state, selectedIds: next };
    }

    case "SELECT_ALL": {
      const allIds = new Set(action.payload);
      const allSelected = action.payload.every((id) => state.selectedIds.has(id));
      return {
        ...state,
        selectedIds: allSelected ? new Set<string>() : allIds,
      };
    }

    case "CLEAR_SELECTION":
      return { ...state, selectedIds: new Set<string>() };

    case "SET_ENGINE":
      return { ...state, engine: action.payload };

    case "SET_MODE":
      return { ...state, voiceControlMode: action.payload };

    case "SET_GAP":
      return { ...state, defaultGap: action.payload };

    case "SET_BUSY":
      return { ...state, busy: action.payload };

    case "SET_ERROR":
      return { ...state, error: action.payload };

    case "UPDATE_SENTENCE_LOCAL": {
      const sentences = state.sentences.map((s) =>
        s.id === action.payload.id ? { ...s, ...action.payload.changes } : s,
      );
      return { ...state, sentences };
    }

    case "PATCH_SENTENCES": {
      const map = new Map(action.payload.map((p) => [p.id, p]));
      return {
        ...state,
        sentences: state.sentences.map((s) => {
          const patch = map.get(s.id);
          return patch ? { ...s, ...patch } : s;
        }),
      };
    }

    case "SET_PROJECT_PROGRESS":
      return { ...state, projectProgress: action.payload };

    default:
      return state;
  }
}

/* ── Context ───────────────────────────────────────────────────────── */

interface DubbingContextValue {
  state: DubbingState;
  dispatch: React.Dispatch<DubbingAction>;
  load: () => Promise<void>;
  queueSentenceUpdate: (sentenceId: string, changes: Partial<VoiceForgeSentence>, currentVersion: number) => void;
}

const DubbingContext = createContext<DubbingContextValue | null>(null);

/* ── Provider ──────────────────────────────────────────────────────── */

export function DubbingProvider({ children }: { children: React.ReactNode }) {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const [state, dispatch] = useReducer(reducer, initialState);
  const mountedRef = useRef(true);

  /* Debounced sentence-update queue */
  const pendingRef = useRef<
    Map<string, { changes: Partial<VoiceForgeSentence>; version: number; timer: ReturnType<typeof setTimeout> }>
  >(new Map());

  /* ── Load all workspace data (independent per-request, no Promise.all) ── */
  const load = useCallback(async () => {
    if (!projectId) return;
    dispatch({ type: "SET_BUSY", payload: "load" });

    // Fire all requests in parallel but catch each independently so one
    // failure doesn't block the rest.
    const settle = <T,>(p: Promise<T>, label: string): Promise<T | null> =>
      p.catch((err) => { console.error(`[VF] ${label} failed:`, err); return null; });

    const [pRes, cRes, chRes, vRes, sRes, tRes, eRes, capRes, emRes] =
      await Promise.all([
        settle(voiceForgeApi.getProject(projectId), "getProject"),
        settle(voiceForgeApi.characters(projectId), "characters"),
        settle(voiceForgeApi.chapters(projectId), "chapters"),
        settle(voiceForgeApi.voices(), "voices"),
        settle(voiceForgeApi.sentences(projectId), "sentences"),
        settle(voiceForgeApi.tasks(projectId), "tasks"),
        settle(voiceForgeApi.exports(projectId), "exports"),
        settle(voiceForgeApi.capabilities(), "capabilities"),
        settle(voiceForgeApi.emotionTags(), "emotionTags"),
      ]);

    if (!mountedRef.current) return;

    console.log("[VF] load results:", {
      project: !!pRes?.data?.project,
      sentences: sRes?.data?.sentences?.length,
      chapters: chRes?.data?.chapters?.length,
      characters: cRes?.data?.characters?.length,
      voices: vRes?.data?.voices?.length,
    });

    const payload: Partial<DubbingState> = {};

    if (pRes?.data?.project) {
      payload.project = pRes.data.project as VoiceForgeProject;
      // 初始化工具栏 TTS 引擎选择，使其与项目已保存的默认接口对齐
      payload.engine = (pRes.data.project.default_interface_id as string) || "";
    }
    if (cRes?.data) payload.characters = (cRes.data.characters ?? []) as Character[];
    if (chRes?.data) payload.chapters = (chRes.data.chapters ?? []) as Chapter[];
    if (vRes?.data) payload.voices = (vRes.data.voices ?? []) as VoiceForgeVoice[];
    if (sRes?.data) payload.sentences = (sRes.data.sentences ?? []) as VoiceForgeSentence[];
    if (tRes?.data) payload.tasks = (tRes.data.tasks ?? []) as VoiceForgeTask[];
    if (eRes?.data) payload.exports = (eRes.data.exports ?? []) as VoiceForgeExport[];
    // Backend returns {"interfaces": [...]}, frontend type expects "capabilities"
    if (capRes?.data) payload.capabilities = (capRes.data.capabilities ?? capRes.data.interfaces ?? []) as VoiceForgeCapability[];
    if (emRes?.data) payload.emotionTags = (emRes.data.tags ?? []) as VoiceForgeEmotionTag[];

    dispatch({ type: "SET_ALL", payload });

    // Surface project-level error if the main resource failed
    if (!pRes) {
      dispatch({ type: "SET_ERROR", payload: "无法加载项目数据，请检查网络连接" });
    }

    dispatch({ type: "SET_BUSY", payload: "" });
  }, [projectId, dispatch]);

  /* Initial load + WebSocket for live updates */
  useEffect(() => {
    mountedRef.current = true;
    void load();

    const socket = new WebSocket(getWebSocketUrl(`/ws/voiceforge/projects/${encodeURIComponent(projectId)}/progress`));

    socket.onerror = () => {}; // swallow – do not crash the component
    socket.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string) as VoiceForgeProgressMessage;
        if (msg.type !== "voiceforge.progress" || !msg.summary) return;
        // 事件驱动式局部更新：仅 patch 变化的句子状态，不整页 reload
        if (Array.isArray(msg.sentences) && msg.sentences.length) {
          dispatch({
            type: "PATCH_SENTENCES",
            payload: msg.sentences.map((s) => ({
              id: s.id,
              status: s.status,
              error_message: s.error_message,
              audio_storage_key: s.audio_storage_key,
              audio_duration: s.audio_duration,
            })),
          });
        }
        if (Array.isArray(msg.tasks)) {
          dispatch({ type: "SET_ALL", payload: { tasks: msg.tasks as VoiceForgeTask[] } });
        }
        dispatch({ type: "SET_PROJECT_PROGRESS", payload: msg.summary });
      } catch {
        // Non-JSON message — ignore
      }
    };

    return () => {
      mountedRef.current = false;
      socket.close();
      // Flush pending debounced updates
      pendingRef.current.forEach(({ timer }) => clearTimeout(timer));
      pendingRef.current.clear();
    };
  }, [projectId, load]);

  /* ── Debounced sentence update ──────────────────────────────────── */
  const queueSentenceUpdate = useCallback(
    (
      sentenceId: string,
      changes: Partial<VoiceForgeSentence>,
      currentVersion: number,
    ) => {
      const prev = pendingRef.current.get(sentenceId);
      if (prev) clearTimeout(prev.timer);

      // Merge changes locally so rapid edits don't lose intermediate values
      const mergedChanges = { ...changes };
      const mergedVersion = currentVersion;

      const timer = setTimeout(async () => {
        pendingRef.current.delete(sentenceId);
        try {
          await voiceForgeApi.updateSentence(sentenceId, {
            ...mergedChanges,
            version: mergedVersion,
          });
          // Reload to get server-side computed fields
          void load();
        } catch (err) {
          const detail =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "保存句子失败";
          dispatch({ type: "SET_ERROR", payload: detail });
        }
      }, 450);

      pendingRef.current.set(sentenceId, { changes: mergedChanges, version: mergedVersion, timer });
    },
    [load, dispatch],
  );

  const value: DubbingContextValue = { state, dispatch, load, queueSentenceUpdate };

  return (
    <DubbingContext.Provider value={value}>{children}</DubbingContext.Provider>
  );
}

/* ── Hook ──────────────────────────────────────────────────────────── */

export function useDubbingContext(): DubbingContextValue {
  const ctx = useContext(DubbingContext);
  if (!ctx) {
    throw new Error("useDubbingContext must be used within a <DubbingProvider>");
  }
  return ctx;
}
