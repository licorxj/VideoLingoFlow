#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
11elevensound-effects 爬虫
===========================

对接 ElevenLabs 音效库的「搜索接口」，从返回的 Next.js RSC(flight) 响应中
提取「营销片段」(sound-effects 文档) 的详细信息与 URL，并输出为 JSON。

接口说明（请求信息详见 elevenlabs_request.json）：
    POST https://elevenlabs.io/zh/sound-effects
    Content-Type : text/plain;charset=UTF-8
    Accept       : text/x-component
    Next-Action  : <server action id>        (从请求文件读取)
    X-Deployment-Id : <deployment id>        (从请求文件读取)
    Cookie       : <登录态 cookie>           (从请求文件读取，会过期需更新)
    请求体(body): 以 React Flight 格式编码的搜索参数，即 JSON 数组字符串 '["<query>"]'

说明：
    - ElevenLabs 该接口有 Cloudflare 防护，普通 urllib/requests 直连会被 403，
      因此本脚本默认使用 Playwright（真实浏览器 TLS）发起请求。
    - 需要：pip install playwright && playwright install chromium
    - Cookie / Next-Action / X-Deployment-Id 等会从「请求信息文件」中自动解析，
      无需手动填写；也可通过命令行参数覆盖。Cookie 过期后需重新用浏览器
      开发者工具导出请求文件。
    - 中文等关键词会被自动调用项目 LLM 服务层（backend.llm）翻译成英文后再检索，
      因为 ElevenLabs 音效搜索为英文检索。可用 --no-translate 关闭。

用法：
    python elevenlabs_sound_effects.py --query explosion --output result.json
    python elevenlabs_sound_effects.py --query "码头船只归来的鸣笛" --output result.json
    python elevenlabs_sound_effects.py --request-file 11elevensound-effects.txt
    python elevenlabs_sound_effects.py --parse-file saved_response.txt --output out.json

    # 爬取并下载音效（按营销片段分子目录）
    python elevenlabs_sound_effects.py --query ferry --download --download-dir downloads
    # 直接按 URL 下载（独立于爬取流程）
    python elevenlabs_sound_effects.py --download-url "https://eleven-public-cdn.../x.mp3"
