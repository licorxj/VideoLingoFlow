import { useEffect, useRef, useState } from "react";

/**
 * 元素进入视口后才返回 true —— 视频/音频等重媒体用它做懒加载,
 * 避免一页几十个 <video>/<audio> 同时加载把浏览器卡死。
 * @param rootMargin 提前加载的边距,默认进入视口前 200px 就开始准备
 */
export function useInView<T extends HTMLElement>(rootMargin = "200px") {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element || inView) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [inView, rootMargin]);

  return { ref, inView };
}
