"""引擎生命周期管理：空闲超时自动卸载（OCR / ASR 通用）。

引擎在最后一次被任务使用后，若超过 idle_timeout 仍无新调用，
后台清扫线程会将其卸载并归还内存/显存；下次调用时按需重建。

空闲超时可用环境变量按引擎覆盖（本机单卡批量建议拉长，避免反复重载）：
  ENGINE_IDLE_TIMEOUT_ASR=120
  ENGINE_IDLE_TIMEOUT_OCR=30
  ENGINE_IDLE_TIMEOUT_DEFAULT=5

用法：
    registry = IdleEngineRegistry(idle_timeout=None, name="ASR")  # None=读 env
    engine = registry.acquire("rapidocr", builder, unloader=my_unload)

安全说明：卸载回调（unloader）需设计为在引擎空闲时执行；对于正在运行的
推理，引擎内部持有的 session/模型引用不会因卸载回调而失效（局部引用仍存活）。
"""
import contextlib
import gc
import os
import tempfile
import threading
import time
from typing import Callable, Dict, Optional

DEFAULT_IDLE_TIMEOUT = 5.0    # 默认空闲多少秒后自动卸载
DEFAULT_SWEEP_INTERVAL = 1.0  # 后台清扫间隔（秒）

# ── 跨进程引擎构建锁 ────────────────────────────────────────────────────────
# 背景：Windows 上多个节点子进程同时首次加载 torch CUDA DLL 会竞争文件锁
# （WinError 32: “另一个程序正在使用此文件”，c10_cuda.dll），导致节点随机失败。
# 该锁让同一时刻只有一个进程在冷加载 torch/模型；等它完成后，其它进程加载相同
# DLL 走内存映射缓存，安全且快。锁只覆盖“构建/冷加载”，不覆盖推理。
_ENGINE_BUILD_LOCK_PATH = os.path.join(tempfile.gettempdir(), "videolingo_engine_build.lock")
_build_lock_local = threading.local()


@contextlib.contextmanager
def global_engine_build_lock(timeout: float = 1800.0):
    """跨进程互斥：串行化引擎（torch/模型）的冷加载。

    - 同线程可重入（引擎 builder 嵌套触发其它引擎构建时不自锁）
    - 等待超过 timeout 后放弃加锁继续执行（宁可冒竞争风险也不无限阻塞节点）
    - 锁文件不可用（只读环境等）时退化为不加锁
    """
    if getattr(_build_lock_local, "depth", 0) > 0:
        _build_lock_local.depth += 1
        try:
            yield
        finally:
            _build_lock_local.depth -= 1
        return
    try:
        lock_file = open(_ENGINE_BUILD_LOCK_PATH, "a+b")
    except OSError:
        _build_lock_local.depth = 1
        try:
            yield
        finally:
            _build_lock_local.depth = 0
        return
    try:
        acquired = False
        deadline = time.time() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.time() >= deadline:
                    print("[engine_lifecycle] 等待引擎构建锁超时，跳过加锁继续（存在 DLL 竞争风险）")
                    break
                time.sleep(0.25)
        _build_lock_local.depth = 1
        try:
            yield
        finally:
            _build_lock_local.depth = 0
            if acquired:
                try:
                    lock_file.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    finally:
        lock_file.close()


def resolve_idle_timeout(name: str, default: float = DEFAULT_IDLE_TIMEOUT) -> float:
    """按引擎名解析空闲超时：ENGINE_IDLE_TIMEOUT_<NAME> > ENGINE_IDLE_TIMEOUT_DEFAULT > default。"""
    for key in (f"ENGINE_IDLE_TIMEOUT_{str(name).upper()}", "ENGINE_IDLE_TIMEOUT_DEFAULT"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            continue
    try:
        return max(1.0, float(default))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_TIMEOUT


class IdleEngineRegistry:
    """带空闲超时自动卸载的引擎注册表。"""

    def __init__(self, idle_timeout: Optional[float] = None, sweep_interval: float = DEFAULT_SWEEP_INTERVAL,
                 name: str = "engine"):
        self._name = name
        # None：优先读 ENGINE_IDLE_TIMEOUT_<NAME>，便于本机批量按引擎拉长驻留
        self._idle_timeout = resolve_idle_timeout(name, DEFAULT_IDLE_TIMEOUT if idle_timeout is None else idle_timeout)
        self._sweep_interval = sweep_interval
        self._entries: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._start_sweeper()

    def acquire(self, key: str, builder: Callable[[], object],
                unloader: Optional[Callable[[object], None]] = None,
                busy_check: Optional[Callable[[], bool]] = None) -> object:
        """获取引擎：不存在则用 builder 构建并注册，同时更新最后使用时间。

        busy_check：可选可调用对象，返回 True 时表示该引擎正忙（如模型加载/
        推理进行中）。busy 引擎即使超过 idle_timeout 也不会被清扫线程卸载，
        避免长耗时模型加载被误判为空闲而中途释放显存/触发重载。
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                # 跨进程串行化模型/torch 冷加载（见 global_engine_build_lock），
                # 避免多任务并行的节点子进程同时冷加载 CUDA DLL 触发 WinError 32
                with global_engine_build_lock():
                    # 双检：等锁期间同进程其它线程可能已构建同 key 引擎
                    entry = self._entries.get(key)
                    if entry is None:
                        engine = builder()
                        entry = {
                            "engine": engine,
                            "last_used": time.monotonic(),
                            "unloader": unloader,
                            "busy_check": busy_check,
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

    def _is_busy(self, entry: dict) -> bool:
        cb = entry.get("busy_check")
        if cb is None:
            return False
        try:
            return bool(cb())
        except Exception:
            return False

    def _sweep(self):
        with self._lock:
            now = time.monotonic()
            expired = [(k, e) for k, e in self._entries.items()
                       if now - e["last_used"] >= self._idle_timeout
                       and not self._is_busy(e)]
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
