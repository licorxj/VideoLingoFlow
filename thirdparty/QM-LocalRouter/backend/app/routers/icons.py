import os
import uuid
import httpx
import json
import re
import urllib.parse
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image
from io import BytesIO

router = APIRouter(prefix="/api/icons", tags=["icons"])

ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "icons")
os.makedirs(ICONS_DIR, exist_ok=True)

ICON_SIZE = 64


class SearchRequest(BaseModel):
    keyword: str
    page: int = 0
    count: int = 9
    engine: str = "baidu"


class IconSaveRequest(BaseModel):
    url: str
    provider_id: int = 0


async def search_baidu(keyword: str, page: int, count: int) -> list:
    """Search Baidu Images with cookie-based session."""
    pn = page * count
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://image.baidu.com/",
    }

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Visit main page first to get cookies (BAIDUID)
        await client.get("https://image.baidu.com/", headers=headers)

        # Now search with cookies
        search_url = "https://image.baidu.com/search/acjson"
        params = {
            "tn": "resultjson_com", "logid": "1234567890", "ipn": "rj",
            "ct": "201326592", "fp": "result",
            "word": keyword, "queryWord": keyword,
            "cl": "2", "lm": "-1", "ie": "utf-8", "oe": "utf-8",
            "istype": "2", "qc": "", "nc": "1",
            "pn": str(pn), "rn": str(count),
        }
        resp = await client.get(search_url, params=params, headers=headers)
        data = resp.json()

    results = []
    for item in data.get("data", []):
        thumb = item.get("thumbURL") or item.get("middleURL") or item.get("hoverURL")
        if thumb:
            results.append({
                "thumb": thumb,
                "width": item.get("width", 0),
                "height": item.get("height", 0),
                "title": item.get("fromPageTitleEnc", ""),
            })
        if len(results) >= count:
            break
    return results


async def search_bing(keyword: str, page: int, count: int) -> list:
    """Search Bing Images."""
    first = page * count + 1
    search_url = "https://www.bing.com/images/search"
    params = {
        "q": keyword,
        "first": str(first),
        "count": str(count),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(search_url, params=params, headers=headers)
        html = resp.text

    results = []
    murl_pattern = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', html)
    for url in murl_pattern[:count]:
        url = url.replace('\\u002f', '/').replace('\\u003d', '=')
        results.append({"thumb": url, "width": 0, "height": 0, "title": ""})
    return results


async def search_sogou(keyword: str, page: int, count: int) -> list:
    """Search Sogou Images."""
    pn = page * count
    search_url = "https://pic.sogou.com/pics"
    params = {
        "query": keyword, "mode": "1", "start": str(pn),
        "reqType": "ajax", "reqFrom": "result", "tn": "0",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://pic.sogou.com/",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(search_url, params=params, headers=headers)
            data = resp.json()
        results = []
        for item in data.get("items", [])[:count]:
            thumb = item.get("oriPicUrl") or item.get("picUrl")
            if thumb:
                if not thumb.startswith("http"):
                    thumb = "https:" + thumb
                results.append({
                    "thumb": thumb,
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                    "title": item.get("title", ""),
                })
        return results
    except Exception:
        return []


@router.post("/search")
async def search_icons(req: SearchRequest):
    """Search icons from selected engine."""
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(400, "Keyword required")

    try:
        if req.engine == "bing":
            results = await search_bing(keyword, req.page, req.count)
        elif req.engine == "sogou":
            results = await search_sogou(keyword, req.page, req.count)
        else:
            results = await search_baidu(keyword, req.page, req.count)
    except Exception as e:
        raise HTTPException(502, f"Search failed: {str(e)[:200]}")

    return {"results": results}


@router.post("/save")
async def save_icon(req: IconSaveRequest):
    """Download an image, crop to square, resize to icon, save locally."""
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL required")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(502, f"Download failed: HTTP {resp.status_code}")
            img_bytes = resp.content
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Download failed: {str(e)[:200]}")

    try:
        img = Image.open(BytesIO(img_bytes))
        img = img.convert("RGBA")
        w, h = img.size
        size = min(w, h)
        left = (w - size) // 2
        top = (h - size) // 2
        img = img.crop((left, top, left + size, top + size))
        img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    except Exception as e:
        raise HTTPException(422, f"Image processing failed: {str(e)[:200]}")

    pid_part = f"provider_{req.provider_id}_" if req.provider_id else ""
    filename = f"{pid_part}{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(ICONS_DIR, filename)
    img.save(filepath, "PNG", optimize=True)
    return {"path": f"icons/{filename}", "filename": filename}


@router.get("/file/{filename}")
async def get_icon_file(filename: str):
    """Serve an icon file."""
    filepath = os.path.join(ICONS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Icon not found")
    return FileResponse(filepath, media_type="image/png")
