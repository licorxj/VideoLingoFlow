import client from "./client";

export interface TTSModeConfig {
  enabled: boolean;
  endpoint: string;
}

export interface TTSModesMap {
  clone?: TTSModeConfig;
  voice_design?: TTSModeConfig;
  controllable_clone?: TTSModeConfig;
  preset_voice?: TTSModeConfig;
}

export interface TTSInterfaceConfig {
  api_url?: string;
  api_key?: string;
  text_param?: string;
  ref_audio_param?: string | null;
  speed_param?: string | null;
  model_options?: string[];
  voice_options?: string[];
  model?: string;
  voice?: string;
  response_format?: string;
  modes?: TTSModesMap;
  voice_design_param?: string | null;
  controllable_clone_param?: string | null;
  model_list_url?: string;
  voice_list_url?: string;
  model_list_key?: string;
  voice_list_key?: string;
  sdk_package?: string;
  sdk_function?: string;
  sdk_module?: string;
  sdk_voice_list_function?: string;
  sdk_api_key?: string;
  startup_script?: string;
  sdk_extra_args?: Record<string, string>;
  max_concurrent?: number;
  timeout?: number;
  custom_params?: Array<{ key: string; default: string; description: string }>;
}

export interface TTSInterface {
  id: string;
  name: string;
  type: "local" | "online" | "sdk";
  builtin: boolean;
  enabled: boolean;
  description: string;
  api_source_url?: string;
  config: TTSInterfaceConfig;
}

export interface TTSTestResult {
  success: boolean;
  audio_url?: string;
  filename?: string;
  file_size?: number;
}

export const ttsInterfacesApi = {
  list: () => client.get("/api/tts-interfaces"),
  getEnabled: () => client.get("/api/tts-interfaces/enabled"),
  get: (id: string) => client.get(`/api/tts-interfaces/${id}`),
  create: (data: Partial<TTSInterface>) =>
    client.post("/api/tts-interfaces", data),
  update: (id: string, data: Partial<TTSInterface>) =>
    client.put(`/api/tts-interfaces/${id}`, data),
  delete: (id: string) => client.delete(`/api/tts-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(`/api/tts-interfaces/${id}/toggle?enabled=${enabled}`),
  reload: () => client.post("/api/tts-interfaces/reload"),
  test: (id: string, data: {
    text?: string;
    mode?: string;
    speed?: number;
    voice?: string;
    model?: string;
    ref_audio?: string;
    voice_design?: string;
    controllable_clone?: string;
  }) => client.post(`/api/tts-interfaces/${id}/test`, data),
  uploadAudio: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return client.post("/api/tts-interfaces/upload-audio", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  fetchSdkVoices: (id: string) =>
    client.post(`/api/tts-interfaces/${id}/fetch-sdk-voices`),
};