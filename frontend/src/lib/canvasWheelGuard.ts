import { useEffect } from "react";

/**
 * 画布滚轮守卫 —— 让 React Flow 节点卡片内的自定义可滚动弹层能正常响应鼠标滚轮。
 *
 * 背景：React Flow 在 `.react-flow__pane` 上以「冒泡阶段」注册 wheel 监听
 * （`d3Selection.on('wheel.zoom', wheelHandler, { passive: false })`），命中时先
 * `event.preventDefault()` 再缩放画布。节点内的原生 `<select>`/输入框还能靠自身
 * 监听拦住，而**自定义下拉 / 列表 / 弹层**（api-select、multiselect 弹层、固定定位
 * 模态框等）的滚轮会一路冒泡到 pane：弹层滚不动，画布反而被缩放。
 *
 * 解法：在画布外层容器上以「捕获阶段」先拦一道 —— 只要滚轮落在「自己会消费滚轮」的
 * 元素内，就阻止事件继续传播到 pane。捕获阶段先于 pane 的冒泡监听执行，因此可靠；
 * 且只 `stopPropagation()` 不 `preventDefault()`，元素自身的滚动照常发生。
 *
 * 判定「会消费滚轮」：确实溢出且 overflow 为 auto/scroll/overlay 的元素、表单控件，
 * 或显式标注了 React Flow 约定类名 `nowheel` 的元素。画布空白处的缩放行为不变。
 */

const SCROLLABLE_OVERFLOW = /^(auto|scroll|overlay)$/;

/** 滚轮事件目标是否位于「自己会消费滚轮」的元素内（boundary 为画布外层容器，不含）。 */
function consumesWheel(target: EventTarget | null, boundary: HTMLElement): boolean {
  let el: HTMLElement | null = target instanceof Element ? (target as HTMLElement) : null;
  while (el && el !== boundary) {
    const tag = el.tagName;
    if (tag === "SELECT" || tag === "TEXTAREA" || tag === "INPUT") return true;
    if (el.classList.contains("nowheel")) return true;
    // 先做便宜的溢出判断，只有确实溢出时才去读计算样式
    if (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1) {
      const style = getComputedStyle(el);
      if (SCROLLABLE_OVERFLOW.test(style.overflowY) || SCROLLABLE_OVERFLOW.test(style.overflowX)) {
        return true;
      }
    }
    el = el.parentElement;
  }
  return false;
}

/**
 * 给画布外层容器装滚轮守卫；`rootRef` 指向包住 `<ReactFlow>` 的 DOM 容器。
 *
 * 参数用结构化只读类型，兼容 React 18/19 两种 `RefObject` 定义。
 */
export function useCanvasWheelGuard(rootRef: { readonly current: HTMLElement | null }): void {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onWheel = (e: WheelEvent) => {
      if (consumesWheel(e.target, root)) e.stopPropagation();
    };
    root.addEventListener("wheel", onWheel, { capture: true });
    return () => root.removeEventListener("wheel", onWheel, { capture: true });
  }, [rootRef]);
}
