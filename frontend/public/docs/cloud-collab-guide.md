# 云控（公网远程协作）安装指南

> 本指南说明如何把软件的**局域网协作**升级为**公网远程协作**（云控）。云控是**可选项**：不开云控，局域网协作照常使用；开了云控，任意地点的浏览器都能访问你的协作平台。
>
> 云控依赖的外部组件（cloudflared）**不在软件分发安装包内**，需要时按本指南单独安装配置，不影响软件本身使用。

---

## 1. 云控能实现什么（简介）

- **公网访问**：把唯一的 11001 端口（前端页面 + API + WebSocket 同一入口）映射到你的域名，任何网络环境下的浏览器都能打开协作平台。
- **零端口暴露**：主机无需公网 IP、无需路由器端口映射、无需开放任何入站端口；隧道是"出站"连接，安全性高。
- **自动 HTTPS**：Cloudflare 自动提供加密证书，公网全程加密传输。
- **身份门禁（可选但强烈推荐）**：通过 Cloudflare Access，只有你指定的邮箱账号能进入，未授权人员连页面都打不开。
- **能力不变**：公网下的功能与局域网完全一致——协作登录、成员审批、在线状态、任务进度、资产上传下载、工作区文件。
- **算力仍在主机**：云控只做"远程通道"，任务执行、数据存储仍在你的主机本地。

## 2. 先决条件（需要额外准备什么）

| 条件 | 说明 | 是否必须 |
|---|---|---|
| **域名** | 一个已注册的域名（如 example.com），且 **DNS 已托管到 Cloudflare**（nameserver 指向 Cloudflare） | 必须 |
| **Cloudflare 账号** | 免费即可 | 必须 |
| **主机电脑** | 运行本软件的电脑，能正常出网、建议 7x24 在线 | 必须 |
| **公网 IP / 端口映射** | 不需要 | 无需 |
| **cloudflared** | Cloudflare 官方客户端，按第 3 节安装 | 必须（仅云控需要） |

> 若你的域名尚未托管到 Cloudflare，请先完成第 4.1 节；**没有 Cloudflare 托管的域名无法继续**。

## 3. 需要安装的东西与安装方法

云控只需安装**一个外部程序：cloudflared**（软件本身已在主机装好）。

### 3.1 Windows 安装 cloudflared

**方式 A：winget 安装（推荐）**
1. 打开 PowerShell 或命令提示符。
2. 执行：
   ```bat
   winget install cloudflare.cloudflared
   ```
3. 安装后新开一个终端，验证：
   ```bat
   cloudflared --version
   ```
   能输出版本号即成功。

**方式 B：官网下载二进制**
1. 打开 Cloudflare 官方下载页（`developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/`），下载 Windows 64 位 `cloudflared-windows-amd64.exe`。
2. 把文件改名为 `cloudflared.exe`，放到固定目录（建议 `C:\Program Files (x86)\cloudflared\`）。
3. 建议把该目录加入系统 PATH，或在后续命令中使用完整路径。

### 3.2 其它安装项（可选）

| 项目 | 用途 | 何时需要 |
|---|---|---|
| 隧道开机自启 | `cloudflared service install` 注册为 Windows 服务，开机自动运行隧道 | 长期对外提供服务时 |
| 关闭 Windows 防火墙阻止 | 首次运行 `cloudflared tunnel run` 时如弹防火墙提示，允许访问 | 按提示处理即可 |

## 4. Cloudflare 从注册到部署到设置的全流程

### 4.1 注册账号与域名托管

1. **注册 Cloudflare**：打开 `dash.cloudflare.com` 注册账号（邮箱 + 密码即可，免费套餐够用）。
2. **注册域名**：在任意域名注册商（阿里云 / 腾讯云 / Namecheap 等）注册你的域名（若还没有）。
3. **添加站点到 Cloudflare**：
   - Cloudflare 控制台 → "Add a site" → 输入你的域名 → 选免费套餐 → 继续。
   - Cloudflare 会给你两个 nameserver 地址（形如 `aaa.ns.cloudflare.com`、`bbb.ns.cloudflare.com`）。
4. **修改域名 NS 记录**：去你的域名注册商后台，把该域名的 nameserver 改为 Cloudflare 给的那两个地址。
5. **等待生效**：生效时间通常几分钟到几小时。Cloudflare 控制台显示站点状态为 **Active** 即托管完成。

> 完成此步后，你的域名才由 Cloudflare 管理 DNS，后续隧道绑定域名、Access 门禁都依赖它。

### 4.2 部署：创建隧道（两种方式选一）

#### 方式 A：一键脚本（推荐，软件自带）

软件根目录提供 `setup_cloudflare_tunnel.bat`，按提示操作即可，脚本自动完成 4.2 的登录 / 建隧道 / 生成配置 / 绑定 DNS / 运行：

1. **建议先改脚本中的 `HOST` 变量**（第 7 行），换成你自己的子域名，如 `vlflow.yourdomain.com`（用记事本打开脚本修改保存）。
2. **管理员身份**双击运行脚本（或右键"以管理员身份运行"）。
3. 按提示操作：登录授权 → 自动创建隧道 → 生成配置 → 绑定 DNS → 启动隧道。
4. 出现隧道在线日志（`Registered tunnel connection`）即成功。

#### 方式 B：手动配置（了解原理）

```bat
:: 1. 登录 Cloudflare（自动打开浏览器，点击 Authorize 授权）
cloudflared tunnel login

