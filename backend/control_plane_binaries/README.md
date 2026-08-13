# control_plane_binaries — 受保护运行中枢编译产物（分平台）

本目录用于存放私有编译仓库 `licorxj/videolingo-billing-core` Release 归档中的
`backend/control_plane/workflow_runtime` 编译扩展（CPython 3.12），
不提交任何 `.pyd` / `.so` 二进制。

## 目录结构

```text
backend/control_plane_binaries/cp312/<target>/backend/control_plane/
    workflow_runtime.<ext>
```

`<target>` 取值（与编译仓库一致）：

- `win-amd64`     —— Windows x64（`.cp312-win_amd64.pyd`）
- `linux-x86_64`  —— Linux x64（`.cpython-312-x86_64-linux-gnu.so`）
- `macos-arm64`   —— macOS Apple Silicon（`.cpython-312-darwin.so`）
- `macos-x86_64`  —— macOS Intel（已停止支持，不再更新）

## 安装说明

1. 从 Release 页下载对应平台归档（必须与 `auth_binaries` 同版本、同平台）。
2. 将归档内的 `backend/control_plane/workflow_runtime.<ext>` 复制到本目录对应
   `<target>` 下。

`backend/control_plane/__init__.py` 会在 CPython 3.12 且存在匹配平台目录时优先
加载该编译模块；缺失时自动回退公开源码。运行中枢内部对数据库、队列与开源节点的
依赖仍在主项目源码树中解析，因此仅需放置本扩展文件。
