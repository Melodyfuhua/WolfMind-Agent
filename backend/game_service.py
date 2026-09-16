# -*- coding: utf-8 -*-
"""FastAPI 下运行 WolfMind 游戏的一些服务端辅助函数。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from agentscope.agent import ReActAgent

from config import config
from core.knowledge_base import PlayerKnowledgeStore
from core.game_engine import werewolves_game
from core.human_agent import HumanAgent, HumanInputChannel
from core.perspective import make_perspective_sink

# 复用 CLI 入口中的官方 prompt 与 agent 构造函数，
# 避免在这里重复维护一大段系统提示词。
from main import get_official_agents  # noqa: E402


@dataclass
class GameStartResult:
    game_id: str


def _model_label(provider: str, cfg: dict[str, str] | None) -> str:
    if provider == "openai" and cfg:
        return f"openai: {cfg.get('model_name', '')}"
    if provider == "dashscope":
        return f"dashscope: {config.dashscope_model_name}"
    if provider == "ollama":
        return f"ollama: {config.ollama_model_name}"
    return provider


def create_players() -> tuple[list[ReActAgent], dict[str, str]]:
    """创建 9 名玩家并返回 (agents, player_model_map)。"""

    model_overrides = (
        config.openai_player_configs if config.model_provider == "openai" else [
            None] * 9
    )

    agents = [
        get_official_agents(f"Player{idx + 1}", model_overrides[idx]) for idx in range(9)
    ]

    player_model_map = {
        player.name: _model_label(config.model_provider, model_overrides[idx])
        for idx, player in enumerate(agents)
    }

    return agents, player_model_map


def create_knowledge_store(player_model_map: dict[str, str]) -> PlayerKnowledgeStore:
    """为本局创建并落盘一个空的知识库（经验存档）。"""

    store = PlayerKnowledgeStore(
        checkpoint_dir=config.experience_dir,
        base_filename=config.experience_id,
    )
    store.set_player_models(player_model_map)
    store.save()
    return store


async def run_game_session(*, game_id: str, event_sink=None, stop_event=None) -> tuple[str, str]:
    """运行完整的一局游戏并返回 (log_path, experience_path)。"""

    is_valid, error_msg = config.validate()
    if not is_valid:
        raise RuntimeError(f"配置错误: {error_msg}")

    agents, player_model_map = create_players()
    knowledge_store = create_knowledge_store(player_model_map)

    log_path, experience_path = await werewolves_game(
        agents,
        knowledge_store=knowledge_store,
        player_model_map=player_model_map,
        game_id=game_id,
        event_sink=event_sink,
        stop_event=stop_event,
    )

    return log_path, experience_path


def create_players_with_human(
    human_seat: int,
    channel: HumanInputChannel,
) -> tuple[list, dict[str, str], HumanAgent]:
    """创建 8 个 AI + 1 个人类玩家。

    Args:
        human_seat: 人类所在座位（1..9）。
        channel: 人类输入通道。

    Returns:
        (agents, player_model_map, human_agent)
    """
    model_overrides = (
        config.openai_player_configs if config.model_provider == "openai" else [
            None] * 9
    )

    agents: list = []
    player_model_map: dict[str, str] = {}
    human_agent: HumanAgent | None = None

    for idx in range(9):
        name = f"Player{idx + 1}"
        if idx + 1 == human_seat:
            human_agent = HumanAgent(name, channel)
            agents.append(human_agent)
            player_model_map[name] = "human: 你"
        else:
            agent = get_official_agents(name, model_overrides[idx])
            agents.append(agent)
            player_model_map[name] = _model_label(
                config.model_provider, model_overrides[idx])

    assert human_agent is not None
    return agents, player_model_map, human_agent


async def run_human_game_session(
    *,
    game_id: str,
    channel: HumanInputChannel,
    event_sink=None,
    stop_event=None,
) -> tuple[str, str]:
    """运行一局有真人参与的游戏（8 AI + 1 人，随机座位、随机身份）。"""

    is_valid, error_msg = config.validate()
    if not is_valid:
        raise RuntimeError(f"配置错误: {error_msg}")

    human_seat = random.randint(1, 9)
    agents, player_model_map, human_agent = create_players_with_human(
        human_seat, channel)
    knowledge_store = create_knowledge_store(player_model_map)

    # 向前端广播人类座位（身份仍随机，稍后由引擎分配并经 private_info 告知本人）
    if event_sink:
        event_sink(
            {
                "type": "human_seat",
                "agentName": human_agent.name,
                "content": f"你将坐在 {human_agent.name} 的位置，身份稍后随机分配。",
            }
        )

    # 引擎事件经“人类视角”过滤后再下发；人类自身的请求/私密信息由 channel 直达。
    perspective_sink = make_perspective_sink(
        event_sink, human_agent.name, lambda: human_agent.role_name
    ) if event_sink else None

    log_path, experience_path = await werewolves_game(
        agents,
        knowledge_store=knowledge_store,
        player_model_map=player_model_map,
        game_id=game_id,
        event_sink=perspective_sink,
        stop_event=stop_event,
    )

    return log_path, experience_path
