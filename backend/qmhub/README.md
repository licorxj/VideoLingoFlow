# qmhub - 能力Hub Python SDK

`qmhub` 是**能力Hub (Capability Hub)** 系统的 Python SDK，封装了 `/api/capability/*` 接口，
支持能力列表查询、能力调用（同步/异步）、异步任务轮询，并内置**视频水印擦除**高层方法。

> 注意：本 SDK 对接后端 `POST /api/capability/invoke`、`GET /api/capability/tasks/{id}` 等接口，
> 使用 **Bearer API Key** 认证（即能力 Hub 中创建的 API Key）。

## 安装

```bash
cd sdk
pip install .
```

## 快速开始

### 1. 初始化客户端

```python
from qmhub import QmHubClient

# base_url 默认 https://www.licorxj.online（前端转发 /api，无需暴露端口），可省略
client = QmHubClient(
    api_key="cbk_xxxx",                 # 能力 Hub 创建的 API Key
)
```

### 2. 列出 / 查询能力

```python
caps = client.capabilities.list()      # 已公开且启用的能力列表
cap = client.capabilities.get("video-watermark-removal")   # 单个能力详情
```

### 3. 调用能力（通用）

```python
# 同步能力
res = client.invoke.create(
    slug="some-sync-cap",
    input_url="https://example.com/a.png",
)
print(res["status"], res.get("result_url"))

# 异步能力（返回 processing + request_id，需轮询）
res = client.invoke.create(
    slug="video-watermark-removal",
    input_url="https://example.com/v.mp4",
    params={"mode": "protect"},
)
if res["status"] == "processing":
    final = client.wait_for_task(res["request_id"], poll_interval=30, timeout=1800)
```

### 4. 视频水印擦除（高层封装，推荐）

```python
result = client.video_watermark.remove(
    video_url="https://example.com/video.mp4",
    # 水印范围坐标（可选，默认全 0）
    x1=100, y1=100, x2=400, y2=300,
    mode="protect",          # "normal"（默认）或 "protect"
    poll=True,               # 阻塞轮询直到完成（默认 True）
    poll_interval=30,        # 轮询间隔（秒，建议 30~60）
    timeout=1800,            # 总超时（秒）
)
print(result["status"])             # success / failed
print(result["result_url"])          # 处理后视频地址（success 时）
print(result.get("duration_seconds"))  # 视频时长（秒）
print(result.get("billing_seconds"))   # 计费秒数
print(result.get("fee"))               # 本次费用（分）
```

仅提交不等待：

```python
submitted = client.video_watermark.submit(
    video_url="https://example.com/video.mp4",
    mode="normal",
)
request_id = submitted["request_id"]

# 之后随时查询
status = client.video_watermark.status(request_id)
```

### 5. 计费说明（视频水印擦除）

- 按视频时长（秒）计费：**1.5 分钱/秒**。
- 不足 **10 秒** 按 **10 秒** 收取。
- **处理失败不扣费**；成功后才扣减用户积分（1 积分 = 1 分钱）。

### 6. 邮箱转发（完整功能）

封装后端 `/api/mail-forwarding/*` 用户端接口，覆盖虚拟邮箱、转发目标、入站邮件与投递记录。

```python
# 功能配置（公开，无需登录）
cfg = client.mail_forwarding.get_config()
print(cfg["mail_domain"], cfg["max_mailboxes"], cfg["points_per_target"])

# 虚拟邮箱
mbox = client.mail_forwarding.generate_mailbox()      # 生成一个随机虚拟邮箱
print(mbox["address"], mbox["id"])

mboxes = client.mail_forwarding.list_mailboxes()      # 列出我的全部虚拟邮箱
client.mail_forwarding.enable_mailbox(mbox["id"])     # 启用
client.mail_forwarding.disable_mailbox(mbox["id"])    # 停用
client.mail_forwarding.delete_mailbox(mbox["id"])     # 删除（不可恢复）

# 转发目标（需先验证才能生效）
client.mail_forwarding.send_verification_code(mbox["id"], "me@gmail.com")
target = client.mail_forwarding.verify_target(mbox["id"], "me@gmail.com", "1234")
print(target["verification_status"])                  # verified

targets = client.mail_forwarding.list_targets(mbox["id"])
client.mail_forwarding.delete_target(mbox["id"], targets[0]["id"])

# 入站邮件 / 投递记录（分页）
inbounds = client.mail_forwarding.list_inbound_mails(mbox["id"], page=1, page_size=20)
deliveries = client.mail_forwarding.list_deliveries(
    mbox["id"], inbound_mail_id=None, page=1, page_size=20,
)
print(inbounds["total"], deliveries["total"])
```

### 7. 主动发送（以虚拟邮箱身份）

通过系统邮箱将内容**直接发送**到目标地址（区别于被动接收转发）。
邮件正文/HTML 会自动追加「来自虚拟邮箱 `<address>` 转发」标识，**每条扣 2 积分**（由 `MAIL_FORWARD_SEND_POINTS` 控制）。

```python
res = client.mail_forwarding.send_mail(
    mailbox_id=mbox["id"],
    to_email="someone@example.com",
    subject="你好",
    body="这是通过我的虚拟邮箱转发的消息内容。",
    html_body="<p>这是通过我的<b>虚拟邮箱</b>转发的消息内容。</p>",  # 可选
)
print(res["sent"], res["message_id"], res["points_charged"])
# True <smtp-id> 2
```

> 注：`mailbox_id` 须归属当前用户且处于 `active` 状态；积分不足将抛出 `InsufficientPointsError`。

完整方法清单：

| 方法 | 说明 |
|------|------|
| `get_config()` | 功能配置（域名/上限/单价） |
| `list_mailboxes()` | 我的全部虚拟邮箱（含统计） |
| `generate_mailbox()` | 生成虚拟邮箱 |
| `update_mailbox_status(id, status)` | 启用/停用（status=active/disabled） |
| `enable_mailbox(id)` / `disable_mailbox(id)` | 便捷开关 |
| `delete_mailbox(id)` | 删除虚拟邮箱 |
| `list_targets(mailbox_id)` | 列出转发目标 |
| `send_verification_code(mailbox_id, email)` | 发送验证验证码 |
| `verify_target(mailbox_id, email, code)` | 验证目标地址 |
| `delete_target(mailbox_id, target_id)` | 移除转发目标 |
| `list_inbound_mails(mailbox_id, page, page_size)` | 入站邮件分页 |
| `list_deliveries(mailbox_id, inbound_mail_id, page, page_size)` | 投递记录分页 |
| `send_mail(mailbox_id, to_email, subject, body, html_body)` | 以虚拟邮箱身份主动发送（2 积分/条） |

## 异常处理

| 异常类 | HTTP/业务码 | 说明 |
|--------|------------|------|
| `QmHubError` | - | 基础异常类 |
| `AuthenticationError` | 401 | 认证失败 |
| `InsufficientPointsError` | 402 | 积分不足 |
| `NotFoundError` | 404 | 资源不存在 |
| `RateLimitError` | 429 | 请求频率超限 |
| `ServerError` | 500+ | 服务器错误 |

```python
from qmhub import QmHubClient, AuthenticationError, InsufficientPointsError

client = QmHubClient(api_key="cbk_xxx")

try:
    result = client.video_watermark.remove(video_url="https://example.com/v.mp4")
except AuthenticationError:
    print("认证失败，请检查 API Key")
except InsufficientPointsError:
    print("积分不足，请充值")
except Exception as e:
    print(f"请求失败: {e}")
```
