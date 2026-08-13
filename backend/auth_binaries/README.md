# auth_binaries — 受保护认证模块编译产物（分平台）

本目录用于存放私有编译仓库 `licorxj/videolingo-billing-core` Release 归档中的
`backend/auth` 编译扩展（CPython 3.12），不提交任何 `.pyd` / `.so` 二进制。

## 目录结构

```text
backend/auth_binaries/cp312/<target>/backend/auth/
    cloud_auth_client.<ext>
    cloud_auth_service.<ext>
    subscription_guard.<ext>
    error_codes.json
```

`<target>` 取值（与编译仓库一致）：

- `win-amd64`     —— Windows x64（`.cp312-win_amd64.pyd`）
- `linux-x86_64`  —— Linux x64（`.cpython-312-x86_64-linux-gnu.so`）
- `macos-arm64`   —— macOS Apple Silicon（`.cpython-312-darwin.so`）
- `macos-x86_64`  —— macOS Intel（已停止支持，不再更新）

## 安装说明

1. 从 Release 页下载对应平台归档，例如 `videolingo-billing-core-v1.0.3-cp312-win-amd64.zip`。
2. 将归档内的 `backend/auth/*` 复制到本目录对应 `<target>` 下。
3. `error_codes.json` 必须与扩展模块同目录（编译后的 `cloud_auth_service` 按
   `__file__` 定位该文件）。

`backend/auth/__init__.py` 会在 CPython 3.12 且存在匹配平台目录时优先加载这些
编译模块；缺失时自动回退公开源码。
