# -*- coding: utf-8 -*-
"""人类玩家代理。

HumanAgent 与 AgentScope 的 ReActAgent 暴露相同的调用接口
（``await agent(prompt, structured_model=Model)`` 返回带 ``metadata`` 的 ``Msg``），
因此可以直接顶替某个座位上的 AI，而游戏引擎与角色逻辑完全不需要改动。

与 AI 不同，HumanAgent 不调用大模型：当轮到人类行动时，它会通过
``HumanInputChannel`` 向前端推送一条 ``human_turn`` 请求事件（携带本步需要
填写的字段与候选项），然后挂起等待前端把人类输入回传，再按 structured_model
组装成 ``Msg.metadata`` 返回。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from agentscope.agent import AgentBase
from agentscope.message import Msg


class HumanInputChannel:
    """人类输入的双向通道。

    - ``emit``：把事件推给前端（与游戏 event_sink 同一条总线）。
    - ``request_input``：在游戏线程的事件循环上创建一个 Future 并挂起，
      等待前端通过 ``submit`` 回传输入后被唤醒。

    游戏在独立线程的事件循环中运行，而 WebSocket 接收输入发生在 FastAPI 主循环，
    因此 ``submit`` 通过 ``call_soon_threadsafe`` 跨线程安全地 resolve Future。
    """

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit
        self._pending: dict[str, asyncio.Future] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def emit(self, event: dict[str, Any]) -> None:
        try:
            self._emit(event)
        except Exception:
            return

    async def request_input(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """推送一条 human_turn 请求并等待人类回传输入。"""
        loop = asyncio.get_running_loop()
        self._loop = loop  # 记录游戏线程的事件循环，供跨线程 resolve 使用
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut

        event = {"type": "human_turn", "requestId": request_id}
        event.update(payload)
        self.emit(event)

        try:
            return await fut
        finally:
            self._pending.pop(request_id, None)

    def submit(self, request_id: str, data: dict[str, Any]) -> bool:
        """从主循环线程提交人类输入，唤醒对应的等待。返回是否命中待处理请求。"""
        fut = self._pending.get(request_id)
        loop = self._loop
        if fut is None or loop is None or fut.done():
            return False

        def _set() -> None:
            if not fut.done():
                fut.set_result(data or {})

        try:
            loop.call_soon_threadsafe(_set)
            return True
        except Exception:
            return False

    def cancel_all(self) -> None:
        """终止游戏时取消所有挂起的等待，避免线程卡死。"""
        loop = self._loop
        for fut in list(self._pending.values()):
            if fut.done():
                continue
            if loop is not None:
                loop.call_soon_threadsafe(fut.cancel)
            else:
                fut.cancel()


# 这些 structured_model 是“后台自动”流程（反思、长期知识更新），不应打扰人类，
# 直接返回空结果即可。
_AUTO_FIELDS = {"impression_updates", "knowledge"}


def _extract_enum(prop: dict[str, Any]) -> tuple[list[str], bool]:
    """从 JSON Schema 的某个属性中提取候选项与是否可空。

    返回 (options, nullable)。兼容直接 ``enum`` 与 ``anyOf`` 两种写法。
    """
    options: list[str] = []
    nullable = False

    def _collect(node: dict[str, Any]) -> None:
        nonlocal nullable
        if not isinstance(node, dict):
            return
        if node.get("type") == "null":
            nullable = True
        for val in node.get("enum", []) or []:
            if isinstance(val, str):
                options.append(val)

    _collect(prop)
    for sub in prop.get("anyOf", []) or []:
        _collect(sub)

    # 去重保序
    seen: set[str] = set()
    uniq = [o for o in options if not (o in seen or seen.add(o))]
    return uniq, nullable


def _derive_spec(structured_model: Any) -> dict[str, Any] | None:
    """根据 structured_model 推导前端需要的输入规格。

    返回 None 表示这是自动流程（无需人类输入）。
    """
    if structured_model is None:
        return None

    try:
        schema = structured_model.model_json_schema()
    except Exception:
        return None

    props: dict[str, Any] = schema.get("properties", {}) or {}

    # 反思/知识更新：自动跳过
    if any(f in props for f in _AUTO_FIELDS):
        return None

    spec: dict[str, Any] = {
        "needsSpeech": "speech" in props,
        "fields": [],
    }

    # 选择类字段（投票目标 / 查验或毒杀或开枪目标）
    for fname in ("vote", "name"):
        if fname in props:
            options, nullable = _extract_enum(props[fname])
            spec["fields"].append(
                {
                    "field": fname,
                    "kind": "choice",
                    "options": options,
                    "nullable": nullable,
                    "label": "选择目标玩家",
                }
            )

    # 布尔类字段
    bool_labels = {
        "reach_agreement": "是否已和队友达成一致",
        "resurrect": "是否使用解药救人",
        "poison": "是否使用毒药",
        "shoot": "是否开枪带走一人",
    }
    for fname, label in bool_labels.items():
        if fname in props:
            spec["fields"].append(
                {"field": fname, "kind": "bool", "label": label})

    return spec


class HumanAgent(AgentBase):
    """由真人通过前端操控的玩家代理。"""

    def __init__(self, name: str, channel: HumanInputChannel) -> None:
        super().__init__()
        self.name = name
        self._channel = channel
        self.role_name: str | None = None  # 角色分配后由 observe 捕获
        self._turn_seq = 0  # 回合序号，保证每次请求 ID 唯一

    async def reply(self, *args: Any, **kwargs: Any) -> Msg:
        """轮到人类行动：向前端要输入并组装结构化结果。"""
        msg = args[0] if args else kwargs.get("msg")
        structured_model = kwargs.get("structured_model")
        if structured_model is None and len(args) > 1:
            structured_model = args[1]

        prompt_text = ""
        if isinstance(msg, Msg):
            prompt_text = msg.content if isinstance(msg.content, str) else str(msg.content)

        spec = _derive_spec(structured_model)

        # 自动流程（反思/知识更新/无结构）：不打扰人类，返回空结果。
        if spec is None:
            meta: dict[str, Any] = {}
            if structured_model is not None:
                try:
                    props = structured_model.model_json_schema().get("properties", {})
                except Exception:
                    props = {}
                if "impression_updates" in props:
                    meta["impression_updates"] = {}
                if "knowledge" in props:
                    meta["knowledge"] = ""
                if "thought" in props:
                    meta["thought"] = ""
            return Msg(self.name, "", role="assistant", metadata=meta)

        # 交互流程：推送请求并等待人类输入。
        self._turn_seq += 1
        request_id = f"{self.name}-{self._turn_seq}"
        payload = {
            "agentName": self.name,
            "prompt": prompt_text,
            "spec": spec,
        }

        try:
            data = await self._channel.request_input(request_id, payload)
        except asyncio.CancelledError:
            # 游戏被终止：返回一个安全的默认值，避免卡住整局。
            data = {}

        if not isinstance(data, dict):
            data = {}

        speech = str(data.get("speech", "") or "")
        metadata: dict[str, Any] = {
            "thought": str(data.get("thought", "") or ""),
            "behavior": str(data.get("behavior", "") or ""),
            "speech": speech,
        }
        for field in spec["fields"]:
            fname = field["field"]
            metadata[fname] = data.get(fname)

        return Msg(self.name, speech, role="assistant", metadata=metadata)

    async def observe(self, msg: Msg | list[Msg] | None) -> None:
        """接收广播/私密消息。

        - 捕获“你的角色是 X”以记录自身身份（供视角屏蔽判断是否为狼人）。
        - 把发给本人的私密提示（角色、查验结果等 ``[名字 ONLY]``）转发到前端，
          让人类能看到只属于自己的信息。
        """
        if msg is None:
            return
        items = msg if isinstance(msg, list) else [msg]
        for m in items:
            content = m.content if isinstance(getattr(m, "content", None), str) else ""
            if not content:
                continue

            # 记录自身角色
            lowered = content.lower()
            if "your role is" in lowered:
                for role in ("werewolf", "villager", "seer", "witch", "hunter"):
                    if role in lowered:
                        self.role_name = role
                        break

            # 仅转发发给本人的私密信息
            tag = f"[{self.name} ONLY]"
            if tag in content:
                clean = content.replace(tag, "").strip()
                self._channel.emit(
                    {
                        "type": "private_info",
                        "agentName": self.name,
                        "content": clean,
                    }
                )

    async def handle_interrupt(self, *args: Any, **kwargs: Any) -> Msg:
        """被打断时返回空消息。"""
        return Msg(self.name, "", role="assistant", metadata={})
