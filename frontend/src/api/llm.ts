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
  placeholders: PromptPlaceholder[];
  system_prompt: string;
  user_prompt: string;
}

export const promptApi = {
  listTemplates: () => client.get<{ templates: PromptTemplate[] }>("/api/prompts/templates"),
  getTemplate: (id: string) => client.get<PromptTemplate>(`/api/prompts/templates/${id}`),
  updateTemplate: (id: string, data: { system_prompt?: string; user_prompt?: string }) =>
    client.put(`/api/prompts/templates/${id}`, data),
  validatePlaceholders: (id: string, data: { system_prompt: string; user_prompt: string }) =>
    client.post<{ invalid: Array<{ tag: string; location: string }>; unused: string[]; valid: boolean }>(
      `/api/prompts/templates/${id}/validate`, data
    ),
};
