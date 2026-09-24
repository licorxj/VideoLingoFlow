// -*- coding: utf-8 -*-
/** Toonflow 创作画布 API 封装（/api/tf/*）。 */
import client from "@/api/client";

export interface TfProject {
  id: number;
  name: string;
  cover: string;
  introduce: string;
  artStyle: string;
  directorManual: string;
  mode: string;
  videoRatio: string;
  imageQuality: string;
  videoResolution: string;
  storyStyle: string;
  createTime: number;
  updateTime: number;
}

export interface TfSkill {
  attribution: string;
  file: string;
  name: string;
  description: string;
}

export interface TfSkillLibrary {
  dir: string;
  mdFiles: number;
  children: string[];
}

export interface TfPrompt {
  id: number;
  name: string;
  type: string;
  effective: string;
  useData: string;
  data: string;
}

export interface TfAgentSlot {
  id: number;
  key: string;
  name: string;
  desc: string;
  temperature: number;
  maxOutputTokens: number;
  disabled: boolean;
}

export interface ProjectCreatePayload {
  name: string;
  introduce?: string;
  artStyle?: string;
  directorManual?: string;
  mode?: string;
  videoRatio?: string;
  imageQuality?: string;
  videoResolution?: string;
  storyStyle?: string;
}

export interface TfArtStyle {
  value: string;
  label: string;
  desc: string;
}

export interface TfVoiceItem {
  id: string;
  name: string;
  displayName: string;
  gender: string;
  age: string;
  description: string;
  designText: string;
  previewUrl: string;
}

export interface TfSnapshot {
  project: { id: number; name: string; introduce: string; artStyle: string; videoRatio: string; imageQuality: string; mode: string };
  chapters: { id: number; reel: string; chapter: string; event: string; eventState: number; chars: number }[];
  scripts: { id: number; title: string; extractState: number; chars: number }[];
  assets: { id: number; name: string; type: string; describe: string; prompt: string; assetsId: number | null; imageId: number | null; imageUrl: string }[];
  storyboards: {
    id: number; orderNo: number; videoDesc: string; prompt: string; videoPrompt: string;
    assetIds: string[]; duration: number; track: string; imageUrl: string; state: string;
    shouldGenerateImage: boolean; videoUrl: string;
  }[];
  videos: { id: number; storyboardId: number | null; prompt: string; candidates: { id: number; url: string; state: string; duration: number; selected: boolean }[] }[];
  bindings: { id: number; assetId: number; assetName: string; audioId: string;
              voiceName?: string; gender?: string; designText?: string; previewUrl?: string }[];
  /** 后台任务活动计数（type → 生成中数量），执行状态条数据源 */
  activities: Record<string, number>;
}

