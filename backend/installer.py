"""
VideoLingoFlow 后端依赖安装脚本
功能:
1. 检测CUDA版本
2. 根据CUDA版本安装PyTorch 2.8三件套
3. 安装其他依赖
"""
import subprocess
import sys
import os
import re
from pathlib import Path

# 配置
PYTORCH_VERSION = "2.8.0"
TORCHVISION_VERSION = "0.23.0"
TORCHAUDIO_VERSION = "2.8.0"

# PyTorch CUDA版本映射（torch 2.8 官方发布 cu128/cu126/cu124/cu118/cpu）
TORCH_CUDA_VERSIONS = {
    "12.8": "cu128",
    "12.6": "cu126",
    "12.4": "cu124",
    "11.8": "cu118",
}

# PyTorch 镜像源 (国内加速)
TORCH_MIRRORS = {
    "default": "https://download.pytorch.org/whl",
    "aliyun": "https://mirrors.aliyun.com/pytorch-wheels",
    "tsinghua": "https://mirrors.tuna.tsinghua.edu.cn/pytorch-wheels",
}

PIP_MIRRORS = {
    "aliyun": "https://mirrors.aliyun.com/pypi/simple/",
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple/",
    "douban": "https://pypi.douban.com/simple/",
}


def run_cmd(cmd, check=True, capture=True):
    """运行命令并返回结果"""
    print(f"[执行] {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, check=check,
            capture_output=capture, text=True,
            encoding='utf-8', errors='replace'
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"[错误] 命令执行失败: {e}")
        if e.stderr:
            print(f"[错误输出] {e.stderr}")
        return e


def get_cuda_version():
    """检测CUDA版本"""
    print("\n" + "="*60)
    print("  检测CUDA环境")
    print("="*60)
    
    # 方法1: 通过nvidia-smi检测
    try:
        result = subprocess.run(
            "nvidia-smi", shell=True, capture_output=True, text=True
        )
        if result.returncode == 0:
            # 从nvidia-smi输出中提取CUDA版本
            match = re.search(r"CUDA(?: UMD)? Version:\s*(\d+\.\d+)", result.stdout)
            if match:
                cuda_version = match.group(1)
                print(f"[成功] 检测到CUDA版本: {cuda_version}")
                return cuda_version
    except Exception:
        pass
    
    # 方法2: 通过nvcc检测
    try:
        result = subprocess.run(
            "nvcc --version", shell=True, capture_output=True, text=True
        )
        if result.returncode == 0:
            match = re.search(r"release (\d+\.\d+)", result.stdout)
            if match:
                cuda_version = match.group(1)
                print(f"[成功] 检测到CUDA版本 (nvcc): {cuda_version}")
                return cuda_version
    except Exception:
        pass
    
    # 方法3: 检查环境变量CUDA_PATH
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        version_file = os.path.join(cuda_path, "version.txt")
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                content = f.read()
                match = re.search(r"CUDA Version (\d+\.\d+)", content)
                if match:
                    cuda_version = match.group(1)
                    print(f"[成功] 检测到CUDA版本 (CUDA_PATH): {cuda_version}")
                    return cuda_version
    
    print("[警告] 未检测到CUDA，将安装CPU版本的PyTorch")
    return None


def get_torch_cuda_tag(cuda_version):
    """根据CUDA版本获取PyTorch CUDA标签"""
    if cuda_version is None:
        return "cpu"

    # 解析主版本号
    major, minor = cuda_version.split('.')
    cuda_key = f"{major}.{minor}"

    # 查找匹配的CUDA版本（取不高于本机CUDA的最高支持版本）
    for supported_cuda in sorted(TORCH_CUDA_VERSIONS.keys(), reverse=True):
        s_major, s_minor = supported_cuda.split('.')
        if int(major) > int(s_major) or (int(major) == int(s_major) and int(minor) >= int(s_minor)):
            tag = TORCH_CUDA_VERSIONS[supported_cuda]
            if supported_cuda == "12.8":
                print(f"[提示] PyTorch {PYTORCH_VERSION} 最高提供 cu128（CUDA 12.8）构建；检测到驱动能力 CUDA {cuda_version} ≥ 12.8，")
                print(f"       驱动向下兼容，将安装 {tag}，无需额外安装 CUDA Toolkit。")
            else:
                print(f"[提示] 检测到 CUDA {cuda_version} 低于推荐 12.8，将安装 {tag} 兼容构建；")
                print(f"       如需完整支持，建议升级驱动/CUDA 至 12.8+：https://developer.nvidia.com/cuda-12-8-2-download-archive")
            return tag

    # CUDA 版本过低（低于 11.8）：cu118 构建无法在其上运行，回退 CPU
    print(f"[警告] CUDA {cuda_version} 过低，PyTorch CUDA 构建最低要求 11.8，将安装 CPU 版")
    return "cpu"


