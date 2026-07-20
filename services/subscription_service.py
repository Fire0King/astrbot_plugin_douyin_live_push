from typing import List, Optional, Tuple
from astrbot.api import logger
from ..core.data_manager import DataManager
from ..core.models import SubscriptionRecord


class SubscriptionService:
    """订阅管理服务"""

    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager

    async def add_subscription(
            self,
            sub_user: str,
            uid: str,
            sub_type: str,
            sec_uid: str = "",
            room_id: str = "",
            nickname: str = "",
            at_all: bool = False,
            live_atall: bool = False,
            filter_keywords: Optional[List[str]] = None
    ) -> Tuple[bool, str]:
        """添加订阅"""
        # 检查是否已存在
        existing = self.data_manager.get_all_subscriptions().get(sub_user, [])
        for r in existing:
            if r.uid == uid and r.sub_type == sub_type:
                return False, f"⚠️ 已存在订阅: {uid} ({sub_type})"

        record = SubscriptionRecord(
            sub_user=sub_user,
            uid=uid,
            sub_type=sub_type,
            sec_uid=sec_uid,
            room_id=room_id,
            nickname=nickname,
            at_all=at_all,
            live_atall=live_atall,
            filter_keywords=filter_keywords or []
        )
        success = self.data_manager.add_subscription(sub_user, record)
        if success:
            type_name = "视频" if sub_type == 'video' else "直播"
            extra = ""
            if at_all:
                extra = " [@全体成员]"
            elif live_atall:
                extra = " [开播@全体]"
            return True, f"✅ 已订阅{type_name}监控: {nickname or uid}{extra}"
        else:
            return False, f"⚠️ 添加订阅失败: {uid}"

    async def remove_subscription(
            self,
            sub_user: str,
            uid: str,
            sub_type: str
    ) -> Tuple[bool, str]:
        """移除订阅"""
        success = self.data_manager.remove_subscription(sub_user, uid, sub_type)
        if success:
            type_name = "视频" if sub_type == 'video' else "直播"
            return True, f"✅ 已取消{type_name}订阅: {uid}"
        else:
            return False, f"⚠️ 未找到订阅: {uid}"

    async def list_subscriptions(self, sub_user: str) -> List[SubscriptionRecord]:
        """列出所有订阅"""
        return self.data_manager.get_subscriptions(sub_user)

    async def remove_all_for_user(self, sub_user: str) -> str:
        """移除某个会话的所有订阅"""
        records = self.data_manager.get_subscriptions(sub_user)
        if not records:
            return "该会话没有订阅"

        count = len(records)
        for r in list(records):
            self.data_manager.remove_subscription(sub_user, r.uid, r.sub_type)
        return f"✅ 已清空 {count} 个订阅"

    def get_subscription_count(self) -> int:
        """获取总的订阅数量"""
        total = 0
        for records in self.data_manager.get_all_subscriptions().values():
            total += len(records)
        return total