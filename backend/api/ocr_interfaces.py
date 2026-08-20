"""OCR Interfaces API: CRUD for OCR interface definitions + rapidocr 配置查询与测试."""
import os
import uuid
import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional

from backend.ocr.ocr_interface_manager import get_ocr_interface_manager
from backend.ocr.ocr_rapidocr import (
    check_ocr_dependencies,
    ENGINE_OPTIONS,
    LANG_OPTIONS,
    SIZES_BY_VERSION,
)

router = APIRouter()

OCR_TEST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tasks", "_ocr_test",
)
OCR_UPLOAD_DIR = os.path.join(OCR_TEST_DIR, "uploads")

_executor = ThreadPoolExecutor(max_workers=2)

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


class OCRInterfaceCreate(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "sdk"
    builtin: Optional[bool] = None
    enabled: bool = True
    description: str = ""
    config: dict = Field(default_factory=dict)


class OCRInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    config: Optional[dict] = None


class OCRTestRequest(BaseModel):
    image_path: str


@router.get("")
async def list_interfaces():
    mgr = get_ocr_interface_manager()
    return {"interfaces": mgr.list_all()}


@router.get("/enabled")
async def list_enabled():
    mgr = get_ocr_interface_manager()
    return {"interfaces": mgr.get_enabled()}


@router.get("/check-deps")
async def get_check_deps():
    """返回 OCR 相关依赖安装状态，供设置页依赖卡展示。"""
    return {"deps": check_ocr_dependencies()}


@router.get("/config-fields")
async def get_ocr_config_fields():
    """返回引擎/模型尺寸/语言选项，供前端联动下拉与未来节点消费。"""
    return {
        "engine_options": ENGINE_OPTIONS,
        "sizes_by_version": SIZES_BY_VERSION,
        "lang_options": LANG_OPTIONS,
    }


@router.get("/{iface_id}")
async def get_interface(iface_id: str):
    mgr = get_ocr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"interface": iface}


@router.post("")
async def create_interface(req: OCRInterfaceCreate):
    mgr = get_ocr_interface_manager()
    iface = mgr.create(req.model_dump())
    return {"success": True, "interface": iface}


@router.put("/{iface_id}")
async def update_interface(iface_id: str, req: OCRInterfaceUpdate):
    mgr = get_ocr_interface_manager()
    iface = mgr.update(iface_id, req.model_dump(exclude_none=True))
    if not iface:
        raise HTTPException(404, "Interface not found")
    # 配置变更后释放引擎缓存，下次识别按新配置重建
    from backend.ocr.ocr_factory import clear_cache
    clear_cache()
    return {"success": True, "interface": iface}


@router.delete("/{iface_id}")
async def delete_interface(iface_id: str):
    mgr = get_ocr_interface_manager()
    if not mgr.delete(iface_id):
        raise HTTPException(400, "Cannot delete builtin interface or not found")
    return {"success": True}


@router.post("/{iface_id}/toggle")
async def toggle_interface(iface_id: str, enabled: bool = True):
    mgr = get_ocr_interface_manager()
    iface = mgr.toggle(iface_id, enabled)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.post("/reload")
async def reload_interfaces():
    mgr = get_ocr_interface_manager()
    mgr.reload()
    return {"success": True, "count": len(mgr.list_all())}


@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "image.png")[1].lower() or ".png"
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(400, f"不支持的图片格式：{ext}，支持 {sorted(ALLOWED_IMAGE_EXTS)}")
    os.makedirs(OCR_UPLOAD_DIR, exist_ok=True)
    filename = f"upload_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(OCR_UPLOAD_DIR, filename)
    with open(filepath, "wb") as fp:
        shutil.copyfileobj(file.file, fp)
    return {
        "success": True,
        "path": filepath,
        "filename": file.filename,
        "saved_as": filename,
    }


def _run_ocr_test(iface_id, image_path):
    """Run OCR test for a given interface."""
    from backend.ocr.ocr_factory import get_ocr_engine
    engine = get_ocr_engine(iface_id)
    return engine.recognize(image_path)


@router.post("/{iface_id}/test")
async def test_interface(iface_id: str, req: OCRTestRequest):
    mgr = get_ocr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    if not req.image_path or not os.path.exists(req.image_path):
        raise HTTPException(400, "图片文件不存在")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            _run_ocr_test,
            iface_id, req.image_path,
        )
        return {
            "success": True,
            "txts": result.get("txts", []),
            "scores": result.get("scores", []),
            "elapse": result.get("elapse", 0.0),
            "box_count": len(result.get("boxes", [])),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"OCR test error: {str(e)}")


@router.delete("/test/cleanup")
async def cleanup_test_results():
    if os.path.exists(OCR_TEST_DIR):
        shutil.rmtree(OCR_TEST_DIR)
    return {"success": True}
