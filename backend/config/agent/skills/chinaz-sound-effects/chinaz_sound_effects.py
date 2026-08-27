#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
chinaz_sound_effects.py —— 站长之家音效库 (https://sc.chinaz.com/yinxiao/) 爬虫。

能力（对外 API）：
  - get_categories()            : 返回全部「筛选标签」列表（name + 子 url），结果持久化到
                                  chinaz_categories.json，首次运行自动抓取并缓存。
  - get_audio_list(url,...)     : 按某个标签的子 url 抓取音频列表，返回结构化数据
                                  [{name, detail_url, preview_url, tags:[{name,url}]}]。
  - get_audio_detail(url)       : 抓取某音频详情页，返回 {download_url, tags}。
  - search(keyword, page=1)     : 按关键词搜索，返回 [{name, detail_url}]。
  - download_audio(url, dir,...) : 下载单个音频文件到本地，返回本地路径。

容错：
  - 网络请求带重试（网络异常 / 5xx 自动退避重试；4xx 不重试）。
  - Windows 下用 Wide API 重新解析命令行，规避中文参数被控制台代码页乱码。
  - 标签名匹配容错：精确(忽略大小写/空白) → 包含匹配；多个候选会列出供参考。
  - 下载文件名自动清洗、同名校验避免覆盖。

页面为 GBK 编码，无需浏览器 / 无 WAF（普通 requests 即可）。
筛选标签在 //*[@id="Screen"] 下；音频列表容器为 //*[@id="AudioList"]。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from lxml import html as lxml_html

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://sc.chinaz.com"
LIST_URL = BASE + "/yinxiao/"
CATEGORIES_FILE = os.path.join(HERE, "chinaz_categories.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# 基础请求（带重试容错）
# --------------------------------------------------------------------------- #
def _decode_body(resp):
    """按页面 charset（多为 GBK/gb2312）解码；失败回退 GBK。"""
    enc = re.search(r'charset=["\']?([\w-]+)', resp.text[:2000])
    enc = enc.group(1).lower() if enc else None
    if enc in ("gb2312", "gbk", "gb18030"):
        enc = "gbk"
    try:
        return resp.content.decode(enc or "utf-8")
    except (LookupError, UnicodeDecodeError):
        return resp.content.decode("gbk", errors="replace")


def _get(url, headers, timeout, retries=3, backoff=1.5):
    """带重试的 GET：网络异常 / 5xx 退避重试；4xx 不重试直接返回由调用方处理。"""
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            return resp
        except (requests.RequestException, requests.HTTPError) as e:
            last = e
            if attempt < retries:
                print(f"[retry] {url} 第{attempt}次失败：{e}；{backoff:.1f}s 后重试",
                      file=sys.stderr)
                time.sleep(backoff * attempt)
    raise last or requests.RequestException("未知请求错误")


def fetch_html(url, referer=None, timeout=30, retries=3):
    """请求页面并解码为文本（GBK 容错）。"""
    headers = {"user-agent": UA, "accept-language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["referer"] = referer
    resp = _get(url, headers, timeout, retries=retries)
    resp.raise_for_status()
    return _decode_body(resp)


def _abs(url):
    """协议相对 //host/path → https://host/path。"""
    if url and url.startswith("//"):
        return "https:" + url
    return url


def audio_number(detail_url):
    """从详情页 url 提取音频编号（如 /yinxiao/260415541901.htm → 260415541901）。"""
    if not detail_url:
        return None
    m = re.search(r"/(\d+)\.htm", detail_url)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# 筛选标签（持久化）
# --------------------------------------------------------------------------- #
def parse_categories(html):
    """从主列表页的 #Screen 提取所有筛选标签（name + 子 url），去重。"""
    tree = lxml_html.fromstring(html)
    screen = tree.xpath('//*[@id="Screen"]')
    out, seen = [], set()
    if not screen:
        return out
    for a in screen[0].xpath(".//a"):
        href = a.get("href")
        name = (a.text_content() or "").strip()
        if not href or not name or "chinaz.com" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append({"name": name, "url": href})
    return out


def load_categories(force_refresh=False):
    """读取缓存；缓存缺失或 force_refresh 时重新抓取主列表页并持久化。"""
    if not force_refresh and os.path.exists(CATEGORIES_FILE):
        try:
            with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)["tags"]
        except (KeyError, json.JSONDecodeError, OSError):
            pass
    html = fetch_html(LIST_URL, referer=BASE + "/")
    tags = parse_categories(html)
    data = {
        "source": LIST_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(tags),
        "tags": tags,
    }
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return tags


def get_categories(force_refresh=False):
    """对外：返回全部筛选标签 [{name, url}, ...]。"""
    return load_categories(force_refresh=force_refresh)


def _find_category(cats, key):
    """容错匹配标签：精确(忽略大小写/空白) → 包含匹配。
    返回单个匹配 dict；若命中多个返回 list（交由调用方提示）；无命中返回 None。"""
    key = (key or "").strip().lower()
    if not key:
        return None
    exact = next((c for c in cats if c["name"].strip().lower() == key), None)
    if exact:
        return exact
    hits = [c for c in cats if key in c["name"].strip().lower()]
    if len(hits) == 1:
        return hits[0]
    return hits  # 0 个或 >1 个，交给调用方


# --------------------------------------------------------------------------- #
# 音频列表
# --------------------------------------------------------------------------- #
def parse_audio_items(html):
    """解析 #AudioList 下的音频条目为结构化数据。"""
    tree = lxml_html.fromstring(html)
    items = []
    for it in tree.xpath('//*[@id="AudioList"]'
                         '//div[contains(@class, "audio-item")]'):
        name_el = it.xpath('.//p[contains(@class, "name")]')
        name = name_el[0].text_content().strip() if name_el else None

        da = it.xpath('.//p[contains(@class, "name")]/ancestor::a[1]')
        detail_url = _abs(da[0].get("href")) if da else None

        aud = it.xpath(".//audio")
        preview_url = _abs(aud[0].get("src")) if aud else None

        tags = [{"name": (t.text_content() or "").strip(), "url": _abs(t.get("href"))}
                for t in it.xpath('.//div[contains(@class, "audio-class")]//a')
                if (t.text_content() or "").strip()]

        items.append({
            "name": name,
            "detail_url": detail_url,
            "preview_url": preview_url,
            "tags": tags,
        })
    return items


def _page_url(base, n):
    """标签页分页规律：第 N 页为 xxx_N.html（N>=2）。"""
    if n <= 1:
        return base
    return re.sub(r"\.html$", f"_{n}.html", base)


def get_audio_list(url, max_pages=1, start_page=1):
    """对外：按标签子 url 抓取音频列表，跨页合并并去重。"""
    all_items, seen = [], set()
    for p in range(start_page, start_page + max_pages):
        page_url = _page_url(url, p)
        try:
            html = fetch_html(page_url, referer=LIST_URL)
        except requests.HTTPError:
            break
        items = parse_audio_items(html)
        if not items:
            break
        for it in items:
            key = it["detail_url"] or it["name"]
            if key in seen:
                continue
            seen.add(key)
            all_items.append(it)
    return all_items


# --------------------------------------------------------------------------- #
# 详情页
# --------------------------------------------------------------------------- #
def parse_detail(html):
    """解析详情页：下载地址 + 多个标签。"""
    tree = lxml_html.fromstring(html)
    dl = tree.xpath('/html/body/div[4]/div/div[2]/div[4]/div[2]'
                    '/div[1]/div[1]/a[1]')
    download_url = _abs(dl[0].get("href")) if dl else None

    tag_div = tree.xpath('/html/body/div[4]/div/div[2]/div[2]/div[2]/div')
    tags = []
    if tag_div:
        tags = [(a.text_content() or "").strip()
                for a in tag_div[0].xpath(".//a")]
        tags = [t for t in tags if t]
    return {"download_url": download_url, "tags": tags}


def get_audio_detail(url):
    """对外：抓取某音频详情页，返回 {download_url, tags}。"""
    html = fetch_html(url, referer=LIST_URL)
    return parse_detail(html)


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #
def search(keyword, page=1):
    """对外：按关键词搜索，返回 [{name, detail_url}]。"""
    kw = quote(keyword)
    url = f"https://aspx.sc.chinaz.com/query.aspx?classid=14&keyword={kw}"
    if page > 1:
        url += f"&page={page}"
    html = fetch_html(url, referer=LIST_URL)
    tree = lxml_html.fromstring(html)
    out, seen = [], set()
    for a in tree.xpath('//a[contains(@href, "sc.chinaz.com/yinxiao/") '
                        'and contains(@href, ".htm")]'):
        href = a.get("href")
        name = (a.text_content() or "").strip()
        if not name or not re.search(r"/yinxiao/\d+\.htm$", href):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append({"name": name, "detail_url": _abs(href)})
    return out


# --------------------------------------------------------------------------- #
# 音频下载
# --------------------------------------------------------------------------- #
def download_audio(url, save_dir, name_hint=None, referer=None, timeout=60):
    """下载单个音频到 save_dir；文件名取自 name_hint(清洗) 或 url basename；
    同名校验自动加序号避免覆盖。返回本地路径。"""
    os.makedirs(save_dir, exist_ok=True)
    base = os.path.basename(url.split("?")[0])
    ext = os.path.splitext(base)[1].lower() or ".mp3"
    if name_hint:
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name_hint).strip()
        safe = safe[:120] or base
        fname = safe + ext
    else:
        fname = base or ("audio" + ext)
    path = os.path.join(save_dir, fname)
    if os.path.exists(path):
        stem, e = os.path.splitext(fname)
        i = 1
        while os.path.exists(path):
            path = os.path.join(save_dir, f"{stem}_{i}{e}")
            i += 1
    headers = {"user-agent": UA, "accept-language": "zh-CN,zh;q=0.9",
               "referer": referer or LIST_URL}
    resp = _get(url, headers, timeout, retries=3)
    resp.raise_for_status()
    with open(path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return path


# --------------------------------------------------------------------------- #
# CLI 辅助
# --------------------------------------------------------------------------- #
def _fix_argv():
    """Windows 下 sys.argv 可能因控制台代码页被错误解码中文参数；
    改用 Wide API 取真正的 UTF-16 命令行，彻底规避乱码。非 Windows 不处理。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import POINTER, byref, c_int
        from ctypes.wintypes import LPCWSTR, LPWSTR
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32
        kernel32.GetCommandLineW.restype = LPCWSTR
        cmd = kernel32.GetCommandLineW()
        shell32.CommandLineToArgvW.argtypes = [LPCWSTR, POINTER(c_int)]
        shell32.CommandLineToArgvW.restype = POINTER(LPWSTR)
        n = c_int()
        argv = shell32.CommandLineToArgvW(cmd, byref(n))
        wide = [argv[i] for i in range(n.value)]
        # 定位脚本名在 wide 列表中的位置，取其后的部分作为真正的参数
        script_base = os.path.basename(sys.argv[0]).lower()
        idx = None
        for i, a in enumerate(wide):
            if os.path.basename(a).lower() == script_base:
                idx = i
                break
        if idx is not None:
            sys.argv = wide[idx:]
    except Exception:
        pass


def _dump(obj, output):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {output}（{len(obj) if hasattr(obj, '__len__') else '?'} 条）",
              file=sys.stderr)
    else:
        print(text)


def _download_list(items, args):
    """对音频列表批量下载：按编号拉详情页取高码率 download_url，文件名用编号；
    若详情/高码率不可用则回退低码率预览。"""
    if not args.download:
        return
    ok = 0
    for it in items:
        du = it.get("detail_url")
        num = audio_number(du) or it.get("name")
        url, referer = None, du or LIST_URL
        if du:
            try:
                det = get_audio_detail(du)
                if det.get("download_url"):
                    url = det["download_url"]
            except Exception as e:
                print(f"[warn] 详情获取失败 {it.get('name')}: {e}", file=sys.stderr)
        if not url and it.get("preview_url"):
            url = it["preview_url"]
            print(f"[warn] 编号 {num} 改用低码率预览", file=sys.stderr)
        if not url:
            continue
        try:
            it["local_path"] = download_audio(
                url, args.save_dir, name_hint=num, referer=referer)
            ok += 1
        except Exception as e:
            print(f"[warn] 下载失败 {it.get('name')}: {e}", file=sys.stderr)
    print(f"[info] 已下载 {ok}/{len(items)} 个音频到 {args.save_dir}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    _fix_argv()
    ap = argparse.ArgumentParser(
        description="站长之家音效库爬虫 (sc.chinaz.com/yinxiao)")
    ap.add_argument("--list-categories", action="store_true",
                    help="列出全部筛选标签")
    ap.add_argument("--refresh-categories", action="store_true",
                    help="强制重新抓取并刷新筛选标签缓存")
    ap.add_argument("--category", help="按标签名称匹配，抓取该标签的音频列表")
    ap.add_argument("--category-url", help="直接给定标签子 url，抓取音频列表")
    ap.add_argument("--search", help="按关键词搜索")
    ap.add_argument("--detail", help="给定音频详情页 url，获取下载地址与标签")
    ap.add_argument("--max-pages", type=int, default=1,
                    help="音频列表最多抓取的页数（默认 1）")
    ap.add_argument("--download", action="store_true",
                    help="同时下载音频文件（按编号取高码率原文件，失败回退低码率预览）")
    ap.add_argument("--save-dir", default="chinaz_audio",
                    help="下载保存目录（默认 chinaz_audio）")
    ap.add_argument("--output", help="结果输出到 JSON 文件（默认打印到终端）")
    args = ap.parse_args(argv)

    if args.refresh_categories:
        tags = get_categories(force_refresh=True)
        print(f"已刷新筛选标签缓存：{len(tags)} 个 → {CATEGORIES_FILE}",
              file=sys.stderr)

    result = None

    if args.list_categories:
        result = get_categories(force_refresh=args.refresh_categories)

    elif args.detail:
        result = get_audio_detail(args.detail)
        if args.download and isinstance(result, dict) and result.get("download_url"):
            try:
                result["local_path"] = download_audio(
                    result["download_url"], args.save_dir,
                    name_hint=audio_number(args.detail), referer=args.detail)
            except Exception as e:
                print(f"[warn] 下载失败：{e}", file=sys.stderr)

    elif args.search:
        result = search(args.search)
        if args.download and isinstance(result, list):
            for r in result:
                du = r.get("detail_url")
                try:
                    det = get_audio_detail(du)
                    if det.get("download_url"):
                        r["local_path"] = download_audio(
                            det["download_url"], args.save_dir,
                            name_hint=audio_number(du) or r["name"],
                            referer=du)
                except Exception as e:
                    print(f"[warn] 下载失败 {r.get('name')}: {e}", file=sys.stderr)

    elif args.category_url:
        result = get_audio_list(args.category_url, max_pages=args.max_pages)
        _download_list(result, args)

    elif args.category:
        cats = get_categories(force_refresh=args.refresh_categories)
        m = _find_category(cats, args.category)
        if isinstance(m, list):
            if not m:
                print(f"[error] 未找到标签「{args.category}」，用 --list-categories 查看。",
                      file=sys.stderr)
                raise SystemExit(1)
            print(f"[warn] 标签「{args.category}」命中 {len(m)} 个，使用第一个「{m[0]['name']}」",
                  file=sys.stderr)
            for c in m:
                print(f"        - {c['name']}  {c['url']}", file=sys.stderr)
            m = m[0]
        print(f"[info] 命中标签「{m['name']}」→ {m['url']}", file=sys.stderr)
        result = get_audio_list(m["url"], max_pages=args.max_pages)
        _download_list(result, args)

    else:
        ap.print_help()
        return

    if result is not None:
        _dump(result, args.output)


if __name__ == "__main__":
    main()
