from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.editor.cutia_updater import CutiaUpdateError, CutiaUpdater


router = APIRouter()
updater = CutiaUpdater()


@router.post("/update")
async def update_cutia():
    try:
        return updater.update()
    except CutiaUpdateError as exc:
        return JSONResponse(status_code=409, content={"success": False, "message": str(exc)})