def _torch_packages(cuda_tag) -> dict:
    """返回当前平台 / CUDA 标签下期望的 {包名: 安装规格}。"""
    if sys.platform == "darwin":
        # macOS：官方 wheel 无 +cpu/+cuXXX 后缀
        return {
            "torch": f"torch=={PYTORCH_VERSION}",
            "torchvision": f"torchvision=={TORCHVISION_VERSION}",
            "torchaudio": f"torchaudio=={TORCHAUDIO_VERSION}",
        }
    suffix = f"+{cuda_tag}" if cuda_tag else "+cpu"
    return {
        "torch": f"torch=={PYTORCH_VERSION}{suffix}",
        "torchvision": f"torchvision=={TORCHVISION_VERSION}{suffix}",
        "torchaudio": f"torchaudio=={TORCHAUDIO_VERSION}{suffix}",
    }


def _missing_torch_packages(cuda_tag) -> list:
    """返回需要（重新）安装的包规格列表；已安装且版本/标签匹配的不包含。"""
    import importlib.metadata as md

    missing = []
    for pkg, spec in _torch_packages(cuda_tag).items():
        want = spec.split("==", 1)[1]
        try:
            got = md.version(pkg)
        except md.PackageNotFoundError:
            print(f"[提示] 未安装 {pkg}，需要安装")
            missing.append(spec)
            continue
        if got != want:
            print(f"[提示] {pkg} 已安装 {got} ≠ 期望 {want}，需要重新安装")
            missing.append(spec)
    return missing


def _torch_installed_ok(cuda_tag: str) -> bool:
    """检查当前解释器环境是否已安装匹配版本/CUDA 标签的 PyTorch 三件套。"""
    return not _missing_torch_packages(cuda_tag)


