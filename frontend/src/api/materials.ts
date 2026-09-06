import client from "./client";

export type MaterialKind = "image" | "video" | "character" | "audio";

export type MaterialImage = {
  id: string;
  path: string;
  abs_path?: string;
  width: number | null;
  height: number | null;
  aspect_ratio: string;
  group_tags: string[];
  custom_tags: string[];
  description: string;
  created_at: string;
};

export type MaterialVideo = {
  id: string;
  path: string;
  abs_path?: string;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  group_tags: string[];
  custom_tags: string[];
  description: string;
  created_at: string;
};

export type MaterialCharacter = {
  id: string;
  name: string;
  tags: string[];
  gender: string;
  age: string;
  personality: string;
  occupation: string;
  aliases: string[];
  voice_design: string;
  voice_ref: string;
  images_dir: string;
  images_dir_abs?: string;
  origin_creation_id: string | null;
  created_at: string;
};

export type MaterialListResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  groups?: string[];
  tags?: string[];
};

export type MaterialSummary = { images: number; videos: number; characters: number; audio: number };

export type MaterialVoiceRecord = {
  id: string;
  name: string;
  display_name: string;
  gender?: string;
  voice_age?: string;
  voice_pitch?: string;
  dialect?: string;
  language?: string;
  tags?: string[];
  description?: string;
  design_text?: string;
  voice_group?: string;
  sample_storage_key?: string;
  preview_storage_key?: string;
  reference_storage_key?: string;
  is_cloned?: boolean;
};

export type MaterialQuery = { page?: number; page_size?: number; group?: string; tag?: string; search?: string };

/** 把素材路径(优先 abs_path)转换为后端文件流地址(带 Range 支持)。 */
export function materialPreviewUrl(path: string, absPath?: string): string {
  const target = absPath || path;
  return `/api/files/stream?path=${encodeURIComponent(target)}`;
}

export const materialsApi = {
  summary: () => client.get<MaterialSummary>("/api/materials/summary"),

  images: (params: MaterialQuery) => client.get<MaterialListResult<MaterialImage>>("/api/materials/images", { params }),
  uploadImage: (file: File, meta: { group_tags?: string; custom_tags?: string; description?: string }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("group_tags", meta.group_tags || "");
    form.append("custom_tags", meta.custom_tags || "");
    form.append("description", meta.description || "");
    return client.post<MaterialImage>("/api/materials/images", form);
  },
  updateImage: (id: string, data: Partial<Pick<MaterialImage, "group_tags" | "custom_tags" | "description" | "width" | "height" | "aspect_ratio">>) =>
    client.put<MaterialImage>(`/api/materials/images/${id}`, data),
  deleteImage: (id: string) => client.delete(`/api/materials/images/${id}`),

  videos: (params: MaterialQuery) => client.get<MaterialListResult<MaterialVideo>>("/api/materials/videos", { params }),
  uploadVideo: (file: File, meta: { group_tags?: string; custom_tags?: string; description?: string }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("group_tags", meta.group_tags || "");
    form.append("custom_tags", meta.custom_tags || "");
    form.append("description", meta.description || "");
    return client.post<MaterialVideo>("/api/materials/videos", form);
  },
  updateVideo: (id: string, data: Partial<Pick<MaterialVideo, "group_tags" | "custom_tags" | "description" | "width" | "height" | "duration_seconds">>) =>
    client.put<MaterialVideo>(`/api/materials/videos/${id}`, data),
  deleteVideo: (id: string) => client.delete(`/api/materials/videos/${id}`),

  characters: (params: MaterialQuery) => client.get<MaterialListResult<MaterialCharacter>>("/api/materials/characters", { params }),
  createCharacter: (data: Omit<MaterialCharacter, "id" | "created_at" | "origin_creation_id">) => client.post<MaterialCharacter>("/api/materials/characters", data),
  updateCharacter: (id: string, data: Partial<Omit<MaterialCharacter, "id" | "created_at" | "origin_creation_id">>) =>
    client.put<MaterialCharacter>(`/api/materials/characters/${id}`, data),
  deleteCharacter: (id: string) => client.delete(`/api/materials/characters/${id}`),

  // 按 ID 取单条素材详情(节点卡片预览/回查用)
  getImageById: (id: string) => client.get<MaterialImage>(`/api/materials/images/${id}`),
  getVideoById: (id: string) => client.get<MaterialVideo>(`/api/materials/videos/${id}`),
  getCharacterById: (id: string) => client.get<MaterialCharacter>(`/api/materials/characters/${id}`),
  /** 音色素材详情来自 voiceforge 音色库 */
  getVoiceRecord: (id: string) => client.get<MaterialVoiceRecord>(`/api/materials/voices/${id}`),
};
