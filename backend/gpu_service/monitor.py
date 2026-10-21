"""GPU 显存监测：优先 nvidia-smi，回退 torch.cuda。"""
import os
import subprocess


def gpu_info() -> dict:
    """返回 {available, total_gb, used_gb, free_gb, name, gpu_count}。监测失败时 available=False。

    语义：free_gb 取**第一块 GPU（device 0）**的剩余显存——lane 内引擎默认
    走 cuda:0，起 lane 的余量判断应以 device 0 为准。多卡时不汇总（汇总会让
    「device 0 已满但 device 1 空闲」被误判为可起 lane）；gpu_count 供上层
    识别多卡环境并告警（当前 lane 调度不利用多卡）。
    """
    info = _nvidia_smi()
    if info["available"]:
        return info
    return _torch_info()


def _nvidia_smi() -> dict:
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu,name", "--format=csv,noheader,nounits"]
        # Windows 下优先 PATH 中的 nvidia-smi；避免 shell=True（路径注入与兼容问题）
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            return {"available": False}
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        if not lines:
            return {"available": False}
        # 取第一块卡（device 0）：lane 引擎默认 cuda:0，余量判断以它为准
        line = lines[0]
        total, used, free, utilization, name = [part.strip() for part in line.split(",")]
        return {
            "available": True,
            "total_gb": round(float(total) / 1024, 1),
            "used_gb": round(float(used) / 1024, 1),
            "free_gb": round(float(free) / 1024, 1),
            "utilization_percent": round(float(utilization), 1),
            "name": name,
            "gpu_count": len(lines),
        }
    except Exception:
        return {"available": False}


def _torch_info() -> dict:
    try:
        import torch
        if not torch.cuda.is_available():
            return {"available": False}
        free, total = torch.cuda.mem_get_info()
        return {
            "available": True,
            "total_gb": round(total / (1024 ** 3), 1),
            "used_gb": round((total - free) / (1024 ** 3), 1),
            "free_gb": round(free / (1024 ** 3), 1),
            "name": torch.cuda.get_device_name(0),
            "gpu_count": torch.cuda.device_count(),
        }
    except Exception:
        return {"available": False}
