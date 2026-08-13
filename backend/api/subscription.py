from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.auth.cloud_auth_service import get_cloud_auth_service
from backend.auth.subscription_guard import get_subscription_guard


router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str
    phone: str | None = None
    verification_code: str | None = None


class EmailRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


class CardRequest(BaseModel):
    card_code: str = Field(default="")


def _raise_if_failed(result: dict):
    if not result.get("ok"):
        code = result.get("code")
        status_code = 401 if code in {1100, 1101, 1102} else 403 if code in {1103, 1203, 1205, 1206, 1207, 1302, 2001, 2002, 2003} else 402 if code == 1209 else 503 if isinstance(code, int) and 4000 <= code <= 4999 else 400
        raise HTTPException(status_code=status_code, detail=result.get("message") or "操作失败")
    return result


@router.get("/status")
async def get_status():
    guard = get_subscription_guard()
    return guard.get_subscription_state(force_refresh=False)


@router.post("/refresh")
async def refresh_status():
    service = get_cloud_auth_service()
    _raise_if_failed(service.refresh())
    guard = get_subscription_guard()
    return guard.get_subscription_state(force_refresh=False)


@router.post("/login")
async def login(req: LoginRequest):
    service = get_cloud_auth_service()
    _raise_if_failed(service.login(req.username, req.password))
    guard = get_subscription_guard()
    guard.recover_usage()
    return guard.get_subscription_state(force_refresh=False)


@router.post("/logout")
async def logout():
    service = get_cloud_auth_service()
    return service.logout()


@router.post("/unbind-device")
async def unbind_device():
    service = get_cloud_auth_service()
    _raise_if_failed(service.unbind_device())
    guard = get_subscription_guard()
    return guard.get_subscription_state(force_refresh=False)


@router.post("/register")
async def register(req: RegisterRequest):
    service = get_cloud_auth_service()
    return _raise_if_failed(service.register(req.username, req.password, req.email, req.phone, req.verification_code))


@router.post("/send-code")
async def send_code(req: EmailRequest):
    service = get_cloud_auth_service()
    return _raise_if_failed(service.send_verification_code(req.email))


@router.post("/reset-password/send-code")
async def send_reset_code(req: EmailRequest):
    service = get_cloud_auth_service()
    return _raise_if_failed(service.send_reset_password_code(req.email))


@router.post("/reset-password/confirm")
async def reset_password(req: ResetPasswordRequest):
    service = get_cloud_auth_service()
    return _raise_if_failed(service.reset_password(req.email, req.code, req.new_password))


@router.post("/verify-card")
async def verify_card(req: CardRequest):
    if not req.card_code.strip():
        raise HTTPException(status_code=400, detail="请输入卡密")
    service = get_cloud_auth_service()
    _raise_if_failed(service.verify_card_advanced(req.card_code.strip()))
    guard = get_subscription_guard()
    guard.recover_usage()
    return guard.get_subscription_state(force_refresh=True)


@router.get("/links")
async def get_links():
    return {
        "products": "https://www.licorxj.online/products",
        "home": "https://www.licorxj.online/home",
        "versions": "https://www.licorxj.online/versions",
    }
