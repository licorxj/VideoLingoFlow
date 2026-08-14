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
            match = re.search(r"CUDA Version:\s*(\d+\.\d+)", result.stdout)
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
            return TORCH_CUDA_VERSIONS[supported_cuda]

    # CUDA 版本过低（低于 11.8）：cu118 构建无法在其上运行，回退 CPU
    print(f"[警告] CUDA {cuda_version} 过低，PyTorch CUDA 构建最低要求 11.8，将安装 CPU 版")
    return "cpu"


def install_pytorch(cuda_tag, mirror="default"):
    """安装PyTorch三件套（按平台/CUDA 版本适配）"""
    print("\n" + "="*60)
    print(f"  安装PyTorch {PYTORCH_VERSION} (CUDA: {cuda_tag})")
    print("="*60)

    # macOS 无 CUDA：使用 PyPI 官方 wheel（含 MPS 支持），不加 +cpu 后缀
    if sys.platform == "darwin":
        extra_index = None
        packages = [
            f"torch=={PYTORCH_VERSION}",
            f"torchvision=={TORCHVISION_VERSION}",
            f"torchaudio=={TORCHAUDIO_VERSION}",
        ]
    # 构建安装命令
    elif cuda_tag == "cpu":
        extra_index = f"https://download.pytorch.org/whl/cpu"
        packages = [
            f"torch=={PYTORCH_VERSION}+cpu",
            f"torchvision=={TORCHVISION_VERSION}+cpu",
            f"torchaudio=={TORCHAUDIO_VERSION}+cpu",
        ]
    else:
        extra_index = f"https://download.pytorch.org/whl/{cuda_tag}"
        packages = [
            f"torch=={PYTORCH_VERSION}+{cuda_tag}",
            f"torchvision=={TORCHVISION_VERSION}+{cuda_tag}",
            f"torchaudio=={TORCHAUDIO_VERSION}+{cuda_tag}",
        ]

    # 使用国内镜像加速
    if mirror in TORCH_MIRRORS and extra_index is not None:
        extra_index = f"{TORCH_MIRRORS[mirror]}/{cuda_tag}"
    
    # 卸载旧版本
    print("[步骤1] 卸载旧版本PyTorch...")
    run_cmd("pip uninstall -y torch torchvision torchaudio", check=False)
    
    # 安装新版本
    print(f"[步骤2] 安装PyTorch三件套...")
    for pkg in packages:
        cmd = f'pip install {pkg} --no-cache-dir'
        if extra_index:
            cmd += f' --extra-index-url {extra_index}'
        result = run_cmd(cmd, check=False)
        if result.returncode != 0:
            print(f"[警告] 安装 {pkg} 失败，尝试使用国内镜像...")
            # 尝试使用阿里云镜像
            cmd = f'pip install {pkg} -i {PIP_MIRRORS["aliyun"]} --trusted-host mirrors.aliyun.com'
            if extra_index:
                cmd += f' --extra-index-url {extra_index}'
            run_cmd(cmd, check=True)
    
    # 验证安装
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
    cmd = f'pip install -r "{requirements_file}" -i {pip_mirror} --trusted-host mirrors.aliyun.com --no-cache-dir'
    result = run_cmd(cmd, check=False)
    
    if result.returncode != 0:
        print("[警告] 部分依赖安装失败，尝试逐个安装...")
        # 逐个安装
        with open(requirements_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    cmd = f'pip install "{line}" -i {pip_mirror} --trusted-host mirrors.aliyun.com'
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
