/**
 * 工作流节点剪贴板：让「复制节点」可以跨画布、跨工作流、跨标签页、跨刷新粘贴。
 *
 * 重要约定：**绝不写入系统剪贴板**（navigator.clipboard）。
 * 早期版本写过，结果把用户复制到系统剪贴板里的文字覆盖成一长串节点 JSON，
 * 去别的输入框粘贴全是乱码；读取又需要「读取剪贴板」授权，失败后又回退成粘节点，
 * 进一步破坏普通粘贴。系统剪贴板只属于用户，这里一律不碰。
 *
 * 三层存储，能力依次递减：
 *   1. localStorage + `storage` 事件 —— 跨标签页 / 跨窗口共享（不污染系统剪贴板）；
 *   2. sessionStorage —— 同标签页内刷新、路由跳走再回来仍可粘贴；
 *   3. 调用方组件内存 state —— 同一次页面实例内的最快路径（见 WorkflowEditor）。
 *
 * 存储值用 MAGIC 前缀做自识别，解析失败一律返回 null（不影响任何其它功能）。
 */

export interface WorkflowClipboardPayload {
  nodes: any[];
  edges: any[];
}

/** localStorage 键：跨标签页共享（配合 storage 事件实时同步） */
const SHARED_KEY = "vl.workflow.clipboard.shared";
/** sessionStorage 键：同标签页内跨刷新/跨路由 */
const STORAGE_KEY = "vl.workflow.clipboard";
const MAGIC = "VLWF_CLIP_V1:";

/** 存储通常只有 5MB 左右，超限直接放弃持久化，避免大画布复制被阻塞 */
const MAX_PERSIST_BYTES = 3_000_000;

function isValidPayload(value: any): value is WorkflowClipboardPayload {
  return !!value && typeof value === "object" && Array.isArray(value.nodes) && Array.isArray(value.edges);
}

export function serializeClipboard(payload: WorkflowClipboardPayload): string {
  return MAGIC + JSON.stringify(payload);
}

/** 从任意文本里解析工作流剪贴板；非本格式或 JSON 损坏一律返回 null */
export function parseClipboardText(text: string | null | undefined): WorkflowClipboardPayload | null {
  if (!text) return null;
  const body = text.startsWith(MAGIC) ? text.slice(MAGIC.length) : "";
  if (!body) return null;
  try {
    const parsed = JSON.parse(body);
    if (!isValidPayload(parsed)) return null;
    return { nodes: parsed.nodes, edges: parsed.edges };
  } catch {
    return null;
  }
}

function fits(text: string): boolean {
  return text.length <= MAX_PERSIST_BYTES;
}

/** 写入 sessionStorage：同标签页刷新/路由跳回后仍可粘贴；配额超限时静默失败 */
export function persistClipboard(payload: WorkflowClipboardPayload): void {
  try {
    const text = serializeClipboard(payload);
    if (!fits(text)) return;
    window.sessionStorage.setItem(STORAGE_KEY, text);
  } catch {
    /* 忽略（隐私模式 / 配额超限） */
  }
}

export function loadPersistedClipboard(): WorkflowClipboardPayload | null {
  try {
    return parseClipboardText(window.sessionStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function clearPersistedClipboard(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* 忽略 */
  }
}

/** 写入 localStorage：让其它标签页也能粘到同一批节点（不经过系统剪贴板） */
export function persistSharedClipboard(payload: WorkflowClipboardPayload): void {
  try {
    const text = serializeClipboard(payload);
    if (!fits(text)) return;
    window.localStorage.setItem(SHARED_KEY, text);
  } catch {
    /* 忽略 */
  }
}

/** 读取跨标签页共享的剪贴板内容；供页面初始化时恢复 */
export function loadSharedClipboard(): WorkflowClipboardPayload | null {
  try {
    return parseClipboardText(window.localStorage.getItem(SHARED_KEY));
  } catch {
    return null;
  }
}

/**
 * 订阅其它标签页的复制动作。本标签页写入不会触发自己的 storage 事件，
 * 因此不会产生回环；回调在节点内容为空时不会触发，避免「清空」把本地剪贴板也清掉。
 */
export function subscribeSharedClipboard(onChange: (payload: WorkflowClipboardPayload) => void): () => void {
  const handler = (e: StorageEvent) => {
    if (e.key !== SHARED_KEY || !e.newValue) return;
    const payload = parseClipboardText(e.newValue);
    if (payload && payload.nodes.length > 0) onChange(payload);
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}