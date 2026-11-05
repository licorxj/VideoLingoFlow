"""
Baijiahao (百家号) platform implementation -- 100% CloakBrowser.

All browser operations go through ``BasePlatform.create_browser()`` /
``BasePlatform.create_context()`` which delegate to CloakBrowser (stealth
Chromium) with automatic Playwright fallback.
"""

import asyncio
import os
import time
from datetime import datetime

from util._logger import bind_account_name, get_channel_logger
import threading
from pathlib import Path
from queue import Queue

from conf import BASE_DIR

from .._browser import create_browser_sync, create_context_sync
from .._utils import (
    clear_and_type,
    get_account_name_by_cookie_file,
    parse_schedule_time,
    raise_if_page_closed,
    save_login_result,
    scrape_baijiahao_profile,
)
from ..base_platform import BasePlatform

logger = get_channel_logger("baijiahao")


class BaijiahaoPlatform(BasePlatform):
    platform_id = 6
    platform_key = "baijiahao"
    platform_name = "百家号"

    # 支持 cookie 字符串导入账号
    supports_cookie_import = True
    # 百度系 cookie 全部由 passport.baidu.com 下发，通配 .baidu.com 后对
    # baijiahao.baidu.com / passport.baidu.com / www.baidu.com 都生效。
    platform_cookie_domain = ".baidu.com"

    # Cookie 失效时可能跳到的所有百度账号体系登录/中间页子串。
    # 任一命中即视为失效,不再依赖单一精确业务登录 URL。
    _COOKIE_INVALID_URL_MARKERS = (
        "/builder/theme/bjh/login",
        "passport.baidu.com/v3/login",
        "passport.baidu.com/v3/ucenter",
        "wappass.baidu.com",
        "auth.baidu.com",
    )

    def _parse_cookie_to_storage_state(
        self, cookie_str: str
    ) -> tuple[list[dict], list[dict]]:
        """把 'k=v; k=v' 解析为 Playwright storage_state 的 (cookies, origins)。

        - 全部 cookie 归属 ``platform_cookie_domain`` (.baidu.com)
        - expires 给 7 天保守占位，sync_profile 跑完后 storage_state 会被
          回写为真实的 cookie（含真实 expires + localStorage）
        - localStorage 留空，由 sync_profile 自然补全
        """
        cookies: list[dict] = []
        expires = time.time() + BasePlatform._IMPORT_COOKIE_EXPIRES_SECONDS
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": self.platform_cookie_domain,
                "path": "/",
                "expires": expires,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            })
        logger.info(
            f"[baijiahao] cookie 解析: {len(cookies)} 条, domain={self.platform_cookie_domain}"
        )
        return cookies, []

    # ------------------------------------------------------------------
    # login -- QR code / redirect via CloakBrowser
    # ------------------------------------------------------------------

    async def login(self, id: str, status_queue: Queue, account_id=None) -> None:
        """Perform Baijiahao login.

        Opens ``https://baijiahao.baidu.com/builder/theme/bjh/login`` and
        waits for the page to redirect to ``**/builder/rc/home**`` without
        timeout — QR code login may take several minutes.  On success,
        scrapes the user profile and saves the login result via the shared
        utility.
        """
        browser = await self.create_browser(login_mode=True)
        success = False
        try:
            context = await self.create_context(browser)
            try:
                page = await context.new_page()
                await page.goto(
                    "https://baijiahao.baidu.com/builder/theme/bjh/login",
                    wait_until="domcontentloaded",
                )
                logger.info("百家号登录页面已打开，请完成扫码登录...")

                # 不设超时——扫码登录可能耗时几分钟，浏览器由用户自己关
                await page.wait_for_url("**/builder/rc/home**", timeout=0)
                logger.info("检测到登录成功，正在保存 cookie...")

                # Scrape profile & save via shared utility
                await save_login_result(
                    context,
                    page,
                    platform_id=self.platform_id,
                    platform_name=self.platform_name,
                    status_queue=status_queue,
                    scrape_fn=scrape_baijiahao_profile,
                    account_id=account_id,
                    # 登录成功后在同一个 session 内补抓 stats(6 项运营数据),
                    # 与 sync_profile 共用同一份抓取逻辑
                    stats_fn=self._login_stats_fn,
                )
                success = True
            finally:
                # 释放 context 资源
                await context.close()
        finally:
            # 成功才关浏览器（失败/异常时留着让用户看现场）
            if success:
                await browser.close()

    # ------------------------------------------------------------------
    # check_cookie -- verify stored cookie is still valid
    # ------------------------------------------------------------------

    async def check_cookie(self, cookie_file: str) -> bool:
        """Return True if the saved cookie file is still valid.

        Opens ``https://baijiahao.baidu.com/builder/rc/home`` with the
        stored cookies.  Cookie invalid if:
        - cookie 文件不存在
        - 跳到任意失效 URL marker (见 ``_COOKIE_INVALID_URL_MARKERS``)
        - 跳出了 baijiahao.baidu.com 业务域 (兜底)
        """
        cookie_path = str(Path(BASE_DIR / "cookiesFile" / cookie_file))
        if not os.path.exists(cookie_path):
            logger.info("[baijiahao] cookie file not found")
            return False
        browser = await self.create_browser(headless=True)
        try:
            context = await self.create_context(
                browser, storage_state=cookie_path
            )
            try:
                page = await context.new_page()
                await page.goto(
                    "https://baijiahao.baidu.com/builder/rc/home"
                )
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await asyncio.sleep(2)

                current_url = page.url or ""
                # 黑名单: 任一失效 marker 命中即视为失效
                for marker in self._COOKIE_INVALID_URL_MARKERS:
                    if marker in current_url:
                        logger.info(
                            f"[baijiahao] cookie expired (matched: {marker})"
                        )
                        return False
                # 业务域兜底: URL 必须在 baijiahao.baidu.com 下才算成功
                if not current_url.startswith(
                    "https://baijiahao.baidu.com/"
                ):
                    logger.info(
                        f"[baijiahao] cookie redirected off-domain: {current_url}"
                    )
                    return False
                logger.info("[baijiahao] cookie valid")
                return True
            except Exception as exc:
                logger.info(f"[baijiahao] cookie check error: {exc}")
                return False
            finally:
                await context.close()
        finally:
            await browser.close()

    # ------------------------------------------------------------------
    # sync_profile -- refresh user name / avatar
    # ------------------------------------------------------------------

    async def sync_profile(self, cookie_file: str) -> dict:
        """Sync profile info (name, avatar, stats) from Baijiahao.

        抓取流程:
        1. 访问 https://baijiahao.baidu.com/builder/rc/home 抓 name/avatar
        2. 访问 https://baijiahao.baidu.com/ 抓 6 项 stats:
           累计投稿量/累计阅读(播放)量/累计百度搜索量/总粉丝量/累计总收益/近30天分润收益
        3. 同步完成后立即回写 storage_state,把本轮产生的 cookie + localStorage 一并落盘

        卡片显示 3 项(粉丝量/累计阅读(播放)量/累计百度搜索量),其余 3 项进悬浮窗。
        """
        cookie_path = str(Path(BASE_DIR / "cookiesFile" / cookie_file))
        browser = await self.create_browser(headless=True)
        try:
            context = await self.create_context(
                browser, storage_state=cookie_path
            )
            try:
                page = await context.new_page()
                await page.goto(
                    "https://baijiahao.baidu.com/builder/rc/home"
                )
                name, avatar = await scrape_baijiahao_profile(page)

                # 抓 stats(运营数据)
                try:
                    await page.goto("https://baijiahao.baidu.com/", wait_until="domcontentloaded", timeout=30000)
                    stats = await self._scrape_baijiahao_stats(page)
                except Exception as exc:
                    logger.info(f"[baijiahao] 抓 stats 失败(不影响 name/avatar): {exc}")
                    stats = []

                # 同步完成后立即把 storage_state 写回(关键):
                # 1) cookie 的真实 expires / httponly 等属性
                # 2) 百家号域下产生的 localStorage (userinfo / token 等)
                # 手工导入的 cookie 没有这些数据,不写回后续流程仍会失败。
                try:
                    await context.storage_state(path=cookie_path)
                    logger.info(
                        f"[baijiahao] sync_profile 已回写 storage_state: {cookie_path}"
                    )
                except Exception as e:
                    logger.info(f"[baijiahao] 回写 storage_state 失败: {e}")

                return {"name": name, "avatar": avatar, "stats": stats}
            finally:
                await context.close()
        finally:
            await browser.close()

    async def _scrape_baijiahao_stats(self, page) -> list:
        """抓取百家号首页 6 项运营数据。

        页面 DOM 结构(参见用户提供的 2026-07-20 抓取样本):
            <div class="FeReactApp-...-filterItem">
                <div class="FeReactApp-...-title">累计投稿量<span>...</span></div>
                <div class="FeReactApp-...-numbers"><span>18</span></div>
                ...
            </div>
        每块 .filterItem 都有 title(指标名)和 numbers(数值)。

        Returns:
            list[dict]: 按 SORT 排序的运营数据列表
        """
        stats = []
        # label_map: 百家号页面上的中文指标名 -> (ICON, SORT, 标准化 NAME)
        # SORT 1-3 是卡片显示的优先项(粉丝/播放量/搜索量);4-6 进悬浮窗
        label_map = {
            "总粉丝量":         ("user",  1, "粉丝"),
            "累计阅读(播放)量": ("play",  2, "播放量"),
            "累计百度搜索量":   ("play",  3, "搜索量"),
            "累计投稿量":       ("edit",  4, "投稿量"),
            "累计总收益":       ("coin",  5, "累计收益"),
            "近30天分润收益":   ("coin",  6, "近30天分润"),
        }

        try:
            try:
                await page.wait_for_selector(".FeReactApp-_3a492ee4f8f1a936-filterItem", timeout=10000)
            except Exception:
                logger.info("[baijiahao stats] 等待 .filterItem 超时")

            raw = await page.evaluate(
                '''() => {
                    const out = [];
                    document.querySelectorAll('.FeReactApp-_3a492ee4f8f1a936-filterItem').forEach(item => {
                        const titleEl = item.querySelector('.FeReactApp-_3a492ee4f8f1a936-title');
                        const numEl = item.querySelector('.FeReactApp-_3a492ee4f8f1a936-numbers span');
                        if (!titleEl || !numEl) return;
                        // title 文本去掉内嵌的 svg/icon 节点,只保留文字
                        const label = (titleEl.textContent || '').trim();
                        const num = (numEl.textContent || '').trim();
                        if (label && num) out.push({label, num});
                    });
                    return out;
                }'''
            )
            for item in raw:
                label = item.get('label', '')
                if label in label_map:
                    icon, sort_no, name = label_map[label]
                    try:
                        count = int(str(item.get('num', '0')).replace(',', '').replace(' ', '').replace('+', '') or '0')
                    except (ValueError, TypeError):
                        count = 0
                    stats.append({"ICON": icon, "COUNT": count, "NAME": name, "SORT": sort_no})
        except Exception as exc:
            logger.info(f"[baijiahao stats] 抓取失败: {exc}")

        stats.sort(key=lambda x: x.get("SORT", 999))
        return stats

    async def _login_stats_fn(self, page, account_id) -> list:
        """登录成功后的 stats 抓取入口(供 save_login_result 调用)。

        与 sync_profile 内部共用 _scrape_baijiahao_stats 抓取逻辑。
        """
        try:
            try:
                await page.goto("https://baijiahao.baidu.com/", wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            return await self._scrape_baijiahao_stats(page)
        except Exception as exc:
            logger.info(f"[baijiahao login] _login_stats_fn 抓取失败: {exc}")
            return []

    # ------------------------------------------------------------------
    # open_creator_center -- visible browser window (sync CloakBrowser)
    # ------------------------------------------------------------------

    async def open_creator_center(self, cookie_file: str) -> None:
        """Open the Baijiahao creator centre in a visible browser window."""
        cookie_path = str(Path(BASE_DIR / "cookiesFile" / cookie_file))
        url = "https://baijiahao.baidu.com/"

        def _launch():
            browser = create_browser_sync(headless=False)
            try:
                context = create_context_sync(browser, storage_state=cookie_path)
                page = context.new_page()
                page.goto(url)
                try:
                    page.wait_for_event("close", timeout=0)
                except Exception:
                    pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

        thread = threading.Thread(target=_launch, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    # publish_video -- full Baijiahao upload pipeline (sync entry point)
    # ------------------------------------------------------------------

    def publish_video(self, **kwargs) -> bool:
        """Publish a video to Baijiahao (sync wrapper).

        Accepted keyword arguments:

        - ``title`` (*str*) -- video title
        - ``files`` (*list[str]*) -- video absolute file paths (resolved by app.py)
        - ``tags`` (*list[str]*) -- hashtags
        - ``account_file`` (*list[str]*) -- cookie file names
        - ``enableTimer`` (*bool*, optional)
        - ``videos_per_day`` (*int*, optional)
        - ``daily_times`` (*list*, optional)
        - ``start_days`` (*int*, optional)
        - ``thumbnail_landscape_path`` (*str*, optional)
        - ``thumbnail_portrait_path`` (*str*, optional)
        - ``desc`` (*str*, optional)
        - ``schedule_time_str`` (*str*, optional)
        - ``creation_declaration`` (*str*, optional)
        - ``supplementary_declaration`` (*str*, optional)
        - ``ai_content`` (*bool*, optional)
        """
        # ===== 前置校验:描述+标签总字符 ≤ 50(emoji 按 3 算),最多 10 标签 =====
        desc = kwargs.get("desc", "") or ""
        tags = kwargs.get("tags", []) or []
        ok, err = self._validate_publish_params(desc, tags)
        if not ok:
            logger.error("[发布视频] 百家号前置校验失败: %s", err)
            raise ValueError(err)

        asyncio.run(self._upload_all(**kwargs))
        return True

    # ------------------------------------------------------------------
    # Internal: orchestrate all file x account uploads
    # ------------------------------------------------------------------

    async def _upload_all(self, **kwargs):
        """Create a browser for each file+account combo and upload."""
        logger.info("=" * 60)
        logger.info("[发布视频] 开始百家号视频发布流程")
        logger.info("=" * 60)

        # 打印所有接收到的参数
        logger.info("[发布参数] 接收到的所有参数:")
        for key, value in kwargs.items():
            logger.info("[发布参数]   %s = %s (类型: %s)", key, value, type(value).__name__)

        title = kwargs.get("title", "")
        files = kwargs.get("files", [])
        tags = kwargs.get("tags", []) or []
        account_file = kwargs.get("account_file", [])
        enableTimer = kwargs.get("enableTimer", False)
        videos_per_day = kwargs.get("videos_per_day", 1)
        daily_times = kwargs.get("daily_times")
        start_days = kwargs.get("start_days", 0)
        thumbnail_landscape_path = kwargs.get("thumbnail_landscape_path")
        thumbnail_portrait_path = kwargs.get("thumbnail_portrait_path")
        # 16:9 横版封面:第一个 cover-container 固定上传 16:9
        thumbnail_landscape_169_path = kwargs.get("thumbnail_landscape_169_path", "") or ""
        desc = kwargs.get("desc", "")
        schedule_time_str = kwargs.get("schedule_time_str", "")
        creation_declaration = kwargs.get("creation_declaration", "")
        supplementary_declaration = kwargs.get("supplementary_declaration", "")
        ai_content = kwargs.get("ai_content", False)
        baijiahao_collection_name = kwargs.get("baijiahao_collection_name", "")

        # 打印发布参数摘要
        logger.info("[发布参数] 标题: %s", title)
        logger.info("[发布参数] 文件数量: %d", len(files))
        logger.info("[发布参数] 标签: %s", tags)
        logger.info("[发布参数] 视频简介: %s", desc[:50] if desc else "无")
        logger.info("[发布参数] 账号数量: %d", len(account_file))
        logger.info("[发布参数] 定时发布: %s", enableTimer)
        logger.info("[发布参数] 横版封面: %s", thumbnail_landscape_path or "无")
        logger.info("[发布参数] 竖版封面: %s", thumbnail_portrait_path or "无")
        logger.info("[发布参数] 横版16:9封面: %s", thumbnail_landscape_169_path or "无")
        logger.info("[发布参数] 创作声明: %s", creation_declaration or "无")
        logger.info("[发布参数] 补充声明: %s", supplementary_declaration or "无")
        logger.info("[发布策略] 发布策略: %s", "scheduled" if enableTimer and schedule_time_str else "immediate")

        # Resolve full paths
        account_paths = [
            str(Path(BASE_DIR / "cookiesFile") / f) for f in account_file
        ]
        # files 已是绝对路径（app.py 通过 _resolve_material_path 处理过）
        file_paths = [str(f) for f in files]
        if thumbnail_landscape_path:
            # 已是绝对路径
            thumbnail_landscape_path = str(thumbnail_landscape_path)
        if thumbnail_portrait_path:
            # 已是绝对路径
            thumbnail_portrait_path = str(thumbnail_portrait_path)

        # Determine schedule times
        publish_datetimes = parse_schedule_time(
            schedule_time_str,
            len(file_paths),
            enableTimer,
            videos_per_day,
            daily_times,
            start_days,
        )

        for file_index, file_path in enumerate(file_paths):
            logger.info("-" * 40)
            logger.info("[发布进度] 处理第 %d/%d 个视频: %s", file_index + 1, len(file_paths), file_path)
            for cookie_index, cookie_path in enumerate(account_paths):
                cookie_name = Path(cookie_path).name
                nick = get_account_name_by_cookie_file(cookie_name)
                with bind_account_name(nick or "-"):
                    logger.info("[发布进度] 发布到第 %d/%d 个账号 (%s)", cookie_index + 1, len(account_paths), nick or "未知")
                    await self._upload_one_video(
                        title=title,
                        file_path=file_path,
                        tags=tags,
                        publish_date=publish_datetimes[file_index],
                        account_file=cookie_path,
                        thumbnail_landscape_path=thumbnail_landscape_path,
                        thumbnail_portrait_path=thumbnail_portrait_path,
                        thumbnail_landscape_169_path=thumbnail_landscape_169_path,
                        desc=desc,
                        creation_declaration=creation_declaration,
                        supplementary_declaration=supplementary_declaration,
                        ai_content=ai_content,
                        baijiahao_collection_name=baijiahao_collection_name,
                    )

        logger.info("=" * 60)
        logger.info("[发布视频] 视频发布流程完成!")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Internal: upload one video to one account
    # ------------------------------------------------------------------

    async def _upload_one_video(
        self,
        title: str,
        file_path: str,
        tags: list,
        publish_date,
        account_file: str,
        thumbnail_landscape_path=None,
        thumbnail_portrait_path=None,
        thumbnail_landscape_169_path="",
        desc="",
        creation_declaration="",
        supplementary_declaration="",
        ai_content=False,
        baijiahao_collection_name="",
    ):
        """Upload a single video to one Baijiahao account."""
        browser = await self.create_browser(headless=False)
        try:
            context = await self.create_context(
                browser,
                storage_state=account_file,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.4324.150 Safari/537.36"
                ),
            )
            try:
                await context.grant_permissions(["geolocation"])
                page = await context.new_page()
                await page.goto(
                    "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2",
                    timeout=60000,
                )
                logger.info("[上传视频] 开始上传视频: %s", title)

                await page.wait_for_url(
                    "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2",
                    timeout=60000,
                )
                logger.info("[上传视频] 发布页面已打开")

                # 注册上传完成请求监听器（必须在 set_input_files 之前注册，
                # 否则可能错过在表单填充期间触发的完成请求）
                upload_done = asyncio.Event()

                def _on_bjh_request(request):
                    if (
                        "materialui/video/compuploadvideo" in request.url
                        and not upload_done.is_set()
                    ):
                        upload_done.set()

                page.on("request", _on_bjh_request)

                # Upload video file
                logger.info("[上传视频] 正在上传视频文件...")
                video_input = page.locator(
                    "input[type='file'][accept*='.mp4']"
                )
                if await video_input.count() == 0:
                    video_input = page.locator("input[type='file']").first
                await video_input.set_input_files(file_path)
                logger.info("[上传视频] 视频文件已选择，等待上传完成...")

                # Wait for the form page to appear
                while True:
                    raise_if_page_closed(page)
                    try:
                        await page.wait_for_selector(
                            "div#formMain:visible"
                        )
                        break
                    except Exception:
                        logger.info("[上传视频] 正在等待进入视频发布页面...")
                        await asyncio.sleep(0.1)

                # Fill title and tags
                await asyncio.sleep(1)
                logger.info("[填写标题] 开始填写标题与话题...")
                await self._add_title_tags(page, title, desc, tags)
                logger.info("[填写标题] 标题: %s", title)
                logger.info("[填写标题] 标题与话题填写完成")

                # Wait for video upload to complete (network signal)
                upload_status = await self._wait_for_upload(
                    page, upload_done
                )
                if not upload_status:
                    logger.error("[上传视频] 发现上传出错了... 文件:%s", file_path)
                    raise Exception("Video upload failed")
                logger.info("[上传视频] 视频上传成功!")

                # Wait for cover area to be ready
                while True:
                    container_count = await page.locator(
                        "div[class*='coverWrap'] > "
                        "div[class*='cover-container']"
                    ).count()
                    if container_count >= 2:
                        logger.info(
                            "[设置封面] 封面区域已就绪（找到 %d 个 cover-container）",
                            container_count,
                        )
                        break
                    else:
                        logger.info(
                            "[设置封面] 等待封面区域就绪（当前 %d 个 cover-container）...",
                            container_count,
                        )
                        await asyncio.sleep(3)

                # Set custom covers
                # 百家号封面对应关系固定, 不按视频方向:
                #   第一个 cover-container  → 横屏 16:9 封面
                #   第二个 cover-container  → 竖屏 3:4  封面
                picked_landscape = thumbnail_landscape_169_path or thumbnail_landscape_path
                picked_portrait = thumbnail_portrait_path
                logger.info(
                    "[设置封面] 横版16:9封面=%s, 竖版3:4封面=%s",
                    picked_landscape or "无", picked_portrait or "无",
                )
                logger.info("[设置封面] 开始设置视频封面...")
                await self._set_cover(
                    page,
                    picked_landscape,
                    picked_portrait,
                )
                logger.info("[设置封面] 封面设置完成")

                # Set creation declaration
                logger.info("[设置声明] 开始设置创作声明: %s", creation_declaration or "无")
                await self._set_creation_declaration(
                    page,
                    creation_declaration,
                    supplementary_declaration,
                )
                logger.info("[设置声明] 创作声明设置完成")

                # Set collection (合集)
                if baijiahao_collection_name:
                    logger.info("[设置合集] 开始设置合集: %s", baijiahao_collection_name)
                    await self._set_collection(page, baijiahao_collection_name)

                # Publish (immediate or scheduled)
                logger.info("[发布] 正在点击发布按钮...")
                await self._publish_video(page, publish_date)
                await page.wait_for_timeout(2000)

                # Handle captcha if present
                captcha_dialog = page.locator(
                    "div.passMod_dialog-container:visible"
                )
                if await captcha_dialog.count():
                    logger.warning(
                        "[发布] 出现人机校验，请在浏览器中手动完成验证..."
                    )
                    try:
                        await captcha_dialog.wait_for(
                            state="hidden", timeout=120000
                        )
                        logger.info("[发布] 人机校验已完成")
                        await asyncio.sleep(3)
                    except Exception:
                        logger.error("[发布] 人机校验等待超时（120秒），退出")
                        raise Exception("人机校验等待超时")

                # Wait for publish success redirect
                try:
                    await page.wait_for_url(
                        "https://baijiahao.baidu.com/builder/rc/clue**",
                        timeout=30000,
                    )
                    logger.info("[发布] 视频发布成功! 页面跳转到: %s", page.url)
                except Exception:
                    current_url = page.url
                    logger.error(
                        "[发布] 发布后未跳转到成功页面, 当前URL: %s",
                        current_url,
                    )
                    raise Exception(
                        f"视频发布后未成功跳转, 当前URL: {current_url}"
                    )

                # Save updated cookie state
                await context.storage_state(path=account_file)
                logger.info("[发布] Cookie状态已更新")
                await asyncio.sleep(2)
            finally:
                await context.close()
        finally:
            await self.close_browser(browser, is_close_by_code=True)

    # ------------------------------------------------------------------
    # Helper: 前置校验 - 描述+标签总字符 ≤50(emoji 按 3 算),最多 10 标签
    # ------------------------------------------------------------------

    @staticmethod
    def _count_chars(s: str) -> int:
        """按百家号规则计算字符数:中文/字母=1,emoji=3。"""
        n = 0
        for ch in s:
            # emoji 通常以 surrogate pair 或 grapheme cluster 出现,这里简化按 codepoint 判断
            if ord(ch) > 0xFFFF:
                n += 3
            else:
                n += 1
        return n

    @staticmethod
    def _validate_publish_params(desc: str, tags: list) -> tuple[bool, str]:
        """校验描述+标签,返回 (ok, msg)。

        规则:
        - 标签数 ≤ 10
        - 描述 + ' ' + ' '.join(f'#{t}' for t in tags) 总字符数 ≤ 50(emoji=3)
        """
        if tags and len(tags) > 10:
            return False, f"百家号最多 10 个标签,当前 {len(tags)} 个"

        # 模拟前端拼装(与 _add_title_tags 行为一致)
        parts = [desc or ""]
        if tags:
            parts.append(" ".join(f"#{t}" for t in tags))
        full = " ".join(p for p in parts if p).strip()
        char_count = BaijiahaoPlatform._count_chars(full)
        if char_count > 50:
            return False, (
                f"百家号描述+标签总字符数 {char_count} 超过 50(emoji 按 3 算),请精简"
            )
        return True, ""

    # ------------------------------------------------------------------
    # Helper: wait for video upload to complete
    # ------------------------------------------------------------------

    @staticmethod
    async def _wait_for_upload(
        page, upload_done: asyncio.Event,
    ) -> bool:
        """Wait for the authoritative upload-complete HTTP request.

        The caller must have registered a ``page.on("request")`` listener
        that sets ``upload_done`` when ``/materialui/video/compuploadvideo``
        is observed (registered BEFORE ``set_input_files`` so the request
        is not missed during form filling).

        DOM-based polling is unreliable — the cover overlay can flip
        states before the server has actually finished ingesting the
        file, leading to a publish click while the video is still
        uploading. The completion HTTP request is the source of truth.

        无超时:视频可能很大(≤16G),一直等到上传完成请求到达。

        Returns True on success, False on failure.
        """
        await upload_done.wait()
        logger.info("[上传视频] 视频上传完毕（检测到 compuploadvideo 请求）")
        return True

    # ------------------------------------------------------------------
    # Helper: fill title and tags (Baijiahao uses description field)
    # ------------------------------------------------------------------

    @staticmethod
    async def _add_title_tags(page, title, desc, tags):
        """Fill the description field (Lexical editor) with title and tags.

        Baijiahao publish page has a "作品描述" field (Lexical editor) rather
        than a separate title input. Tags are typed as #话题 via keyboard
        to trigger the topic search dropdown, then the first suggestion is
        selected.
        """
        # 描述为空时不再回落标题，保持为空
        desc_text = (desc or "").strip()[:2000]

        # Lexical contenteditable editor
        lexical_editor = page.locator('[data-lexical-editor="true"]')
        editor = None
        if await lexical_editor.count():
            editor = lexical_editor.first
        else:
            # Fallback: placeholder
            title_container = page.get_by_placeholder("添加标题获得更多推荐")
            if await title_container.count():
                full_text = desc_text
                if tags:
                    full_text += " " + " ".join(f"#{t}" for t in tags)
                await title_container.fill(full_text[:2000])
                logger.info("[填写简介] 已通过 placeholder 填充描述: %s", full_text[:2000])
                return
            logger.warning("[填写标题] 未找到描述输入框，跳过填充")
            return

        # 1. 清空编辑器 + 输入描述文本(跨平台:Mac 用 Cmd+A,其他用 Ctrl+A)
        await editor.click()
        await asyncio.sleep(0.3)
        await clear_and_type(page, desc_text, delay=50)
        if desc_text:
            logger.info("[填写标题] 已填充作品描述: %s", desc_text)

        # 2. 逐个输入 #话题 并从下拉列表选择第一个
        for tag in (tags or []):
            await page.keyboard.type(f" #{tag}", delay=50)
            await asyncio.sleep(1)

            # 等待话题搜索下拉出现
            topic_list = page.locator("div[class*='topicListInner']")
            try:
                await topic_list.wait_for(state="visible", timeout=3000)
                first_item = topic_list.locator("div[class*='topicItem']").first
                await first_item.click()
                logger.info("[填写标题] 已选择话题: #%s", tag)
                await asyncio.sleep(0.5)
            except Exception:
                logger.info("[填写标题] 话题 #%s 未出现下拉建议，跳过选择", tag)

    # ------------------------------------------------------------------
    # Helper: publish (immediate or scheduled)
    # ------------------------------------------------------------------

    @staticmethod
    async def _set_collection(page, collection_name: str) -> None:
        """选择指定合集(按名称匹配);无名称时跳过。

        TODO: 百家号视频发布页合集入口文案与下拉选项 DOM 需真实账号校准。
        当前按同类平台同源模式假设(「合集」入口 + 选项文本匹配),
        选择器不对时仅 warning 跳过,不阻塞发布。
        """
        if not collection_name:
            return
        try:
            entry = page.get_by_text("合集", exact=True)
            if await entry.count() == 0:
                logger.warning("[设置合集] 未找到「合集」入口,跳过")
                return
            await entry.first.click()
            await asyncio.sleep(1)
            # TODO: 合集下拉选项选择器需真实账号校准
            option_items = page.locator(".collection-item, [class*='collection'] [class*='item']")
            count = await option_items.count()
            for i in range(count):
                name = (await option_items.nth(i).inner_text()).strip()
                if name == collection_name:
                    await option_items.nth(i).click()
                    logger.info("[设置合集] 已选择合集: %s", collection_name)
                    return
            logger.warning("[设置合集] 未找到合集: %s", collection_name)
            await page.keyboard.press("Escape")
        except Exception as e:
            logger.warning("[设置合集] 合集设置失败(非致命): %s", e)

    async def _publish_video(self, page, publish_date):
        """Click the publish button, with optional scheduling."""
        if publish_date != 0:
            await self._set_schedule_publish(page, publish_date)
        else:
            await self._direct_publish(page)

    @staticmethod
    async def _direct_publish(page):
        """Click the publish button immediately."""
        try:
            publish_button = page.locator(
                "button[data-testid='publish-btn']"
            )
            if await publish_button.count():
                await publish_button.click()
            else:
                publish_button = page.locator(
                    "button.cheetah-btn-primary:has-text('发布')"
                )
                if await publish_button.count():
                    await publish_button.first.click()
        except Exception as e:
            logger.error("[发布] 直接发布视频失败: %s", e)
            raise

    # ------------------------------------------------------------------
    # Helper: schedule publish
    # ------------------------------------------------------------------

    async def _set_schedule_publish(self, page, publish_date):
        """Open the schedule dialog and set the time.

        Baijiahao only allows scheduled publish within the next 1 hour to 7 days.
        If the target time is today, the selected hour must be strictly greater
        than the current hour.
        """
        now = datetime.now()
        delta_days = (publish_date.date() - now.date()).days

        if delta_days < 0:
            raise ValueError(
                f"定时发布失败: 发布时间 {publish_date} 已早于当前时间"
            )
        if delta_days > 7:
            raise ValueError(
                f"定时发布失败: 发布时间 {publish_date} 超出百家号 7 天限制"
            )
        if delta_days == 0 and publish_date.hour <= now.hour:
            raise ValueError(
                f"定时发布失败: 今天发布时小时({publish_date.hour})必须大于当前小时({now.hour})"
            )

        date_label = f"{publish_date.month}月{publish_date.day}日"
        hour_label = f"{publish_date.hour}点"
        minute_label = f"{publish_date.minute}分"

        schedule_button = page.get_by_role(
            "button", name="定时发布", exact=True
        )
        await schedule_button.click()
        await page.wait_for_selector("#select-date", timeout=5000)
        await page.wait_for_timeout(500)

        await self._pick_schedule_option(page, "#select-date", date_label)
        await self._pick_schedule_option(page, "#select-hour", hour_label)
        await self._pick_schedule_option(page, "#select-minute", minute_label)

        await page.wait_for_timeout(500)
        # Confirm button is INSIDE the schedule dialog (not the page-level one)
        await page.locator("div[role='dialog']").get_by_role(
            "button", name="定时发布"
        ).click()
        logger.info(
            "百家号定时发布设置完成: %s %s:%s",
            date_label, publish_date.hour, publish_date.minute,
        )

    @staticmethod
    async def _pick_schedule_option(page, input_id: str, label: str) -> None:
        """Open one of the schedule selects and pick the target option.

        Force-clicks the hidden combobox input to open the dropdown, then
        navigates from the currently-highlighted option (``aria-activedescendant``)
        to the target using ArrowUp / ArrowDown keys, and confirms with Enter.
        ``rc-virtual-list`` auto-scrolls to keep the active option in view,
        so keyboard navigation drives the visible scroll.

        ``input_id`` must include the leading ``#``.
        """
        await page.locator(input_id).click(force=True)
        try:
            await page.wait_for_selector(
                f"{input_id}[aria-expanded='true']", timeout=3000
            )
        except Exception:
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(500)

        # Read current highlighted index (format: select-{kind}_list_{n})
        current_id = await page.evaluate(
            """(selector) => {
                const input = document.querySelector(selector);
                return input ? input.getAttribute('aria-activedescendant') : null;
            }""",
            input_id,
        )
        current_num = 0
        if current_id:
            parts = current_id.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                current_num = int(parts[1])

        # Compute target list index from label
        if "分" in label:
            target_num = int(label.replace("分", ""))
        elif "点" in label:
            target_num = int(label.replace("点", ""))
        elif "日" in label:
            day = int(label.split("月")[1].replace("日", ""))
            target_num = day - datetime.now().day
            if target_num < 0 or target_num > 7:
                target_num = 0
        else:
            target_num = 0

        # Re-focus the combobox so key events are routed to its keydown handler
        await page.locator(input_id).focus()
        await page.wait_for_timeout(200)

        diff = target_num - current_num
        if diff != 0:
            key = "ArrowDown" if diff > 0 else "ArrowUp"
            for _ in range(abs(diff)):
                await page.keyboard.press(key)
                await page.wait_for_timeout(40)

        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)

    # ------------------------------------------------------------------
    # Helper: set custom cover images (landscape + portrait)
    # ------------------------------------------------------------------

    @staticmethod
    async def _set_cover(
        page,
        thumbnail_landscape_path=None,
        thumbnail_portrait_path=None,
    ):
        """Upload custom cover images (landscape + portrait).

        Locates cover-container elements inside coverWrap, clicks each one
        to open a modal, uploads the image, and clicks confirm.
        """
        containers = page.locator(
            "div[class*='coverWrap'] > "
            "div[class*='cover-container']"
        )
        total = await containers.count()
        logger.info("[封面] 找到 %d 个 cover-container，开始逐个设置", total)

        for idx, (cover_type, cover_path) in enumerate(
            [
                ("横屏封面", thumbnail_landscape_path),
                ("竖屏封面", thumbnail_portrait_path),
            ]
        ):
            logger.info(
                "[封面] === 处理第 %d 个: %s ===", idx + 1, cover_type
            )

            if not cover_path or not os.path.exists(cover_path):
                logger.info("[封面] %s 无图片文件，跳过", cover_type)
                continue
            if idx >= total:
                logger.warning(
                    "[封面] cover-container 不足（%d），跳过%s",
                    total,
                    cover_type,
                )
                continue

            logger.info(
                "[封面] %s 图片: %s", cover_type, os.path.basename(cover_path)
            )
            try:
                container = containers.nth(idx)

                # 1. Click cover area to open modal
                logger.info(
                    "[封面] 点击第 %d 个 cover-container ...", idx + 1
                )
                await container.click()
                logger.info(
                    "[封面] 已点击%s，等待弹窗打开...", cover_type
                )

                # Wait for modal to appear
                await page.wait_for_selector(
                    "div.cheetah-modal:visible", timeout=10000
                )
                logger.info("[封面] %s弹窗已出现", cover_type)
                await asyncio.sleep(1)

                # 2. Upload image via file input inside the modal
                file_input_count = await page.locator(
                    "div.cheetah-modal:visible input[type='file']"
                ).count()
                logger.info(
                    "[封面] 弹窗中找到 %d 个 file input", file_input_count
                )

                dialog_input = page.locator(
                    "div.cheetah-modal:visible input[type='file']"
                ).first
                await dialog_input.set_input_files(cover_path)
                logger.info("[封面] 已上传%s文件", cover_type)
                await asyncio.sleep(2)

                # 3. Click confirm button in the modal
                confirm_btn = page.locator(
                    "div.cheetah-modal:visible "
                    "button.cheetah-btn-primary:has-text('确定')"
                )
                confirm_count = await confirm_btn.count()
                logger.info(
                    "[封面] 弹窗中找到 %d 个确定按钮", confirm_count
                )

                if confirm_count:
                    await confirm_btn.first.click()
                    logger.info("[封面] 已点击确定提交%s", cover_type)
                else:
                    logger.warning(
                        "[封面] %s弹窗未找到确定按钮", cover_type
                    )

                await asyncio.sleep(2)
                logger.info("[封面] %s设置完成", cover_type)

            except Exception as e:
                logger.error("[封面] 设置%s失败: %s", cover_type, e)

    # ------------------------------------------------------------------
    # Helper: set creation declaration
    # ------------------------------------------------------------------

    @staticmethod
    async def _set_creation_declaration(
        page, creation_declaration="", supplementary_declaration=""
    ):
        """Set the creation declaration (required + supplementary).

        Opens the declaration dialog, selects matching radio options, and
        confirms.
        """
        if not creation_declaration and not supplementary_declaration:
            return

        logger.info(
            "设置创作声明 - 必选: %s, 补充: %s",
            creation_declaration,
            supplementary_declaration,
        )
        try:
            declaration_input = page.locator(
                "input[placeholder='请选择创作声明']"
            )
            if not await declaration_input.count():
                logger.info("[设置声明] 未找到创作声明输入框，跳过")
                return

            await declaration_input.click()
            logger.info("[设置声明] 已点击创作声明输入框")
            await asyncio.sleep(1)

            # Locate dialog
            modal = page.get_by_role("dialog", name="创作声明")
            await modal.wait_for(state="visible", timeout=5000)
            logger.info("[设置声明] 创作声明弹窗已出现")

            # Select required declaration
            if creation_declaration:
                target_text = creation_declaration.strip()
                count = await modal.locator(
                    "div.flex.items-center.cursor-pointer"
                ).count()
                clicked = False
                for i in range(count):
                    row = modal.locator(
                        "div.flex.items-center.cursor-pointer"
                    ).nth(i)
                    row_text = (await row.inner_text() or "").strip()
                    if row_text == target_text:
                        await row.locator(
                            "input.cheetah-radio-input"
                        ).click(force=True)
                        logger.info("[设置声明] 已选择必选声明: %s", row_text)
                        clicked = True
                        break
                if not clicked:
                    logger.warning(
                        "未找到匹配的必选声明: %s", target_text
                    )
                await asyncio.sleep(0.5)

            # Select supplementary declaration
            if supplementary_declaration:
                target_text = supplementary_declaration.strip()
                count = await modal.locator(
                    "div.flex.items-center.cursor-pointer"
                ).count()
                clicked = False
                for i in range(count):
                    row = modal.locator(
                        "div.flex.items-center.cursor-pointer"
                    ).nth(i)
                    row_text = (await row.inner_text() or "").strip()
                    if row_text == target_text:
                        await row.locator(
                            "input.cheetah-radio-input"
                        ).click(force=True)
                        logger.info("[设置声明] 已选择补充声明: %s", row_text)
                        clicked = True
                        break
                if not clicked:
                    logger.warning(
                        "未找到匹配的补充声明: %s", target_text
                    )
                await asyncio.sleep(0.5)

            # Click confirm
            confirm_btn = modal.locator(
                "button.cheetah-btn-primary:has-text('确定')"
            )
            if await confirm_btn.count():
                await confirm_btn.click()
                logger.info("[设置声明] 已点击创作声明确定按钮")
            else:
                logger.warning("[设置声明] 未找到创作声明确定按钮")

            await asyncio.sleep(1)
            logger.info("[设置声明] 创作声明设置完成")

        except Exception as e:
            logger.warning("[设置声明] 设置创作声明失败（不影响上传）: %s", e)


    # ------------------------------------------------------------------
    # Publish image — 图文文章 (rich article with inline images)
    # ------------------------------------------------------------------

    BAIJIAHAO_ARTICLE_EDIT_URL = "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1"
    BAIJIAHAO_ARTICLE_TITLE_LIMIT = 64
    BAIJIAHAO_ARTICLE_MAX_IMAGES = 20

    def publish_image(self, **kwargs) -> bool:
        """Publish a rich article (图文文章) to Baijiahao (sync wrapper).

        Accepted keyword arguments (aligned with the ``publish_image`` contract
        in ``blueprints/image_publish_bp.py``):

        - ``title`` (*str*) -- article title, 2..64 chars (BJH limit)
        - ``files`` (*list[str]*) -- images inserted inline into the article body
        - ``tags`` (*list[str]*) -- accepted for contract parity; appended as a
          hashtag line at the end of the article body (article flow has no
          dedicated tag widget)
        - ``account_file`` (*list[str]*) -- cookie file names
        - ``desc`` (*str*) -- article body text (paragraphs split by newlines)
        - ``cover_path`` (*str*, optional) -- cover image; falls back to files[0]
        - ``creation_declaration`` / ``supplementary_declaration`` -- 创作声明
        - ``enableTimer`` / ``schedule_time_str`` -- scheduled publish
        - ``dry_run`` (*bool*) -- walk the whole flow but skip the final publish
          click (default True); a screenshot is saved under ``logs/``
        """
        title = kwargs.get("title", "")
        files = kwargs.get("files", []) or []
        tags = kwargs.get("tags", []) or []
        account_file = kwargs.get("account_file", []) or []
        desc = kwargs.get("desc", "")
        cover_path = kwargs.get("cover_path", "")
        creation_declaration = kwargs.get("creation_declaration", "") or kwargs.get("ai_content", "")
        supplementary_declaration = kwargs.get("supplementary_declaration", "")
        enable_timer = kwargs.get("enableTimer", False)
        schedule_time_str = kwargs.get("schedule_time_str", "")
        dry_run = kwargs.get("dry_run", True)

        logger.info("=" * 60)
        logger.info("[发布图文] 开始百家号图文文章发布流程")
        logger.info("=" * 60)

        # 文章流校验:标题 2..64(emoji 按 3 算),正文非空,图片数量上限
        t_len = self._count_chars(title)
        if t_len < 2 or t_len > self.BAIJIAHAO_ARTICLE_TITLE_LIMIT:
            raise ValueError(
                f"百家号文章标题需 2~{self.BAIJIAHAO_ARTICLE_TITLE_LIMIT} 字(emoji 按 3 算), 当前 {t_len} 字"
            )
        if not desc:
            raise ValueError("百家号图文文章需要正文内容(desc 不能为空)")
        if len(files) > self.BAIJIAHAO_ARTICLE_MAX_IMAGES:
            raise ValueError(
                f"百家号文章插图最多 {self.BAIJIAHAO_ARTICLE_MAX_IMAGES} 张, 当前 {len(files)} 张"
            )

        logger.info("[发布参数] 标题: %s", title)
        logger.info("[发布参数] 插图数量: %d", len(files))
        logger.info("[发布参数] 正文长度: %d 字符", self._count_chars(desc))
        logger.info("[发布参数] 标签: %s", tags)
        logger.info("[发布参数] 账号数量: %d", len(account_file))
        logger.info("[发布参数] 创作声明: %s", creation_declaration or "无")
        logger.info("[发布参数] 补充声明: %s", supplementary_declaration or "无")
        logger.info("[发布策略] 模式: %s", "演练(dry_run)" if dry_run else "正式发布")

        if cover_path and not Path(cover_path).is_file():
            logger.warning("[发布参数] 封面文件不存在, 回退用第一张插图: %s", cover_path)
            cover_path = ""

        asyncio.run(self._upload_all_articles(**kwargs))
        return True

    async def _upload_all_articles(self, **kwargs):
        """Publish the article for each account cookie."""
        title = kwargs.get("title", "")
        files = [str(f) for f in (kwargs.get("files", []) or [])]
        tags = kwargs.get("tags", []) or []
        account_file = kwargs.get("account_file", []) or []
        desc = kwargs.get("desc", "")
        cover_path = kwargs.get("cover_path", "") or (files[0] if files else "")
        creation_declaration = kwargs.get("creation_declaration", "") or kwargs.get("ai_content", "")
        supplementary_declaration = kwargs.get("supplementary_declaration", "")
        enable_timer = kwargs.get("enableTimer", False)
        schedule_time_str = kwargs.get("schedule_time_str", "")
        dry_run = kwargs.get("dry_run", True)

        for cookie_index, cookie_name in enumerate(account_file):
            cookie_path = str(Path(BASE_DIR / "cookiesFile" / cookie_name))
            nick = get_account_name_by_cookie_file(cookie_name)
            with bind_account_name(nick or "-"):
                logger.info(
                    "[发布进度] 发布到第 %d/%d 个账号 (%s)",
                    cookie_index + 1, len(account_file), nick or "未知",
                )
                await self._upload_one_article(
                    title=title,
                    file_paths=files,
                    tags=tags,
                    account_file=cookie_path,
                    desc=desc,
                    cover_path=cover_path,
                    creation_declaration=creation_declaration,
                    supplementary_declaration=supplementary_declaration,
                    enable_timer=enable_timer,
                    schedule_time_str=schedule_time_str,
                    dry_run=dry_run,
                )

    async def _upload_one_article(
        self, *, title, file_paths, tags, account_file, desc, cover_path="",
        creation_declaration="", supplementary_declaration="",
        enable_timer=False, schedule_time_str="", dry_run=True,
    ):
        """Create one rich article (图文文章) for a single Baijiahao account."""
        logger.info("[上传文章] 开始创建图文文章 (%d 张插图)", len(file_paths))
        browser = await self.create_browser(headless=False)
        try:
            context = await self.create_context(browser, storage_state=account_file)
            try:
                page = await context.new_page()
                await page.goto(
                    self.BAIJIAHAO_ARTICLE_EDIT_URL,
                    wait_until="domcontentloaded", timeout=60000,
                )

                # 1. 等编辑器加载(页面较慢, ~15s)
                logger.info("[上传文章] 等待文章编辑器加载...")
                title_editor = page.locator(
                    '[class*="FeEditorApp-"][contenteditable="true"]'
                ).first
                await title_editor.wait_for(state="visible", timeout=60000)
                await asyncio.sleep(2)
                await self._close_bjh_article_popups(page)

                # 2. 标题(placeholder「请输入标题(2 - 64字)」)
                #    标题是 #newsTextArea 内的 Lexical 编辑器(整页唯一
                #    contenteditable), 隐藏的 simulator textarea 用 :visible 过滤
                title_input = page.locator(
                    '#newsTextArea input:visible, #newsTextArea textarea:visible, '
                    '#newsTextArea [contenteditable="true"]:visible'
                ).first
                if await title_input.count():
                    await title_input.wait_for(state="visible", timeout=20000)
                    await clear_and_type(page, title, element=title_input)
                else:
                    title_box = page.locator(
                        '#newsTextArea .input-container, #newsTextArea'
                    ).first
                    await title_box.wait_for(state="visible", timeout=20000)
                    await title_box.click()
                    await page.keyboard.press("Control+KeyA")
                    await page.keyboard.press("Delete")
                    await page.keyboard.type(title, delay=15)
                logger.info("[填写标题] 标题已填写: %s", title)

                # 3. 正文 —— 在 UEditor iframe 内(请输入正文), 不在主文档
                ue_frame = await self._bjh_get_editor_frame(page)
                body = ue_frame.locator("body")
                await body.click()
                await clear_and_type(page, desc, element=body)
                body_text = (await body.inner_text()).strip()
                logger.info(
                    "[填写正文] 正文已填写 (%d 字符), 编辑器实际文本长度: %d, 前50字: %s",
                    len(desc), len(body_text), body_text[:50],
                )

                # 4. 逐张插入插图(光标保持在文末)
                if file_paths:
                    for idx, img in enumerate(file_paths, 1):
                        await self._bjh_insert_image(page, img)
                        logger.info("[插图] 已插入第 %d/%d 张", idx, len(file_paths))

                # 5. 标签作为话题行追加到文末(UEditor iframe 内)
                if tags:
                    tag_line = " ".join(f"#{t}" for t in tags[:10])
                    await body.click()
                    await page.keyboard.press("Control+End")
                    await page.keyboard.press("Enter")
                    await page.keyboard.type(tag_line, delay=20)
                    logger.info("[正文话题] 已追加话题行: %s", tag_line)

                # 6. 封面(单图 radio 默认选中; 点「选择封面」上传)
                if cover_path:
                    try:
                        await self._bjh_set_article_cover(page, cover_path)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[设置封面] 设置失败(不影响发布): %s", exc)

                # 7. 创作声明(非致命)
                if creation_declaration:
                    try:
                        await self._bjh_set_article_declaration(
                            page, creation_declaration, supplementary_declaration
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[设置声明] 设置创作声明失败(不影响上传): %s", exc)

                # 8. 定时发布(非致命)
                if enable_timer and schedule_time_str:
                    try:
                        publish_dates = parse_schedule_time(
                            schedule_time_str, 1, enable_timer, 1, None, 0
                        )
                        if publish_dates and publish_dates[0] != 0:
                            await self._bjh_set_article_schedule(page, publish_dates[0])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[定时发布] 设置失败(忽略继续): %s", exc)

                logger.info(
                    "[填写完成] 表单填写完成, 模式: %s",
                    "演练(dry_run)" if dry_run else "正式发布",
                )

                if not dry_run:
                    # 9. 发布(可能触发人机校验 passMod)
                    publish_btn = page.get_by_role("button", name="发布", exact=True).first
                    await publish_btn.wait_for(state="visible", timeout=15000)
                    await publish_btn.click()
                    logger.info("[发布] 已点击发布, 等待结果...")
                    try:
                        await page.wait_for_url("**/builder/rc/clue**", timeout=120000)
                        logger.info("[发布] 图文文章发布成功! URL: %s", page.url)
                    except Exception:
                        # 可能被人机校验阻塞, 给足等待
                        await self._bjh_wait_passmod(page)
                        await page.wait_for_url("**/builder/rc/clue**", timeout=120000)
                        logger.info("[发布] 人机校验后发布成功!")
                    await context.storage_state(path=account_file)
                    logger.info("[发布] Cookie状态已更新")
                else:
                    shot = Path(BASE_DIR) / "logs" / (
                        f"dryrun_baijiahao_{int(time.time())}.png"
                    )
                    try:
                        await page.screenshot(path=str(shot))
                        logger.info("[演练] 表单截图已保存: %s", shot)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[演练] 截图失败(忽略): %s", exc)
                    logger.info("[演练] dry_run=True, 已跳过发布点击")
            finally:
                await context.close()
        finally:
            await self.close_browser(browser, is_close_by_code=True)

    # -- 百家号图文文章内部小工具 -------------------------------------

    @staticmethod
    def _bjh_title_locator(page):
        """Locate the article title input inside the #newsTextArea container.

        编辑器改版频繁, 依次尝试: 原生 input/textarea → contenteditable →
        容器本身(点击后键盘输入)。"""
        return page.locator(
            '#newsTextArea input, #newsTextArea textarea, '
            '#newsTextArea [contenteditable="true"], '
            'input[placeholder*="请输入标题"], textarea[placeholder*="请输入标题"], '
            '[data-placeholder*="请输入标题"]'
        ).first

    @staticmethod
    async def _close_bjh_article_popups(page) -> None:
        """Close the AI-assistant welcome dialog / top tip on the article editor.

        cheetah-modal 引导窗会拦截一切鼠标事件, 且可能延迟挂载。用 JS 直点关闭
        (绕开 actionability 拦截), 多轮确认直到无可见弹窗。"""
        js_close = r"""
() => {
  const wraps = [...document.querySelectorAll('.cheetah-modal-wrap')]
    .filter(w => w.offsetParent !== null || getComputedStyle(w).display !== 'none');
  if (!wraps.length) return 0;
  // 1) aria-label 关闭按钮(百家号引导窗的 × 是 aria-label="关闭", class 里无 close 字样)
  let btn = document.querySelector(
    '.cheetah-modal-wrap button[aria-label="关闭"], '
    + '.cheetah-modal-wrap button[aria-label="Close"], '
    + '.cheetah-modal-wrap .cheetah-modal-close'
  );
  if (btn) { btn.click(); return 1; }
  // 2) 主行动按钮(立即体验/我知道了等, 点击后同样关窗)
  btn = [...document.querySelectorAll('.cheetah-modal-wrap button')].find(b => {
    const t = (b.textContent || '').trim();
    return t.includes('立即体验') || t.includes('我知道了') || t.includes('知道了') || t.includes('开始使用');
  });
  if (btn) { btn.click(); return 2; }
  return 3;
}
"""
        for attempt in range(6):
            try:
                result = await page.evaluate(js_close)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[弹窗] JS 关闭执行失败: %s", exc)
                break
            if result == 0:
                # 无可见弹窗; 再观察 1.2s 确认没有延迟挂载的新弹窗
                await page.wait_for_timeout(1200)
                try:
                    again = await page.evaluate(js_close)
                except Exception:  # noqa: BLE001
                    again = 0
                if again == 0:
                    if attempt:
                        logger.info("[弹窗] 全部引导弹窗已关闭")
                    return
                continue
            logger.info("[弹窗] JS 关闭引导弹窗(策略 %d, 第 %d 次)", result, attempt + 1)
            await page.wait_for_timeout(900)
        logger.warning("[弹窗] 多轮关闭后仍可能有弹窗存在, 继续流程")

    @staticmethod
    async def _bjh_get_editor_frame(page):
        """Locate the UEditor iframe that hosts the article body (请输入正文).

        正文编辑器跑在 document.write 出来的 iframe 里(UEditor 经典架构),
        主文档里唯一的 contenteditable 是标题。按 body 特征识别:
        contenteditable=true 或 class 含 view。"""
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                hit = await frame.evaluate(
                    "() => !!document.body && "
                    "(document.body.classList.contains('view') || "
                    "document.body.getAttribute('contenteditable') === 'true' || "
                    "!!document.querySelector('.edui-body-container'))"
                )
            except Exception:  # noqa: BLE001, PERF203
                continue
            if hit:
                return frame
        raise RuntimeError("未找到百家号正文编辑器 iframe(UEditor)")

    @staticmethod
    async def _bjh_insert_image(page, image_path: str) -> None:
        """Insert one image via the UEditor insertimage dialog (本地图片 tab).

        点击 .edui-for-insertimage(div)后弹出 cheetah-modal「插入图片」对话框:
        本地图片 tab 默认激活, 走 .cheetah-upload input[type=file] 上传后点「确认」。
        """
        # 注意: edui-for-insertimage 是 div 而非 button
        insert_btn = page.locator(".edui-for-insertimage").first
        await insert_btn.wait_for(state="visible", timeout=15000)
        await insert_btn.click()

        # 等待「插入图片」对话框(本地图片 tab 默认激活)
        dialog = page.locator('.cheetah-modal-wrap:has-text("本地图片")').first
        await dialog.wait_for(state="visible", timeout=15000)

        # 上传图片(cheetah-upload 的隐藏 file input 可直接 set_input_files)
        file_input = dialog.locator(
            'input[type="file"][accept*="image"]'
        ).first
        await file_input.set_input_files(image_path)

        # 等上传完成: 确认按钮从禁用变为可用(最长 30s)
        confirm_btn = dialog.get_by_role("button", name="确认").first
        for _ in range(30):
            try:
                if await confirm_btn.is_enabled():
                    break
            except Exception:  # noqa: BLE001, PERF203
                pass
            await page.wait_for_timeout(1000)
        await confirm_btn.click()
        # 等对话框关闭 + 图片插入正文
        await dialog.wait_for(state="hidden", timeout=30000)
        await page.wait_for_timeout(1000)

    @staticmethod
    async def _bjh_set_article_cover(page, cover_path: str) -> None:
        """Set the article cover via the「选择封面」dialog (正文/本地上传 tab).

        点击「选择封面」弹出 cheetah-modal 封面对话框: 上传(或选已有插图)后
        必须点「确定」关闭, 否则弹窗会一直挡住页面。"""
        cover_box = page.get_by_text("选择封面", exact=True).first
        await cover_box.wait_for(state="visible", timeout=15000)
        await cover_box.click()

        dialog = page.locator('.cheetah-modal-wrap:has-text("本地上传")').first
        await dialog.wait_for(state="visible", timeout=15000)

        if cover_path:
            try:
                file_input = dialog.locator(
                    'input[type="file"][accept*="image"]'
                ).first
                await file_input.set_input_files(cover_path)
                await page.wait_for_timeout(2000)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[设置封面] 本地上传失败(改选已有插图): %s", exc)

        # 等确定按钮可用(上传/选择完成后出现 确定(N))
        confirm_btn = dialog.get_by_role("button", name="确定").first
        for _ in range(20):
            try:
                if await confirm_btn.is_enabled():
                    break
            except Exception:  # noqa: BLE001, PERF203
                pass
            await page.wait_for_timeout(1000)
        await confirm_btn.click()
        await dialog.wait_for(state="hidden", timeout=30000)
        await page.wait_for_timeout(1000)
        logger.info("[设置封面] 封面已设置并确认")

    @staticmethod
    async def _bjh_set_article_declaration(
        page, creation_declaration: str, supplementary_declaration: str
    ) -> None:
        """Best-effort: tick the article declaration checkboxes (non-fatal).

        文章页的创作声明是 checkbox 组(采用AI生成内容 / 来源说明), 与视频流的
        下拉不同; 按传入值的关键词映射, 无匹配则跳过。"""
        text = creation_declaration or ""
        target = ""
        if "AI" in text or "ai" in text:
            target = "采用AI生成内容"
        elif "转载" in text or "来源" in text:
            target = "来源说明"
        if not target:
            logger.info(
                "[设置声明] 声明值「%s」在文章页无可对应勾选项, 跳过(非致命)", text
            )
            return
        checkbox = page.locator(
            f'label:has-text("{target}") input[type="checkbox"], '
            f'label:has-text("{target}")'
        ).first
        try:
            if await checkbox.count():
                await checkbox.click()
                await page.wait_for_timeout(500)
                logger.info("[设置声明] 已勾选: %s", target)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[设置声明] 勾选失败(不影响发布): %s", exc)

    @staticmethod
    async def _bjh_set_article_schedule(page, publish_date) -> None:
        """Best-effort: switch to scheduled publish and fill the datetime input."""
        timer_btn = page.get_by_role("button", name="定时发布").first
        await timer_btn.click()
        await page.wait_for_timeout(800)
        time_input = page.locator('input[placeholder="请选择时间"]').first
        await time_input.fill(publish_date.strftime("%Y-%m-%d %H:%M:%S"))
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)
        logger.info("[定时发布] 定时发布设置完成: %s", publish_date)

    @staticmethod
    async def _bjh_wait_passmod(page, timeout_s: int = 120) -> bool:
        """Wait for the BJH captcha dialog (passMod) to appear and be solved."""
        captcha = page.locator("div.passMod_dialog-container")
        try:
            await captcha.wait_for(state="visible", timeout=timeout_s * 1000)
            logger.info("[人机校验] 检测到人机校验, 等待人工完成...")
            await captcha.wait_for(state="hidden", timeout=300000)
            logger.info("[人机校验] 人机校验已通过")
            return True
        except Exception:
            return False