"""

import argparse
import json
import os
import re
import sys
import time

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
ENDPOINT = "https://elevenlabs.io/zh/sound-effects"
BASE_URL = "https://elevenlabs.io/zh/sound-effects"

# 需要识别的请求头名称（文件内以「名称 / 值」成对出现）
HEADER_NAMES = {
    "content-type", "cookie", "next-action", "x-deployment-id", "accept",
    "origin", "referer", "user-agent", "next-router-state-tree",
    "next-router-prefetch", "rsc", "priority", "baggage", "sentry-trace",
}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# LLM 服务层 step 名称（在 backend.llm 中按此名路由模型，找不到时回退默认模型）
TRANSLATE_STEP = "sound_effects_translate"

# 工作区根目录（backend 的父目录，用于 import backend 包）
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(_HERE))  # .../VideoLingoLc

# 匹配中日韩汉字，用于判断是否需要进行翻译
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def _contains_cjk(text):
    return bool(_CJK_RE.search(text or ""))


def translate_query_to_english(query):
    """调用项目 LLM 服务层，将（中文等）搜索词翻译为英文检索词。

    失败时回退返回原始 query，不影响主流程。
    """
    try:
        if _WORKSPACE_ROOT not in sys.path:
            sys.path.insert(0, _WORKSPACE_ROOT)
        from backend.llm.llm_client import get_llm_client
    except Exception as e:  # noqa: BLE001
        print(f"[translate] 无法加载 LLM 服务层: {e}，将使用原查询。", file=sys.stderr)
        return query

    system_prompt = (
        "You are a search-keyword translator for an audio / sound-effect library. "
        "Translate the user's query into concise English keywords that best match "
        "sound effects. Return ONLY the English keywords (comma-separated if multiple "
        "concepts), with no explanation and no quotation marks."
    )
    try:
        client = get_llm_client()
        result = client.chat(
            step_name=TRANSLATE_STEP,
            prompt=query,
            system_prompt=system_prompt,
            response_json=False,
            log=True,
        )
        if isinstance(result, str) and result.strip():
            return result.strip()
        if isinstance(result, dict):
            # 极少数情况下返回了 JSON，尝试取其中的文本字段
            for k in ("keywords", "translation", "text", "result"):
                if isinstance(result.get(k), str) and result[k].strip():
                    return result[k].strip()
    except Exception as e:  # noqa: BLE001
        print(f"[translate] 翻译失败: {e}，将使用原查询。", file=sys.stderr)
    return query


# --------------------------------------------------------------------------- #
# 从「请求信息文件」解析请求头
# --------------------------------------------------------------------------- #
def load_headers_from_request_file(path):
    """解析浏览器导出的请求信息文件，返回 {header_name: value}。

    支持两种格式：
      - 原始文本（请求头 / 响应头 区段，名称与值成对出现）；
      - 精简 JSON：``{"cookie": "...", "next_action": "...", "x_deployment_id": "..."}``
        （也接受带连字符的键名 ``next-action`` / ``x-deployment-id``）。
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    stripped = raw.lstrip()
    if path.endswith(".json") or stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(raw)
        except Exception as error:
            print(f"[request-file] JSON 解析失败: {error}", file=sys.stderr)
            return {}
        normalize = {
            "cookie": "cookie",
            "next_action": "next-action",
            "next-action": "next-action",
            "x_deployment_id": "x-deployment-id",
            "x-deployment-id": "x-deployment-id",
            "user_agent": "user-agent",
            "user-agent": "user-agent",
        }
        return {
            out_key: str(data[key]).strip()
            for key, out_key in normalize.items()
            if key in data and str(data[key]).strip()
        }
    lines = raw.splitlines()

    # 定位请求头区段
    start = end = None
    for i, line in enumerate(lines):
        s = line.strip()
        if start is None and "请求头" in s:
            start = i + 1
        elif start is not None and "响应头" in s:
            end = i
            break
    if start is None:
        start = 0
    if end is None:
        end = len(lines)

    pairs = {}
    idx = start
    while idx < end:
        name = lines[idx].strip().lower()
        # 跳过元数据/空行/带冒号的非标准行
        if (
            name in HEADER_NAMES
            and ":" not in lines[idx]
            and "：" not in lines[idx]
            and idx + 1 < end
        ):
            value = lines[idx + 1].strip()
            pairs[name] = value
            idx += 2
        else:
            idx += 1
    return pairs


def build_request_headers(pairs, overrides=None):
    """组装实际请求使用的请求头。"""
    overrides = overrides or {}
    cookie = overrides.get("cookie") or pairs.get("cookie", "")
    next_action = overrides.get("next_action") or pairs.get("next-action", "")
    xdep = overrides.get("x_deployment_id") or pairs.get("x-deployment-id", "")
    ua = overrides.get("user_agent") or pairs.get("user-agent") or DEFAULT_UA

    headers = {
        "accept": "text/x-component",
        "content-type": "text/plain;charset=UTF-8",
        "origin": "https://elevenlabs.io",
        "referer": BASE_URL,
        "user-agent": ua,
    }
    if cookie:
        headers["cookie"] = cookie
    if next_action:
        headers["next-action"] = next_action
    if xdep:
        headers["x-deployment-id"] = xdep
    return headers


# --------------------------------------------------------------------------- #
# 解析 RSC(flight) 响应，提取 docs
# --------------------------------------------------------------------------- #
def parse_docs_from_response(text):
    """从 flight 响应文本中提取包含 'docs' 键的 JSON 对象。

    兼容两种形态：
      1) 原始 flight 行：  `1:{"docs":[...]}`
      2) HTML 中嵌入的脚本：`self.__next_f.push(["1","{\"docs\":...}"])`
    """
    # 1) 原始 flight 行（以数字编号开头的行）
    for line in text.splitlines():
        head, sep, tail = line.partition(":")
        if sep and head.isdigit():
            try:
                obj = json.loads(tail)
            except Exception:
                continue
            if isinstance(obj, dict) and "docs" in obj:
                return obj

    # 2) self.__next_f.push(...) 块
    for m in re.finditer(r"self\.__next_f\.push\((.*?)\)\s*;?\s*$", text, re.M | re.S):
        try:
            arr = json.loads(m.group(1).strip())
        except Exception:
            continue
        if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str):
            try:
                obj = json.loads(arr[1])
            except Exception:
                continue
            if isinstance(obj, dict) and "docs" in obj:
                return obj

    return None


