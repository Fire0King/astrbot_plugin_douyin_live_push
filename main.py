import asyncio
import json
import os
from typing import List
from dataclasses import dataclass, asdict
from urllib.parse import urlencode

import aiohttp
from astrbot.api.all import *
from astrbot.api import AstrBotConfig, logger
from astrbot.core.star.filter.command import GreedyStr

# 导入抖音签名库
from utils.request import Request, sign

# ================== 数据模型 ==================
@dataclass
class Subscription:
    room_id: str           # 用户ID（同时也是房间ID）
    user_name: str         # 主播昵称
    group_id: str          # 群组/会话ID
    at_all: bool = False
    last_is_live: bool = False

@dataclass
class LiveStatus:
    is_live: bool
    title: str = ""
    viewer_count: int = 0
    cover: str = ""
    duration: str = ""      # 下播时可用


# ================== 数据管理器 ==================
class DataManager:
    def __init__(self, data_dir: str = "data/douyin_live"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.subscriptions_file = os.path.join(self.data_dir, "subscriptions.json")
        self._subscriptions: List[Subscription] = []
        self._load()

    def _load(self):
        if os.path.exists(self.subscriptions_file):
            with open(self.subscriptions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._subscriptions = [Subscription(**item) for item in data]

    def _save(self):
        with open(self.subscriptions_file, 'w', encoding='utf-8') as f:
            json.dump([asdict(s) for s in self._subscriptions], f, ensure_ascii=False, indent=2)

    def get_all(self) -> List[Subscription]:
        return self._subscriptions.copy()

    def get_by_group(self, group_id: str) -> List[Subscription]:
        return [s for s in self._subscriptions if s.group_id == group_id]

    def add(self, room_id: str, user_name: str, group_id: str, at_all: bool = False) -> bool:
        for s in self._subscriptions:
            if s.room_id == room_id and s.group_id == group_id:
                return False
        self._subscriptions.append(Subscription(room_id, user_name, group_id, at_all, False))
        self._save()
        return True

    def remove(self, room_id: str, group_id: str) -> bool:
        orig = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if not (s.room_id == room_id and s.group_id == group_id)]
        if len(self._subscriptions) != orig:
            self._save()
            return True
        return False

    def update_status(self, room_id: str, group_id: str, is_live: bool):
        for s in self._subscriptions:
            if s.room_id == room_id and s.group_id == group_id:
                s.last_is_live = is_live
                self._save()
                return

    def update_at_all(self, room_id: str, group_id: str, at_all: bool):
        for s in self._subscriptions:
            if s.room_id == room_id and s.group_id == group_id:
                s.at_all = at_all
                self._save()
                return


# ================== 抖音客户端（纯Python签名） ==================
class DouyinClient:
    def __init__(self, cookie: str):
        self.cookie = cookie
        self.request = Request(cookie=cookie) if cookie else None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }

    async def _get_signed_url(self, url: str) -> str:
        """使用签名库对URL附加签名参数"""
        if not self.request:
            return url
        # 签名库的 sign 函数返回类似于 "&X-Bogus=xxx&..." 的字符串
        signed = sign(url, self.headers["User-Agent"])
        # 如果返回的字符串以&开头，直接拼接
        if signed:
            return url + signed
        return url

    async def get_user_info(self, user_id: str) -> tuple:
        """
        获取用户昵称和真实的房间ID（其实就是user_id本身）
        返回 (昵称, room_id)
        """
        if not self.request:
            raise Exception("未配置抖音Cookie，无法获取用户信息")

        # 使用Request类自动签名
        # 注意：Request的base_url是https://www.douyin.com
        # 但getJSON方法只接受path，我们传完整URL会出错，所以用path
        # 为了保险，我们直接使用内部方法
        # 简便方法：调用其内部session发请求，但可能有签名问题。
        # 建议直接使用Request.getJSON
        try:
            # 先临时修改base_url以防万一
            old_base = self.request.base_url
            self.request.base_url = "https://www.douyin.com"
            result = await self.request.getJSON(
                "/web/api/v2/user/info/",
                params={"user_id": user_id}
            )
            self.request.base_url = old_base
        except Exception as e:
            raise Exception(f"请求用户信息失败: {e}")

        if result.get("status_code") != 0:
            raise Exception(f"接口返回错误: {result}")
        user_info = result.get("user_info", {})
        nickname = user_info.get("nickname", "未知")
        # 房间ID通常和user_id相同（数字ID），如果是短号，可能需要转换，这里简化
        return nickname, user_id

    async def get_live_status(self, room_id: str) -> LiveStatus:
        """
        获取直播间状态
        """
        if not self.request:
            # 没有cookie，尝试使用普通请求+签名（但可能缺少cookie导致失败）
            # 此处直接返回未开播
            logger.warning("未配置Cookie，无法获取直播状态")
            return LiveStatus(is_live=False)

        # 直播接口使用 live.douyin.com
        try:
            old_base = self.request.base_url
            self.request.base_url = "https://live.douyin.com"
            result = await self.request.getJSON(
                "/webcast/room/info/",
                params={"room_id": room_id}
            )
            self.request.base_url = old_base
        except Exception as e:
            logger.error(f"请求直播状态失败: {e}")
            return LiveStatus(is_live=False)

        if result.get("status_code") != 0:
            logger.warning(f"直播接口返回错误: {result}")
            return LiveStatus(is_live=False)

        room_data = result.get("data", {}).get("room", {})
        status = room_data.get("status")  # 2=直播中
        if status == 2:
            title = room_data.get("title", "")
            viewer_count = room_data.get("user_count", 0)
            cover = room_data.get("cover", {}).get("url_list", [""])[0]
            return LiveStatus(is_live=True, title=title, viewer_count=viewer_count, cover=cover)
        else:
            # 未开播或已下播
            return LiveStatus(is_live=False)


