import asyncio
import os
import sys
import time
import json
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime

from astrbot.api.star import Star, Context
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

# 添加 DouYin_Spider 到路径
plugin_dir = Path(__file__).parent
spider_path = plugin_dir / "DouYin_Spider"
if str(spider_path) not in sys.path:
    sys.path.insert(0, str(spider_path))

# 导入 DouYin_Spider 的相关模块（根据实际结构调整）
try:
    from dy_apis.douyin_api import DouYinApi
    from dy_live.server import LiveServer  # 假设直播间监听模块
except ImportError as e:
    logger.error(f"导入 DouYin_Spider 模块失败: {e}")
    DouYinApi = None
    LiveServer = None

# 持久化存储监控状态的文件
STATE_FILE = plugin_dir / "monitor_state.json"


class DouyinPushPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.douyin_client = None
        self.live_server = None
        
        # 监控状态：{ "users": {user_id: last_video_id}, "rooms": {room_id: is_live} }
        self.state = self.load_state()
        
        # 初始化 DouYin_Spider 客户端
        cookie_path = self.config.get("cookie_path", str(plugin_dir / ".env"))
        if DouYinApi is not None:
            try:
                self.douyin_client = DouYinApi(cookie_path=cookie_path)
                logger.info("DouYinApi 初始化成功")
            except Exception as e:
                logger.error(f"DouYinApi 初始化失败: {e}")
        else:
            logger.error("DouYinApi 未导入，视频监控功能不可用")
        
        # 初始化直播间监听（如果需要）
        if LiveServer is not None and self.config.get("enable_live_monitor", True):
            try:
                self.live_server = LiveServer(cookie_path=cookie_path)
                logger.info("LiveServer 初始化成功")
            except Exception as e:
                logger.error(f"LiveServer 初始化失败: {e}")
        else:
            logger.warning("LiveServer 未导入或未启用，直播监控功能不可用")
        
        # 启动后台任务
        self.monitor_task = None
        self.live_task = None
        self._start_background_tasks()

    def load_state(self) -> dict:
        """加载持久化状态"""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"users": {}, "rooms": {}}

    def save_state(self):
        """保存状态"""
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _start_background_tasks(self):
        """启动后台监控任务"""
        loop = asyncio.get_event_loop()
        # 视频监控任务（轮询）
        if self.douyin_client is not None:
            self.monitor_task = loop.create_task(self._video_monitor_loop())
        # 直播间监控任务（WebSocket长连接）
        if self.live_server is not None:
            self.live_task = loop.create_task(self._live_monitor_loop())

    # ==================== 视频监控 ====================
    async def _video_monitor_loop(self):
        """定时轮询监控用户视频更新"""
        while True:
            try:
                for user_id in list(self.state["users"].keys()):
                    await self._check_user_videos(user_id)
                await asyncio.sleep(self.config.get("poll_interval", 60))  # 默认60秒
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"视频监控循环出错: {e}")
                await asyncio.sleep(10)

    async def _check_user_videos(self, user_id: str):
        """检查单个用户的视频更新"""
        try:
            # 调用 DouYin_Spider 获取用户视频列表（假设返回视频列表，每个视频有 id 和 title）
            # 注意：实际 API 方法名和返回结构需参考 DouYin_Spider 文档
            videos = await self.douyin_client.get_user_videos(user_id, count=5)  # 取最新5条
            if not videos:
                return
            
            last_video_id = self.state["users"].get(user_id)
            new_videos = []
            
            # 从旧到新遍历，检测新视频
            for video in reversed(videos):
                video_id = video.get('video_id') or video.get('id')
                if not video_id:
                    continue
                if video_id == last_video_id:
                    break
                new_videos.append(video)
            
            if new_videos:
                # 更新状态（保存最新的视频ID）
                self.state["users"][user_id] = videos[0].get('video_id') or videos[0].get('id')
                self.save_state()
                
                # 推送新视频消息
                for video in reversed(new_videos):  # 按发布时间正序
                    await self._push_video_message(user_id, video)
                    
        except Exception as e:
            logger.error(f"检查用户 {user_id} 视频失败: {e}")

    async def _push_video_message(self, user_id: str, video: dict):
        """推送单个视频消息到所有绑定的群聊/私聊"""
        # 视频信息提取（根据实际返回结构调整）
        title = video.get('title') or video.get('desc') or '无标题'
        video_url = video.get('share_url') or f"https://www.douyin.com/video/{video.get('id')}"
        cover = video.get('cover_url') or ''
        
        msg = (
            f"📹 新视频发布\n"
            f"用户ID: {user_id}\n"
            f"标题: {title}\n"
            f"链接: {video_url}"
        )
        # 发送给所有绑定的会话（这里简化，只发送给管理群）
        # 可以扩展为从配置读取目标会话列表
        target_groups = self.config.get("push_targets", [])
        for target in target_groups:
            await self.context.send_message(target, msg)
            # 或者直接使用 event 回复，但需要获取 event 对象，这里使用 context.send_message

    # ==================== 直播间监控 ====================
    async def _live_monitor_loop(self):
        """WebSocket 监听直播间上下播"""
        # 假设 LiveServer 提供了监听多个房间的方法
        # 我们需要从 state["rooms"] 获取需要监听的房间列表
        if not self.live_server:
            return
        
        # 这里需要根据 DouYin_Spider 的直播间监听 API 来集成
        # 示例：假设 LiveServer 有 async def monitor(room_id, callback) 方法
        # 我们为每个房间创建一个监听任务
        tasks = []
        for room_id in list(self.state["rooms"].keys()):
            task = asyncio.create_task(self._listen_single_room(room_id))
            tasks.append(task)
        
        # 等待所有任务（它们会一直运行）
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _listen_single_room(self, room_id: str):
        """监听单个直播间"""
        # 这里根据实际 API 调用
        # 假设 LiveServer 有方法 start_listen(room_id, on_event)
        # 我们使用回调处理上下播事件
        try:
            # 示例：使用 asyncio.Queue 或回调
            # 实际 DouYin_Spider 可能使用 WebSocket 并触发事件
            # 由于我们不清楚具体 API，这里给出伪代码
            # 实际上可能需要从 DouYin_Spider 的 dy_live/server.py 中继承或使用其类
            # 建议直接参考 DouYin_Spider 的示例，将监听逻辑封装在此
            # 这里简单模拟
            await self.live_server.start_monitor(room_id, self._on_live_event)
            # 保持运行
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info(f"直播间 {room_id} 监听已停止")
        except Exception as e:
            logger.error(f"直播间 {room_id} 监听出错: {e}")

    def _on_live_event(self, room_id: str, event_type: str, data: dict):
        """处理直播间事件（由 LiveServer 回调）"""
        # event_type: 'start' 开播, 'end' 下播
        if event_type == 'start':
            msg = f"🔴 直播间 {room_id} 开播了！\n标题: {data.get('title', '')}"
        elif event_type == 'end':
            msg = f"⚫ 直播间 {room_id} 已下播"
        else:
            return
        # 推送消息
        target_groups = self.config.get("push_targets", [])
        for target in target_groups:
            # 注意：这里需要异步发送，但回调可能是同步的，需要把事件放入队列或使用 asyncio.run_coroutine_threadsafe
            # 建议在回调中使用 asyncio.create_task 来异步发送
            asyncio.create_task(self._send_message(target, msg))

    async def _send_message(self, target: str, msg: str):
        """通用消息发送"""
        # 这里根据 AstrBot 的 API 发送消息，可以支持多种目标
        # 例如：target 可以是群号或用户ID
        await self.context.send_message(target, msg)

    # ==================== 用户命令 ====================
    @filter.command("dy_add_user")
    async def add_user(self, event: AstrMessageEvent):
        '''添加视频监控用户：/dy_add_user [用户ID]'''
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("请提供用户ID，例如：/dy_add_user 123456789")
            return
        user_id = args[1]
        if user_id in self.state["users"]:
            yield event.plain_result(f"用户 {user_id} 已在监控列表中")
            return
        # 初始化状态（可以获取一次最新视频ID）
        # 这里简化，先设为 None，下次轮询会获取
        self.state["users"][user_id] = None
        self.save_state()
        yield event.plain_result(f"✅ 已添加用户 {user_id} 的视频监控")

    @filter.command("dy_remove_user")
    async def remove_user(self, event: AstrMessageEvent):
        '''移除视频监控用户：/dy_remove_user [用户ID]'''
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("请提供用户ID，例如：/dy_remove_user 123456789")
            return
        user_id = args[1]
        if user_id not in self.state["users"]:
            yield event.plain_result(f"用户 {user_id} 不在监控列表中")
            return
        del self.state["users"][user_id]
        self.save_state()
        yield event.plain_result(f"✅ 已移除用户 {user_id} 的视频监控")

    @filter.command("dy_add_room")
    async def add_room(self, event: AstrMessageEvent):
        '''添加直播间监控：/dy_add_room [直播间号]'''
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("请提供直播间号，例如：/dy_add_room 123456789")
            return
        room_id = args[1]
        if room_id in self.state["rooms"]:
            yield event.plain_result(f"直播间 {room_id} 已在监控列表中")
            return
        self.state["rooms"][room_id] = False  # 初始状态未开播
        self.save_state()
        # 如果直播监控已启动，需要动态添加新房间的监听（此处简化，重启后生效）
        yield event.plain_result(f"✅ 已添加直播间 {room_id} 的监控（重启插件生效）")

    @filter.command("dy_remove_room")
    async def remove_room(self, event: AstrMessageEvent):
        '''移除直播间监控：/dy_remove_room [直播间号]'''
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("请提供直播间号，例如：/dy_remove_room 123456789")
            return
        room_id = args[1]
        if room_id not in self.state["rooms"]:
            yield event.plain_result(f"直播间 {room_id} 不在监控列表中")
            return
        del self.state["rooms"][room_id]
        self.save_state()
        yield event.plain_result(f"✅ 已移除直播间 {room_id} 的监控")

    @filter.command("dy_list")
    async def list_targets(self, event: AstrMessageEvent):
        '''列出当前监控的所有用户和直播间'''
        users = list(self.state["users"].keys())
        rooms = list(self.state["rooms"].keys())
        msg = f"📋 当前监控列表\n用户: {', '.join(users) if users else '无'}\n直播间: {', '.join(rooms) if rooms else '无'}"
        yield event.plain_result(msg)

    # ==================== 生命周期 ====================
    async def terminate(self):
        """插件卸载时停止后台任务"""
        logger.info("抖音推送插件正在卸载，停止后台任务...")
        if self.monitor_task:
            self.monitor_task.cancel()
        if self.live_task:
            self.live_task.cancel()
        if self.douyin_client:
            # 如果有需要关闭的连接
            pass
        if self.live_server:
            pass
