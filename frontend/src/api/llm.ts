import client from "./client";

export const llmApi = {
  getPresets: () => client.get("/api/llm/presets"),
  test: (stepName?: string) => client.post("/api/llm/test", { step_name: stepName || "test" }),
};

export interface PromptPlaceholder {
  tag: string;
  label: string;
  description: string;
  type?: string;
}

export interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  scope?: string;
  category?: string;
  placeholders: PromptPlaceholder[];
  system_prompt: string;
  user_prompt: string;
}

export const VOICEFORGE_PROMPT_SCOPE = "voiceforge";

export const promptApi = {
  // scope=voiceforge 时只返回晴沐配音谷的 Prompt 预设
  listTemplates: (scope?: string) =>
    client.get<{ templates: PromptTemplate[] }>("/api/prompts/templates", {
      params: scope ? { scope } : undefined,
    }),
  getTemplate: (id: string) => client.get<PromptTemplate>(`/api/prompts/templates/${id}`),
  createTemplate: (data: Partial<PromptTemplate>) =>
    client.post<{ ok: boolean; template: PromptTemplate }>("/api/prompts/templates", data),
  deleteTemplate: (id: string) => client.delete(`/api/prompts/templates/${id}`),
  resetTemplate: (id: string) => client.post(`/api/prompts/templates/${id}/reset`),
  updateTemplate: (
    id: string,
    data: {
      name?: string;
      description?: string;
      category?: string;
      placeholders?: PromptPlaceholder[];
      system_prompt?: string;
      user_prompt?: string;
    }
  ) => client.put(`/api/prompts/templates/${id}`, data),
  validatePlaceholders: (id: string, data: { system_prompt: string; user_prompt: string }) =>
    client.post<{ invalid: Array<{ tag: string; location: string }>; unused: string[]; valid: boolean }>(
      `/api/prompts/templates/${id}/validate`, data
    ),
};