# --------------------------------------------------------------------------- #
# 将 docs 整理为结构化条目
# --------------------------------------------------------------------------- #
def _sound_to_dict(s):
    media = s.get("media") or {}
    return {
        "name": s.get("name"),
        "short_description": s.get("shortDescription"),
        "audio_url": media.get("url"),
        "id": s.get("id"),
        "labels": s.get("labels") or [],
    }


def docs_to_items(docs):
    items = []
    for d in docs or []:
        slug = d.get("slug")
        page_url = f"{BASE_URL}/{slug}" if slug else None
        hero = d.get("heroCover") or {}
        items.append({
            "title": d.get("title"),
            "slug": slug,
            "page_url": page_url,
            "hero_cover_url": hero.get("url") if isinstance(hero, dict) else None,
            "question": d.get("question"),
            "meta": d.get("meta"),
            "generation_suggestions": d.get("generationSuggestions"),
            "sounds": [_sound_to_dict(s) for s in (d.get("sounds") or [])],
        })
    return items


# --------------------------------------------------------------------------- #
# 网络请求（Playwright，绕过 Cloudflare 的 TLS 指纹校验）
# --------------------------------------------------------------------------- #
def fetch_response(query, headers, proxy=None):
    """发起搜索请求，返回响应文本。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "缺少 playwright，请先执行: pip install playwright && playwright install chromium"
        )

    body = json.dumps([query]).encode("utf-8")
    with sync_playwright() as p:
        ctx_kwargs = {"user_agent": headers.get("user-agent", DEFAULT_UA)}
        if proxy:
            ctx_kwargs["proxy"] = {"server": proxy}
        ctx = p.request.new_context(**ctx_kwargs)
        # 移除 playwright 不接受的自定义头中的 None 值
        send_headers = {k: v for k, v in headers.items() if v}
        r = ctx.post(ENDPOINT, data=body, headers=send_headers)
        text = r.text()
        ctx.dispose()
    return text


# --------------------------------------------------------------------------- #
# 下载音效片段（音频托管在 eleven-public-cdn，可直接用 requests 下载）
# --------------------------------------------------------------------------- #
_INVALID_FNAME = re.compile(r'[\\/*?:"<>|\r\n\t]+')


def sanitize_filename(name, max_len=80):
    """把任意字符串清理为可用的文件名。"""
    name = (name or "audio").strip()
    name = _INVALID_FNAME.sub("_", name)
    name = name.strip("._ ")
    return (name[:max_len] or "audio")


def _extension_from_url(url):
    path = url.split("?", 1)[0].split("#", 1)[0]
    ext = os.path.splitext(path)[1].lower()
    return ext or ".mp3"


def download_url(url, dest_path, proxy=None, timeout=60, max_retries=3):
    """下载单个音频文件到 dest_path，支持代理与重试。优先用 requests，
    不可用时回退 urllib。
    """
    headers = {
        "user-agent": DEFAULT_UA,
        "referer": "https://elevenlabs.io/",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    last_err = None
    for attempt in range(max_retries):
        try:
            try:
                import requests

                with requests.get(
                    url, headers=headers, proxies=proxies, timeout=timeout, stream=True
                ) as r:
                    r.raise_for_status()
                    with open(dest_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
            except ImportError:
                import urllib.request

                req = urllib.request.Request(url, headers=headers)
                if proxies:
                    proxy_h = urllib.request.ProxyHandler(proxies)
                    opener = urllib.request.build_opener(proxy_h)
                    resp = opener.open(req, timeout=timeout)
                else:
                    resp = urllib.request.urlopen(req, timeout=timeout)
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            return True
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"下载失败 {url}: {last_err}")


def download_items(items, download_dir, proxy=None, flatten=False):
    """下载所有 item 下的音效片段，返回下载记录列表。

    默认按 item 分目录：download_dir/<slug>/<序号>_<音效名>.<ext>；
    flatten=True 时全部平铺到 download_dir。
    """
    os.makedirs(download_dir, exist_ok=True)
    records = []
    for item in items or []:
        slug = item.get("slug") or sanitize_filename(item.get("title") or "item")
        item_dir = download_dir if flatten else os.path.join(download_dir, sanitize_filename(slug))
        if not flatten:
            os.makedirs(item_dir, exist_ok=True)
        for i, s in enumerate(item.get("sounds") or []):
            url = s.get("audio_url")
            if not url:
                continue
            ext = _extension_from_url(url)
            base = sanitize_filename(f"{i + 1:02d}_{s.get('name') or 'sound'}")
            dest = os.path.join(item_dir, base + ext)
            try:
                download_url(url, dest, proxy=proxy)
                ok, err = True, None
            except Exception as e:  # noqa: BLE001
                ok, err = False, str(e)
            records.append({
                "title": s.get("name"),
                "url": url,
                "path": dest,
                "ok": ok,
                "error": err,
            })
    return records


def download_urls(url_list, download_dir, proxy=None):
    """直接按给定 URL 列表下载音效（独立模式，不依赖爬取结果）。"""
    os.makedirs(download_dir, exist_ok=True)
    records = []
    for idx, url in enumerate(url_list, 1):
        url = url.strip()
        if not url:
            continue
        ext = _extension_from_url(url)
        dest = os.path.join(download_dir, f"{idx:03d}{ext}")
        try:
            download_url(url, dest, proxy=proxy)
            ok, err = True, None
        except Exception as e:  # noqa: BLE001
            ok, err = False, str(e)
        records.append({"url": url, "path": dest, "ok": ok, "error": err})
    return records


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def crawl(query, request_file=None, cookie=None, next_action=None,
          x_deployment_id=None, proxy=None, translate=True):
    query_original = query

    # 含中日韩字符时，调用项目 LLM 服务层翻译为英文检索词
    if translate and _contains_cjk(query):
        print(f"[translate] 原文: {query}", flush=True)
        translated = translate_query_to_english(query)
        print(f"[translate] 译文: {translated}", flush=True)
        query = translated

    pairs = {}
    if request_file and os.path.isfile(request_file):
        pairs = load_headers_from_request_file(request_file)
    overrides = {
        "cookie": cookie,
        "next_action": next_action,
        "x_deployment_id": x_deployment_id,
    }
    headers = build_request_headers(pairs, overrides)

    if not headers.get("next-action") or not headers.get("cookie"):
        raise SystemExit(
            "缺少必要请求头(next-action / cookie)。请通过 --request-file 提供浏览器导出的"
            "请求信息文件，或使用 --cookie / --next-action / --x-deployment-id 覆盖。"
        )

    # 翻译结果可能是多个逗号分隔的关键词，分别检索后按 slug 去重合并，
    # 以覆盖更多相关营销片段（ElevenLabs 单查询为短语匹配，整串易无结果）。
    keywords = [k.strip() for k in query.split(",") if k.strip()][:3]
    if not keywords:
        keywords = [query]

    seen = {}
    merged = []
    for kw in keywords:
        try:
            text = fetch_response(kw, headers, proxy=proxy)
        except Exception as e:  # noqa: BLE001
            print(f"[search] 关键词 '{kw}' 请求失败: {e}", file=sys.stderr)
            continue
        obj = parse_docs_from_response(text)
        if not obj or "docs" not in obj:
            continue
        for d in obj.get("docs", []):
            sid = d.get("slug") or d.get("id")
            if sid and sid not in seen:
                seen[sid] = True
                merged.append(d)

    if not merged:
        raise SystemExit("未能从响应中解析出 docs 数据，可能 Cookie 已过期或接口有变动。")
    items = docs_to_items(merged)
    return {
        "query_original": query_original,
        "query": query,
        "query_keywords": keywords,
        "translated": query != query_original,
        "count": len(items),
        "source": ENDPOINT,
        "items": items,
    }


def main():
    parser = argparse.ArgumentParser(
        description="爬取 ElevenLabs 音效库营销片段(搜索接口)并输出 JSON"
    )
    parser.add_argument("--query", default="", help="搜索关键词，例如 explosion（默认空=默认列表）")
    parser.add_argument("--request-file", default=None,
                        help="浏览器导出的请求信息文件路径（含 cookie/next-action 等）")
    parser.add_argument("--cookie", default=None, help="覆盖 cookie（不填则从请求文件读取）")
    parser.add_argument("--next-action", dest="next_action", default=None, help="覆盖 next-action")
    parser.add_argument("--x-deployment-id", dest="x_deployment_id", default=None,
                        help="覆盖 x-deployment-id")
    parser.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY"),
                        help="HTTP/HTTPS 代理，例如 http://127.0.0.1:7892")
    parser.add_argument("--output", "-o", default="elevenlabs_sound_effects.json",
                        help="输出 JSON 文件路径")
    parser.add_argument("--parse-file", default=None,
                        help="直接解析已保存的响应文件（跳过网络请求，用于离线调试）")
    parser.add_argument("--no-translate", dest="translate", action="store_false",
                        help="关闭中文→英文的 LLM 自动翻译（仅用英文原词检索）")
    # 下载相关
    parser.add_argument("--download", action="store_true",
                        help="爬取完成后，下载各营销片段下的音效音频")
    parser.add_argument("--download-dir", default="downloads",
                        help="音效下载目录（默认 ./downloads）")
    parser.add_argument("--flatten", action="store_true",
                        help="下载时所有音频平铺到下载目录，不按营销片段分子目录")
    parser.add_argument("--download-url", action="append", default=None, metavar="URL",
                        help="直接下载给定音频 URL（可多次指定，独立于爬取流程）")
    args = parser.parse_args()

    # 直接下载模式（按 URL 列表，不经过爬取）
    if args.download_url:
        records = download_urls(args.download_url, args.download_dir, proxy=args.proxy)
        ok_n = sum(1 for r in records if r["ok"])
        print(f"已下载 {ok_n}/{len(records)} 个音频至: {args.download_dir}")
        for r in records:
            print(f"  [{'OK' if r['ok'] else 'FAIL'}] {r['url']} -> {r['path']}"
                  + ("" if r["ok"] else f"  ({r['error']})"))
        return

    # 离线解析模式
    if args.parse_file:
        with open(args.parse_file, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        obj = parse_docs_from_response(text)
        if not obj or "docs" not in obj:
            raise SystemExit("从 --parse-file 中未能解析出 docs 数据。")
        result = {
            "query_original": args.query,
            "query": args.query,
            "translated": False,
            "count": len(obj.get("docs", [])),
            "source": ENDPOINT,
            "items": docs_to_items(obj.get("docs")),
        }
    else:
        if not args.request_file:
            # 默认尝试脚本同目录下的精简 JSON 请求信息文件
            guess = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "elevenlabs_request.json")
            if os.path.isfile(guess):
                args.request_file = guess
        result = crawl(
            query=args.query,
            request_file=args.request_file,
            cookie=args.cookie,
            next_action=args.next_action,
            x_deployment_id=args.x_deployment_id,
            proxy=args.proxy,
            translate=args.translate,
        )

    # 可选：下载音效
    if args.download:
        print("开始下载音效片段…", flush=True)
        records = download_items(
            result["items"], args.download_dir, proxy=args.proxy, flatten=args.flatten
        )
        ok_n = sum(1 for r in records if r["ok"])
        result["downloaded"] = {
            "dir": os.path.abspath(args.download_dir),
            "total": len(records),
            "ok": ok_n,
            "failed": len(records) - ok_n,
            "records": records,
        }
        print(f"下载完成：{ok_n}/{len(records)} 成功，目录: {args.download_dir}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"已抓取 {result['count']} 个营销片段，保存至: {args.output}")
    for it in result["items"][:5]:
        print(f"  - {it['title']}  ({it['slug']})  sounds={len(it['sounds'])}")


if __name__ == "__main__":
    main()
