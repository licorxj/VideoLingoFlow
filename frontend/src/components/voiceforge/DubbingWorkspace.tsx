import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Loader2, Music2 } from "lucide-react";
import { voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/shared/PageHeader";
import { useNotificationStore } from "@/stores/notificationStore";
import { DubbingProvider, useDubbingContext } from "./dubbing/DubbingContext";
import { DubbingLayout } from "./dubbing/DubbingLayout";
import { ChapterPanel } from "./dubbing/ChapterPanel";
import { DubbingToolbar } from "./dubbing/DubbingToolbar";
import { SentenceList } from "./dubbing/SentenceList";
import { CharacterPanel } from "./dubbing/CharacterPanel";
import { VoiceTree } from "./dubbing/VoiceTree";
import { TextCleanModal } from "./dubbing/dialogs/TextCleanModal";
import { SentenceSplitModal } from "./dubbing/dialogs/SentenceSplitModal";
import { BatchRoleModal } from "./dubbing/dialogs/BatchRoleModal";
import { ImportTextModal } from "./dubbing/dialogs/ImportTextModal";
import { ChapterExportModal } from "./dubbing/dialogs/ChapterExportModal";
import { AIDialogueModal } from "./dubbing/dialogs/AIDialogueModal";
import { AICharacterModal } from "./dubbing/dialogs/AICharacterModal";
import { AddCharacterModal } from "./dubbing/dialogs/AddCharacterModal";
import { BindVoiceModal } from "./dubbing/dialogs/BindVoiceModal";
import { PreviewSectionModal } from "./dubbing/dialogs/PreviewSectionModal";
import { ExportedAudioModal } from "./dubbing/dialogs/ExportedAudioModal";
import { EditOriginalModal } from "./dubbing/dialogs/EditOriginalModal";
import { RuleChapterSplitModal } from "./dubbing/dialogs/RuleChapterSplitModal";
import { AIChapterSplitModal } from "./dubbing/dialogs/AIChapterSplitModal";
import { EngineSettingsModal } from "./dubbing/dialogs/EngineSettingsModal";
import { ProcessChapterModal } from "./dubbing/dialogs/ProcessChapterModal";
import { RuleSplitModal } from "./dubbing/dialogs/RuleSplitModal";
import { BatchVoiceDesignDialog } from "./dubbing/dialogs/BatchVoiceDesignDialog";

/* ══════════════════════════════════════════════════════════════════════
   Wrapper — provides DubbingProvider for all child components
   ══════════════════════════════════════════════════════════════════════ */

export function DubbingWorkspace() {
  const { projectId = "" } = useParams();
  useEffect(() => {
    if (projectId) localStorage.setItem("vl_last_voiceforge_project", projectId);
  }, [projectId]);
  return (
    <DubbingProvider>
      <DubbingWorkspaceInner />
    </DubbingProvider>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Inner — actual workspace UI, must be inside DubbingProvider
   ══════════════════════════════════════════════════════════════════════ */

function DubbingWorkspaceInner() {
  const { projectId = "" } = useParams();
  const { state, dispatch, load, queueSentenceUpdate } = useDubbingContext();

  const {
    project,
    chapters,
    characters,
    voices,
    sentences,
    tasks,
    exports,
    capabilities,
    emotionTags,
    selectedChapterId,
    selectedIds,
    engine,
    voiceControlMode,
    defaultGap,
    busy,
    error,
  } = state;

  /* ── 把运行时错误统一推到顶部导航的铃铛抽屉 ─────────────── */
  const lastErrorRef = useRef("");
  useEffect(() => {
    if (!error) return;
    if (error === lastErrorRef.current) return;
    lastErrorRef.current = error;
    useNotificationStore.getState().pushNotification({
      kind: "error",
      title: "配音操作失败",
      description: error,
      source: "voiceforge",
    });
  }, [error]);

  /* ── Filtered sentences by selected chapter ────────────────────── */
  const shownSentences = useMemo(
    () =>
      selectedChapterId
        ? sentences.filter((s) => s.chapter_id === selectedChapterId)
        : sentences,
    [selectedChapterId, sentences],
  );

  const visibleIds = useMemo(
    () => shownSentences.map((s) => s.id),
    [shownSentences],
  );

  const allText = useMemo(
    () => sentences.map((s) => s.edited_text || s.text).join("\n"),
    [sentences],
  );

  /* ── Dialog open states ────────────────────────────────────────── */
  const [importTextOpen, setImportTextOpen] = useState(false);
  const [editOriginalOpen, setEditOriginalOpen] = useState(false);
  const [textCleanOpen, setTextCleanOpen] = useState(false);
  const [sentenceSplitOpen, setSentenceSplitOpen] = useState(false);
  const [batchRoleOpen, setBatchRoleOpen] = useState(false);
  const [addCharacterOpen, setAddCharacterOpen] = useState(false);
  const [bindVoiceOpen, setBindVoiceOpen] = useState(false);
  const [aiDialogueOpen, setAiDialogueOpen] = useState(false);
  const [aiCharacterOpen, setAiCharacterOpen] = useState(false);
  const [previewSectionOpen, setPreviewSectionOpen] = useState(false);
  const [exportedAudioOpen, setExportedAudioOpen] = useState(false);
  const [chapterExportOpen, setChapterExportOpen] = useState(false);
  const [ruleChapterSplitOpen, setRuleChapterSplitOpen] = useState(false);
  const [ruleSplitText, setRuleSplitText] = useState("");
  const [aiChapterSplitOpen, setAiChapterSplitOpen] = useState(false);
  const [engineSettingsOpen, setEngineSettingsOpen] = useState(false);
  const [processChapterOpen, setProcessChapterOpen] = useState(false);
  const [ruleSplitOpen, setRuleSplitOpen] = useState(false);
  const [batchVoiceDesignOpen, setBatchVoiceDesignOpen] = useState(false);
  const [processChapter, setProcessChapter] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [bindTargetCharacterId, setBindTargetCharacterId] = useState<
    string | null
  >(null);

  /* ── Local state for edit original modal ───────────────────────── */
  const [editChapterName, setEditChapterName] = useState("");
  const [editChapterText, setEditChapterText] = useState("");

  /* ── Audio playback ────────────────────────────────────────────── */
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);

  /* ════════════════════════════════════════════════════════════════════
     ChapterPanel callbacks
     ════════════════════════════════════════════════════════════════════ */

  const handleImportText = useCallback(() => setImportTextOpen(true), []);

  const handleEditOriginal = useCallback(() => {
    const ch = selectedChapterId
      ? chapters.find((c) => c.id === selectedChapterId)
      : null;
    setEditChapterName(ch?.title ?? "全部句子");
    setEditChapterText(
      shownSentences.map((s) => s.edited_text || s.text).join("\n"),
    );
    setEditOriginalOpen(true);
  }, [selectedChapterId, chapters, shownSentences]);

  const handleRuleSplitChapters = useCallback(() => {
    const text = shownSentences.map((s) => s.edited_text || s.text).join("\n");
    if (!text.trim()) {
      alert("请先导入文本内容");
      return;
    }
    setRuleSplitText(text);
    setRuleChapterSplitOpen(true);
  }, [shownSentences]);

  const handleApplyRuleChapters = useCallback(
    async (splitChapters: Array<{ chapterName: string; textContent: string; charCount: number }>) => {
      try {
        await voiceForgeApi.batchCreateChapters(projectId, {
          chapters: splitChapters.map((c) => ({ title: c.chapterName, text_content: c.textContent })),
          delete_existing: true,
        });
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "规则拆分失败" });
      }
    },
    [projectId, load, dispatch],
  );

  const handleAISplitChapters = useCallback(() => {
    setAiChapterSplitOpen(true);
  }, []);

  const handleApplyAIChapters = useCallback(
    async (aiChapters: Array<{ title: string; text: string }>) => {
      try {
        await voiceForgeApi.batchCreateChapters(projectId, {
          chapters: aiChapters.map((c) => ({
            title: c.title,
            text_content: c.text,
          })),
          delete_existing: true,
        });
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "应用 AI 分章节失败" });
      }
    },
    [projectId, load, dispatch],
  );

  const handleCreateChapter = useCallback(
    async (title: string, _parentId?: string | null) => {
      try {
        await voiceForgeApi.createChapter(projectId, { title });
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "创建章节失败" });
      }
    },
    [projectId, load, dispatch],
  );

  const handleDeleteChapter = useCallback(
    async (id: string) => {
      try {
        await voiceForgeApi.deleteChapter(id);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "删除章节失败" });
      }
    },
    [load, dispatch],
  );

  const handleUpdateChapterText = useCallback(
    async (id: string, text: string) => {
      try {
        await voiceForgeApi.updateChapter(id, { title: text });
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "更新章节失败" });
      }
    },
    [load, dispatch],
  );

  /* ════════════════════════════════════════════════════════════════════
     DubbingToolbar callbacks
     ════════════════════════════════════════════════════════════════════ */

  const handleSelectAll = useCallback(() => {
    dispatch({ type: "SELECT_ALL", payload: visibleIds });
  }, [dispatch, visibleIds]);

  const handleDelete = useCallback(async () => {
    if (!selectedIds.size) return;
    try {
      await voiceForgeApi.deleteSentences(projectId, [...selectedIds]);
      dispatch({ type: "CLEAR_SELECTION" });
      await load();
    } catch {
      dispatch({ type: "SET_ERROR", payload: "删除句子失败" });
    }
  }, [projectId, selectedIds, dispatch, load]);

  const handleToolbarAIDialogue = useCallback(() => setAiDialogueOpen(true), []);

  const handleToolbarTextClean = useCallback(() => setTextCleanOpen(true), []);

  const handleToolbarSentenceSplit = useCallback(
    () => setSentenceSplitOpen(true),
    [],
  );

  const handleToolbarBatchRole = useCallback(() => setBatchRoleOpen(true), []);

  const handleBatchGenerate = useCallback(async () => {
    dispatch({ type: "SET_BUSY", payload: "batch" });
    try {
      const sentenceIds = selectedIds.size > 0 ? [...selectedIds] : undefined;
      await voiceForgeApi.synthesizeProject(projectId, {
        sentence_ids: sentenceIds,
        interface_id: state.engine || undefined,
      });
    } catch {
      dispatch({ type: "SET_ERROR", payload: "提交合成失败" });
    } finally {
      dispatch({ type: "SET_BUSY", payload: "" });
    }
  }, [projectId, selectedIds, state.engine, dispatch]);

  const handleCompleteGenerate = useCallback(async () => {
    dispatch({ type: "SET_BUSY", payload: "batch" });
    try {
      const sentenceIds = selectedIds.size > 0 ? [...selectedIds] : undefined;
      await voiceForgeApi.synthesizeProject(projectId, {
        sentence_ids: sentenceIds,
        retry_failed: true,
        interface_id: state.engine || undefined,
      });
    } catch {
      dispatch({ type: "SET_ERROR", payload: "补全合成失败" });
    } finally {
      dispatch({ type: "SET_BUSY", payload: "" });
    }
  }, [projectId, selectedIds, state.engine, dispatch]);

  const handleToolbarPreviewSection = useCallback(
    () => setPreviewSectionOpen(true),
    [],
  );

  const handleToolbarExportChapter = useCallback(
    () => setChapterExportOpen(true),
    [],
  );

  const handleToolbarBrowseExports = useCallback(
    () => setExportedAudioOpen(true),
    [],
  );

  const handleEngineChange = useCallback(
    async (value: string) => {
      // 立即更新本地选择，保证后续合成即时生效
      dispatch({ type: "SET_ENGINE", payload: value });
      // 持久化到项目默认 TTS 接口，使「配音功能」真正联通本项目的 TTS 服务层
      try {
        if (state.project) {
          await voiceForgeApi.updateProject(projectId, {
            default_interface_id: value || undefined,
            version: state.project.version,
          });
        }
      } catch {
        dispatch({ type: "SET_ERROR", payload: "保存引擎设置失败" });
      }
    },
    [projectId, state.project, dispatch],
  );

  const handleVoiceControlModeChange = useCallback(
    (mode: "clone" | "instruct") =>
      dispatch({ type: "SET_MODE", payload: mode }),
    [dispatch],
  );

  const handleGapChange = useCallback(
    (gap: number) => dispatch({ type: "SET_GAP", payload: gap }),
    [dispatch],
  );

  const handleEngineSettings = useCallback(() => {
    setEngineSettingsOpen(true);
  }, []);

  /* ════════════════════════════════════════════════════════════════════
     SentenceList callbacks
     ════════════════════════════════════════════════════════════════════ */

  const handleToggleSelect = useCallback(
    (id: string) => dispatch({ type: "TOGGLE_SELECT", payload: id }),
    [dispatch],
  );

  const handleUpdateSentence = useCallback(
    async (id: string, patch: Record<string, unknown>) => {
      try {
        const sentence = sentences.find((s) => s.id === id);
        if (!sentence) return;
        await voiceForgeApi.updateSentence(id, {
          ...patch,
          version: sentence.version,
        });
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "保存句子失败" });
      }
    },
    [sentences, load, dispatch],
  );

  const handlePlaySentence = useCallback(
    (id: string) => {
      audioRef.current?.pause();
      const audio = new Audio(voiceForgeApi.sentenceAudioUrl(id));
      audio.addEventListener("ended", () => setPlayingId(null));
      audio.addEventListener("error", () => setPlayingId(null));
      audio.play().catch(() => setPlayingId(null));
      audioRef.current = audio;
      setPlayingId(id);
    },
    [],
  );

  const handleRegenerateSentence = useCallback(
    async (id: string) => {
      dispatch({ type: "SET_BUSY", payload: `regen-${id}` });
      try {
        await voiceForgeApi.synthesize(id, state.engine || undefined);
      } catch {
        dispatch({ type: "SET_ERROR", payload: "重新生成失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [dispatch, state.engine],
  );

  const handleAddAfter = useCallback(
    async (_index: number) => {
      // Insert a blank sentence after the given index
      try {
        const chapterId = selectedChapterId || shownSentences[0]?.chapter_id || "";
        await voiceForgeApi.importText(projectId, " ");
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "添加句子失败" });
      }
    },
    [projectId, selectedChapterId, shownSentences, load, dispatch],
  );

  const handleReorder = useCallback(
    async (orderedIds: string[]) => {
      try {
        await voiceForgeApi.reorderSentences(projectId, orderedIds);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "排序失败" });
      }
    },
    [projectId, load, dispatch],
  );

  const handleQueueUpdate = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      const sentence = sentences.find((s) => s.id === id);
      if (sentence) {
        queueSentenceUpdate(id, patch, sentence.version);
      }
    },
    [sentences, queueSentenceUpdate],
  );

  /* ════════════════════════════════════════════════════════════════════
     CharacterPanel callbacks
     ════════════════════════════════════════════════════════════════════ */

  const handleCreateCharacter = useCallback(
    async (name: string) => {
      try {
        await voiceForgeApi.createCharacter(projectId, { name });
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "创建角色失败" });
      }
    },
    [projectId, load, dispatch],
  );

  const handleDeleteCharacter = useCallback(
    async (id: string) => {
      try {
        await voiceForgeApi.deleteCharacter(id);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "删除角色失败" });
      }
    },
    [load, dispatch],
  );

  const handleUpdateCharacter = useCallback(
    async (id: string, data: Record<string, unknown>) => {
      try {
        await voiceForgeApi.updateCharacter(id, data);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "更新角色失败" });
      }
    },
    [load, dispatch],
  );

  const handleClearAllCharacters = useCallback(async () => {
    try {
      await voiceForgeApi.clearCharacters(projectId);
      await load();
    } catch {
      dispatch({ type: "SET_ERROR", payload: "清空角色失败" });
    }
  }, [projectId, load, dispatch]);

  const handleAIExtractCharacters = useCallback(
    () => setAiCharacterOpen(true),
    [],
  );

  const handleBindVoice = useCallback((character: { id: string }) => {
    setBindTargetCharacterId(character.id);
    setBindVoiceOpen(true);
  }, []);

  const handleBatchVoiceDesign = useCallback(() => {
    setBatchVoiceDesignOpen(true);
  }, []);

  const handleBatchVoiceDesignSuccess = useCallback(() => {
    load();
  }, [load]);

  const handleProcessChapter = useCallback(
    (chapter: { id: string; title: string }) => {
      dispatch({ type: "SET_CHAPTER", payload: chapter.id });
      setProcessChapter({ id: chapter.id, name: chapter.title });
      setProcessChapterOpen(true);
    },
    [dispatch],
  );

  const handleProcessRuleSplit = useCallback(() => {
    if (!processChapter) return;
    const text = sentences
      .filter((s) => s.chapter_id === processChapter.id)
      .map((s) => s.edited_text || s.text)
      .join("\n");
    setProcessChapterOpen(false);
    setRuleSplitText(text);
    setRuleSplitOpen(true);
  }, [processChapter, sentences]);

  const handleProcessAIDialogue = useCallback(() => {
    setProcessChapterOpen(false);
    setAiDialogueOpen(true);
  }, []);

  const handleApplyRuleSplit = useCallback(
    async (splitSentences: string[]) => {
      if (!processChapter) return;
      dispatch({ type: "SET_BUSY", payload: "rule-split" });
      try {
        const chapterSentenceIds = sentences
          .filter((s) => s.chapter_id === processChapter.id)
          .map((s) => s.id);
        if (chapterSentenceIds.length) {
          await voiceForgeApi.deleteSentences(projectId, chapterSentenceIds);
        }
        await voiceForgeApi.deleteChapter(processChapter.id);
        await voiceForgeApi.applyTextPlan(projectId, {
          chapters: [
            {
              title: processChapter.name,
              sentences: splitSentences.map((text) => ({ text })),
            },
          ],
        });
        setRuleSplitOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "规则断句失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [processChapter, sentences, projectId, load, dispatch],
  );

  /* ════════════════════════════════════════════════════════════════════
     VoiceTree callbacks
     ════════════════════════════════════════════════════════════════════ */

  const handlePlayVoice = useCallback(
    (_voiceId: string, storageKey: string) => {
      audioRef.current?.pause();
      const url = voiceForgeApi.voiceFileUrl(_voiceId, storageKey);
      const audio = new Audio(url);
      audio.play().catch(() => {});
      audioRef.current = audio;
    },
    [],
  );

  /* ════════════════════════════════════════════════════════════════════
     Dialog apply handlers
     ════════════════════════════════════════════════════════════════════ */

  // TextCleanModal
  const handleTextCleanApply = useCallback(
    async (data: {
      chars_to_remove: string;
      wildcards: Array<{ open: string; close: string }>;
      find_text: string;
      replace_text: string;
      delete_empty: boolean;
    }) => {
      dispatch({ type: "SET_BUSY", payload: "text-clean" });
      try {
        await voiceForgeApi.cleanApply(projectId, {
          chars_to_remove: data.chars_to_remove || undefined,
          wildcards: data.wildcards.length ? data.wildcards : undefined,
          find_text: data.find_text || undefined,
          replace_text: data.replace_text || undefined,
          chapter_id: selectedChapterId || undefined,
          delete_empty: data.delete_empty,
        });
        setTextCleanOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "文本清洗失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, selectedChapterId, load, dispatch],
  );

  // SentenceSplitModal
  const handleSentenceSplitApply = useCallback(
    async (symbols: string[]) => {
      dispatch({ type: "SET_BUSY", payload: "sentence-split" });
      try {
        await voiceForgeApi.splitApply(projectId, {
          symbols,
          chapter_id: selectedChapterId || undefined,
        });
        setSentenceSplitOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "句子拆分失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, selectedChapterId, load, dispatch],
  );

  // BatchRoleModal
  const handleBatchRoleApply = useCallback(
    async (characterId: string) => {
      if (!selectedIds.size) return;
      dispatch({ type: "SET_BUSY", payload: "batch-role" });
      try {
        await voiceForgeApi.bulkUpdateSentences(projectId, {
          sentence_ids: [...selectedIds],
          character_id: characterId,
        });
        setBatchRoleOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "批量分配角色失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, selectedIds, load, dispatch],
  );

  // ImportTextModal
  const handleImportTextApply = useCallback(
    async (text: string, chapterTitle: string) => {
      dispatch({ type: "SET_BUSY", payload: "import" });
      try {
        await voiceForgeApi.importText(projectId, text);
        setImportTextOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "导入文本失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, load, dispatch],
  );

  const handleImportFileApply = useCallback(
    async (file: File, type: "txt" | "subtitle") => {
      dispatch({ type: "SET_BUSY", payload: "import" });
      try {
        await voiceForgeApi.importContent(projectId, type, file);
        setImportTextOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "导入文件失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, load, dispatch],
  );

  // ChapterExportModal
  const handleChapterExportApply = useCallback(
    async (data: {
      format: string;
      bitrate: string;
      normalize_volume: boolean;
      denoise: boolean;
      global_speed: number;
    }) => {
      if (!selectedChapterId) {
        dispatch({
          type: "SET_ERROR",
          payload: "请先选择一个章节",
        });
        return;
      }
      dispatch({ type: "SET_BUSY", payload: "chapter-export" });
      try {
        await voiceForgeApi.chapterExport(projectId, {
          chapter_id: selectedChapterId,
          ...data,
        });
        setChapterExportOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "章节导出失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, selectedChapterId, load, dispatch],
  );

  // AIDialogueModal
  const handleAIDialogueApply = useCallback(
    async (
      dialogues: Array<{
        speaker: string;
        text: string;
        emotion: string;
        tone_description: string;
      }>,
    ) => {
      dispatch({ type: "SET_BUSY", payload: "ai-dialogue" });
      try {
        // Use the dialogue results as a text plan
        const sentences = dialogues.map((d) => ({
          text: d.text,
          character_name: d.speaker,
          emotion: d.emotion,
          tone_description: d.tone_description,
        }));
        await voiceForgeApi.applyTextPlan(projectId, {
          chapter_title: "AI对话",
          sentences,
        });
        setAiDialogueOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "应用AI对话失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, load, dispatch],
  );

  // AICharacterModal
  const handleAICharacterApply = useCallback(
    async (
      charactersList: Array<{
        name: string;
        gender?: string;
        personality?: string;
      }>,
    ) => {
      dispatch({ type: "SET_BUSY", payload: "ai-character" });
      try {
        const mapped = charactersList.map((c) => ({
          name: c.name,
          character_type: c.gender,
          note: c.personality,
        }));
        await voiceForgeApi.applyAnalysisCharacters(projectId, mapped);
        setAiCharacterOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "应用AI角色失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, load, dispatch],
  );

  // AddCharacterModal
  const handleAddCharacterApply = useCallback(
    async (data: {
      name: string;
      gender?: string;
      age_range?: string;
      personality?: string;
      voice_design_desc?: string;
    }) => {
      dispatch({ type: "SET_BUSY", payload: "add-character" });
      try {
        await voiceForgeApi.createCharacter(projectId, {
          name: data.name,
          character_type: data.gender,
          note: [data.age_range, data.personality]
            .filter(Boolean)
            .join(" · "),
        });
        setAddCharacterOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "添加角色失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [projectId, load, dispatch],
  );

  // BindVoiceModal
  const handleBindVoiceApply = useCallback(
    async (characterId: string, voiceId: string) => {
      dispatch({ type: "SET_BUSY", payload: "bind-voice" });
      try {
        await voiceForgeApi.updateCharacter(characterId, {
          voice_profile_id: voiceId,
        });
        setBindVoiceOpen(false);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "绑定音色失败" });
      } finally {
        dispatch({ type: "SET_BUSY", payload: "" });
      }
    },
    [load, dispatch],
  );

  // ExportedAudioModal
  const handleDeleteExport = useCallback(
    async (id: string) => {
      try {
        await voiceForgeApi.deleteExport(id);
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "删除导出失败" });
      }
    },
    [load, dispatch],
  );

  // EditOriginalModal
  const handleEditOriginalSave = useCallback(
    async (text: string) => {
      try {
        if (selectedChapterId) {
          await voiceForgeApi.updateChapter(selectedChapterId, { title: text });
        }
        // Also update all sentences in the chapter
        for (const s of shownSentences) {
          await voiceForgeApi.updateSentence(s.id, {
            edited_text: text,
            version: s.version,
          });
        }
        await load();
      } catch {
        dispatch({ type: "SET_ERROR", payload: "保存原文失败" });
      }
    },
    [selectedChapterId, shownSentences, load, dispatch],
  );

  /* ── Cleanup audio on unmount ──────────────────────────────────── */
  // (handled via DubbingProvider's cleanup)

  /* ════════════════════════════════════════════════════════════════════
     Derived values for sub-components
     ════════════════════════════════════════════════════════════════════ */

  const chapterName = useMemo(() => {
    if (!selectedChapterId) return "全部句子";
    return chapters.find((c) => c.id === selectedChapterId)?.title ?? "章节";
  }, [selectedChapterId, chapters]);

  const selectedChapter = useMemo(
    () =>
      selectedChapterId
        ? chapters.find((c) => c.id === selectedChapterId)
        : null,
    [selectedChapterId, chapters],
  );

  const currentEngineId = useMemo(() => {
    const matched =
      capabilities.find((c) => c.name === engine) ??
      capabilities.find((c) => c.id === engine);
    return matched?.id ?? engine;
  }, [capabilities, engine]);

  /* ════════════════════════════════════════════════════════════════════
     Render
     ════════════════════════════════════════════════════════════════════ */

  return (
    <div className="flex h-full w-full flex-col">
      {/* ── 固定顶栏（sticky + 玻璃） ──────────────────────────────── */}
      <PageHeader
        sticky
        compact
        tone="ai"
        icon={Music2}
        title={project?.name || "配音台"}
        detail="文本配音制作台 · 章节、角色、句子、批量合成与导出"
        hideTitle
        breadcrumbs={[
          { label: project?.name || "配音台" },
        ]}
      />

      {/* ── Main workspace (3-panel layout) ────────────────────────── */}
      <div className="flex-1 min-h-0">
        <DubbingLayout
          left={
            <ChapterPanel
              projectName={project?.name || ""}
              chapters={chapters}
              selectedChapterId={selectedChapterId}
              onSelectChapter={(id) =>
                dispatch({ type: "SET_CHAPTER", payload: id })
              }
              onImportText={handleImportText}
              onEditOriginal={handleEditOriginal}
              onRuleSplitChapters={handleRuleSplitChapters}
              onAISplitChapters={handleAISplitChapters}
              onCreateChapter={handleCreateChapter}
              onDeleteChapter={handleDeleteChapter}
              onUpdateChapterText={handleUpdateChapterText}
              onProcessChapter={handleProcessChapter}
              sentences={sentences}
            />
          }
          center={
            <>
              <DubbingToolbar
                selectedCount={selectedIds.size}
                totalCount={shownSentences.length}
                engine={engine}
                engines={capabilities.map((c) => ({ id: c.id, name: c.name }))}
                voiceControlMode={voiceControlMode}
                defaultGap={defaultGap}
                onSelectAll={handleSelectAll}
                onDelete={handleDelete}
                onAIDialogue={handleToolbarAIDialogue}
                onTextClean={handleToolbarTextClean}
                onSentenceSplit={handleToolbarSentenceSplit}
                onBatchRole={handleToolbarBatchRole}
                onBatchGenerate={handleBatchGenerate}
                onCompleteGenerate={handleCompleteGenerate}
                onPreviewSection={handleToolbarPreviewSection}
                onExportChapter={handleToolbarExportChapter}
                onBrowseExports={handleToolbarBrowseExports}
                onEngineChange={handleEngineChange}
                onVoiceControlModeChange={handleVoiceControlModeChange}
                onGapChange={handleGapChange}
                onEngineSettings={handleEngineSettings}
                busy={busy}
              />
              <SentenceList
                sentences={shownSentences}
                characters={characters}
                emotionTags={emotionTags}
                selectedIds={selectedIds}
                isPlaying={busy === ""}
                playingId={playingId}
                onToggleSelect={handleToggleSelect}
                onUpdateSentence={handleUpdateSentence}
                onPlay={handlePlaySentence}
                onRegenerate={handleRegenerateSentence}
                onAddAfter={handleAddAfter}
                onReorder={handleReorder}
                queueUpdate={handleQueueUpdate}
              />
            </>
          }
          right={
            <>
              <CharacterPanel
                characters={characters}
                voices={voices}
                onCreateCharacter={handleCreateCharacter}
                onDeleteCharacter={handleDeleteCharacter}
                onUpdateCharacter={handleUpdateCharacter}
                onClearAll={handleClearAllCharacters}
                onAIExtract={handleAIExtractCharacters}
                onBindVoice={handleBindVoice}
                onBatchVoiceDesign={handleBatchVoiceDesign}
              />
              <VoiceTree
                voices={voices}
                onPlayVoice={handlePlayVoice}
              />
            </>
          }
        />
      </div>

      {/* ── All Dialog components ──────────────────────────────────── */}
      <TextCleanModal
        open={textCleanOpen}
        onOpenChange={setTextCleanOpen}
        onApply={handleTextCleanApply}
        busy={busy === "text-clean"}
      />

      <SentenceSplitModal
        open={sentenceSplitOpen}
        onOpenChange={setSentenceSplitOpen}
        onApply={handleSentenceSplitApply}
        busy={busy === "sentence-split"}
      />

      <BatchRoleModal
        open={batchRoleOpen}
        onOpenChange={setBatchRoleOpen}
        characters={characters}
        selectedCount={selectedIds.size}
        onApply={handleBatchRoleApply}
      />

      <ImportTextModal
        open={importTextOpen}
        onOpenChange={setImportTextOpen}
        onImportText={handleImportTextApply}
        onImportFile={handleImportFileApply}
        busy={busy === "import"}
      />

      <ChapterExportModal
        open={chapterExportOpen}
        onOpenChange={setChapterExportOpen}
        onExport={handleChapterExportApply}
        busy={busy === "chapter-export"}
      />

      <AIDialogueModal
        open={aiDialogueOpen}
        onOpenChange={setAiDialogueOpen}
        projectId={projectId}
        text={shownSentences
          .map((s) => s.edited_text || s.text)
          .join("\n")}
        characterNames={characters.map((c) => c.name)}
        emotionTags={emotionTags}
        onApply={handleAIDialogueApply}
        busy={busy === "ai-dialogue"}
      />

      <AICharacterModal
        open={aiCharacterOpen}
        onOpenChange={setAiCharacterOpen}
        sentences={shownSentences}
        onExtract={handleAICharacterApply}
        busy={busy === "ai-character"}
      />

      <AddCharacterModal
        open={addCharacterOpen}
        onOpenChange={setAddCharacterOpen}
        onAdd={handleAddCharacterApply}
        busy={busy === "add-character"}
      />

      <BindVoiceModal
        open={bindVoiceOpen}
        onOpenChange={(v) => {
          setBindVoiceOpen(v);
          if (!v) setBindTargetCharacterId(null);
        }}
        voices={voices}
        onBind={(voiceId) => {
          if (bindTargetCharacterId) {
            handleBindVoiceApply(bindTargetCharacterId, voiceId);
          }
        }}
      />

      <PreviewSectionModal
        open={previewSectionOpen}
        onOpenChange={setPreviewSectionOpen}
        projectId={projectId}
        chapterName={chapterName}
        sentences={shownSentences}
        defaultGap={defaultGap}
        onRegenerateSentence={handleRegenerateSentence}
      />

      <ExportedAudioModal
        open={exportedAudioOpen}
        onOpenChange={setExportedAudioOpen}
        projectId={projectId}
        exports={exports}
        onDelete={handleDeleteExport}
      />

      <EditOriginalModal
        open={editOriginalOpen}
        onOpenChange={setEditOriginalOpen}
        chapterName={editChapterName}
        initialText={editChapterText}
        onSave={handleEditOriginalSave}
      />
      <RuleChapterSplitModal
        open={ruleChapterSplitOpen}
        textContent={ruleSplitText}
        onClose={() => setRuleChapterSplitOpen(false)}
        onApply={handleApplyRuleChapters}
      />

      <AIChapterSplitModal
        open={aiChapterSplitOpen}
        onOpenChange={setAiChapterSplitOpen}
        projectId={projectId}
        textContent={allText}
        onApply={handleApplyAIChapters}
      />

      <EngineSettingsModal
        open={engineSettingsOpen}
        onOpenChange={setEngineSettingsOpen}
        currentEngine={currentEngineId}
        onSaved={() => {
          void load();
        }}
      />

      <ProcessChapterModal
        open={processChapterOpen}
        onOpenChange={setProcessChapterOpen}
        chapterName={processChapter?.name ?? ""}
        onRuleSplit={handleProcessRuleSplit}
        onAIDialogue={handleProcessAIDialogue}
      />

      <RuleSplitModal
        open={ruleSplitOpen}
        onOpenChange={setRuleSplitOpen}
        textContent={ruleSplitText}
        onApplySplit={handleApplyRuleSplit}
      />

      <BatchVoiceDesignDialog
        open={batchVoiceDesignOpen}
        onOpenChange={setBatchVoiceDesignOpen}
        characters={characters}
        capabilities={capabilities}
        onSuccess={handleBatchVoiceDesignSuccess}
      />
    </div>
  );
}