export const toonflowApi = {
  system: () => client.get("/api/tf/system"),
  listProjects: () => client.get<{ projects: TfProject[] }>("/api/tf/projects"),
  createProject: (data: ProjectCreatePayload) => client.post<{ success: boolean; project: TfProject }>("/api/tf/projects", data),
  getProject: (id: number) => client.get<{ project: TfProject }>(`/api/tf/projects/${id}`),
  updateProject: (id: number, data: Partial<ProjectCreatePayload>) => client.put<{ success: boolean; project: TfProject }>(`/api/tf/projects/${id}`, data),
  deleteProject: (id: number) => client.delete(`/api/tf/projects/${id}`),
  listArtStyles: () => client.get<{ styles: TfArtStyle[] }>("/api/tf/art-styles"),
  listStoryStyles: () => client.get<{ styles: TfArtStyle[] }>("/api/tf/story-styles"),
  listSkills: () => client.get<{ skills: TfSkill[] }>("/api/tf/skills"),
  listSkillLibraries: () => client.get<{ libraries: TfSkillLibrary[] }>("/api/tf/skills/libraries"),
  listPrompts: () => client.get<{ prompts: TfPrompt[] }>("/api/tf/prompts"),
  updatePrompt: (id: number, useData: string) => client.put(`/api/tf/prompts/${id}`, { useData }),
  listAgents: () => client.get<{ agents: TfAgentSlot[] }>("/api/tf/agents"),

  // ---- 创作画布：快照与流水线 ----
  getCanvas: (projectId: number) => client.get<TfSnapshot>(`/api/tf/canvas/${projectId}`),
  addNovels: (projectId: number, chapters: { reel?: string; chapter: string; chapterData: string }[]) =>
    client.post(`/api/tf/projects/${projectId}/novels`, { chapters, generate_events: true }),
  makeScriptDraft: (projectId: number) => client.post(`/api/tf/projects/${projectId}/scripts/draft`),
  extractScriptAssets: (scriptId: number) => client.post(`/api/tf/scripts/${scriptId}/extract-assets`),
  runStage: (projectId: number, action: string, body: Record<string, unknown> = {}) => {
    const routes: Record<string, string> = {
      table: `/api/tf/projects/${projectId}/storyboards/table`,
      prompts: `/api/tf/projects/${projectId}/storyboards/prompts`,
      boardImages: `/api/tf/projects/${projectId}/storyboards/images`,
      videoPrompts: `/api/tf/projects/${projectId}/videos/prompts`,
      videos: `/api/tf/projects/${projectId}/videos/generate`,
      dubbing: `/api/tf/projects/${projectId}/dubbing/bind`,
    };
    const url = routes[action];
    if (!url) return Promise.reject(new Error(`未知流水线操作: ${action}`));
    return client.post(url, { ids: [], force: false, ...body });
  },
  generateAssetImages: (projectId: number, ids: number[]) =>
    client.post(`/api/tf/projects/${projectId}/assets/images`, { ids }),
  regenerateAssetImage: (assetId: number) => client.post(`/api/tf/assets/${assetId}/images/regenerate`),
  deleteAsset: (assetId: number) => client.delete(`/api/tf/assets/${assetId}`),
  regenerateStoryboardImage: (storyboardId: number) => client.post(`/api/tf/storyboards/${storyboardId}/image/regenerate`),
  deleteStoryboard: (storyboardId: number) => client.delete(`/api/tf/storyboards/${storyboardId}`),
  deleteVideo: (videoId: number) => client.delete(`/api/tf/videos/${videoId}`),
  selectTrackVideo: (trackId: number, videoId: number) => client.post(`/api/tf/tracks/${trackId}/select`, { ids: [videoId] }),
  // ---- 卡片手动控制：编辑 / 删除 / 单条重跑 ----
  getNovel: (novelId: number) => client.get<{ id: number; reel: string; chapter: string; chapterData: string; event: string; eventState: number }>(`/api/tf/novels/${novelId}`),
  getScript: (scriptId: number) => client.get<{ id: number; title: string; scriptData: string; extractState: number }>(`/api/tf/scripts/${scriptId}`),
  updateNovel: (novelId: number, data: { chapter?: string; chapterData?: string; reel?: string }) =>
    client.put(`/api/tf/novels/${novelId}`, data),
  deleteNovel: (novelId: number) => client.delete(`/api/tf/novels/${novelId}`),
  extractNovelEvent: (novelId: number) => client.post(`/api/tf/novels/${novelId}/extract-event`),
  updateScript: (scriptId: number, data: { title?: string; scriptData?: string }) =>
    client.put(`/api/tf/scripts/${scriptId}`, data),
  deleteScript: (scriptId: number) => client.delete(`/api/tf/scripts/${scriptId}`),
  updateAssetFields: (assetId: number, data: { name?: string; describe?: string; prompt?: string }) =>
    client.put(`/api/tf/assets/${assetId}`, data),
  updateStoryboardFields: (storyboardId: number, data: { videoDesc?: string; prompt?: string; videoPrompt?: string; duration?: number }) =>
    client.put(`/api/tf/storyboards/${storyboardId}`, data),
  generateStoryboardImage: (projectId: number, ids: number[]) =>
    client.post(`/api/tf/projects/${projectId}/storyboards/images`, { ids }),
  generateVideoForStoryboard: (projectId: number, storyboardId: number) =>
    client.post(`/api/tf/projects/${projectId}/videos/generate`, { ids: [storyboardId], force: true }),
  // ---- 角色音色：音色库 / 绑定 / 解绑 / 设计 ----
  listVoiceLibrary: (keyword = "") =>
    client.get<{ voices: TfVoiceItem[] }>("/api/tf/voice-library", { params: keyword ? { keyword } : {} }),
  bindRoleVoice: (assetId: number, audioId: string) =>
    client.post(`/api/tf/roles/${assetId}/bind`, { audioId }),
  unbindRoleVoice: (assetId: number) => client.post(`/api/tf/roles/${assetId}/unbind`),
  designRoleVoice: (assetId: number) => client.post(`/api/tf/roles/${assetId}/design-voice`),
  bindDubbing: (projectId: number) => client.post(`/api/tf/projects/${projectId}/dubbing/bind`),
};

export default toonflowApi;
