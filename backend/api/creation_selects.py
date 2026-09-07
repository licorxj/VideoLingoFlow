"""AI 创作项目骨架查询接口（工作流节点下拉数据源）。

供工作流节点 configFields 的 api-select 消费，前端会以当前节点其他配置值
替换端点中的 ``{creation_id}`` / ``{chapter_id}`` 占位符实现联动：

- ``GET /api/creation/list``                        项目下拉
- ``GET /api/creation/{creation_id}/chapters``      章节下拉
- ``GET /api/creation/{creation_id}/shots?chapter_id=``  分镜下拉(可按章节过滤)
"""

from fastapi import APIRouter, HTTPException

from backend import creation as agi

router = APIRouter(prefix="/api/creation", tags=["creation-selects"])


def _require_creation(creation_id: str) -> None:
    try:
        agi.get_creation(creation_id)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"创作项目不存在: {creation_id}")


@router.get("/list")
def list_creations():
    """全部创作项目（项目下拉）。"""
    items = agi.list_creations()
    return [
        {
            "id": c["id"],
            "name": c.get("name") or c["id"],
            "status": c.get("status") or "",
            "updated_at": c.get("updated_at") or "",
        }
        for c in items
    ]


@router.get("/{creation_id}/chapters")
def list_chapters(creation_id: str):
    """指定项目的章节列表（章节下拉），按 order_no 升序。"""
    _require_creation(creation_id)
    out = []
    for ch in agi.list_chapters(creation_id):
        out.append(
            {
                "id": ch["id"],
                "order_no": ch.get("order_no"),
                "title": ch.get("title") or f"第{ch.get('order_no')}章",
                "summary": ch.get("summary") or "",
            }
        )
    return out


@router.get("/{creation_id}/shots")
def list_shots(creation_id: str, chapter_id: str = ""):
    """指定项目的分镜列表（分镜下拉），可按章节过滤，按 order_no 升序。"""
    _require_creation(creation_id)
    proj = agi.get_creation(creation_id, with_detail=True)
    out = []
    for ch in proj.get("chapters", []):
        if chapter_id and ch["id"] != chapter_id:
            continue
        for s in ch.get("shots", []):
            scenes = s.get("scene_descriptions") or []
            desc = (scenes[0] if scenes else "").strip()[:24]
            out.append(
                {
                    "id": s["id"],
                    "chapter_id": ch["id"],
                    "order_no": s.get("order_no"),
                    "label": f"#{s.get('order_no')} {desc}".strip(),
                }
            )
    out.sort(key=lambda x: x["order_no"] or 0)
    return out