# ================== 插件主类 ==================
@register("astrbot_plugin_douyin_live", "你的名字", "抖音直播监控", "1.0.0", "")
class DouyinLivePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.cfg = config

        self.check_interval = self.cfg.get("check_interval", 60)
        self.default_at_all = self.cfg.get("default_at_all", False)
        self.cookie = self.cfg.get("douyin_cookie", "")

        self.data_manager = DataManager()
        self.douyin_client = DouyinClient(self.cookie)

        # 启动后台监控
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        while True:
            try:
                subs = self.data_manager.get_all()
                for sub in subs:
                    try:
                        status = await self.douyin_client.get_live_status(sub.room_id)
                        if status.is_live and not sub.last_is_live:
                            await self._notify_live_start(sub, status)
                        elif not status.is_live and sub.last_is_live:
                            await self._notify_live_end(sub, status)
                        self.data_manager.update_status(sub.room_id, sub.group_id, status.is_live)
                    except Exception as e:
                        logger.error(f"检查 {sub.room_id} 出错: {e}")
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
                await asyncio.sleep(self.check_interval)

    async def _notify_live_start(self, sub: Subscription, status: LiveStatus):
        at_all = sub.at_all or self.default_at_all
        msg = (
            f"🎉 {sub.user_name} 开播啦！\n\n"
            f"📺 标题：{status.title}\n"
            f"👀 观看人数：{status.viewer_count}\n"
            f"🔗 直播间：https://live.douyin.com/{sub.room_id}"
        )
        chain = MessageChain()
        if at_all:
            chain.append(AtAll())
        chain.append(Plain(msg))
        await self.context.send_message(sub.group_id, chain)

    async def _notify_live_end(self, sub: Subscription, status: LiveStatus):
        msg = (
            f"🛑 {sub.user_name} 已下播\n\n"
            f"📊 直播时长：{status.duration}\n"
            f"👀 最高观看：{status.viewer_count}"
        )
        chain = MessageChain([Plain(msg)])
        await self.context.send_message(sub.group_id, chain)

    # ================== 指令 ==================
    @command("dy_sub")
    async def sub(self, event: AstrMessageEvent, room_id: GreedyStr):
        """订阅抖音主播（使用用户ID）"""
        if not room_id:
            yield event.make_result().message("请提供抖音用户ID（数字）")
            return
        group_id = event.get_session_id()
        try:
            nickname, real_room_id = await self.douyin_client.get_user_info(room_id)
        except Exception as e:
            yield event.make_result().message(f"获取用户信息失败: {e}")
            return

        success = self.data_manager.add(real_room_id, nickname, group_id, self.default_at_all)
        if success:
            yield event.make_result().message(f"✅ 已订阅 {nickname} 的直播通知")
        else:
            yield event.make_result().message("⚠️ 该主播已被订阅")

    @command("dy_unsub")
    async def unsub(self, event: AstrMessageEvent, room_id: GreedyStr):
        if not room_id:
            yield event.make_result().message("请提供抖音用户ID")
            return
        group_id = event.get_session_id()
        if self.data_manager.remove(room_id, group_id):
            yield event.make_result().message("✅ 已取消订阅")
        else:
            yield event.make_result().message("⚠️ 未找到该订阅")

    @command("dy_list")
    async def list_sub(self, event: AstrMessageEvent):
        group_id = event.get_session_id()
        subs = self.data_manager.get_by_group(group_id)
        if not subs:
            yield event.make_result().message("当前群没有订阅任何主播")
            return
        lines = ["📋 本群订阅列表："]
        for s in subs:
            at_status = "✅" if s.at_all else "❌"
            lines.append(f"- {s.user_name} (ID: {s.room_id}) @全体: {at_status}")
        yield event.make_result().message("\n".join(lines))

    @command("dy_at_on")
    @permission_type(PermissionType.ADMIN)
    async def at_on(self, event: AstrMessageEvent, room_id: GreedyStr):
        if not room_id:
            yield event.make_result().message("请提供抖音用户ID")
            return
        group_id = event.get_session_id()
        subs = self.data_manager.get_by_group(group_id)
        for s in subs:
            if s.room_id == room_id:
                self.data_manager.update_at_all(room_id, group_id, True)
                yield event.make_result().message("✅ 已开启 @全体")
                return
        yield event.make_result().message("⚠️ 未找到该订阅")

    @command("dy_at_off")
    @permission_type(PermissionType.ADMIN)
    async def at_off(self, event: AstrMessageEvent, room_id: GreedyStr):
        if not room_id:
            yield event.make_result().message("请提供抖音用户ID")
            return
        group_id = event.get_session_id()
        subs = self.data_manager.get_by_group(group_id)
        for s in subs:
            if s.room_id == room_id:
                self.data_manager.update_at_all(room_id, group_id, False)
                yield event.make_result().message("✅ 已关闭 @全体")
                return
        yield event.make_result().message("⚠️ 未找到该订阅")

    # ================== 清理 ==================
    async def terminate(self):
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass