"""消息渲染器 —— 格式化抖音推送消息"""

from typing import Optional

from ..core.models import LiveInfo, UserInfo, VideoInfo
from ..core.utils import build_live_url, build_video_url, format_number

# ==================== 视频消息模板 ====================

VIDEO_TEMPLATE = """📹 新视频发布
👤 {nickname}
📝 {desc}
❤️ {digg_count} 👍 {comment_count} 💬 {collect_count} ⭐
🔗 {share_url}"""

LIVE_START_TEMPLATE = """🔴 {nickname} 开播啦！
📺 {title}
🔗 {live_url}"""

LIVE_END_TEMPLATE = """⚫ {nickname} 已下播
📺 本次直播: {title}"""

USER_INFO_TEMPLATE = """👤 {nickname}
📝 {signature}
👥 粉丝: {follower_count}  ·  关注: {following_count}
❤️ 获赞: {total_favorited}  ·  作品: {aweme_count}
🔗 {user_url}"""


def render_video_message(video: VideoInfo, nickname: str = "") -> str:
    """渲染视频推送消息"""
    return VIDEO_TEMPLATE.format(
        nickname=nickname or video.nickname or "未知用户",
        desc=video.title[:100] if video.title else "无标题",
        digg_count=format_number(video.digg_count),
        comment_count=format_number(video.comment_count),
        collect_count=0,
        share_url=video.share_url or build_video_url(video.aweme_id),
    )


def render_live_start_message(live: LiveInfo) -> str:
    """渲染开播推送消息"""
    return LIVE_START_TEMPLATE.format(
        nickname=live.nickname or live.user_id or live.room_id,
        title=live.title or "无标题",
        live_url=build_live_url(live.room_id),
    )


def render_live_end_message(nickname: str, title: str = "") -> str:
    """渲染下播推送消息"""
    return LIVE_END_TEMPLATE.format(
        nickname=nickname or "未知用户",
        title=title or "无标题",
    )


def render_user_info(user: UserInfo) -> str:
    """渲染用户信息"""
    return USER_INFO_TEMPLATE.format(
        nickname=user.nickname,
        signature=user.signature[:50] if user.signature else "这个人很懒，什么都没写",
        follower_count=format_number(user.follower_count),
        following_count=format_number(user.following_count),
        total_favorited=format_number(user.total_favorited),
        aweme_count=user.aweme_count,
        user_url=user.user_url or build_user_url(user.sec_uid),
    )


def build_user_url(sec_uid: str) -> str:
    """构建抖音用户主页 URL"""
    return f"https://www.douyin.com/user/{sec_uid}"