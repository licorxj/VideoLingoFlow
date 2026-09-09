import client from "./client";

export interface MusicGenModeConfig {
  enabled: boolean;
  endpoint: string;
}

export interface MusicGenModesMap {
  txt2music?: MusicGenModeConfig;
  instrumental?: MusicGenModeConfig;
  lyrics?: MusicGenModeConfig;
  extend?: MusicGenModeConfig;
  cover?: MusicGenModeConfig;
  add_instrumental?: MusicGenModeConfig;
  add_vocals?: MusicGenModeConfig;
  separate?: MusicGenModeConfig;
  to_wav?: MusicGenModeConfig;
  upload_extend?: MusicGenModeConfig;
  [key: string]: MusicGenModeConfig | undefined;
}

export interface MusicGenModelMeta {
  modes?: string[];
  price?: string;
  durations?: number[];
  max_ref_audios?: number;
  supports_lyrics?: boolean;
}

export interface MusicGenInterfaceConfig {
  api_url?: string;
  api_key?: string;
  sdk_package?: string;
  sdk_module?: string;
  sdk_function?: string;
  sdk_api_key?: string;
  sdk_extra_args?: Record<string, any>;
  default_model?: string;
  model_options?: string[];
  model_metadata?: Record<string, MusicGenModelMeta>;
  modes?: MusicGenModesMap;
  max_concurrent?: number;
  timeout?: number;
  poll_timeout?: number;
}

export interface MusicGenInterface {
  id: string;
  name: string;
  type: "sdk" | "openai_compatible";
  builtin: boolean;
  enabled: boolean;
  description: string;
  api_source_url?: string;
  model_docs_url?: string;
  balance?: number | string | null;
  config: MusicGenInterfaceConfig;
}

export interface MusicGenTestResult {
  success: boolean;
  audios?: string[];
  output_dir?: string;
  count?: number;
}

export const musicgenInterfacesApi = {
  list: () => client.get("/api/musicgen-interfaces/"),
  getEnabled: () => client.get("/api/musicgen-interfaces/enabled"),
  get: (id: string) => client.get(`/api/musicgen-interfaces/${id}`),
  create: (data: Partial<MusicGenInterface>) =>
    client.post("/api/musicgen-interfaces/", data),
  update: (id: string, data: Partial<MusicGenInterface>) =>
    client.put(`/api/musicgen-interfaces/${id}`, data),
  delete: (id: string) => client.delete(`/api/musicgen-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(`/api/musicgen-interfaces/${id}/toggle`, { enabled }),
  reload: () => client.post("/api/musicgen-interfaces/reload"),
  test: (id: string, data: {
    prompt?: string;
    model?: string;
    mode?: string;
    duration?: number;
    extra_args?: Record<string, any>;
  }) => client.post(`/api/musicgen-interfaces/${id}/test`, data),
  getModels: (id: string) => client.get(`/api/musicgen-interfaces/${id}/models`),
  addModel: (id: string, model_name: string, modes?: string[], price?: string, durations?: number[], max_ref_audios?: number, supports_lyrics?: boolean) =>
    client.post(`/api/musicgen-interfaces/${id}/models`, {
      model_name, modes: modes || [], price: price || "", durations: durations || [],
      max_ref_audios: max_ref_audios || 0, supports_lyrics: supports_lyrics ?? true,
    }),
  removeModel: (id: string, model_name: string) =>
    client.delete(`/api/musicgen-interfaces/${id}/models/${model_name}`),
  fetchModels: (id: string) => client.post(`/api/musicgen-interfaces/${id}/fetch-models`),
  refreshBalance: (id: string) => client.post(`/api/musicgen-interfaces/${id}/refresh-balance`),
};
