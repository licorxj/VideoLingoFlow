"""Credentials API: 第三方能力密钥的统一管理。

密钥真实值保存在 control-plane 数据库（用户私有资产），配置文件只保存
``secret://NAME`` 引用。列表接口一律脱敏，明文仅在显式请求时返回。
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import credential_store

router = APIRouter()


class CredentialCreate(BaseModel):
    name: str
    value: str = ""  # 多行文本，每行一个 key
    purpose: str = ""
    rotate: bool = True


class CredentialUpdate(BaseModel):
    name: str | None = None
    value: str | None = None  # 多行文本，每行一个 key
    purpose: str | None = None
    rotate: bool | None = None


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


@router.get("")
async def list_credentials(
    keyword: str = "",
    reveal: bool = Query(False, description="是否返回明文（仅用于编辑回填）"),
):
    try:
        items = credential_store.list_credentials(reveal=reveal, keyword=keyword)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取密钥失败：{exc}")
    return {"credentials": items, "total": len(items)}


@router.post("")
async def create_credential(req: CredentialCreate):
    try:
        item = credential_store.create_credential(req.name, req.value, req.purpose, rotate=req.rotate)
    except credential_store.CredentialError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建密钥失败：{exc}")
    return {"success": True, "credential": item}


@router.get("/usage/{credential_id}")
async def credential_usage(credential_id: str):
    try:
        return credential_store.usage_of(credential_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"统计引用失败：{exc}")


@router.get("/{credential_id}")
async def get_credential(
    credential_id: str,
    reveal: bool = Query(False, description="是否返回明文"),
):
    item = credential_store.get_credential(credential_id, reveal=reveal)
    if not item:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return {"credential": item}


@router.put("/{credential_id}")
async def update_credential(credential_id: str, req: CredentialUpdate):
    try:
        item = credential_store.update_credential(
            credential_id, name=req.name, value=req.value, purpose=req.purpose, rotate=req.rotate
        )
    except credential_store.CredentialError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新密钥失败：{exc}")
    return {"success": True, "credential": item}


@router.delete("/{credential_id}")
async def delete_credential(credential_id: str):
    try:
        removed = credential_store.delete_credential(credential_id)
    except credential_store.CredentialError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除密钥失败：{exc}")
    return {"success": True, "removed": removed}
