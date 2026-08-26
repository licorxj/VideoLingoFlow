"""qmhub - 邮箱转发高层封装

封装后端 /api/mail-forwarding/* 用户端接口，覆盖完整功能：
  - 查询功能配置（域名、上限、单价）
  - 虚拟邮箱：列表 / 生成 / 启用-停用 / 删除
  - 转发目标：列表 / 发送验证码 / 验证 / 删除
  - 入站邮件：分页查询
  - 投递记录：分页查询（可按入站邮件过滤）

认证：使用 Bearer API Key（优先）或用户名/密码（Basic 风格头），
      与 QmHubClient 其他模块一致。

示例：
    from qmhub import QmHubClient

    client = QmHubClient(api_key="cbk_xxx")

    # 生成虚拟邮箱
    mb = client.mail_forwarding.generate_mailbox()
    address = mb["address"]

    # 添加并验证转发目标
    client.mail_forwarding.send_verification_code(mb["id"], "me@gmail.com")
    client.mail_forwarding.verify_target(mb["id"], "me@gmail.com", "1234")

    # 查询入站邮件与投递记录
    inbounds = client.mail_forwarding.list_inbound_mails(mb["id"])
    deliveries = client.mail_forwarding.list_deliveries(mb["id"])
"""


class MailForwardingAPI:
    def __init__(self, client):
        self._client = client

    # ── 功能配置 ──

    def get_config(self) -> dict:
        """
        查询邮箱转发功能配置（域名、上限、单价），公开接口，未登录也可调用。

        Returns:
            {mail_domain, max_mailboxes, max_targets, points_per_target}
        """
        return self._client._request("GET", "/api/mail-forwarding/config") or {}

    # ── 虚拟邮箱 ──

    def list_mailboxes(self) -> list:
        """
        列出当前用户所有未删除的虚拟邮箱（含统计信息）。

        Returns:
            list[dict]: 每个元素含
                id, address, status, verified_targets, total_targets,
                inbound_count, last_delivery_status, created_at
        """
        return self._client._request("GET", "/api/mail-forwarding/mailboxes") or []

    def generate_mailbox(self) -> dict:
        """
        生成一个随机虚拟邮箱地址（归属当前用户）。

        Returns:
            dict: {id, address, status, ...}
        """
        return self._client._request("POST", "/api/mail-forwarding/mailboxes/generate")

    def update_mailbox_status(self, mailbox_id: int, status: str) -> dict:
        """
        启用 / 停用虚拟邮箱。

        Args:
            mailbox_id: 虚拟邮箱 ID
            status: "active"（启用）或 "disabled"（停用）
        Returns:
            {id, status}
        """
        if status not in ("active", "disabled"):
            raise ValueError("status 必须为 'active' 或 'disabled'")
        return self._client._request(
            "PATCH",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}",
            json={"status": status},
        )

    def enable_mailbox(self, mailbox_id: int) -> dict:
        """启用虚拟邮箱（便捷方法）。"""
        return self.update_mailbox_status(mailbox_id, "active")

    def disable_mailbox(self, mailbox_id: int) -> dict:
        """停用虚拟邮箱（便捷方法）。"""
        return self.update_mailbox_status(mailbox_id, "disabled")

    def delete_mailbox(self, mailbox_id: int) -> dict:
        """
        删除虚拟邮箱（不可恢复，地址不可复用）。

        Returns:
            {msg}
        """
        return self._client._request(
            "DELETE", f"/api/mail-forwarding/mailboxes/{mailbox_id}"
        )

    # ── 转发目标 ──

    def list_targets(self, mailbox_id: int) -> list:
        """
        列出某虚拟邮箱下的全部转发目标地址。

        Returns:
            list[dict]: {id, email, verification_status, verified_at, created_at}
        """
        return (
            self._client._request(
                "GET", f"/api/mail-forwarding/mailboxes/{mailbox_id}/targets"
            )
            or []
        )

    def send_verification_code(self, mailbox_id: int, email: str) -> dict:
        """
        向目标邮箱发送验证验证码邮件。

        Args:
            mailbox_id: 虚拟邮箱 ID
            email: 待验证的转发目标邮箱地址
        Returns:
            {msg}
        """
        return self._client._request(
            "POST",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/targets/verification-code",
            json={"email": email},
        )

    def verify_target(self, mailbox_id: int, email: str, code: str) -> dict:
        """
        使用验证码验证转发目标地址。

        Args:
            mailbox_id: 虚拟邮箱 ID
            email: 待验证的转发目标邮箱地址
            code: 收到的验证码（4~8 位）
        Returns:
            {id, email, verification_status, verified_at, created_at}
        """
        return self._client._request(
            "POST",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/targets/verify",
            json={"email": email, "code": code},
        )

    def delete_target(self, mailbox_id: int, target_id: int) -> dict:
        """
        移除某个转发目标地址。

        Args:
            mailbox_id: 虚拟邮箱 ID
            target_id: 转发目标 ID
        Returns:
            {msg}
        """
        return self._client._request(
            "DELETE",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/targets/{target_id}",
        )

    # ── 入站邮件 ──

    def list_inbound_mails(
        self,
        mailbox_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        分页查询某虚拟邮箱收到的入站邮件。

        Args:
            mailbox_id: 虚拟邮箱 ID
            page: 页码（从 1 开始）
            page_size: 每页条数（1~100）
        Returns:
            {total, items[ {id, envelope_from, message_id, subject,
             received_at, size_bytes, recipient_count, status, rejection_reason} ]}
        """
        return self._client._request(
            "GET",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/inbound-mails",
            params={"page": page, "page_size": page_size},
        ) or {"total": 0, "items": []}

    # ── 投递记录 ──

    def list_deliveries(
        self,
        mailbox_id: int,
        inbound_mail_id: int = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        分页查询某虚拟邮箱的邮件转发投递记录。

        Args:
            mailbox_id: 虚拟邮箱 ID
            inbound_mail_id: 按入站邮件过滤（可选）
            page: 页码（从 1 开始）
            page_size: 每页条数（1~100）
        Returns:
            {total, items[ {id, inbound_mail_id, target_email, status,
             attempt_count, last_error, points_charged, charged_at,
             sent_at, created_at} ]}
        """
        params = {"page": page, "page_size": page_size}
        if inbound_mail_id is not None:
            params["inbound_mail_id"] = inbound_mail_id
        return self._client._request(
            "GET",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/deliveries",
            params=params,
        ) or {"total": 0, "items": []}

    # ── 主动发送（虚拟邮箱身份） ──

    def send_mail(
        self,
        mailbox_id: int,
        to_email: str,
        subject: str,
        body: str,
        html_body: str = None,
    ) -> dict:
        """
        以虚拟邮箱身份，通过系统邮箱将内容直接发送到目标地址。

        邮件正文/HTML 会自动追加「来自虚拟邮箱 <address> 转发」标识，
        每次发送扣减配置积分（默认 2 积分/条）。

        Args:
            mailbox_id: 虚拟邮箱 ID（须归属当前用户且处于 active）
            to_email: 接收方邮箱地址
            subject: 邮件主题
            body: 纯文本正文
            html_body: HTML 正文（可选；提供时同样追加转发标识）
        Returns:
            {sent, message_id, points_charged, mailbox_address}
        """
        return self._client._request(
            "POST",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/send",
            json={
                "to_email": to_email,
                "subject": subject,
                "body": body,
                "html_body": html_body,
            },
        )
