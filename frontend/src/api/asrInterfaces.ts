import client from "./client";

export interface ASRInterfaceConfig {
  api_url?: string;
  api_key?: string;
  audio_param?: string;
  language_param?: string;
  endpoint?: string;
  body_type?: string;
  sdk_package?: string;
  sdk_function?: string;
  sdk_module?: string;
  sdk_api_key?: string;
  sdk_language_list_function?: string;
  model?: string;
  text_param?: string;
  max_duration?: number;
  hotwords_enabled?: boolean;
  hotwords?: string;
  word_timestamps?: boolean;
  diarize?: boolean;
  diarize_model?: string;
  hf_token?: string;
  num_speakers?: number;
  min_speakers?: number;
  max_speakers?: number;
  model_options?: string[];
  voice_options?: string[];
  model_list_url?: string;
  voice_list_url?: string;
  model_list_key?: string;
  voice_list_key?: string;
  language_list_url?: string;
  language_list_key?: string;
  sdk_extra_args?: Record<string, string>;
  max_concurrent?: number;
  timeout?: number;
  custom_params?: Array<{ key: string; default: string; description: string }>;
}

export interface ASRInterface {
  id: string;
  name: string;
  type: "local" | "sdk";
  builtin: boolean;
  enabled: boolean;
  description: string;
  config: ASRInterfaceConfig;
}

export interface ASRTestResult {
  success: boolean;
  result?: {
    segments?: Array<{ start: number; end: number; text: string }>;
    language?: string;
    text?: string;
  };
  segment_count?: number;
  result_url?: string;
}

export const asrInterfacesApi = {
  list: () => client.get("/api/asr-interfaces"),
  getEnabled: () => client.get("/api/asr-interfaces/enabled"),
  get: (id: string) => client.get(`/api/asr-interfaces/${id}`),
  create: (data: Partial<ASRInterface>) =>
    client.post("/api/asr-interfaces", data),
  update: (id: string, data: Partial<ASRInterface>) =>
    client.put(`/api/asr-interfaces/${id}`, data),
  delete: (id: string) => client.delete(`/api/asr-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(`/api/asr-interfaces/${id}/toggle?enabled=${enabled}`),
  reload: () => client.post("/api/asr-interfaces/reload"),
  test: (id: string, data: {
    audio_path: string;
    language?: string;
    model?: string;
  }) => client.post(`/api/asr-interfaces/${id}/test`, data),
  uploadAudio: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return client.post("/api/asr-interfaces/upload-audio", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  fetchSdkLanguages: (id: string) =>
    client.post(`/api/asr-interfaces/${id}/fetch-sdk-languages`),
};
