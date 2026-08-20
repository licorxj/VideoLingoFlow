"""GPU 显存监测：优先 nvidia-smi，回退 torch.cuda。"""
import os
import subprocess


def gpu_info() -> dict:
    """返回 {available, total_gb, used_gb, free_gb, name}。监测失败时 available=False。"""
    info = _nvidia_smi()
    if info["available"]:
        return info
    return _torch_info()


def _nvidia_smi() -> dict:
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu,name", "--format=csv,noheader,nounits"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=(os.name == "nt"))
        if result.returncode != 0:
            return {"available": False}
        line = result.stdout.strip().splitlines()[0]
        total, used, free, utilization, name = [part.strip() for part in line.split(",")]
        return {
            "available": True,
            "total_gb": round(float(total) / 1024, 1),
            "used_gb": round(float(used) / 1024, 1),
            "free_gb": round(float(free) / 1024, 1),
            "utilization_percent": round(float(utilization), 1),
            "name": name,
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
        }
    except Exception:
        return {"available": False}
