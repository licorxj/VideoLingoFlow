import client from "./client";

export interface Credential {
  id: string;
  name: string;
  purpose: string;
  register_url: string;
  masked: string;
  keys_count: number;
  rotate: boolean;
  current_index: number;
  value?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CredentialUsage {
  name: string;
  references: string[];
}

export const credentialsApi = {
  list: (params?: { keyword?: string; reveal?: boolean }) =>
    client.get<{ credentials: Credential[]; total: number }>("/api/credentials", { params }),
  get: (id: string, reveal = false) =>
    client.get<{ credential: Credential }>(`/api/credentials/${id}`, { params: { reveal } }),
  create: (data: { name: string; value: string; purpose?: string; register_url?: string; rotate?: boolean }) =>
    client.post<{ success: boolean; credential: Credential }>("/api/credentials", data),
  update: (id: string, data: { name?: string; value?: string; purpose?: string; register_url?: string; rotate?: boolean }) =>
    client.put<{ success: boolean; credential: Credential }>(`/api/credentials/${id}`, data),
  remove: (id: string) =>
    client.delete<{ success: boolean; removed: { id: string; name: string } }>(`/api/credentials/${id}`),
  usage: (id: string) => client.get<CredentialUsage>(`/api/credentials/usage/${id}`),
};
