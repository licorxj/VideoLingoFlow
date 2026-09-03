import client from "./client";

export type VoiceForgeProject = {
  id: string;
  name: string;
  description: string;
  status: string;
  source_language: string;
  target_language: string;
  default_interface_id?: string;
  default_voice_id?: string;
  default_speed: number;
  version: number;
  sentence_count?: number;
  done_count?: number;
  pending_count?: number;
  generating_count?: number;
  error_count?: number;
  active_task_count?: number;
  audio_duration?: number;
  updated_at: string;
};

export type VoiceForgeDashboard = {
  overview: {
    project_count: number;
    sentence_total: number;
    sentence_pending: number;
    sentence_generating: number;
    sentence_done: number;
    sentence_error: number;
    task_queued: number;
    task_running: number;
    task_failed: number;
    audio_duration_done: number;
  };
  project_statuses: Record<string, number>;
};

export type VoiceForgeSentence = {
  id: string;
  project_id: string;
  chapter_id?: string;
  order_index: number;
  text: string;
  edited_text?: string;
  character_id?: string;
  character_name?: string;
  voice_profile_id?: string;
  voice_name?: string;
  speed: number;
  pitch: number;
  volume: number;
  emotion: string;
  tone_description?: string;
  pause_after?: number;
  status: string;
  audio_storage_key?: string;
  audio_duration?: number;
  error_message?: string;
  version: number;
};

export type VoiceForgeTask = { id: string; task_type: string; status: string; progress: number; error_message?: string; created_at: string; output?: Record<string, unknown> };

export type VoiceForgeProjectProgress = {
  total: number;
  done: number;
  generating: number;
  queued: number;
  error: number;
  in_flight: number;
  concurrency: number;
  progress_pct: number;
  eta_seconds: number | null;
};

export type VoiceForgeProgressMessage = {
  type: "voiceforge.progress";
  project_id: string;
  summary: VoiceForgeProjectProgress;
  sentences: Array<{ id: string; status: string; error_message?: string; audio_storage_key?: string; audio_duration?: number }>;
  tasks: VoiceForgeTask[];
};
export type VoiceForgeExport = { id: string; export_type: string; storage_key: string; file_name: string; status: string; task_id?: string; format?: string; error_message?: string; created_at: string };

export type VoiceForgeVoice = {
  id: string;
  name: string;
  display_name: string;
  interface_id?: string;
  voice_id?: string;
  mode: string;
  language: string;
  tags: string[];
  description: string;
  status: string;
  reference_storage_key?: string;
  preview_storage_key?: string;
  sample_storage_key?: string;
  preview_text?: string;
  params?: Record<string, unknown>;
  gender?: string;
  voice_age?: string;
  voice_pitch?: string;
  dialect?: string;
  voice_group?: string;
  is_cloned?: boolean;
  is_builtin?: boolean;
  design_text?: string;
  emotions?: Array<{ name: string; audio_path?: string; text?: string; engine?: string; instruct?: string }>;
};

export type VoiceForgeCapability = {
  id: string;
  name: string;
  type: string;
  modes: Record<string, { enabled?: boolean }>;
  voice_options: string[];
  default_voice?: string;
};

export type VoiceForgeEmotionTag = { id: string; name: string; description: string; color?: string; sort_order: number };
export type VoiceForgeEmotionTask = { id: string; status: string; progress: number; error_message?: string; output?: { emotion?: string; text?: string; instruct?: string; interface_id?: string; storage_key?: string; duration?: number } };
export type VoiceForgeEmotionSuggestion = { emotion: string; text: string; instruct: string };

export type VoiceForgeAsset = {
  id: string;
  name: string;
  asset_type: string;
  category?: string;
  tags: string[];
  file_name: string;
  file_size?: number;
  duration?: number;
  description: string;
  external_path?: string;
  sample_rate?: number;
  channels?: number;
  format?: string;
  is_favorite?: boolean;
};

export type VoiceForgeAssetCategory = {
  id: string;
  name: string;
  label: string;
  asset_type: string;
  sort_order: number;
  count: number;
};

export type VoiceForgeAssetTag = { id: string; name: string; usage_count: number };

export type OnlineSoundItem = {
  name: string;
  short_description: string;
  audio_url: string;
  id: string;
  labels: string[];
};

export type OnlineAssetItem = {
  title: string;
  slug?: string;
  page_url?: string;
  hero_cover_url?: string;
  question?: string;
  meta?: Record<string, unknown>;
  generation_suggestions?: string[];
  sounds: OnlineSoundItem[];
};