def _verify_torch_installed() -> bool:
    """验证并打印 PyTorch 安装结果。"""
    print("[步骤3] 验证PyTorch安装...")
    try:
        import torch
        print(f"[成功] torch版本: {torch.__version__}")
        print(f"[成功] CUDA可用: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"[成功] CUDA设备: {torch.cuda.get_device_name(0)}")
    except ImportError:
        print("[错误] PyTorch安装失败")
        return False
    return True


def install_pytorch(cuda_tag, mirror="default"):
    """安装PyTorch三件套（按平台/CUDA 版本适配）

    策略：
      1. 只重装缺失 / 版本或 CUDA 标签不符的子包，已匹配的不动
      2. 镜像源失败时自动回退 PyTorch 官方源，最后回退 PyPI 默认源
    """
    print("\n" + "="*60)
    print(f"  安装PyTorch {PYTORCH_VERSION} (CUDA: {cuda_tag})")
    print("="*60)

    # 只处理需要安装的组件
    missing = _missing_torch_packages(cuda_tag)
    if not missing:
        print(f"[OK] venv 中已安装匹配的 PyTorch {PYTORCH_VERSION}+{cuda_tag}，跳过卸载与重装")
        return _verify_torch_installed()

    # 官方源（兜底）
    if sys.platform == "darwin":
        official_index = None
    elif cuda_tag == "cpu":
        official_index = "https://download.pytorch.org/whl/cpu"
    else:
        official_index = f"https://download.pytorch.org/whl/{cuda_tag}"

    # 国内镜像源（可选加速，失败会回退到官方源）
    mirror_index = None
    if mirror in TORCH_MIRRORS and mirror != "default" and official_index is not None:
        mirror_index = f"{TORCH_MIRRORS[mirror]}/{cuda_tag}"

    # 只卸载需要重装的包
    to_uninstall = [spec.split("==", 1)[0] for spec in missing]
    print(f"[步骤1] 卸载需要重装的组件: {', '.join(to_uninstall)}")
    run_cmd(f"{sys.executable} -m pip uninstall -y {' '.join(to_uninstall)}", check=False)

    # 安装：镜像源 → 官方源 → PyPI 默认源，逐级回退
    print(f"[步骤2] 安装 {len(missing)} 个 PyTorch 组件（失败自动回退下一个源）...")
    for spec in missing:
        sources = []
        for index in (mirror_index, official_index, None):
            if index not in sources:
                sources.append(index)
        installed = False
        for index in sources:
            cmd = f"{sys.executable} -m pip install {spec} --no-cache-dir"
            if index:
                cmd += f" --extra-index-url {index}"
            result = run_cmd(cmd, check=False)
            if result.returncode == 0:
                installed = True
                break
            print(f"[警告] 从 {index or 'PyPI 默认源'} 安装 {spec} 失败，尝试下一个源...")
        if not installed:
            print(f"[错误] {spec} 安装失败（已尝试镜像源与官方源），验证步骤会体现")

    return _verify_torch_installed()


def install_requirements():
    """安装其他依赖"""
    print("\n" + "="*60)
    print("  安装其他依赖")
    print("="*60)
    
    requirements_file = Path(__file__).parent / "requirements.txt"
    
    if not requirements_file.exists():
        print(f"[错误] 依赖文件不存在: {requirements_file}")
        return False
    
    print(f"[信息] 使用依赖文件: {requirements_file}")
    
    # 配置pip镜像
    pip_mirror = PIP_MIRRORS["aliyun"]
    
    # 安装依赖
    cmd = f'{sys.executable} -m pip install -r "{requirements_file}" -i {pip_mirror} --trusted-host mirrors.aliyun.com --no-cache-dir'
    result = run_cmd(cmd, check=False)
    
    if result.returncode != 0:
        print("[警告] 部分依赖安装失败，尝试逐个安装...")
        # 逐个安装
        with open(requirements_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    cmd = f'{sys.executable} -m pip install "{line}" -i {pip_mirror} --trusted-host mirrors.aliyun.com'
                    run_cmd(cmd, check=False)
    
    return True


def verify_installation():
    """验证安装结果"""
    print("\n" + "="*60)
    print("  验证安装结果")
    print("="*60)
    
    packages = [
        ("torch", "PyTorch"),
        ("torchvision", "TorchVision"),
        ("torchaudio", "TorchAudio"),
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("cv2", "OpenCV (headless)"),
        ("PIL", "Pillow"),
        ("yt_dlp", "yt-dlp"),
    ]
    
    success_count = 0
    for module, name in packages:
        try:
            __import__(module)
            print(f"[OK] {name}")
            success_count += 1
        except ImportError:
            print(f"[FAIL] {name}")
    
    print(f"\n[结果] 成功安装 {success_count}/{len(packages)} 个包")
    return success_count == len(packages)


def main():
    """主函数"""
    print("="*60)
    print("  VideoLingoFlow 后端依赖安装脚本")
    print(f"  PyTorch版本: {PYTORCH_VERSION}")
    print("="*60)
    
    # 1. 检测CUDA版本
    cuda_version = get_cuda_version()
    cuda_tag = get_torch_cuda_tag(cuda_version)
    
    print(f"\n[决策] 将安装 {cuda_tag} 版本的PyTorch")
    
    # 2. 安装PyTorch
    if not install_pytorch(cuda_tag):
        print("[错误] PyTorch安装失败，退出")
        sys.exit(1)
    
    # 3. 安装其他依赖
    if not install_requirements():
        print("[错误] 依赖安装失败")
        sys.exit(1)
    
    # 4. 验证安装
    if verify_installation():
        print("\n" + "="*60)
        print("  安装完成!")
        print("="*60)
    else:
        print("\n[警告] 部分依赖可能未正确安装，请检查上方错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
