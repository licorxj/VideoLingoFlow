"""s_qm_virtual_mailbox: QM 虚拟邮箱节点 — 以虚拟邮箱身份向已验证的目标邮箱转发发送内容。

核心功能：使用建立的虚拟邮箱，将「前端文本框内容 + 上游连线输入的文本」串联后，
作为邮件正文通过 qmhub 虚拟邮箱服务转发发送给已验证的转发目标（费用 2 分钱/封，云端处理）。

Logic:
  1. 通过 auth 组件验证用户已注册登录软件
  2. 读取选中的虚拟邮箱 ID
  3. 解析发送内容（文本框 prefix_content 与上游连线输入的文本串联）
  4. 读取选中的转发目标邮箱地址
  5. 校验虚拟邮箱与目标邮箱的绑定关系（目标已绑定且该虚拟邮箱下已验证）
  6. 调用 qmhub 后端 send_mail 以虚拟邮箱身份发送内容邮件
  7. 保存发送结果 JSON

费用：2 分钱/封（以虚拟邮箱身份发送内容邮件计费，云端转发处理）。
"""
import json
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_QmVirtualMailbox(BaseStep):
    step_id = "s_qm_virtual_mailbox"
    step_name = "QM虚拟邮箱"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        path = os.path.join(cache_dir, f"qm_mail_{node_id}.json")
        return os.path.exists(path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ==================== 认证 ====================

    @staticmethod
    def _check_user_auth() -> dict:
        from backend.auth.cloud_auth_service import get_cloud_auth_service

        svc = get_cloud_auth_service()
        session = svc.get_session() or {}
        token = session.get("token") or ""
        username = (session.get("user_info") or {}).get("username") or ""

        if not token:
            raise RuntimeError("节点需要注册登录软件")

        return {"token": token, "username": username}

    @staticmethod
    def _build_qmhub_client():
        """构造 qmhub 客户端（mail_forwarding 用软件 token 认证）。"""
        from backend.qmhub.auth_helper import build_mail_forwarding_client

        return build_mail_forwarding_client()

    # ==================== 内容解析 ====================

    @staticmethod
    def _resolve_content(task_dir: str, step_inputs: dict, node_config: dict) -> str:
        """拼接发送内容：输入框内容作为前缀 + 连线文本/文本路径内容。

        - node_config.prefix_content: 卡片输入框内容（作为前缀，最高优先级存在）
        - step_inputs.text: 连线输入的文本内容或文本文件路径（后端自动适配）
        没有连线内容时，仅使用输入框内容。
        """
        prefix = (node_config.get("prefix_content") or "").strip()

        # 连线输入（text 端口）：可能是文本，也可能是文本文件路径
        linked_text = ""
        raw = step_inputs.get("text", "")
        if raw:
            raw_abs = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(raw_abs):
                try:
                    with open(raw_abs, "r", encoding="utf-8") as f:
                        linked_text = f.read().strip()
                except Exception:
                    linked_text = raw.strip()
            else:
                linked_text = raw.strip()

        # 前缀 + 连线内容拼接（前缀在前）
        if prefix and linked_text:
            return f"{prefix}\n{linked_text}"
        return prefix or linked_text

    # ==================== 主流程 ====================

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # ========== 阶段 1：验证用户登录 ==========
        if callback:
            callback(5, "验证用户注册登录状态...")
        auth_info = self._check_user_auth()
        if callback:
            callback(10, f"用户已登录: {auth_info['username'] or '已认证'}")

        # ========== 阶段 2：读取选中的虚拟邮箱 ==========
        mailbox_id = str(node_config.get("mailbox_id", "")).strip()
        if not mailbox_id:
            raise ValueError("未选择虚拟邮箱，请在节点设置中选择或前往网页设置")

        if callback:
            callback(30, f"使用虚拟邮箱 ID: {mailbox_id}")

        # ========== 阶段 2.5：解析拼接发送内容 ==========
        # 输入框内容作为前缀 + 连线文本/文本文件内容；无连线时仅输入框内容
        content = self._resolve_content(task_dir, step_inputs, node_config)
        if callback:
            callback(38, f"拼接发送内容（{len(content)} 字符）")

        # ========== 阶段 3：读取选中的转发目标 ==========
        target_email = str(node_config.get("target_email", "")).strip()
        if not target_email:
            raise ValueError(
                "未选择转发目标邮箱。请先在卡片中选择虚拟邮箱，再从其已验证目标中选择一个。"
            )

        if callback:
            callback(45, f"校验转发目标绑定: {target_email}")

        client = self._build_qmhub_client()

        # 前置校验 1：邮箱归属当前登录用户
        owned_mailboxes = []
        try:
            owned_mailboxes = client.mail_forwarding.list_mailboxes() or []
            owned_ids = {str(m.get("id")) for m in owned_mailboxes if isinstance(m, dict)}
        except Exception:
            owned_ids = set()
        if owned_ids and mailbox_id not in owned_ids:
            raise RuntimeError(
                f"虚拟邮箱 ID {mailbox_id} 不存在或不属于当前登录用户，"
                f"请在节点设置中重新选择（当前可用: {sorted(owned_ids)}）。"
            )

        # 前置校验 2：目标邮箱已绑定到该虚拟邮箱且已验证
        # 复用 list_mailboxes 的邮箱对象（与前端卡片同源），优先取其 targets；
        # 个别部署下 list_mailboxes 不内嵌 targets，再回退到 list_targets 显式查询。
        def _target_email_of(t):
            return str(
                t.get("email")
                or t.get("address")
                or t.get("email_address")
                or t.get("target_email")
                or ""
            ).strip().lower()

        selected_mb = next(
            (mb for mb in owned_mailboxes if str(mb.get("id")) == mailbox_id),
            None,
        )
        targets = (selected_mb or {}).get("targets") if selected_mb else None
        if not targets:
            try:
                targets = client.mail_forwarding.list_targets(int(mailbox_id)) or []
            except Exception:
                targets = []
        targets = targets or []

        target = next(
            (t for t in targets if _target_email_of(t) == target_email.lower()),
            None,
        )
        if target is None:
            available = [_target_email_of(t) for t in targets]
            raise RuntimeError(
                f"目标邮箱 {target_email} 未绑定到该虚拟邮箱，"
                f"请先在卡片中将其添加为转发目标并完成验证。"
                f"（该虚拟邮箱当前已绑定目标: {available or '无'}）"
            )
        ver_status = (target.get("verification_status") or target.get("status") or "").lower()
        if ver_status != "verified":
            raise RuntimeError(
                f"目标邮箱 {target_email} 尚未验证（状态: {ver_status}），"
                f"请先发送验证码并完成验证后再发送内容。"
            )

        if not content:
            raise RuntimeError("发送内容为空：请在前端输入框填写内容，或连接上游文本输出节点。")

        # ========== 阶段 4：以虚拟邮箱身份发送内容邮件 ==========
        if callback:
            callback(55, "调用 qmhub 发送内容邮件...")

        subject = (node_config.get("subject") or "").strip() or "VideoLingo 邮件转发"
        send_result = None

        # 调试：打印 send_mail 请求参数（排查 qmhub 服务端 500）
        print(
            "[DEBUG qm_mail] send_mail 请求参数: "
            f"mailbox_id={int(mailbox_id)!r}, to_email={target_email!r}, "
            f"subject={subject!r}, body_length={len(content)}, "
            f"body_head={content[:80]!r}",
            flush=True,
        )

        try:
            send_result = client.mail_forwarding.send_mail(
                mailbox_id=int(mailbox_id),
                to_email=target_email,
                subject=subject,
                body=content,
            )
        except Exception as e:
            err_record = {
                "node_id": node_id,
                "node_name": "QM虚拟邮箱",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "error": str(e),
                "mailbox_id": mailbox_id,
                "target_email": target_email,
            }
            cache_dir = os.path.join(task_dir, "cache")
            os.makedirs(cache_dir, exist_ok=True)
            err_path = os.path.join(cache_dir, f"qm_mail_{node_id}.json")
            with open(err_path, "w", encoding="utf-8") as f:
                json.dump(err_record, f, ensure_ascii=False, indent=2)
            raise RuntimeError(f"发送邮件失败: {e}") from e

        if callback:
            callback(85, "内容邮件已发送")

        # ========== 阶段 5：保存结果 JSON ==========
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        json_filename = f"qm_mail_{node_id}.json"
        json_path = os.path.join(cache_dir, json_filename)

        record = {
            "node_id": node_id,
            "node_name": "QM虚拟邮箱",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "mailbox_id": mailbox_id,
            "target_email": target_email,
            "subject": (node_config.get("subject") or "").strip() or "VideoLingo 邮件转发",
            "content": content,
            "cost": {
                "rate_per_email": 0.02,
                "rate_description": "2分钱/封（以虚拟邮箱身份发送内容邮件，云端转发处理）",
            },
            "result": send_result,
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, "内容邮件发送完成")

        return {
            "artifacts": [f"cache/{json_filename}"],
            "outputs": {
                "json": f"cache/{json_filename}",
            },
        }


StepQmVirtualMailbox = S_QmVirtualMailbox
