"""引擎生命周期管理：空闲超时自动卸载（OCR / ASR 通用）。

引擎在最后一次被任务使用后，若超过 idle_timeout（默认 5 秒）仍无新调用，
后台清扫线程会将其卸载并归还内存/显存；下次调用时按需重建。

用法：
    registry = IdleEngineRegistry(idle_timeout=5.0, name="OCR")
    engine = registry.acquire("rapidocr", builder, unloader=my_unload)

安全说明：卸载回调（unloader）需设计为在引擎空闲时执行；对于正在运行的
推理，引擎内部持有的 session/模型引用不会因卸载回调而失效（局部引用仍存活）。
"""
import gc
import threading
import time
from typing import Callable, Dict, Optional

DEFAULT_IDLE_TIMEOUT = 5.0    # 空闲多少秒后自动卸载
DEFAULT_SWEEP_INTERVAL = 1.0  # 后台清扫间隔（秒）


class IdleEngineRegistry:
    """带空闲超时自动卸载的引擎注册表。"""

    def __init__(self, idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
                 sweep_interval: float = DEFAULT_SWEEP_INTERVAL,
                 name: str = "engine"):
        self._name = name
        self._idle_timeout = idle_timeout
        self._sweep_interval = sweep_interval
        self._entries: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._start_sweeper()

    def acquire(self, key: str, builder: Callable[[], object],
                unloader: Optional[Callable[[object], None]] = None) -> object:
        """获取引擎：不存在则用 builder 构建并注册，同时更新最后使用时间。"""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                engine = builder()
                entry = {
                    "engine": engine,
                    "last_used": time.monotonic(),
                    "unloader": unloader,
                }
                self._entries[key] = entry
                print(f"[{self._name}] 引擎 '{key}' 已加载"
                      f"（空闲 {self._idle_timeout:.0f}s 自动卸载）")
            else:
                entry["last_used"] = time.monotonic()
            return entry["engine"]

    def evict(self, key: str):
        """立即卸载指定引擎。"""
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is not None:
            self._unload_entry(key, entry)

    def clear_all(self):
        """卸载全部引擎（如配置变更时调用）。"""
        with self._lock:
            entries = list(self._entries.items())
            self._entries.clear()
        for key, entry in entries:
            self._unload_entry(key, entry)

    def stats(self) -> dict:
        """返回当前缓存的引擎与空闲时长（秒）。"""
        now = time.monotonic()
        with self._lock:
            return {k: {"idle": round(now - e["last_used"], 1)}
                    for k, e in self._entries.items()}

    # ── 内部 ──────────────────────────────────────────────────

    def _unload_entry(self, key: str, entry: dict):
        engine = entry.get("engine")
        unloader = entry.get("unloader")
        try:
            if unloader is not None:
                unloader(engine)
            elif hasattr(engine, "unload"):
                engine.unload()
        except Exception as exc:
            print(f"[{self._name}] 卸载引擎 '{key}' 失败: {exc}")
        print(f"[{self._name}] 引擎 '{key}' 已卸载（归还内存/显存）")

    def _sweep(self):
        with self._lock:
            now = time.monotonic()
            expired = [(k, e) for k, e in self._entries.items()
                       if now - e["last_used"] >= self._idle_timeout]
            for k, _ in expired:
                self._entries.pop(k)
        for key, entry in expired:
            self._unload_entry(key, entry)

    def _start_sweeper(self):
        def loop():
            while True:
                time.sleep(self._sweep_interval)
                try:
                    self._sweep()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True,
                         name=f"{self._name}-idle-sweeper").start()


def release_gpu_cache():
    """清空 torch 显存缓存并触发一次 GC（卸载辅助，可在任意线程安全调用）。"""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()
