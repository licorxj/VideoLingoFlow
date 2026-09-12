"""节点额度不足提醒：向系统通知中心写入一条去重通知。

额度不足可能发生在两条链路上：
1. Celery worker 执行节点时，``subscription_guard.consume_for_node`` 抛出 402/403；
2. 前端提交任务前的本地预校验（经 ``POST /api/subscription/quota-notice`` 触发）。

两处共用本模块：统一文案、统一去重（同一天只提醒一次），避免额度耗尽后
每个失败节点都刷屏。
"""
from datetime import datetime, timedelta, timezone

from backend.utils.runtime_notifications import push_notification

# 通知上的 link 标记：前端据此提供「前往用户和订阅」入口
SUBSCRIPTION_LINK = "subscription"

_CN_TZ = timezone(timedelta(hours=8))


def _today_key() -> str:
    """按 UTC+8 计算「今天」，与每日额度刷新的口径保持一致。"""
    return datetime.now(_CN_TZ).strftime("%Y-%m-%d")


def _notice_text(user_type: str) -> tuple[str, str]:
    if user_type == "guest":
        return (
            "今日免费节点额度已用完",
            "游客你好，今日免费节点额度已用完，请注册获取更多免费额度或订阅解锁无限权益，"
            "也可以明天额度刷新后再来。",
        )
    return (
        "今日节点额度已用完",
        "今日免费节点额度已用完，请订阅以获得更多使用权益，也可以明天额度刷新后再来。",
    )


def notify_quota_exhausted(state: dict | None = None) -> bool:
    """额度不足时推送系统通知（同一天只提醒一次）。返回是否已写入通知中心。"""
    user_type = str((state or {}).get("user_type") or "guest")
    title, description = _notice_text(user_type)
    try:
        push_notification(
            "error",
            title,
            description,
            link=SUBSCRIPTION_LINK,
            dedup_key=f"quota_exhausted:{_today_key()}",
        )
        return True
    except Exception:
        return False


def notify_quota_file_locked() -> bool:
    """本地额度文件异常（403）时推送提示通知（同一天只提醒一次）。"""
    try:
        push_notification(
            "error",
            "本地额度校验异常",
            "本地额度文件异常，请重新登录或验码激活后重试。",
            link=SUBSCRIPTION_LINK,
            dedup_key=f"quota_locked:{_today_key()}",
        )
        return True
    except Exception:
        return False
