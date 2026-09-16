# -*- coding: utf-8 -*-
"""人类视角的事件屏蔽。

纯 AI 对局是“上帝视角”：前端会收到全部身份、狼人频道、所有人的心声。
当真人参与对局时，必须只让其看到自己座位合法可见的信息。本模块提供一个
包装器，把游戏 event_sink 过滤成“人类视角”的事件流。

过滤规则（站在人类座位 H 的角度）：
- 玩家名单：仅暴露 H 自己的身份，其他人显示“未知”。
- 狼人频道（讨论/投票/投票结果）：仅当 H 是狼人时可见。
- 女巫/预言家的夜间私密行动：仅当行动者是 H 时可见。
- 反思（memory）：仅 H 自己的可见。
- 任何其他玩家发言事件中的“心声(thought)”一律剥离。
- 其余（回合/昼夜、公告、死亡、存活名单、公开发言、公开投票、遗言、猎人开枪
  等）均为公开信息，照常透传。
"""
from __future__ import annotations

import copy
from typing import Any, Callable

# 仅狼人可见的类别（含“正在输入”状态用的别名 夜晚讨论/夜晚投票）
_WOLF_CATEGORIES = {"狼人讨论", "狼人投票", "狼人投票结果", "夜晚讨论", "夜晚投票"}

# 神职夜间私密行动：按角色门控（无论事件是 system 摘要还是 agent_message 详情，
# 也无论是否带 agentName，都只对对应神职本人可见）。
_SEER_CATEGORIES = {"预言家行动", "预言家查验"}
_WITCH_CATEGORIES = {"女巫行动", "女巫行动(解药)", "女巫行动(毒药)"}


def _rebuild_content(behavior: str, speech: str) -> str:
    lines = []
    if behavior:
        lines.append(f"(表现) {behavior}")
    if speech:
        lines.append(f"(发言) {speech}")
    return "\n".join(lines)


def _strip_thought(event: dict[str, Any], human_name: str) -> dict[str, Any]:
    """剥离非本人事件中的私密心声。"""
    if event.get("agentName") == human_name:
        return event
    if not event.get("thought"):
        return event
    masked = copy.deepcopy(event)
    masked["thought"] = ""
    masked["content"] = _rebuild_content(
        str(masked.get("behavior", "")), str(masked.get("speech", "")))
    return masked


def make_perspective_sink(
    real_sink: Callable[[dict[str, Any]], None],
    human_name: str,
    get_role: Callable[[], str | None],
) -> Callable[[dict[str, Any]], None]:
    """返回一个按人类视角过滤后再转发给 ``real_sink`` 的新 sink。"""

    def sink(event: dict[str, Any]) -> None:
        masked = _filter_event(event, human_name, get_role)
        if masked is not None:
            real_sink(masked)

    return sink


def _filter_event(
    event: dict[str, Any],
    human_name: str,
    get_role: Callable[[], str | None],
) -> dict[str, Any] | None:
    etype = event.get("type")
    category = str(event.get("category", "") or "")
    agent_name = event.get("agentName")
    is_wolf = get_role() == "werewolf"

    # 玩家名单初始化：屏蔽他人身份。
    # 例外：若人类是狼人，狼队友身份对其可见（狼人天然互认队友）。
    if (
        etype == "system"
        and isinstance(event.get("players"), list)
        and "死亡" not in category
    ):
        masked = copy.deepcopy(event)
        for p in masked["players"]:
            if not isinstance(p, dict):
                continue
            if p.get("name") == human_name:
                continue
            if is_wolf and str(p.get("role")) == "werewolf":
                continue  # 向狼人暴露其队友
            p["role"] = "未知"
        return masked

    # 反思：仅本人（含反思内容 memory 与“回合反思”输入状态）
    if etype == "memory" or category == "回合反思":
        return event if agent_name == human_name else None

    # 私密提示（人类自己的角色/查验结果）直接透传
    if etype == "private_info":
        return event if agent_name == human_name else None

    # 神职夜间私密行动：按角色门控（覆盖 system 摘要与 agent_message 详情）。
    # 例如“预言家查验 结果:狼人”“女巫使用解药救了X”——非该神职本人一律屏蔽。
    if category in _SEER_CATEGORIES:
        return _strip_thought(event, human_name) if get_role() == "seer" else None
    if category in _WITCH_CATEGORIES:
        return _strip_thought(event, human_name) if get_role() == "witch" else None

    # 狼人频道（讨论/投票/投票结果）：仅狼人可见
    if category in _WOLF_CATEGORIES:
        return _strip_thought(event, human_name) if is_wolf else None

    # 玩家发言 / 正在输入（公开发言 / 投票 / 遗言 / 猎人开枪等）
    if etype in ("agent_message", "agent_typing"):
        return _strip_thought(event, human_name)

    # 其余一律公开
    return event
