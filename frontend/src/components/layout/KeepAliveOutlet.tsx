import {
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ContextType,
  type ReactNode,
} from "react";
import { UNSAFE_LocationContext, useLocation, useOutlet } from "react-router-dom";

/**
 * 需要「保活」的路由前缀。
 *
 * 命中前缀的路由在首次访问后会被缓存：切换走时仅隐藏而不卸载组件树，
 * 再切回来时沿用原来的实例，已加载的数据、展开的面板、滚动位置、
 * iframe（如 Cutia 编辑器）都保持原样，不会重新挂载、不会重新请求。
 */
const KEEP_ALIVE_PREFIXES = ["/editing", "/voiceforge"];

/** 同时保活的页面数量上限，超出后按「最久未使用」淘汰 */
const MAX_CACHED = 6;

type LocationContextValue = ContextType<typeof UNSAFE_LocationContext>;

type CachedBranch = {
  key: string;
  element: ReactNode;
  /** 离开时冻结的 LocationContext，隐藏期间保持不变，避免无谓重渲染 */
  frozen: LocationContextValue;
};

type ScrollMemo = {
  indices: number[];
  tops: number[];
  lefts: number[];
};

function isKeepAlive(pathname: string): boolean {
  return KEEP_ALIVE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/** 记录容器内所有已经滚动过的元素位置（按遍历序号定位，DOM 不变即可还原） */
function collectScroll(root: HTMLElement | null): ScrollMemo | null {
  if (!root) return null;
  const nodes = root.querySelectorAll<HTMLElement>("*");
  const indices: number[] = [];
  const tops: number[] = [];
  const lefts: number[] = [];
  nodes.forEach((node, index) => {
    if (node.scrollTop > 0 || node.scrollLeft > 0) {
      indices.push(index);
      tops.push(node.scrollTop);
      lefts.push(node.scrollLeft);
    }
  });
  return indices.length ? { indices, tops, lefts } : null;
}

function restoreScroll(root: HTMLElement | null, memo: ScrollMemo | null): void {
  if (!root || !memo) return;
  const nodes = root.querySelectorAll<HTMLElement>("*");
  memo.indices.forEach((index, i) => {
    const node = nodes[index];
    if (!node) return;
    node.scrollTop = memo.tops[i];
    node.scrollLeft = memo.lefts[i];
  });
}

/** 外部可用该事件丢弃某个前缀下的缓存分支（例如项目被删除后） */
export const DROP_ROUTE_CACHE_EVENT = "vl-route-cache-drop";

export function dropRouteCache(prefix: string): void {
  window.dispatchEvent(
    new CustomEvent(DROP_ROUTE_CACHE_EVENT, { detail: { prefix } }),
  );
}

/** 单个保活分支：未激活时隐藏并从可访问性树中移除，激活时恢复滚动位置 */
function KeepAliveBranch({
  active,
  locationValue,
  children,
}: {
  active: boolean;
  locationValue: LocationContextValue;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const scrollMemoRef = useRef<ScrollMemo | null>(null);
  const prevActiveRef = useRef(active);

  // 即将被隐藏：此刻 DOM 仍是可见状态，先把内部滚动位置记下来
  if (prevActiveRef.current && !active) {
    scrollMemoRef.current = collectScroll(ref.current);
  }
  prevActiveRef.current = active;

  useLayoutEffect(() => {
    if (active) restoreScroll(ref.current, scrollMemoRef.current);
  }, [active]);

  return (
    <UNSAFE_LocationContext.Provider value={locationValue}>
      <div
        ref={ref}
        className="animate-fade-in-up h-full"
        style={active ? undefined : { display: "none" }}
        aria-hidden={active ? undefined : true}
      >
        {children}
      </div>
    </UNSAFE_LocationContext.Provider>
  );
}

/**
 * 带缓存的 Outlet。
 *
 * - 命中保活前缀：缓存已访问过的页面，未激活的用 `display: none` 隐藏；
 *   同时为每个分支注入「冻结」的 LocationContext，使隐藏分支里的
 *   useLocation / useSearchParams 仍读到自己离开时的地址，而不是当前地址。
 * - 未命中前缀：行为与原生 `<Outlet />` 完全一致（离开即卸载）。
 */
export default function KeepAliveOutlet() {
  const location = useLocation();
  const liveLocation = useContext(UNSAFE_LocationContext);
  const outlet = useOutlet();
  const cacheRef = useRef<Map<string, CachedBranch>>(new Map());
  const [, setDropVersion] = useState(0);

  // 资源被删除后丢弃对应分支，避免回来时看到已经不存在的内容
  useEffect(() => {
    const handleDrop = (event: Event) => {
      const prefix = (event as CustomEvent<{ prefix?: string }>).detail?.prefix;
      if (!prefix) return;
      let dropped = false;
      Array.from(cacheRef.current.keys()).forEach((cachedKey) => {
        if (cachedKey.startsWith(prefix)) {
          cacheRef.current.delete(cachedKey);
          dropped = true;
        }
      });
      if (dropped) setDropVersion((version) => version + 1);
    };
    window.addEventListener(DROP_ROUTE_CACHE_EVENT, handleDrop);
    return () => window.removeEventListener(DROP_ROUTE_CACHE_EVENT, handleDrop);
  }, []);

  // 同一 pathname 下 search 不同视为两个工作区（例如 /editing?task=xxx）
  const key = `${location.pathname}${location.search}`;
  const cache = cacheRef.current;

  if (!isKeepAlive(location.pathname)) {
    // 非保活路由本身不缓存，但已缓存的分支必须继续留在树里（隐藏），
    // 否则 React 会直接卸载它们，回到标签页时就丢失状态了。
    return (
      <>
        {Array.from(cache.values()).map((branch) => (
          <KeepAliveBranch key={branch.key} active={false} locationValue={branch.frozen}>
            {branch.element}
          </KeepAliveBranch>
        ))}
        <div key={key} className="animate-fade-in-up h-full">
          {outlet}
        </div>
      </>
    );
  }

  const cached = cache.get(key);
  if (cached) {
    // delete + set 让 Map 保持「最近使用在末尾」的顺序，便于 LRU 淘汰
    cache.delete(key);
    cached.element = outlet;
    cached.frozen = liveLocation;
    cache.set(key, cached);
  } else {
    cache.set(key, { key, element: outlet, frozen: liveLocation });
  }

  while (cache.size > MAX_CACHED) {
    const oldest = cache.keys().next().value as string | undefined;
    if (!oldest || oldest === key) break;
    cache.delete(oldest);
  }

  return (
    <>
      {Array.from(cache.values()).map((branch) => (
        <KeepAliveBranch
          key={branch.key}
          active={branch.key === key}
          locationValue={branch.key === key ? liveLocation : branch.frozen}
        >
          {branch.element}
        </KeepAliveBranch>
      ))}
    </>
  );
}
