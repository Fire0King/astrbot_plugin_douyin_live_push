"""
消息渲染器 —— 支持图文渲染和纯文本两种模式。

图文模式（rai=true）：
  使用 HTML 模板生成卡片图片，需要 AstrBot 的 HTML 渲染支持。
纯文本模式（rai=false）：
  直接返回格式化的纯文本消息。
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

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

    def render_video(self, work: dict, nickname: str = "") -> str:
        """渲染视频消息，返回纯文本（rai 模式下返回 HTML）"""
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

        if self.rai:
            tmpl = self._load_template("video_card.html")
            if tmpl:
                return tmpl.format(
                    nickname=nickname,
                    avatar=avatar,
                    cover=cover,
                    title=desc[:100],
                    digg_count=digg,
                    comment_count=comment,
                    collect_count=collect,
                    share_count=share,
                    url=url,
                )
        return VIDEO_TEXT_TEMPLATE.format(
            nickname=nickname,
            desc=desc[:100],
            digg_count=digg,
            comment_count=comment,
            collect_count=collect,
            url=url,
        )

    def render_live(self, record, is_live: bool, title: str = "",
                    work: Optional[dict] = None) -> str:
        """渲染直播消息"""
        nickname = record.nickname or record.uid
        live_id = record.room_id or record.uid
        url = build_live_url(live_id)
        title = title or "无标题"

        if self.rai:
            tmpl = self._load_template("live_card.html")
            if tmpl:
                avatar = ""
                if work:
                    avatar = work.get('author', {}).get('avatar_thumb', {}).get('url_list', [None])[0] or ""
                return tmpl.format(
                    badge_class="live-badge" if is_live else "offline-badge",
                    badge_text="🔴 直播中" if is_live else "⭕ 已下播",
                    nickname=nickname,
                    avatar=avatar,
                    title=title,
                    url=url,
                )

        template = LIVE_START_TEXT if is_live else LIVE_END_TEXT
        return template.format(nickname=nickname, title=title, url=url)

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