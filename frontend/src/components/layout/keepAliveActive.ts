import { createContext, useContext } from "react";

/**
 * KeepAlive 分支的「激活态」。
 *
 * 命中保活前缀的路由在离开时不会被卸载，而是 `display: none` 隐藏（见 KeepAliveOutlet）。
 * 隐藏分支内的组件树仍然挂载，因此 setInterval 轮询、WebSocket 订阅、音频/视频播放等
 * 后台任务会继续运行 —— 用户感知不到，却持续占用内存与 CPU。
 *
 * 这里把「当前分支是否可见」下发到子树，业务侧用 `useKeepAliveActive()` 决定是否
 * 暂停后台任务。未被 Provider 包裹的场景（非保活路由、独立弹层）默认返回 true，
 * 行为与改造前完全一致。
 */
const KeepAliveActiveContext = createContext(true);

/** 当前分支是否处于激活（可见）状态；false 表示被 KeepAlive 隐藏，应暂停后台任务 */
export function useKeepAliveActive(): boolean {
  return useContext(KeepAliveActiveContext);
}

export { KeepAliveActiveContext };
