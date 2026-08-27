import client from "./client";

export interface VideoGenModeConfig {
  enabled: boolean;
  endpoint: string;
}

export interface VideoGenModesMap {
  txt2video?: VideoGenModeConfig;
  img2video?: VideoGenModeConfig;
  flf2video?: VideoGenModeConfig;
  autovideo?: VideoGenModeConfig;
}

export interface VideoGenModelMeta {
  modes?: string[];                       // 支持的生成类型: txt2video / img2video / flf2video / autovideo
  price?: string;                         // 价格说明
  resolutions?: string[];                 // 支持的分辨率: 480P / 720P / 768P / 1080P
  durations?: number[];                   // 支持的时长(秒): 5 / 10 / 15 ...
  max_ref_images?: number;                // 最大参考图数
  max_ref_videos?: number;                // 最大参考视频数
  supports_audio?: boolean;               // 是否支持声音开关
  default_audio?: string;                 // 默认声音行为: model_default / on / off / keep_original
}

export interface VideoGenInterfaceConfig {
  api_url?: string;
  api_key?: string;
  sdk_package?: string;
  sdk_module?: string;
  sdk_function?: string;
  sdk_api_key?: string;
  sdk_extra_args?: Record<string, string>;
  default_model?: string;
  model_options?: string[];
  model_metadata?: Record<string, VideoGenModelMeta>;
  model_list_url?: string;
  model_list_key?: string;
  balance_endpoint?: string;
  modes?: VideoGenModesMap;
  custom_params?: { key: string; default: string; description: string }[];
  max_concurrent?: number;
  timeout?: number;
}

export interface VideoGenInterface {
  id: string;
  name: string;
  type: "sdk" | "openai_compatible";
  builtin: boolean;
  enabled: boolean;
  description: string;
  api_source_url?: string;
  model_docs_url?: string;
  balance?: number | string | null;
  config: VideoGenInterfaceConfig;
}

export interface VideoGenTestResult {
  success: boolean;
  videos?: string[];
  output_dir?: string;
  count?: number;
}

export const videogenInterfacesApi = {
  list: () => client.get("/api/videogen-interfaces/"),
  getEnabled: () => client.get("/api/videogen-interfaces/enabled"),
  get: (id: string) => client.get(`/api/videogen-interfaces/${id}`),
  create: (data: Partial<VideoGenInterface>) =>
    client.post("/api/videogen-interfaces/", data),
  update: (id: string, data: Partial<VideoGenInterface>) =>
    client.put(`/api/videogen-interfaces/${id}`, data),
  delete: (id: string) =>
    client.delete(`/api/videogen-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(`/api/videogen-interfaces/${id}/toggle`, { enabled }),
  reload: () => client.post("/api/videogen-interfaces/reload"),
  test: (id: string, data: {
    prompt?: string;
    negative_prompt?: string;
    resolution?: string;
    duration?: number;
    num_videos?: number;
    ref_images?: string[];
    ref_videos?: string[];
    audio?: any;
    model?: string;
    mode?: string;
  }) => client.post(`/api/videogen-interfaces/${id}/test`, data),
  getModels: (id: string) =>
    client.get(`/api/videogen-interfaces/${id}/models`),
  getModelsForNode: (id: string, mode: string) =>
    client.get(`/api/videogen-interfaces/${id}/models-for-node?mode=${mode}`),
  addModel: (id: string, model_name: string, modes?: string[], price?: string,
    resolutions?: string[], durations?: number[], meta?: Record<string, any>) =>
    client.post(`/api/videogen-interfaces/${id}/models`, {
      model_name, modes: modes || ["txt2video"], price: price || "",
      resolutions: resolutions || [], durations: durations || [], metadata: meta || {},
    }),
  removeModel: (id: string, model_name: string) =>
    client.delete(`/api/videogen-interfaces/${id}/models/${encodeURIComponent(model_name)}`),
  getModelParams: (id: string, model: string) =>
    client.get(`/api/videogen-interfaces/${id}/params/${encodeURIComponent(model)}`),
  fetchModels: (id: string) =>
    client.post(`/api/videogen-interfaces/${id}/fetch-models`),
  refreshBalance: (id: string) =>
    client.post(`/api/videogen-interfaces/${id}/refresh-balance`),
  uploadFile: (id: string, file: File, apiKey: string = "", purpose: string = "reference") => {
    const form = new FormData();
    form.append("file", file);
    if (apiKey) form.append("api_key", apiKey);
    form.append("purpose", purpose);
    return client.post(`/api/videogen-interfaces/${id}/upload`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
};
