import client from "./client";

export type ControlUser = {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  is_active: boolean;
};

export type ControlProject = {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  version: number;
};

export type ControlProjectMember = {
  user: ControlUser;
  role: "viewer" | "editor";
};

export type ControlWorkflow = {
  key: string;
  revision: number;
  definition: Record<string, unknown>;
};

export type RevisionConflictError = Error & {
  code: "revision_conflict";
  expectedRevision: number;
  actualRevision: number;
  currentDefinition: Record<string, unknown> | null;
};

export async function getControlSession(): Promise<ControlUser | null> {
  try {
    const response = await client.get<{ user: ControlUser }>("/api/control/auth/me");
    return response.data.user;
  } catch (error: any) {
    const status = Number(error?.status ?? error?.response?.status ?? 0);
    if (status === 401 || status === 404) return null;
    throw error;
  }
}

export async function loginControlSession(username: string, password: string): Promise<ControlUser> {
  const response = await client.post<{ user: ControlUser }>("/api/control/auth/login", { username, password });
  return response.data.user;
}

export async function restoreLocalControlSession(): Promise<ControlUser | null> {
  try {
    const response = await client.post<{ user: ControlUser }>("/api/control/auth/local-session");
    return response.data.user;
  } catch (error: any) {
    const status = Number(error?.status ?? error?.response?.status ?? 0);
    if (status === 403 || status === 409) return null;
    throw error;
  }
}

export async function logoutControlSession() {
  await client.post("/api/control/auth/logout");
}

/**
 * 启动期确保存在一个可用的控制面会话：
 * 1) 优先尝试环回地址自动登录（local-session，无需密码）；
 * 2) 若后端尚未初始化管理员（local-session 返回 409 bootstrap_required），
 *    则用默认账号自动 bootstrap，然后再次建立本地会话。
 * 这样任意页面（不局限于多人协作页）首次打开都能直接通信，无需手动登录。
 */
export async function ensureControlSession(): Promise<ControlUser | null> {
  const existing = await restoreLocalControlSession().catch(() => null);
  if (existing) return existing;
  try {
    await client.post("/api/control/auth/bootstrap", { username: "admin", password: "admin123456" });
  } catch {
    /* 已初始化（409）或网络错误时静默忽略 */
  }
  return restoreLocalControlSession().catch(() => null);
}

export async function listControlProjects(): Promise<ControlProject[]> {
  const response = await client.get<{ projects: ControlProject[] }>("/api/control/projects");
  return response.data.projects;
}

export async function listControlProjectMembers(projectId: string): Promise<ControlProjectMember[]> {
  const response = await client.get<{ members: ControlProjectMember[] }>(`/api/control/projects/${projectId}/members`);
  return response.data.members;
}

export async function changeControlProjectMember(projectId: string, username: string, role: "viewer" | "editor") {
  await client.post(`/api/control/projects/${projectId}/members`, { username, role });
}

export async function removeControlProjectMember(projectId: string, userId: string) {
  await client.delete(`/api/control/projects/${projectId}/members/${userId}`);
}

export async function getControlWorkflow(projectId: string, workflowKey: string): Promise<ControlWorkflow> {
  const response = await client.get<{ workflow: ControlWorkflow }>(`/api/control/projects/${projectId}/workflows/${workflowKey}`);
  return response.data.workflow;
}

export async function saveControlWorkflow(
  projectId: string,
  workflowKey: string,
  definition: Record<string, unknown>,
  expectedRevision: number,
  force = false,
): Promise<ControlWorkflow> {
  try {
    const response = await client.put<{ workflow: ControlWorkflow }>(`/api/control/projects/${projectId}/workflows/${workflowKey}`, {
      definition,
      expected_revision: expectedRevision,
      force,
    });
    return response.data.workflow;
  } catch (error: any) {
    if (error?.status === 409 && error?.code === "revision_conflict") {
      const detail = error.details as Record<string, unknown>;
      throw Object.assign(new Error(error.message), {
        code: "revision_conflict" as const,
        expectedRevision: detail.expected_revision,
        actualRevision: detail.actual_revision,
        currentDefinition: detail.current_definition ?? null,
      }) as RevisionConflictError;
    }
    throw error;
  }
}
