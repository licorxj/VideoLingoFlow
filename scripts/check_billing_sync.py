#!/usr/bin/env python
"""校验计费源码与已部署编译产物是否同源（r3 §13.2 #3）。

**要解决的问题**

改了 `backend/auth/*.py`（或 `backend/control_plane/*.py`）却忘了重新编译分发，
于是公开仓库里分发的 `.pyd` / `.so` 仍是旧逻辑。这类问题只在运行时才暴露，
且"源码看着是新的、行为却是旧的"，极难排查（本项目的第 7、8 条坑位都与此有关）。

**判定依据**

编译产物内 `manifest.json` 的 `source_sha` 字段，由计费子仓库的
`.github/workflows/build-release.yml` 在打包时写入。本脚本按**完全相同的
算法与文件顺序**计算当前源码指纹并比对。

**用法**

    python scripts/check_billing_sync.py                 # 校验全部已部署平台
    python scripts/check_billing_sync.py --target win-amd64

**退出码**

    0 = 同源（或仅有"缺指纹"提示）
    1 = 存在不同源产物（源码改了但没重编）→ 应重新编译后再分发

> 说明：`source_sha` 自 v2.0.10 起写入。更早版本的产物没有该字段，脚本会给出
> `[??]` 提示而不是误报，先用新工作流编译一次即可启用校验。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARIES = ROOT / "backend" / "auth_binaries" / "cp312"
TARGETS = ("win-amd64", "linux-x86_64", "macos-arm64")

# ⚠️ 必须与子仓库 .github/workflows/build-release.yml 里的 SOURCE_FILES 逐项一致：
#    文件清单与**顺序**都参与哈希计算，任何一边改动都要同步另一边。
SOURCE_FILES = (
    "backend/auth/cloud_auth_client.py",
    "backend/auth/cloud_auth_service.py",
    "backend/auth/subscription_guard.py",
    "backend/auth/secure_config.py",
    "backend/auth/error_codes.json",
    "backend/control_plane/workflow_runtime.py",
    "backend/control_plane/runtime.py",
    "backend/control_plane/custom_node_runtime.py",
)


def source_fingerprint(newline: str = "lf") -> str:
    """按顺序累加各源码文件的内容哈希（文件名与分隔符也参与，防止换名重排）。

    `newline` 控制换行规范化方式，默认 `"lf"`：

      - `"lf"` / `"crlf"`：先把换行统一后再参与哈希；
      - `"raw"`：按文件原样（不做规范化）。

    **为什么必须规范化**：同一份源码在 Windows runner（`core.autocrlf=true`）
    上 checkout 出 CRLF、在 Linux/macOS 上出 LF，若按原样哈希，会导致
    v2.0.10 起各平台 `source_sha` 互不相同、且与本机（常见为混合换行）
    都对不上，同源校验将永久误报。规范化 LF 后各平台指纹一致。
    """
    digest = hashlib.sha256()
    for rel in SOURCE_FILES:
        path = ROOT / rel
        body = path.read_bytes() if path.is_file() else b""
        if newline == "lf":
            body = body.replace(b"\r\n", b"\n")
        elif newline == "crlf":
            body = body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(body)
    return digest.hexdigest()


def check_target(target: str, expected: str, expected_crlf: str) -> tuple[bool | None, str]:
    """返回 (True 同源 / False 不同源 / None 无法判定, 说明文本)。

    `expected_crlf` 用于兼容由**旧算法**（未做换行规范化）在 Windows runner 上
    编译出的产物（v2.0.11 之前）：其指纹等于 CRLF 变体，属换行差异而非源码漂移。
    """
    manifest_path = BINARIES / target / "manifest.json"
    if not manifest_path.is_file():
        return False, f"{target}: 未找到 manifest.json（产物缺失）"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"{target}: manifest 解析失败（{exc}）"

    recorded = str(manifest.get("source_sha") or "")
    version = manifest.get("version")
    if not recorded:
        return None, (
            f"{target}: manifest 缺少 source_sha（产物 version={version} 由旧版工作流生成），"
            f"需用含指纹的新工作流重新编译一次才能启用同源校验"
        )
    if recorded == expected:
        return True, f"{target}: 同源（产物 version={version}）"
    if recorded == expected_crlf:
        return True, (
            f"{target}: 同源（产物 version={version}；指纹为 CRLF 变体，由 v2.0.11 之前的"
            f"旧算法在 Windows runner 上生成，属换行差异）"
        )
    return False, (
        f"{target}: **源码与产物不同源**（产物 version={version}）\n"
        f"        当前源码指纹: {expected}\n"
        f"        产物记录指纹: {recorded}\n"
        f"        → 源码改过但未重新编译，请按《收费代码编译流程》重新编译并部署产物"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验计费源码与编译产物是否同源")
    parser.add_argument("--target", choices=TARGETS, help="只校验指定平台（默认全部）")
    args = parser.parse_args()

    expected = source_fingerprint("lf")
    expected_crlf = source_fingerprint("crlf")
    print(f"当前源码指纹（{len(SOURCE_FILES)} 个文件，换行规范化为 LF）: {expected}")
    print()

    targets = (args.target,) if args.target else TARGETS
    mismatched: list[str] = []
    unverifiable: list[str] = []
    checked = 0

    for target in targets:
        if not (BINARIES / target).is_dir():
            print(f"  [--]  {target}: 未部署（跳过）")
            continue
        ok, message = check_target(target, expected, expected_crlf)
        checked += 1
        if ok is True:
            print(f"  [OK]  {message}")
        elif ok is None:
            unverifiable.append(target)
            print(f"  [??]  {message}")
        else:
            mismatched.append(target)
            print(f"  [!!]  {message}")

    print()
    if mismatched:
        print(f"结果：**失败** —— {', '.join(mismatched)} 的产物与当前源码不同源，请重新编译后再分发。")
        return 1
    if unverifiable:
        print(f"结果：通过（但 {', '.join(unverifiable)} 缺少指纹，暂无法校验；下次编译后自动生效）")
        return 0
    if checked == 0:
        print("结果：未发现任何已部署平台，无需校验。")
        return 0
    print("结果：**通过** —— 已部署产物与当前源码同源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