export type AssetListResult = {
  assets: VoiceForgeAsset[];
  total: number;
  page: number;
  page_size: number;
  type_counts: Record<string, number>;
};

export type VoiceForgeAnalysis = {
  summary?: string;
  characters?: Array<{ name: string; character_type?: string; note?: string }>;
};

export const voiceForgeApi = {
  health: () => client.get("/api/voiceforge/health"),
  dashboard: () => client.get("/api/voiceforge/dashboard"),
  projects: (search = "", status?: string) => client.get("/api/voiceforge/projects", { params: { search, status } }),
  getProject: (projectId: string) => client.get(`/api/voiceforge/projects/${projectId}`),
  createProject: (data: Partial<VoiceForgeProject>) => client.post("/api/voiceforge/projects", data),
  updateProject: (projectId: string, data: Partial<VoiceForgeProject> & { version: number }) => client.put(`/api/voiceforge/projects/${projectId}`, data),
  deleteProject: (projectId: string) => client.delete(`/api/voiceforge/projects/${projectId}`),
  chapters: (projectId: string) => client.get(`/api/voiceforge/projects/${projectId}/chapters`),
  createChapter: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/chapters`, data),
  batchCreateChapters: (projectId: string, data: { chapters: Array<{ title: string; text_content?: string }>; delete_existing?: boolean }) =>
    client.post(`/api/voiceforge/projects/${projectId}/chapters/batch`, data),
  updateChapter: (chapterId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/chapters/${chapterId}`, data),
  deleteChapter: (chapterId: string) => client.delete(`/api/voiceforge/chapters/${chapterId}`),
  characters: (projectId: string) => client.get(`/api/voiceforge/projects/${projectId}/characters`),
  createCharacter: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/characters`, data),
  updateCharacter: (characterId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/characters/${characterId}`, data),
  deleteCharacter: (characterId: string) => client.delete(`/api/voiceforge/characters/${characterId}`),
  sentences: (projectId: string) => client.get(`/api/voiceforge/projects/${projectId}/sentences`),
  updateSentence: (sentenceId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/sentences/${sentenceId}`, data),
  bulkUpdateSentences: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/sentences/bulk-update`, data),
  deleteSentences: (projectId: string, sentenceIds: string[]) => client.delete(`/api/voiceforge/projects/${projectId}/sentences`, { params: { sentence_ids: sentenceIds } }),
  importText: (projectId: string, text: string) => client.post(`/api/voiceforge/projects/${projectId}/import-text`, { text }),
  importContent: (projectId: string, mode: "subtitle" | "txt" | "paste", file?: File, text = "") => {
    const form = new FormData();
    form.append("mode", mode);
    if (file) form.append("file", file);
    if (text) form.append("text", text);
    return client.post(`/api/voiceforge/projects/${projectId}/import-content`, form);
  },
  cleanPreview: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/text/clean-preview`, data),
  splitPreview: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/text/split-preview`, data),
  aiSplitPreview: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/text/ai-split`, data, { timeout: 180000 }),
  aiDialoguePreview: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/text/ai-dialogue`, data, { timeout: 180000 }),
  aiChapterPreview: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/text/ai-chapters`, data, { timeout: 180000 }),
  applyTextPlan: (projectId: string, data: Record<string, unknown>) => client.post(`/api/voiceforge/projects/${projectId}/text/apply`, data),
  synthesize: (sentenceId: string, interfaceId?: string) =>
    client.post(
      `/api/voiceforge/sentences/${sentenceId}/synthesize` +
        (interfaceId ? `?interface_id=${encodeURIComponent(interfaceId)}` : ""),
    ),
  synthesizeProject: (
    projectId: string,
    data: { sentence_ids?: string[]; retry_failed?: boolean; interface_id?: string } = {},
  ) => client.post(`/api/voiceforge/projects/${projectId}/synthesize`, data),
  tasks: (projectId: string, activeOnly = false) => client.get(`/api/voiceforge/projects/${projectId}/tasks`, { params: { active_only: activeOnly } }),
  cancelTask: (taskId: string) => client.post(`/api/voiceforge/tasks/${taskId}/cancel`),
  retryTask: (taskId: string) => client.post(`/api/voiceforge/tasks/${taskId}/retry`),
  analyze: (projectId: string) => client.post(`/api/voiceforge/projects/${projectId}/analyze`),
  applyAnalysisCharacters: (projectId: string, characters: Array<{ name: string; character_type?: string; note?: string }>) => client.post(`/api/voiceforge/projects/${projectId}/analysis-characters`, { characters }),
  voices: (search = "", filters: Record<string, string | undefined> = {}) => client.get("/api/voiceforge/voices", { params: { search, ...filters } }),
  batchGroupVoices: (voiceIds: string[], group: string) => client.post("/api/voiceforge/voices/batch-group", { voice_ids: voiceIds, group }),
  createVoice: (data: Record<string, unknown>) => client.post("/api/voiceforge/voices", data),
  updateVoice: (voiceId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/voices/${voiceId}`, data),
  deleteVoice: (voiceId: string) => client.delete(`/api/voiceforge/voices/${voiceId}`),
  duplicateVoice: (voiceId: string) => client.post(`/api/voiceforge/voices/${voiceId}/duplicate`),
  capabilities: () => client.get("/api/voiceforge/tts-capabilities"),
  uploadVoiceReference: (file: File) => { const form = new FormData(); form.append("file", file); return client.post("/api/voiceforge/voices/reference-audio", form); },
  previewVoice: (data: Record<string, unknown>) => client.post("/api/voiceforge/voices/preview", data),
  previewVoiceBatch: (data: Record<string, unknown>) => client.post("/api/voiceforge/voices/preview-batch", data),
  cleanupVoicePreviews: (storageKeys: string[]) => client.post("/api/voiceforge/voices/preview-cleanup", { storage_keys: storageKeys }),
  aiFillVoiceParams: (data: { intent: string; language: string; gender: string; age: string; pitch_label: string; dialect: string }) => client.post("/api/voiceforge/voices/ai-fill-params", data),
  voicePreviewUrl: (storageKey: string) => `/api/voiceforge/voices/preview-file?storage_key=${encodeURIComponent(storageKey)}`,
  voiceFileUrl: (voiceId: string, storageKey: string) => `/api/voiceforge/voices/${voiceId}/file?storage_key=${encodeURIComponent(storageKey)}`,
  emotionTags: () => client.get("/api/voiceforge/emotion-tags"),
  createEmotionTag: (data: Record<string, unknown>) => client.post("/api/voiceforge/emotion-tags", data),
  updateEmotionTag: (tagId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/emotion-tags/${tagId}`, data),
  deleteEmotionTag: (tagId: string) => client.delete(`/api/voiceforge/emotion-tags/${tagId}`),
  fillVoiceEmotions: (voiceId: string, data: { emotions: string[]; character_background?: string; interface_id: string }) => client.post<{ tasks: VoiceForgeEmotionSuggestion[] }>(`/api/voiceforge/voices/${voiceId}/emotions/llm-fill`, data, { timeout: 180000 }),
  generateVoiceEmotions: (voiceId: string, tasks: Array<{ emotion: string; text: string; instruct: string; interface_id: string }>) => client.post<{ tasks: Array<{ task_id: string; emotion: string }> }>(`/api/voiceforge/voices/${voiceId}/emotions/generate`, { tasks }),
  voiceEmotionTasks: (voiceId: string) => client.get(`/api/voiceforge/voices/${voiceId}/emotions/tasks`),
  saveVoiceEmotions: (voiceId: string, taskIds: string[]) => client.post(`/api/voiceforge/voices/${voiceId}/emotions/save`, { task_ids: taskIds }),
  assets: (filters: { asset_type?: string; category?: string; tag?: string; is_favorite?: boolean; min_duration?: number; max_duration?: number; search?: string; page?: number; page_size?: number } = {}) => client.get<AssetListResult>("/api/voiceforge/assets", { params: filters }),
  assetTypeCounts: () => client.get<Record<string, number>>("/api/voiceforge/assets/type-counts"),
  createAssetFromPath: (data: { name?: string; asset_type: string; category?: string; tags?: string[]; description?: string; path: string }) => client.post(`/api/voiceforge/assets`, data),
  assetCategories: (assetType?: string) => client.get<{ categories: VoiceForgeAssetCategory[] }>("/api/voiceforge/assets/categories", { params: assetType ? { asset_type: assetType } : {} }),
  createAssetCategory: (data: { name: string; label: string; asset_type: string; sort_order?: number }) => client.post(`/api/voiceforge/assets/categories`, data),
  updateAssetCategory: (categoryId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/assets/categories/${categoryId}`, data),
  deleteAssetCategory: (categoryId: string) => client.delete(`/api/voiceforge/assets/categories/${categoryId}`),
  assetTags: (search = "", assetType?: string) => client.get<{ tags: VoiceForgeAssetTag[] }>("/api/voiceforge/assets/tags", { params: { search, asset_type: assetType } }),
  createAssetTag: (name: string) => client.post(`/api/voiceforge/assets/tags`, { name }),
  deleteAssetTag: (tagId: string) => client.delete(`/api/voiceforge/assets/tags/${tagId}`),
  deleteAsset: (assetId: string) => client.delete(`/api/voiceforge/assets/${assetId}`),
  updateAsset: (assetId: string, data: Record<string, unknown>) => client.put(`/api/voiceforge/assets/${assetId}`, data),
  deleteAssets: (assetIds: string[]) => client.delete("/api/voiceforge/assets", { params: { asset_ids: assetIds } }),
  assetStreamUrl: (assetId: string) => `/api/voiceforge/assets/${assetId}/stream`,
  fileDialog: (data: { type?: string; title?: string; filetypes?: Array<[string, string]>; multiple?: boolean }) => client.post<{ paths: string[]; path?: string; cancelled: boolean }>("/api/files/native-dialog", data),
  scanAudio: (path: string, recursive = false) => client.post<{ files: Array<{ name: string; path: string; size: number }> }>("/api/files/scan-audio", { path, recursive }),
  fileStreamUrl: (path: string) => `/api/files/stream?path=${encodeURIComponent(path)}`,
  onlineSearch: (params: { keyword?: string; source?: string; categoryUrl?: string }) =>
    client.post<{ items: OnlineAssetItem[] }>("/api/voiceforge/assets/online/search", {
      keyword: params.keyword || "", source: params.source || "elevenlabs", category_url: params.categoryUrl || "",
    }),
  onlineCategories: () =>
    client.get<{ tags: { name: string; url: string }[] }>("/api/voiceforge/assets/online/chinaz/categories"),
  onlineImport: (data: {
    name: string; asset_type: string; source_url: string; source_site?: string; source_id?: string;
    category?: string; tags?: string[]; description?: string; download?: boolean;
  }) => client.post<{ asset: VoiceForgeAsset; downloaded: boolean }>("/api/voiceforge/assets/online/import", data),
  onlineProxyUrl: (url: string) => `/api/voiceforge/assets/online/proxy?url=${encodeURIComponent(url)}`,
  srtUrl: (projectId: string) => `/api/voiceforge/projects/${projectId}/exports/srt`,
  audioZipUrl: (projectId: string) => `/api/voiceforge/projects/${projectId}/exports/audio-zip`,
  sentenceAudioUrl: (sentenceId: string) => `/api/voiceforge/sentences/${sentenceId}/audio`,
  exportMergedAudio: (projectId: string) => client.post(`/api/voiceforge/projects/${projectId}/exports/merged-audio`),
  createExport: (projectId: string, data: { export_type: "merged_audio" | "srt" | "sentence_zip"; format?: "wav" | "mp3" | "flac"; chapter_id?: string; gap_seconds?: number }) => client.post(`/api/voiceforge/projects/${projectId}/exports`, data),
  exports: (projectId: string) => client.get(`/api/voiceforge/projects/${projectId}/exports`),
  exportDownloadUrl: (exportId: string) => `/api/voiceforge/exports/${exportId}/download`,
  deleteExport: (exportId: string) => client.delete(`/api/voiceforge/exports/${exportId}`),

  // New endpoints
  reorderSentences: (projectId: string, orderedIds: string[]) =>
    client.put(`/api/voiceforge/projects/${projectId}/sentences/reorder`, { ordered_ids: orderedIds }),
  cleanApply: (projectId: string, data: { chars_to_remove?: string; wildcards?: Array<{open: string; close: string}>; find_text?: string; replace_text?: string; chapter_id?: string; delete_empty?: boolean }) =>
    client.post(`/api/voiceforge/projects/${projectId}/text/clean-apply`, data),
  splitApply: (projectId: string, data: { symbols: string[]; chapter_id?: string }) =>
    client.post(`/api/voiceforge/projects/${projectId}/text/split-apply`, data),
  chapterExport: (projectId: string, data: { chapter_id: string; format?: string; bitrate?: string; normalize_volume?: boolean; denoise?: boolean; global_speed?: number }) =>
    client.post(`/api/voiceforge/projects/${projectId}/exports/chapter`, data),
  clearCharacters: (projectId: string) =>
    client.delete(`/api/voiceforge/projects/${projectId}/characters/clear`),
};
