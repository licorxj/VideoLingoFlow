"""GPU Service manager：常驻主进程。

- 后台线程监测显存（nvidia-smi，回退 torch）
- 按需拉起 lane 工作子进程（上限 GPU_SERVICE_MAX_LANES）；
  显存充足才开新 lane，不足时任务留在队列让调用 worker 等待
- 空闲 lane 超过空闲时长后释放（lane 自退 + manager 兜底强杀）；
  显存紧张（free < 2×headroom）时自动切换到更短的加压空闲超时，但始终保留 1 个空闲 lane 避免杀-拉抖动
- 状态写入 Redis（videolingo:gpu:status），供 API/前端展示
"""
import os
import json
import signal
import subprocess
import sys
import threading
import time
import uuid

from backend.gpu_service import config, jobs
from backend.gpu_service.monitor import gpu_info

LANE_POLL = 1.0  # 主循环轮询间隔（秒）


class GpuServiceManager:
    def __init__(self):
        self._rc = jobs.get_redis()
        self._lanes: dict[str, dict] = {}  # lane_id -> {"proc": Popen, "spawned_at": float}
        self._vram = {"available": False, "free_gb": 0.0, "total_gb": 0.0, "used_gb": 0.0, "name": ""}
        self._stop = threading.Event()
        self._max_lanes = config.max_lanes()
        self._idle_timeout = config.lane_idle_timeout()
        self._pressure_idle_timeout = config.pressure_idle_timeout()
        self._headroom = config.vram_headroom_gb()
        self._last_status = 0.0
        self._project_root = self._find_project_root()

    @staticmethod
    def _find_project_root() -> str:
        current = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for parent in (current, os.getcwd()):
            if os.path.exists(os.path.join(parent, "backend", "main.py")):
                return parent
        return current

    # ── 显存监测线程 ──────────────────────────────────────────────
    def _vram_loop(self) -> None:
        while not self._stop.is_set():
            self._vram = gpu_info()
            self._stop.wait(3.0)

    # ── lane 管理 ─────────────────────────────────────────────────
    def _live_lanes(self) -> list[tuple[str, dict]]:
        return [(lid, lane) for lid, lane in self._lanes.items() if lane["proc"].poll() is None]

    def _reap(self) -> None:
        dead = [lid for lid, lane in self._lanes.items() if lane["proc"].poll() is not None]
        for lid in dead:
            print(f"[GPU-manager] lane {lid} exited", flush=True)
            self._lanes.pop(lid, None)
            jobs.clear_lane(lid)

    def _spawn_lane(self) -> str | None:
        if len(self._live_lanes()) >= self._max_lanes:
            return None
        if self._vram.get("available") and self._vram.get("free_gb", 0.0) < self._headroom:
            print(f"[GPU-manager] VRAM {self._vram.get('free_gb')}GB < headroom {self._headroom}GB, keep queued", flush=True)
            return None
        lane_id = f"lane-{uuid.uuid4().hex[:8]}"
        cmd = [sys.executable, "-m", "backend.gpu_service.lane", "--lane-id", lane_id]
        env = os.environ.copy()
        env["PYTHONPATH"] = self._project_root + os.pathsep + env.get("PYTHONPATH", "")
        # lane 内禁用 GPU 服务代理，防止任务被递归提交回队列形成死锁
        env["GPU_SERVICE_LANE_WORKER"] = "1"
        try:
            proc = subprocess.Popen(
                cmd, cwd=self._project_root, env=env,
                stdout=None, stderr=None,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as exc:
            print(f"[GPU-manager] spawn lane failed: {exc}", flush=True)
            return None
        self._lanes[lane_id] = {"proc": proc, "spawned_at": time.time()}
        print(f"[GPU-manager] lane {lane_id} spawned pid={proc.pid}", flush=True)
        return lane_id

    def _idle_lane_id(self) -> str | None:
        hbs = jobs.read_heartbeats(self._rc)
        for lid, lane in self._live_lanes():
            info = hbs.get(lid)
            if info and info.get("status") == "idle":
                return lid
        return None

    def _vram_pressure(self) -> bool:
        """显存紧张判定：可用显存低于 2×headroom 时进入加压模式。"""
        if not self._vram.get("available"):
            return False
        return self._vram.get("free_gb", 0.0) < self._headroom * 2

    def _effective_idle_timeout(self) -> int:
        """当前生效的空闲超时：显存紧张时缩短，加快空闲 lane 归还显存。"""
        if self._vram_pressure():
            return min(self._idle_timeout, self._pressure_idle_timeout)
        return self._idle_timeout

    def _idle_lanes(self) -> list[str]:
        """按心跳筛选当前空闲的 lane。"""
        hbs = jobs.read_heartbeats(self._rc)
        return [lid for lid, _lane in self._live_lanes()
                if (hbs.get(lid) or {}).get("status") == "idle"]

    def _release_stuck_idle_lanes(self) -> None:
        """兜底强杀空闲过久的 lane：常规超时按 1.5×；加压模式下额外释放多余空闲 lane
        （始终保留 1 个空闲 lane 预热，避免杀完立刻又拉起的抖动）。"""
        hbs = jobs.read_heartbeats(self._rc)
        now = time.time()
        limit = self._effective_idle_timeout() * 1.5
        pressure = self._vram_pressure()
        idle_ids = self._idle_lanes()
        for idx, lid in enumerate(idle_ids):
            lane = self._lanes.get(lid)
            info = hbs.get(lid)
            if not (lane and info):
                continue
            stuck = (now - float(info.get("ts", now))) > limit
            surplus = pressure and idx > 0  # 加压时保留第一个空闲 lane
            if stuck or surplus:
                reason = "stuck" if stuck else "vram pressure"
                print(f"[GPU-manager] force release idle lane {lid} ({reason})", flush=True)
                try:
                    lane["proc"].terminate()
                except Exception:
                    pass

    # ── 调度 ──────────────────────────────────────────────────────
    def _purge_stale_jobs(self) -> None:
        """启动时清理长期无人认领的孤儿任务。

        等待侧超时与 job_timeout 对齐，超过 job_timeout 仍未被消费的任务，
        其等待方必然已超时回退/退出，再执行只会浪费 GPU，直接丢弃。
        避免 manager 重启（或 Redis 残留）后把历史死任务重新跑一遍。
        """
        cutoff = time.time() - config.job_timeout()
        try:
            pending = self._rc.lrange(config.job_queue_key(), 0, -1)
        except Exception:
            return
        keep = []
        for raw in pending:
            try:
                ts = float(json.loads(raw).get("ts", 0))
            except (TypeError, ValueError):
                continue  # 损坏条目直接丢弃
            if ts >= cutoff:
                keep.append(raw)
        dropped = len(pending) - len(keep)
        if dropped <= 0:
            return
        try:
            pipe = self._rc.pipeline()
            pipe.delete(config.job_queue_key())
            if keep:
                # 按 lrange 顺序 rpush 回写，保持原顺序（BRPOP 从右端取最旧）
                pipe.rpush(config.job_queue_key(), *keep)
            pipe.execute()
            print(f"[GPU-manager] purged {dropped} stale job(s) on startup", flush=True)
        except Exception:
            pass

    def _dispatch_or_queue(self, job: dict) -> None:
        lane_id = self._idle_lane_id()
        if lane_id is None:
            lane_id = self._spawn_lane()
        if lane_id is None:
            # 无空闲 lane 且无法新开（满员/显存不足）→ 任务留在队列等待
            self._rc.lpush(config.job_queue_key(), json.dumps(job, ensure_ascii=False))
            return
        jobs.push_lane_job(self._rc, lane_id, job)

    def _publish_status(self) -> None:
        now = time.time()
        if now - self._last_status < 2.0:
            return
        self._last_status = now
        hbs = jobs.read_heartbeats(self._rc)
        lanes = [
            {
                "id": lid,
                "pid": lane["proc"].pid,
                "status": (hbs.get(lid) or {}).get("status", "starting"),
                "job_id": (hbs.get(lid) or {}).get("job_id", ""),
                "last_activity": (hbs.get(lid) or {}).get("ts", 0),
            }
            for lid, lane in self._live_lanes()
        ]
        try:
            depth = self._rc.llen(config.job_queue_key())
        except Exception:
            depth = 0
        jobs.publish_status(self._rc, {
            "available": True,
            "vram": self._vram,
            "max_lanes": self._max_lanes,
            "active_lanes": len(lanes),
            "busy_lanes": sum(1 for lane in lanes if lane["status"] == "busy"),
            "queue_depth": depth,
            "idle_timeout": self._effective_idle_timeout(),
            "vram_pressure": self._vram_pressure(),
            "lanes": lanes,
        })

    # ── 主循环 ────────────────────────────────────────────────────
    def run(self) -> None:
        print(f"[GPU-manager] started pid={os.getpid()} max_lanes={self._max_lanes} "
              f"idle_timeout={self._idle_timeout}s pressure_idle={self._pressure_idle_timeout}s "
              f"headroom={self._headroom}GB", flush=True)
        threading.Thread(target=self._vram_loop, daemon=True).start()
        try:
            self._rc.delete(config.shutdown_key())  # 清掉历史停机标记
        except Exception:
            pass
        self._purge_stale_jobs()
        while not self._stop.is_set():
            self._reap()
            self._release_stuck_idle_lanes()
            job = jobs.pop_job(self._rc, timeout=LANE_POLL)
            if job is not None:
                self._dispatch_or_queue(job)
            self._publish_status()
        self._shutdown_lanes()

    def _shutdown_lanes(self) -> None:
        for lid, lane in self._live_lanes():
            try:
                lane["proc"].terminate()
            except Exception:
                pass
        time.sleep(1.0)
        for lid, lane in self._live_lanes():
            try:
                if lane["proc"].poll() is None:
                    lane["proc"].kill()
            except Exception:
                pass
        self._lanes.clear()
        print("[GPU-manager] all lanes stopped", flush=True)

    def stop(self) -> None:
        self._stop.set()


_manager: GpuServiceManager | None = None


def main() -> int:
    global _manager
    _manager = GpuServiceManager()

    def _signal(signum, frame):
        print(f"[GPU-manager] signal {signum}, stopping", flush=True)
        _manager.stop()

    signal.signal(signal.SIGTERM, _signal)
    signal.signal(signal.SIGINT, _signal)
    try:
        _manager.run()
    except KeyboardInterrupt:
        _manager.stop()
        _manager._shutdown_lanes()
    return 0


if __name__ == "__main__":
    sys.exit(main())
