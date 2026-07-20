import asyncio
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import AtAll, Image, Plain
from astrbot.core.star import Context

from ..core.data_manager import DataManager
from ..core.models import SubscriptionRecord
from ..core.utils import build_user_url, build_video_url, build_live_url
from .renderer import Renderer


class DouyinAuthWrapper:
    """
    抖音认证包装器。
    封装 DouyinAuth 对象的创建和管理。
    """

    def __init__(self):
        self.auth = None
        self.cookie_str = ""

    def setup(self, cookie_str: str):
        """使用 Cookie 初始化认证"""
        if not cookie_str:
            self.auth = None
            return
        try:
            from builder.auth import DouyinAuth
            self.auth = DouyinAuth()
            self.auth.perepare_auth(cookie_str, "", "")
            self.cookie_str = cookie_str
            logger.info("抖音认证初始化成功")
        except Exception as e:
            logger.error(f"抖音认证初始化失败: {e}")
            self.auth = None


class DouyinListener:
    """抖音后台监听服务"""

    def __init__(
            self,
            context: Context,
            data_manager: DataManager,
            dy_auth: DouyinAuthWrapper,
            live_auth: Optional[DouyinAuthWrapper],
            renderer: Renderer,
            cfg: dict
    ):
        self.context = context
        self.data_manager = data_manager
        self.dy_auth = dy_auth
        self.live_auth = live_auth or dy_auth
        self.renderer = renderer
        self.cfg = cfg

        self.interval_secs = max(10, int(cfg.get("poll_interval", 60)))
        self.enable_live = cfg.get("enable_live_monitor", True)

        self._running = False
        self._video_task: Optional[asyncio.Task] = None
        self._live_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动后台监听"""
        if self._running:
            return
        self._running = True
        logger.info("抖音监听服务已启动")

        # 启动视频监控
        self._video_task = asyncio.create_task(self._video_loop())
        # 启动直播监控
        if self.enable_live:
            self._live_task = asyncio.create_task(self._live_loop())

        # 等待任务（保持运行）
        await asyncio.gather(
            self._video_task,
            self._live_task,
            return_exceptions=True
        )

    async def stop(self):
        """停止后台监听"""
        self._running = False
        if self._video_task and not self._video_task.done():
            self._video_task.cancel()
        if self._live_task and not self._live_task.done():
            self._live_task.cancel()
        logger.info("抖音监听服务已停止")

    # ==================== 视频监控 ====================

    async def _video_loop(self):
        """视频监控循环"""
        while self._running:
            try:
                all_subs = self.data_manager.get_all_subscriptions()
                for sub_user, records in all_subs.items():
                    for record in records:
                        if record.sub_type == 'video':
                            await self._check_user_videos(sub_user, record)
                await asyncio.sleep(self.interval_secs)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"视频监控循环出错: {e}")
                await asyncio.sleep(10)

    async def _check_user_videos(self, sub_user: str, record: SubscriptionRecord):
        """检查单个用户的视频更新"""
        auth = self.dy_auth.auth
        if not auth:
            logger.warning("抖音认证未配置，跳过视频检查")
            return

        sec_uid = record.sec_uid or record.uid
        if not sec_uid:
            return

        user_url = build_user_url(sec_uid)

        try:
            # 在线程中运行同步 API 调用
            from dy_apis.douyin_api import DouyinAPI
            works = await asyncio.to_thread(
                DouyinAPI.get_user_all_work_info, auth, user_url
            )

            if not works or len(works) == 0:
                return

            # 获取最新的作品
            latest = works[0]
            latest_id = str(latest.get('aweme_id', ''))

            if not latest_id:
                return

            # 如果没有记录过的 ID，只记录不推送（首次订阅）
            if not record.last_video_id:
                record.last_video_id = latest_id
                self.data_manager.update_subscription(
                    sub_user, record.uid, 'video',
                    last_video_id=latest_id,
                    nickname=latest.get('author', {}).get('nickname', record.nickname)
                )
                logger.info(f"首次记录用户 {sec_uid} 的最新视频: {latest_id}")
                return

            # 如果最新视频 ID 相同，无新视频
            if latest_id == record.last_video_id:
                return

            # 收集新视频（从 old 往后到 new）
            new_videos = []
            for work in works:
                wid = str(work.get('aweme_id', ''))
                if not wid:
                    continue
                if wid == record.last_video_id:
                    break
                new_videos.append(work)

            if new_videos:
                # 更新最后视频ID和昵称
                nickname = latest.get('author', {}).get('nickname', record.nickname)
                self.data_manager.update_subscription(
                    sub_user, record.uid, 'video',
                    last_video_id=latest_id,
                    nickname=nickname
                )
                # 从旧到新推送
                for work in reversed(new_videos):
                    await self._push_video_message(sub_user, record, work)

        except Exception as e:
            logger.error(f"检查用户 {sec_uid} 视频失败: {e}")

    async def _push_video_message(self, sub_user: str, record: SubscriptionRecord, work: dict):
        """推送视频消息"""
        try:
            nickname = work.get('author', {}).get('nickname', record.nickname or record.uid)
            aweme_id = str(work.get('aweme_id', ''))

            # 使用渲染器生成消息（返回文本 + 可选图片）
            text, img_path = await self.renderer.render_video(work, nickname)

            # 构建 MessageChain
            chain = MessageChain()
            if record.at_all:
                chain.at_all()
            if img_path:
                chain.file_image(img_path)
                url = build_video_url(aweme_id)
                chain.message(f"\n{url}")
            else:
                chain.message(text)

            await self.context.send_message(sub_user, chain)
            logger.info(f"已向 {sub_user} 推送视频: {aweme_id}")
        except Exception as e:
            logger.error(f"推送视频消息失败: {e}")

    # ==================== 直播监控 ====================

    async def _live_loop(self):
        """直播监控循环"""
        while self._running:
            try:
                all_subs = self.data_manager.get_all_subscriptions()
                for sub_user, records in all_subs.items():
                    for record in records:
                        if record.sub_type == 'live':
                            await self._check_live_status(sub_user, record)
                await asyncio.sleep(self.interval_secs)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"直播监控循环出错: {e}")
                await asyncio.sleep(10)

    async def _check_live_status(self, sub_user: str, record: SubscriptionRecord):
        """检查直播间状态"""
        auth = self.live_auth.auth
        if not auth:
            logger.warning("抖音认证未配置，跳过直播检查")
            return

        live_id = record.room_id or record.uid
        if not live_id:
            return

        try:
            from dy_apis.douyin_api import DouyinAPI
            result = await asyncio.to_thread(
                DouyinAPI.get_live_info, auth, live_id
            )

            if not result or not isinstance(result, dict):
                return

            room_status = result.get('room_status')
            room_title = result.get('room_title', '')
            # 2 = 直播中, 4 = 未开播
            is_now_live = (room_status == '2' or room_status == 2)

            if is_now_live and not record.is_live:
                # 开播了！
                self.data_manager.update_subscription(
                    sub_user, record.uid, 'live',
                    is_live=True,
                    last_live_title=room_title,
                    nickname=result.get('sec_uid', record.nickname)
                )
                await self._push_live_message(sub_user, record, True, room_title)

            elif not is_now_live and record.is_live:
                # 下播了
                self.data_manager.update_subscription(
                    sub_user, record.uid, 'live',
                    is_live=False
                )
                await self._push_live_message(sub_user, record, False, record.last_live_title)

        except Exception as e:
            logger.error(f"检查直播状态失败 (live_id={live_id}): {e}")

    async def _push_live_message(self, sub_user: str, record: SubscriptionRecord, is_live: bool, title: str = ""):
        """推送直播消息"""
        live_id = record.room_id or record.uid

        # 使用渲染器生成消息（返回文本 + 可选图片）
        text, img_path = await self.renderer.render_live(record, is_live, title)

        try:
            # 构建 MessageChain
            chain = MessageChain()
            if is_live and (record.live_atall or record.at_all):
                chain.at_all()
            if img_path:
                chain.file_image(img_path)
                url = build_live_url(live_id)
                chain.message(f"\n{url}")
            else:
                chain.message(text)

            await self.context.send_message(sub_user, chain)
            logger.info(f"已向 {sub_user} 推送直播状态: {'开播' if is_live else '下播'}")
        except Exception as e:
            logger.error(f"推送直播消息失败: {e}")