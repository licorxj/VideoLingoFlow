"""QM 虚拟邮箱 + qmhub 能力调用 API 代理。

前端通过本代理调用 qmhub，后端自动管理 API Key 认证。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.qmhub.auth_helper import build_qmhub_client_with_retry, build_mail_forwarding_client

router = APIRouter(prefix="/api/qm-mail", tags=["qm-mail"])


@router.get("/mailboxes")
def list_mailboxes_with_targets():
    """一次性获取用户所有虚拟邮箱及其转发目标。"""
    try:
        client = build_mail_forwarding_client()
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    mf = client.mail_forwarding

    try:
        mailboxes = mf.list_mailboxes()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取邮箱列表失败: {e}")

    result = []
    for mb in mailboxes:
        mb_id = mb.get("id")
        targets = []
        if mb_id:
            try:
                targets = mf.list_targets(mb_id)
            except Exception:
                targets = []
        result.append({
            "id": mb_id,
            "address": mb.get("address", ""),
            "status": mb.get("status", ""),
            "inbound_count": mb.get("inbound_count", 0),
            "targets": targets,
        })

    return {"mailboxes": result}


# ── qmhub invoke 代理 ──

class InvokeRequest(BaseModel):
    slug: str
    input_url: str | None = None
    params: dict | None = None
    duration_seconds: float | None = None


@router.post("/invoke")
def invoke_capability(req: InvokeRequest):
    """代理 qmhub 能力调用。"""
    try:
        client = build_qmhub_client_with_retry()
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        result = client.invoke.create(
            slug=req.slug,
            input_url=req.input_url,
            params=req.params or {},
            duration_seconds=req.duration_seconds,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"能力调用失败: {e}")


@router.get("/task-status/{request_id}")
def get_task_status(request_id: int):
    """代理 qmhub 任务状态查询。"""
    try:
        client = build_qmhub_client_with_retry()
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        result = client.invoke.task_status(request_id=request_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"查询任务状态失败: {e}")


@router.post("/send-mail")
def send_mail(mailbox_id: int, content: str = ""):
    """代理发送邮件内容到转发目标。"""
    try:
        client = build_mail_forwarding_client()
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        result = client._request(
            "POST",
            f"/api/mail-forwarding/mailboxes/{mailbox_id}/send",
            json={"content": content},
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"发送邮件失败: {e}")
