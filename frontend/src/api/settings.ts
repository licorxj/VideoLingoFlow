import client from "./client";

export const settingsApi = {
  getAll: () => client.get("/api/settings"),
  get: (key: string) => client.get(`/api/settings/${key}`),
  update: (key: string, value: any) => client.put("/api/settings", { key, value }),
};
