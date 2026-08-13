import client from "./client";

export const historyApi = {
  list: (status?: string) => client.get("/api/history", { params: { status } }),
};
