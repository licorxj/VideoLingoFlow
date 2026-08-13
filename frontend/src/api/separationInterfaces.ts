import client from "./client";

export interface SeparationInterfaceConfig {
  sdk_module?: string;
  sdk_class?: string;
  model: string;
  model_options: string[];
  model_details?: Record<string, { name: string; description: string }>;
  segment?: number;
  two_stems?: string;
  format: string;
  format_options: string[];
  timeout: number;
  max_concurrent: number;
  custom_params: Array<{ key: string; default: string; description: string }>;
  // online/local fields
  api_url?: string;
  api_key?: string;
  endpoint?: string;
  body_type?: string;
  audio_param?: string;
  startup_script?: string;
}

export interface SeparationInterface {
  id: string;
  name: string;
  type: "local" | "online" | "sdk";
  builtin: boolean;
  enabled: boolean;
  description: string;
  config: SeparationInterfaceConfig;
}

export interface SeparationTestResult {
  success: boolean;
  vocals_url?: string;
  background_url?: string;
}

export const separationInterfacesApi = {
  list: () => client.get("/api/separation-interfaces"),
  getEnabled: () => client.get("/api/separation-interfaces/enabled"),
  get: (id: string) => client.get(`/api/separation-interfaces/${id}`),
  create: (data: any) => client.post("/api/separation-interfaces", data),
  update: (id: string, data: any) =>
    client.put(`/api/separation-interfaces/${id}`, data),
  delete: (id: string) => client.delete(`/api/separation-interfaces/${id}`),
  toggle: (id: string, enabled: boolean) =>
    client.post(
      `/api/separation-interfaces/${id}/toggle?enabled=${enabled}`
    ),
  reload: () => client.post("/api/separation-interfaces/reload"),
  test: (id: string, data: { audio_path: string; model?: string; format?: string }) =>
    client.post(`/api/separation-interfaces/${id}/test`, data),
  uploadAudio: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return client.post("/api/separation-interfaces/upload-audio", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  // Model detail management
  setModelDetail: (ifaceId: string, modelName: string, data: { name: string; description: string }) =>
    client.post(`/api/separation-interfaces/${ifaceId}/models/${modelName}`, data),
  deleteModelDetail: (ifaceId: string, modelName: string) =>
    client.delete(`/api/separation-interfaces/${ifaceId}/models/${modelName}`),
  setModelAsDefault: (ifaceId: string, modelName: string) =>
    client.put(`/api/separation-interfaces/${ifaceId}/models/${modelName}/set-default`),
};