:: 2. 创建隧道（名字随意，如 videolingo）
cloudflared tunnel create videolingo
```

3. 编辑配置文件 `C:\Users\你的用户名\.cloudflared\config.yml`：

```yaml
tunnel: videolingo
credentials-file: C:\Users\<你的用户名>\.cloudflared\<隧道ID>.json
ingress:
  - hostname: vlflow.yourdomain.com
    service: http://127.0.0.1:11001
  - service: http_status:404   # 其它域名一律 404
```

> 隧道 ID 可在 `~/.cloudflared/` 下以隧道 ID 命名的 `.json` 文件查看（文件内容里的 `id` 字段，也是文件名）。

```bat
:: 4. 绑定域名（自动在 Cloudflare DNS 建 CNAME 记录）
cloudflared tunnel route dns videolingo vlflow.yourdomain.com

:: 5. 启动隧道（保持此窗口开启即在线）
cloudflared tunnel run videolingo
```

### 4.3 设置：Cloudflare 后台配置

#### 4.3.1 规划子域名

建议使用专用子域名，例如 `vlflow` + 你的域名。示例：`vlflow.yourdomain.com`。

#### 4.3.2 开启 Cloudflare Access 身份门禁（强烈推荐，先于对外发布）

> 作用：在"应用层"之前先加一道"身份层"——只有你批准的邮箱账号能通过 Cloudflare 的登录页验证，未授权人员连页面、API、WebSocket 都访问不到。

1. 登录 Cloudflare 控制台 → 左侧菜单 **Zero Trust** → **Access** → **Applications**。
2. 点 **Add an application** → 选择 **Self-hosted**。
3. **新版界面按三段式设置目的地（Destinations）**：
   - **Subdomain**：填 `vlflow`
   - **Domain**：选择或填你的域名 `yourdomain.com`
   - **Path**：填 `*`
   - 下方会实时拼出规则，形如 `vlflow.yourdomain.com/*`
4. 配置 **Policy**（登录策略）：
   - 名称随意（如 `collab-members`），Action 选 **Allow**。
   - 规则选择 **Emails** → 添加允许访问的邮箱（管理员 / 协作成员的邮箱，多个用 OR 连接）。
5. 保存。此时访问域名会跳转 Cloudflare 登录页，输入允许的邮箱后通过验证码登录。

> 强烈建议**先配置好 Access 并验证拦截生效，再对外发布/分享域名**，避免未授权访问。

#### 4.3.3 打开软件内的"远程网络协作"开关（关键步骤）

软件侧的远程通道默认关闭（安全起见），需手动开启：

1. 本机打开软件 → 进入**多人协作**页。
2. 顶栏右侧找到 **远程网络协作** 开关 → 打开。
3. 弹出提示后，**重启管理器**使其生效。
4. 重启后再次进入多人协作页，确认"远程网络协作"开关处于开启状态。

> 此开关关闭时，公网域名访问会返回 403（"远程网络协作已关闭"），本机与局域网访问不受影响。

### 4.4 常用运维

| 操作 | 命令 |
|---|---|
| 隧道开机自启（注册为 Windows 服务） | `cloudflared service install` |
| 查看隧道是否在线 | `cloudflared tunnel list` / `cloudflared tunnel info videolingo` |
| 停止隧道 | 关闭运行 `tunnel run` 的窗口，或 `cloudflared service uninstall`（若已注册服务） |
| 完全下线公网入口（回滚） | Cloudflare 控制台删除该 DNS CNAME 记录；`cloudflared tunnel delete videolingo` |

## 5. 验证清单

- [ ] `cloudflared --version` 输出版本号
- [ ] 运行隧道后日志出现 `Registered tunnel connection`
- [ ] 手机热点（非本机网络）浏览器访问 `https://vlflow.yourdomain.com`：能打开前端页面
- [ ] 未授权邮箱访问被 Cloudflare Access 登录页拦截
- [ ] 用授权邮箱通过 Access 登录后，进入多人协作页，用 admin 或成员账号登录协作成功
- [ ] 多人协作页"远程网络协作"开关处于开启状态
- [ ] 两台不同网络的设备同时在线，互相可见在线/编辑状态、任务进度推送
- [ ] 资产上传 / 下载、工作区文件浏览正常

## 6. 常见问题（FAQ）

| 现象 | 原因 | 解决 |
|---|---|---|
| 浏览器访问显示 **530** | 隧道未运行 / 运行窗口被关闭 | 重新运行 `cloudflared tunnel run videolingo`，保持窗口开启 |
| 访问提示 **403 远程网络协作已关闭** | 软件内远程开关未开启 | 多人协作页打开"远程网络协作"开关（立即生效，无需重启） |
| 登录 Cloudflare 时报错 / 隧道创建失败 | 网络无法访问 Cloudflare 或未登录 | 重试 `cloudflared tunnel login`；检查主机能否访问外网 |
| 域名一直不生效 | 域名未托管到 Cloudflare / NS 修改未生效 | 确认 Cloudflare 站点状态为 Active；等 NS 生效 |
| Access 配置界面与文档对不上 | Cloudflare 新版界面为三段式 | 按"Subdomain / Domain / Path"三段填写，Path 填 `*` |
| 大文件上传失败 | Cloudflare 免费版上传体积限制 | 控制文件体积或升级套餐；大文件建议走对象存储直传 |

## 7. 说明：cloudflared 是可选项

- 软件分发安装包**不包含** cloudflared，也**不需要**它来运行软件本身。
- 仅当你要对外提供**公网远程协作**时，才需要按本指南安装并配置 cloudflared。
- 不开云控：局域网协作、任务执行、资产共享等全部功能不受影响，照常使用。
