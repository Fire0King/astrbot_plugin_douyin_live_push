"""
消息渲染器 —— 支持 Playwright 图文渲染和纯文本两种模式。

图文模式（rai=true）：
  使用 HTML 模板 + Playwright 生成卡片图片，自动附带封面图。
纯文本模式（rai=false）：
  直接返回格式化的纯文本消息。
"""

import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Tuple

from astrbot.api import logger

from ..core.models import LiveInfo, UserInfo, VideoInfo
from ..core.utils import build_live_url, build_video_url, format_number

# 插件根目录
plugin_dir = Path(__file__).resolve().parent.parent

# ==================== 纯文本消息模板 ====================

VIDEO_TEXT_TEMPLATE = """📹 新视频发布
👤 {nickname}
📝 {desc}
❤️ {digg_count} 👍 {comment_count} 💬 {collect_count} ⭐
🔗 {url}"""

LIVE_START_TEXT = """🔴 {nickname} 开播啦！
📺 {title}
🔗 {url}"""

LIVE_END_TEXT = """⚫ {nickname} 已下播
📺 本次直播: {title}"""


class Renderer:
    """消息渲染器"""

    def __init__(self, rai: bool = False):
        self.rai = rai
        self._templates = {}
        self._playwright = None
        self._browser = None

    async def _get_browser(self):
        """延迟获取 Playwright 浏览器实例"""
        if self._browser:
            return self._browser
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            logger.info("Playwright 浏览器已启动")
            return self._browser
        except Exception as e:
            logger.error(f"Playwright 浏览器启动失败: {e}")
            return None

    async def close(self):
        """释放 Playwright 资源"""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None

    def _load_template(self, name: str) -> Optional[str]:
        """加载 HTML 模板"""
        if name in self._templates:
            return self._templates[name]
        tmpl_path = plugin_dir / "assets" / "templates" / name
        if not tmpl_path.exists():
            return None
        try:
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self._templates[name] = content
                return content
        except Exception as e:
            logger.error(f"加载模板 {name} 失败: {e}")
            return None

    async def _html_to_image(self, html: str) -> Optional[str]:
        """将 HTML 渲染为图片，返回图片路径"""
        browser = await self._get_browser()
        if not browser:
            return None
        try:
            page = await browser.new_page(
                viewport={"width": 460, "height": 10},
                device_scale_factor=2
            )
            await page.set_content(html, wait_until="networkidle")
            # 等待图片加载（最多 5 秒）
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            # 计算内容高度
            box = await page.evaluate("""
                () => {
                    const card = document.querySelector('.card');
                    if (card) return card.getBoundingClientRect();
                    return document.body.getBoundingClientRect();
                }
            """)
            height = int(box.get('height', 400) + 40)
            await page.set_viewport_size({"width": 460, "height": height})

            # 渲染为图片
            img_dir = os.path.join(tempfile.gettempdir(), "dy_push_images")
            os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, f"dy_card_{uuid.uuid4().hex[:8]}.png")

            await page.screenshot(
                path=img_path,
                full_page=True,
                type="png"
            )
            await page.close()
            return img_path
        except Exception as e:
            logger.error(f"HTML 渲染图片失败: {e}")
            return None

    async def render_video(self, work: dict, nickname: str = "") -> Tuple[str, Optional[str]]:
        """
        渲染视频消息。
        返回 (消息文本, 可选的图片路径)
        """
        author = work.get('author', {})
        nickname = nickname or author.get('nickname', '未知')
        aweme_id = str(work.get('aweme_id', ''))
        desc = work.get('desc', '无标题')
        statistics = work.get('statistics', {})
        cover = work.get('video', {}).get('cover', {}).get('url_list', [None])[0] or ""
        avatar = author.get('avatar_thumb', {}).get('url_list', [None])[0] or ""
        digg = format_number(statistics.get('digg_count', 0))
        comment = format_number(statistics.get('comment_count', 0))
        collect = format_number(statistics.get('collect_count', 0))
        share = format_number(statistics.get('share_count', 0))
        url = build_video_url(aweme_id)

        text = VIDEO_TEXT_TEMPLATE.format(
            nickname=nickname, desc=desc[:100],
            digg_count=digg, comment_count=comment,
            collect_count=collect, url=url,
        )

        # 图文模式：尝试渲染 HTML 卡片
        img_path = None
        if self.rai:
            tmpl = self._load_template("video_card.html")
            if tmpl:
                html = tmpl.format(
                    nickname=nickname, avatar=avatar, cover=cover,
                    title=desc[:100], digg_count=digg,
                    comment_count=comment, collect_count=collect,
                    share_count=share, url=url,
                )
                img_path = await self._html_to_image(html)

        return text, img_path

    async def render_live(self, record, is_live: bool, title: str = "",
                          work: Optional[dict] = None) -> Tuple[str, Optional[str]]:
        """
        渲染直播消息。
        返回 (消息文本, 可选的图片路径)
        """
        nickname = record.nickname or record.uid
        live_id = record.room_id or record.uid
        url = build_live_url(live_id)
        title = title or "无标题"

        text = (LIVE_START_TEXT if is_live else LIVE_END_TEXT).format(
            nickname=nickname, title=title, url=url,
        )

        img_path = None
        if self.rai:
            tmpl = self._load_template("live_card.html")
            if tmpl:
                avatar = ""
                if work:
                    avatar = work.get('author', {}).get('avatar_thumb', {}).get('url_list', [None])[0] or ""
                html = tmpl.format(
                    badge_class="live-badge" if is_live else "offline-badge",
                    badge_text="🔴 直播中" if is_live else "⭕ 已下播",
                    nickname=nickname, avatar=avatar, title=title, url=url,
                )
                img_path = await self._html_to_image(html)

        return text, img_path

    def render_user_info(self, user: UserInfo) -> str:
        """渲染用户信息（仅纯文本）"""
        user_url = user.user_url or build_user_url(user.sec_uid)
        return (
            f"👤 {user.nickname}\n"
            f"📝 {user.signature[:50] if user.signature else '这个人很懒，什么都没写'}\n"
            f"👥 粉丝: {format_number(user.follower_count)}  ·  关注: {format_number(user.following_count)}\n"
            f"❤️ 获赞: {format_number(user.total_favorited)}  ·  作品: {user.aweme_count}\n"
            f"🔗 {user_url}"
        )


def build_user_url(sec_uid: str) -> str:
    """构建抖音用户主页 URL"""
    return f"https://www.douyin.com/user/{sec_uid}"