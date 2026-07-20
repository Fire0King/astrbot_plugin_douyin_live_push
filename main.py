import asyncio
import sys
from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import command, permission_type, PermissionType
from astrbot.core.star.filter.command import GreedyStr

from .core.data_manager import DataManager
from .core.models import SubscriptionRecord
from .core.utils import (
    build_user_url,
    parse_live_room_id,
    parse_sec_uid,
    format_number,
)
from .services.listener import DouyinAuthWrapper, DouyinListener
from .services.subscription_service import SubscriptionService

# 插件根目录
plugin_dir = Path(__file__).parent

# 添加 DouYin_Spider 子模块到 sys.path
spider_path = plugin_dir / "DouYin_Spider"
if str(spider_path) not in sys.path:
    sys.path.insert(0, str(spider_path))

try:
    from dy_apis.douyin_api import DouyinAPI
    _HAS_SPIDER = True
except ImportError as e:
    logger.error(f"导入 DouYin_Spider 失败: {e}")
    DouyinAPI = None
    _HAS_SPIDER = False


@register(
    "astrbot_plugin_douyin_live_push",
    "Fire_King",
    "抖音视频更新与直播间上下播推送插件",
    "1.3.0",
    "https://github.com/Fire0King/astrbot_plugin_douyin_live_push"
)
class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = config
        self.context = context

        # 1. 初始化数据管理器（使用标准数据目录）
        self.data_manager = DataManager()

        # 2. 初始化抖音认证
        self.dy_auth = DouyinAuthWrapper()
        self.live_auth = DouyinAuthWrapper()
        self._init_auth()

        # 3. 初始化订阅服务
        self.subscription_service = SubscriptionService(self.data_manager)

        # 4. 初始化监听服务
        self.listener = DouyinListener(
            context=self.context,
            data_manager=self.data_manager,
            dy_auth=self.dy_auth,
            live_auth=self.live_auth,
            cfg=self.cfg
        )

        # 5. 启动后台任务
        self._listener_task: Optional[asyncio.Task] = None
        self._start_listener()

    def _init_auth(self):
        """从配置初始化抖音认证"""
        cookie_main = self.cfg.get("douyin_cookie", "").strip()
        cookie_live = self.cfg.get("douyin_live_cookie", "").strip()
        if not cookie_live:
            cookie_live = cookie_main

        if cookie_main:
            self.dy_auth.setup(cookie_main)
        if cookie_live:
            self.live_auth.setup(cookie_live)
        else:
            self.live_auth = self.dy_auth

        if not self.dy_auth.auth:
            logger.warning("⚠️ 抖音 Cookie 未配置，请先在插件设置中配置 douyin_cookie")

    def _start_listener(self):
        """启动后台监听"""
        if self._listener_task and not self._listener_task.done():
            return
        self._listener_task = asyncio.create_task(self.listener.start())
        logger.info("后台监听任务已启动")

    def _restart_listener(self):
        """重启监听服务"""
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
        self._listener_task = asyncio.create_task(self.listener.start())
        logger.info("监听服务已重启")

    # ==================== 用户命令 ====================

    @command("dy_sub")
    async def dy_sub(self, event: AstrMessageEvent, raw_args: GreedyStr):
        """
        订阅抖音用户的视频更新和直播状态。

        用法:
          /dy_sub <URL/sec_uid> [at_all|live_atall]     — 订阅视频+直播
          /dy_sub video <URL/sec_uid> [at_all]           — 仅订阅视频
          /dy_sub live <直播间ID> [live_atall]            — 仅订阅直播

        选项说明:
          at_all      — 开播/发视频时 @全体成员（仅管理员）
          live_atall  — 仅开播时 @全体成员（仅管理员）

        示例:
          /dy_sub https://www.douyin.com/user/MS4wLjABAAAA... at_all
          /dy_sub video MS4wLjABAAAA... live_atall
          /dy_sub live 852953608964 live_atall
        """
        sub_user = event.unified_msg_origin
        args = raw_args.strip().split() if raw_args.strip() else []

        if not args:
            yield event.plain_result(
                "❌ 请提供订阅参数。\n"
                "用法:\n"
                "  /dy_sub <URL/sec_uid> [at_all|live_atall]\n"
                "  /dy_sub video <URL/sec_uid> [at_all]\n"
                "  /dy_sub live <直播间ID> [live_atall]\n"
                "选项: at_all=全部@全体, live_atall=仅开播@全体"
            )
            return

        # 解析 @全体 选项
        at_all = False
        live_atall = False
        options = {'at_all', 'live_atall'}
        filtered_args = [a for a in args if a not in options]
        for a in args:
            if a == 'at_all':
                at_all = True
            elif a == 'live_atall':
                live_atall = True

        # 权限检查：只有管理员可以设置 @全体
        if (at_all or live_atall) and not event.is_admin():
            yield event.plain_result("❌ 权限不足：只有管理员可以设置 @全体成员 相关选项。")
            return

        # 解析 sub_type 和 target
        sub_type = 'both'
        target = filtered_args[0]

        if target in ('video', 'live', 'both') and len(filtered_args) > 1:
            sub_type = target
            target = filtered_args[1]

        # 尝试解析 sec_uid 或 直播间ID
        sec_uid = parse_sec_uid(target)
        live_id = parse_live_room_id(target) if sub_type in ('live', 'both') else None

        results = []

        if sub_type in ('video', 'both') and sec_uid:
            nickname = await self._fetch_user_nickname(sec_uid)
            uid = sec_uid
            success, msg = await self.subscription_service.add_subscription(
                sub_user, uid, 'video',
                sec_uid=sec_uid,
                nickname=nickname or sec_uid,
                at_all=at_all,
                live_atall=live_atall,
            )
            results.append(msg)

        if sub_type in ('live', 'both'):
            if sub_type == 'live' and live_id:
                uid = f"live_{live_id}"
                success, msg = await self.subscription_service.add_subscription(
                    sub_user, uid, 'live',
                    room_id=live_id,
                    nickname=f"直播间 {live_id}",
                    at_all=at_all,
                    live_atall=live_atall,
                )
                results.append(msg)
            elif sub_type == 'live' and not live_id:
                results.append("❌ 未识别到有效的直播间ID")

        if not results:
            yield event.plain_result("❌ 无法识别输入，请提供正确的抖音用户URL、sec_uid 或直播间ID")
            return

        self._restart_listener()
        yield event.plain_result("\n".join(results))

    async def _fetch_user_nickname(self, sec_uid: str) -> Optional[str]:
        """从抖音 API 获取用户昵称"""
        auth = self.dy_auth.auth
        if not auth or not DouyinAPI:
            return None
        try:
            user_url = build_user_url(sec_uid)
            info = await asyncio.to_thread(
                DouyinAPI.get_user_info, auth, user_url
            )
            if info and 'user' in info:
                return info['user'].get('nickname', '')
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
        return None

    @command("dy_unsub")
    async def dy_unsub(self, event: AstrMessageEvent, raw_args: GreedyStr):
        """
        取消订阅。

        用法: /dy_unsub <sec_uid/直播间ID> [video/live]
        """
        sub_user = event.unified_msg_origin
        args = raw_args.strip().split(None, 1) if raw_args.strip() else []

        if not args:
            yield event.plain_result("❌ 请提供要取消订阅的ID。\n用法: /dy_unsub <sec_uid/直播间ID> [video/live]")
            return

        uid = args[0]
        sub_type = args[1] if len(args) > 1 else None

        if sub_type:
            success, msg = await self.subscription_service.remove_subscription(
                sub_user, uid, sub_type
            )
            if success:
                self._restart_listener()
            yield event.plain_result(msg)
        else:
            # 尝试移除 video 和 live
            results = []
            for st in ['video', 'live']:
                success, msg = await self.subscription_service.remove_subscription(
                    sub_user, uid, st
                )
                if success:
                    results.append(msg)
            if results:
                self._restart_listener()
                yield event.plain_result("\n".join(results))
            else:
                yield event.plain_result(f"⚠️ 未找到 {uid} 的订阅")

    @command("dy_list")
    async def dy_list(self, event: AstrMessageEvent):
        """列出当前会话的所有订阅"""
        sub_user = event.unified_msg_origin
        records = await self.subscription_service.list_subscriptions(sub_user)

        if not records:
            yield event.plain_result("📋 当前没有订阅")
            return

        msg_parts = ["📋 当前订阅列表\n"]
        for i, r in enumerate(records, 1):
            type_tag = "📹视频" if r.sub_type == 'video' else "🔴直播"
            status = " 🟢直播中" if r.is_live else ""
            at_tag = ""
            if r.at_all:
                at_tag = " [@全体]"
            elif r.live_atall:
                at_tag = " [开播@全体]"
            nickname = r.nickname or r.uid
            msg_parts.append(f"{i}. {type_tag} {nickname}{at_tag}{status}")

        yield event.plain_result("\n".join(msg_parts))

    @command("dy_clear")
    @permission_type(PermissionType.ADMIN)
    async def dy_clear(self, event: AstrMessageEvent):
        """清空当前会话的所有订阅（管理员）"""
        sub_user = event.unified_msg_origin
        msg = await self.subscription_service.remove_all_for_user(sub_user)
        self._restart_listener()
        yield event.plain_result(msg)

    @command("dy_info")
    async def dy_info(self, event: AstrMessageEvent, raw_args: GreedyStr):
        """
        获取抖音用户信息。

        用法: /dy_info <抖音用户URL或sec_uid>
        """
        target = raw_args.strip()
        if not target:
            yield event.plain_result("❌ 请提供抖音用户URL或sec_uid")
            return

        sec_uid = parse_sec_uid(target)
        if not sec_uid:
            yield event.plain_result("❌ 无法识别，请提供有效的抖音用户URL或sec_uid")
            return

        auth = self.dy_auth.auth
        if not auth or not DouyinAPI:
            yield event.plain_result("❌ 抖音 Cookie 未配置，无法查询用户信息")
            return

        try:
            user_url = build_user_url(sec_uid)
            info = await asyncio.to_thread(
                DouyinAPI.get_user_info, auth, user_url
            )

            if not info or 'user' not in info:
                yield event.plain_result("❌ 获取用户信息失败，请检查 Cookie 是否有效")
                return

            user = info['user']
            nickname = user.get('nickname', '未知')
            signature = user.get('signature', '这个人很懒，什么都没写')
            follower = format_number(user.get('follower_count', 0))
            following = format_number(user.get('following_count', 0))
            total_favorited = format_number(user.get('total_favorited', 0))
            aweme_count = user.get('aweme_count', 0)

            msg = (
                f"👤 {nickname}\n"
                f"📝 {signature[:100]}\n"
                f"👥 粉丝: {follower}  ·  关注: {following}\n"
                f"❤️ 获赞: {total_favorited}  ·  作品: {aweme_count}\n"
                f"🔗 {user_url}"
            )
            yield event.plain_result(msg)

        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            yield event.plain_result(f"❌ 获取用户信息失败: {str(e)}")

    # ==================== 管理员命令 ====================

    @command("dy_global_list")
    @permission_type(PermissionType.ADMIN)
    async def dy_global_list(self, event: AstrMessageEvent):
        """查看所有会话的订阅（管理员）"""
        all_subs = self.data_manager.get_all_subscriptions()
        if not all_subs or not any(all_subs.values()):
            yield event.plain_result("📋 暂无任何订阅")
            return

        msg_parts = ["📋 全局订阅列表"]
        total = 0
        for sub_user, records in all_subs.items():
            if records:
                msg_parts.append(f"\n📌 {sub_user}:")
                for r in records:
                    total += 1
                    tag = "📹" if r.sub_type == 'video' else "🔴"
                    name = r.nickname or r.uid
                    status = " 🟢" if r.is_live else ""
                    msg_parts.append(f"  {tag} {name} ({r.sub_type}){status}")
        msg_parts.append(f"\n总计: {total} 个订阅")
        yield event.plain_result("".join(msg_parts))

    @command("dy_global_unsub")
    @permission_type(PermissionType.ADMIN)
    async def dy_global_unsub(self, event: AstrMessageEvent, raw_args: GreedyStr):
        """
        删除指定会话指定用户的订阅（管理员）。

        用法: /dy_global_unsub <会话UMO> <UID>
        """
        args = raw_args.strip().split() if raw_args.strip() else []
        if len(args) < 2:
            yield event.plain_result("❌ 用法: /dy_global_unsub <会话UMO> <UID>")
            return
        target_user = args[0]
        target_uid = args[1]
        for st in ['video', 'live']:
            self.data_manager.remove_subscription(target_user, target_uid, st)
        self._restart_listener()
        yield event.plain_result(f"✅ 已移除 {target_user} 的 {target_uid} 订阅")

    @command("dy_status")
    @permission_type(PermissionType.ADMIN)
    async def dy_status(self, event: AstrMessageEvent):
        """查看插件运行状态（管理员）"""
        cookie_ok = "✅ 已配置" if self.dy_auth.auth else "❌ 未配置"
        live_ok = "✅ 已配置" if self.live_auth.auth else "❌ 未配置"
        total_subs = self.subscription_service.get_subscription_count()
        running = "🟢 运行中" if (self._listener_task and not self._listener_task.done()) else "🔴 已停止"

        msg = (
            f"📊 插件运行状态\n"
            f"{'=' * 20}\n"
            f"运行状态: {running}\n"
            f"Cookie: {cookie_ok}\n"
            f"直播Cookie: {live_ok}\n"
            f"轮询间隔: {self.cfg.get('poll_interval', 60)}秒\n"
            f"直播监控: {'🟢 开启' if self.cfg.get('enable_live_monitor', True) else '🔴 关闭'}\n"
            f"订阅总数: {total_subs}\n"
            f"DouYin_Spider: {'✅ 已加载' if _HAS_SPIDER else '❌ 未加载'}"
        )
        yield event.plain_result(msg)

    # ==================== 生命周期 ====================

    async def terminate(self):
        """插件卸载时清理"""
        logger.info("抖音推送插件正在卸载...")
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
        if hasattr(self, 'listener'):
            await self.listener.stop()
        logger.info("抖音推送插件已卸载")