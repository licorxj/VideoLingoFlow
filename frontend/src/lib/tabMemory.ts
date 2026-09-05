/**
 * 标签页位置记忆
 *
 * 侧边栏的一级标签（如 /voiceforge、/editing）下面还有子路由
 * （/voiceforge/projects/:id、/editing?task=xxx）。默认点击一级标签只会回到
 * 首页，导致用户离开后再回来丢失工作状态。
 *
 * 这里在内存中记录每个一级标签最近一次访问的位置，侧边栏点击时优先跳回该位置。
 * 仅保存在内存中，刷新页面后自然重置，避免指向已经不存在的资源。
 */

const memory = new Map<string, string>();

/** 顶层标签 key：`/voiceforge/projects/1` -> `voiceforge`，`/` -> 空串 */
function tabKeyOf(pathname: string): string {
  return pathname.split("/")[1] ?? "";
}

/** 记住某个顶层标签下最近一次访问的位置（含查询串） */
export function rememberTabLocation(pathname: string, search: string): void {
  memory.set(tabKeyOf(pathname), `${pathname}${search}`);
}

/** 侧边栏点击一级标签时的跳转目标：优先回到上次离开的位置 */
export function resolveTabLocation(tabPath: string): string {
  return memory.get(tabKeyOf(tabPath)) ?? tabPath;
}

/** 判断当前路径是否属于某个一级标签 */
export function isTabActive(tabPath: string, pathname: string): boolean {
  if (tabPath === "/") return pathname === "/";
  return pathname === tabPath || pathname.startsWith(`${tabPath}/`);
}
