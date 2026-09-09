"""AI 漫剧四层状态机：项目 / 章节 / 分镜 / 资产 的统一状态与流转工具。

状态语义（各层通用）：
- draft      草稿/未开始
- generating 生成中（节点已启动、尚未完成）
- ready      已完成、可下游使用
- failed     执行失败（可重试）
"""

# 各层统一状态
STATUS_DRAFT = "draft"
STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# 可写入“已完成”的就绪态集合（用于断点续跑判断：已就绪则跳过）
READY_STATES = frozenset({STATUS_READY})

# 章节/分镜 节点推进时的合法状态流转（用于校验，防止状态倒挂）
_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_GENERATING, STATUS_FAILED, STATUS_READY},
    STATUS_GENERATING: {STATUS_READY, STATUS_FAILED, STATUS_GENERATING},
    STATUS_READY: {STATUS_GENERATING, STATUS_FAILED, STATUS_READY},
    STATUS_FAILED: {STATUS_GENERATING, STATUS_READY, STATUS_FAILED},
}


def can_transition(current: str, target: str) -> bool:
    """判断 current -> target 是否为合法流转（用于防御性校验）。"""
    if current == target:
        return True
    return target in _TRANSITIONS.get(current or STATUS_DRAFT, set())


def should_skip(current_status: str, *, force: bool = False) -> bool:
    """断点续跑判断：已就绪且非强制时跳过该单元。"""
    if force:
        return False
    return current_status in READY_STATES
