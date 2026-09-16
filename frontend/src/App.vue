<template>
  <div class="app">
    <div class="header">
      <Header
        :status-text="statusText"
        :phase-text="phaseText"
        :on-start-game="startGame"
        :on-stop-game="stopGame"
        :on-join-game="startHumanGame"
        :join-disabled="joiningGame || isGameRunning"
        :join-label="joiningGame ? '启动中…' : '玩家参与游戏'"
        :on-toggle-sound="toggleSound"
        :sound-label="soundOn ? '🔊 音效' : '🔇 静音'"
        :start-disabled="startingGame || isGameRunning"
        :start-label="startingGame ? '启动中…' : '开始游戏'"
        :stop-disabled="stoppingGame || !isGameRunning"
        :stop-label="stoppingGame ? '终止中…' : '终止游戏'"
        :on-export-log="exportLog"
        :export-log-disabled="exportingLog"
        :export-log-label="exportingLog ? '导出中…' : '导出日志'"
        :on-export-experience="exportExperience"
        :export-experience-disabled="exportingExperience"
        :export-experience-label="exportingExperience ? '导出中…' : '导出经验'"
      />
    </div>

    <div style="flex: 1; min-height: 0; display: flex;">
      <div style="width: 60%; min-width: 0; border-right: 1px solid #e0e0e0;">
        <RoomView
          :agents="agents"
          :bubbles="bubbles"
          :bubble-for="bubbleFor"
          :leaderboard="[]"
          :feed="feed"
          :phase-text="phaseText"
          :on-jump-to-message="handleJumpToMessage"
        />
      </div>
      <div style="width: 40%; min-width: 360px;">
        <GameFeed ref="feedRef" :feed="feed" />
      </div>
    </div>

    <HumanInputPanel
      :request="humanRequest"
      :role-text="humanRoleText"
      :on-submit="submitHumanInput"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import Header from "./components/Header.vue";
import RoomView from "./components/RoomView.vue";
import GameFeed from "./components/GameFeed.vue";
import HumanInputPanel from "./components/HumanInputPanel.vue";

import { DEFAULT_AGENTS, API_URL, BUBBLE_LIFETIME_MS, TYPING_LIFETIME_MS, ASSETS } from "./config/constants";
import { ReadOnlyClient } from "./services/websocket";
import { AudioManager } from "./services/audio";
import { useFeedProcessor } from "./hooks/useFeedProcessor";

const extractBubbleText = (content) => {
  const text = String(content || "");
  return text.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
};

const connectionStatus = ref("connecting");
const phaseText = ref("准备中");
const startingGame = ref(false);
const joiningGame = ref(false);
const stoppingGame = ref(false);
const exportingLog = ref(false);
const exportingExperience = ref(false);

// 真人参与模式状态
const humanRequest = ref(null); // 当前等待人类输入的请求（human_turn 事件）
const humanRole = ref(""); // 人类的角色（英文，如 werewolf）

const ROLE_ZH = {
  werewolf: "狼人",
  villager: "村民",
  seer: "预言家",
  witch: "女巫",
  hunter: "猎人",
};
const humanRoleText = computed(() => ROLE_ZH[humanRole.value] || (humanRole.value ? humanRole.value : ""));

// 氛围音（仅人类对局生效）
const audio = new AudioManager();
const audioActive = ref(false); // 是否处于人类对局（决定要不要放音乐）
const soundOn = ref(true);
const toggleSound = () => {
  soundOn.value = !soundOn.value;
  audio.init(); // 点击即为可发声的交互时机
  audio.setMuted(!soundOn.value);
  if (soundOn.value) {
    audio.resume();
    audio.blip(); // 即时确认音频可用
  }
};

const gameStatus = ref({ status: "idle", gameId: null, logPath: null, experiencePath: null });

const agents = ref([...DEFAULT_AGENTS]);

const getAgentById = (agentId) => {
  if (!agentId) return null;
  return agents.value.find((a) => a.id === agentId) || null;
};

const { feed, processHistoricalFeed, processFeedEvent, addSystemMessage } = useFeedProcessor({ getAgentById });

const bubbles = ref({});
const clientRef = ref(null);
const feedRef = ref(null);
const bubbleTimersRef = ref({});

const roleMetaFromRole = (role) => {
  const raw = String(role || "").toLowerCase();
  const isWerewolf = raw.includes("狼人") || raw.includes("werewolf");
  const isSeer = raw.includes("预言家") || raw.includes("seer") || raw.includes("prophet");
  const isWitch = raw.includes("女巫") || raw.includes("witch");
  const isHunter = raw.includes("猎人") || raw.includes("hunter");
  const isGuard = raw.includes("守卫") || raw.includes("guard") || raw.includes("bodyguard");
  const isVillager = raw.includes("平民") || raw.includes("villager") || raw.includes("村民");

  if (isWerewolf) {
    return {
      alignment: "werewolves",
      avatar: ASSETS.avatars.werewolf,
      colors: { bg: "#111827", text: "#F8FAFC", accent: "#F8FAFC" },
    };
  }
  if (isSeer) {
    return {
      alignment: "villagers",
      avatar: ASSETS.avatars.seer,
      colors: { bg: "#EEF2FF", text: "#3730A3", accent: "#3730A3" },
    };
  }
  if (isWitch) {
    return {
      alignment: "villagers",
      avatar: ASSETS.avatars.witch,
      colors: { bg: "#ECFEFF", text: "#0F766E", accent: "#0F766E" },
    };
  }
  if (isHunter) {
    return {
      alignment: "villagers",
      avatar: ASSETS.avatars.hunter,
      colors: { bg: "#FEF3C7", text: "#92400E", accent: "#92400E" },
    };
  }
  if (isGuard) {
    return {
      alignment: "villagers",
      avatar: ASSETS.avatars.guard,
      colors: { bg: "#ECFDF5", text: "#065F46", accent: "#065F46" },
    };
  }
  if (isVillager) {
    return {
      alignment: "villagers",
      avatar: ASSETS.avatars.villager,
      colors: { bg: "#F8FAFC", text: "#111827", accent: "#111827" },
    };
  }

  return {
    alignment: "unknown",
    avatar: ASSETS.avatars.villager,
    colors: { bg: "#F8FAFC", text: "#111827", accent: "#111827" },
  };
};

const mapPlayerNameToAgentId = (name) => {
  const n = String(name || "");
  const lower = n.toLowerCase();
  if (lower.startsWith("player")) {
    const suffix = lower.slice(6);
    const num = Number(suffix);
    if (Number.isFinite(num) && num >= 1 && num <= 99) {
      return `player_${num}`;
    }
  }
  return null;
};

const applyPlayersInit = (players) => {
  if (!Array.isArray(players) || players.length === 0) return;

  const prev = agents.value.length ? agents.value : DEFAULT_AGENTS;
  const byId = new Map((prev || []).map((a) => [a.id, a]));

  for (const p of players) {
    const agentId = mapPlayerNameToAgentId(p?.name);
    if (!agentId) continue;

    const base = byId.get(agentId) || { id: agentId, name: agentId };
    const seatNum = agentId.startsWith("player_") ? agentId.slice(7) : "";
    const meta = roleMetaFromRole(p?.role);
    byId.set(agentId, {
      ...base,
      id: agentId,
      name: seatNum ? `${Number(seatNum)}号` : base.name,
      role: String(p?.role || "未知"),
      alignment: meta.alignment,
      avatar: meta.avatar,
      colors: meta.colors,
      model: p?.model || base.model,
      alive: p?.alive !== false,
    });
  }

  const nextAgents = Array.from(byId.values()).sort((a, b) => {
    const na = Number(String(a.id).replace("player_", ""));
    const nb = Number(String(b.id).replace("player_", ""));
    return (Number.isFinite(na) ? na : 0) - (Number.isFinite(nb) ? nb : 0);
  });

  agents.value = nextAgents;
};

const markPlayersDead = (deadPlayerNames) => {
  if (!Array.isArray(deadPlayerNames) || deadPlayerNames.length === 0) return;

  agents.value = agents.value.map((agent) => {
    const isDead = deadPlayerNames.some((name) => {
      const deadId = mapPlayerNameToAgentId(name);
      return deadId === agent.id || name === agent.name || name === `${agent.name.replace("号", "")}号`;
    });
    if (isDead) {
      return { ...agent, alive: false };
    }
    return agent;
  });
};

const statusText = computed(() => {
  if (connectionStatus.value === "connected") return "已连接";
  if (connectionStatus.value === "disconnected") return "连接断开";
  return "连接中";
});

const isGameRunning = computed(() => String(gameStatus.value?.status || "").toLowerCase() === "running");

const refreshGameStatus = async () => {
  try {
    const res = await fetch(`${API_URL}/api/game/status`, { method: "GET" });
    if (!res.ok) return;
    const data = await res.json().catch(() => null);
    if (!data) return;
    gameStatus.value = {
      status: data.status || "idle",
      gameId: data.gameId ?? null,
      logPath: data.logPath ?? null,
      experiencePath: data.experiencePath ?? null,
    };
  } catch {
    // ignore
  }
};

const downloadBlob = async (url, fallbackName) => {
  const res = await fetch(url, { method: "GET" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${text || res.statusText}`.trim());
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const filename = decodeURIComponent((m && (m[1] || m[2])) || fallbackName || "download");

  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
};

const bubbleFor = (idOrName) => {
  if (!idOrName) return null;
  const direct = bubbles.value[idOrName];
  if (direct) return direct;

  const agent = agents.value.find((a) => a.id === idOrName || a.name === idOrName);
  if (!agent) return null;
  return bubbles.value[agent.id] || null;
};

const handleJumpToMessage = (bubble) => {
  if (feedRef.value?.scrollToMessage) {
    feedRef.value.scrollToMessage(bubble);
  }
};

const upsertBubbleFromMessage = (messageOrFeedItem) => {
  if (!messageOrFeedItem) return;

  const isFeedItem =
    typeof messageOrFeedItem === "object" &&
    messageOrFeedItem !== null &&
    Object.prototype.hasOwnProperty.call(messageOrFeedItem, "data") &&
    messageOrFeedItem.data;

  const msg = isFeedItem ? messageOrFeedItem.data : messageOrFeedItem;
  if (!msg || !msg.agentId) return;

  const agent = agents.value.find((a) => a.id === msg.agentId);
  const behaviorText = String(msg.behavior || "").trim();
  const speechTextRaw = String(msg.speech || "").trim();
  const contentTextRaw = String(msg.content || "").trim();
  const hasStructured = Boolean(behaviorText || speechTextRaw);

  const lines = [];
  if (hasStructured) {
    if (behaviorText) {
      lines.push(`(表现) ${extractBubbleText(behaviorText)}`);
    }
    const speechText = speechTextRaw ? speechTextRaw : contentTextRaw;
    if (String(speechText || "").trim()) {
      lines.push(`(发言) ${extractBubbleText(speechText)}`);
    }
  }

  const bubble = {
    agentId: msg.agentId,
    agentName: msg.agentName || msg.agent || agent?.name,
    text: hasStructured ? lines.join("\n") : extractBubbleText(speechTextRaw || contentTextRaw),
    timestamp: msg.timestamp || Date.now(),
    ts: msg.timestamp || Date.now(),
    id: msg.id,
    feedItemId: msg.id,
  };

  bubbles.value = {
    ...bubbles.value,
    [msg.agentId]: bubble,
  };

  const timers = bubbleTimersRef.value;
  if (timers[msg.agentId]) {
    clearTimeout(timers[msg.agentId]);
  }
  timers[msg.agentId] = setTimeout(() => {
    if (!bubbles.value[msg.agentId]) return;
    const next = { ...bubbles.value };
    delete next[msg.agentId];
    bubbles.value = next;
    delete timers[msg.agentId];
  }, BUBBLE_LIFETIME_MS);
};

const handleAgentTyping = (evt) => {
  if (!evt || !evt.agentId) return;

  const agent = agents.value.find((a) => a.id === evt.agentId);
  const bubble = {
    agentId: evt.agentId,
    agentName: evt.agentName || agent?.name,
    text: "",
    isTyping: true,
    category: evt.category,
    categoryDisplay: evt.categoryDisplay,
    timestamp: evt.timestamp || Date.now(),
    ts: evt.timestamp || Date.now(),
  };

  bubbles.value = {
    ...bubbles.value,
    [evt.agentId]: bubble,
  };

  const timers = bubbleTimersRef.value;
  if (timers[evt.agentId]) {
    clearTimeout(timers[evt.agentId]);
  }
  // Typing indication should have a longer timeout to prevent premature disappearance if LLM is slow
  timers[evt.agentId] = setTimeout(() => {
    const currentBubble = bubbles.value[evt.agentId];
    if (currentBubble && currentBubble.isTyping) {
      const next = { ...bubbles.value };
      delete next[evt.agentId];
      bubbles.value = next;
    }
    delete timers[evt.agentId];
  }, TYPING_LIFETIME_MS);
};

const startGame = async () => {
  if (startingGame.value) return;
  startingGame.value = true;
  // 纯 AI 观战模式不放音乐
  audioActive.value = false;
  audio.setPhase("none");
  try {
    addSystemMessage("正在请求后端开始游戏…");
    const res = await fetch(`${API_URL}/api/game/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      const text = await res.text();
      addSystemMessage(`开始游戏失败: ${res.status} ${text || res.statusText}`);
      return;
    }
    const data = await res.json().catch(() => ({}));
    addSystemMessage(`已开始游戏 (gameId=${data?.gameId || ""})`);
    refreshGameStatus();
  } catch (e) {
    addSystemMessage(`开始游戏失败: ${String(e?.message || e)}`);
  } finally {
    startingGame.value = false;
  }
};

const startHumanGame = async () => {
  if (joiningGame.value) return;
  joiningGame.value = true;
  humanRequest.value = null;
  humanRole.value = "";
  try {
    // 用户点击即为可发声的交互时机：初始化音频
    audio.init();
    audio.setMuted(!soundOn.value);
    audioActive.value = true;
    addSystemMessage("正在请求后端开始游戏（真人参与）…");
    const res = await fetch(`${API_URL}/api/game/start_human`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      const text = await res.text();
      addSystemMessage(`开始游戏失败: ${res.status} ${text || res.statusText}`);
      return;
    }
    const data = await res.json().catch(() => ({}));
    addSystemMessage(`已开始真人对局 (gameId=${data?.gameId || ""})，随机分配座位与身份中…`);
    refreshGameStatus();
  } catch (e) {
    addSystemMessage(`开始游戏失败: ${String(e?.message || e)}`);
  } finally {
    joiningGame.value = false;
  }
};

const submitHumanInput = (requestId, payload) => {
  const client = clientRef.value;
  if (!client) return;
  client.send({ type: "human_input", requestId, data: payload });
  humanRequest.value = null; // 收起输入面板，等待下一步
};

const stopGame = async () => {
  if (stoppingGame.value) return;
  stoppingGame.value = true;
  humanRequest.value = null;
  audioActive.value = false;
  audio.setPhase("none");
  try {
    addSystemMessage("正在请求后端终止游戏…");
    const res = await fetch(`${API_URL}/api/game/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      const text = await res.text();
      addSystemMessage(`终止游戏失败: ${res.status} ${text || res.statusText}`);
      return;
    }
    const data = await res.json().catch(() => ({}));
    addSystemMessage(data?.message || "已请求终止游戏");
    refreshGameStatus();
  } catch (e) {
    addSystemMessage(`终止游戏失败: ${String(e?.message || e)}`);
  } finally {
    stoppingGame.value = false;
  }
};

const exportLog = async () => {
  if (exportingLog.value) return;
  exportingLog.value = true;
  try {
    await downloadBlob(`${API_URL}/api/exports/log`, "game.log");
    addSystemMessage("已导出最新游戏日志");
  } catch (e) {
    addSystemMessage(`导出日志失败: ${String(e?.message || e)}`);
  } finally {
    exportingLog.value = false;
  }
};

const exportExperience = async () => {
  if (exportingExperience.value) return;
  exportingExperience.value = true;
  try {
    await downloadBlob(`${API_URL}/api/exports/experience`, "experience.json");
    addSystemMessage("已导出最新经验文件");
  } catch (e) {
    addSystemMessage(`导出经验失败: ${String(e?.message || e)}`);
  } finally {
    exportingExperience.value = false;
  }
};

let statusTimer = null;
let audioGestureCleanup = null;

onMounted(() => {
  refreshGameStatus();
  statusTimer = setInterval(refreshGameStatus, 1500);

  const onEvent = (evt) => {
    if (!evt || !evt.type) return;

    if (evt.type === "system") {
      const content = String(evt.content || "");
      if (content.toLowerCase().includes("connected")) {
        connectionStatus.value = "connected";
      }
      if (content.toLowerCase().includes("try to connect")) {
        connectionStatus.value = "disconnected";
      }

      const category = String(evt.category || "");
      if ((category.includes("死亡") || content.includes("被淘汰")) && Array.isArray(evt.players)) {
        markPlayersDead(evt.players);
      }
    }

    if (evt.type === "system" && Array.isArray(evt.players)) {
      const category = String(evt.category || "");
      if (!category.includes("死亡")) {
        applyPlayersInit(evt.players);
      }
    }

    if (evt.type === "day_start") {
      phaseText.value = "白天";
      if (audioActive.value) audio.setPhase("day");
    }
    if (evt.type === "night_start") {
      phaseText.value = "夜晚";
      if (audioActive.value) audio.setPhase("night");
    }

    // 氛围音效（仅人类对局）：狼人刀人 / 猎人开枪
    if (audioActive.value) {
      const cat = String(evt.category || "");
      // “狼人投票结果”事件经屏蔽只会送达狼人玩家本人 → 天然满足“只有狼人玩家能听到”
      if (cat === "狼人投票结果" || /被选中击杀/.test(String(evt.content || ""))) {
        audio.playWolfKill();
      }
      if (cat === "猎人开枪" && evt.type === "system") {
        audio.playHunterShot();
      }
    }

    // 真人参与模式事件
    if (evt.type === "human_seat") {
      addSystemMessage(String(evt.content || "你已加入游戏"));
      return;
    }
    if (evt.type === "private_info") {
      const content = String(evt.content || "");
      const m = content.match(/your role is\s+(\w+)/i);
      if (m) {
        humanRole.value = m[1].toLowerCase();
      }
      addSystemMessage(`🔒 仅你可见：${content}`);
      return;
    }
    if (evt.type === "human_turn") {
      humanRequest.value = evt;
      return;
    }

    // 游戏结束/终止时收起输入面板
    if (evt.type === "system") {
      const c = String(evt.content || "");
      if (c.includes("游戏结束") || c.includes("游戏已终止") || c.includes("异常终止")) {
        humanRequest.value = null;
        audio.setPhase("none");
        audioActive.value = false;
      }
    }

    if (evt.type === "historical" && Array.isArray(evt.events)) {
      const playersInit = evt.events
        .filter((e) => e && e.type === "system" && Array.isArray(e.players) && !String(e.category || "").includes("死亡"))
        .map((e) => e.players)
        .pop();
      if (playersInit) {
        applyPlayersInit(playersInit);
      }

      const deathEvents = evt.events.filter(
        (e) => e && e.type === "system" && String(e.category || "").includes("死亡") && Array.isArray(e.players)
      );
      for (const deathEvt of deathEvents) {
        markPlayersDead(deathEvt.players);
      }

      // 重连时恢复真人模式状态：角色 + 是否有未完成的行动
      const events = evt.events.slice().reverse(); // historical 为“最新在前”，反转成时间顺序
      for (const e of events) {
        if (e && e.type === "private_info") {
          const m = String(e.content || "").match(/your role is\s+(\w+)/i);
          if (m) humanRole.value = m[1].toLowerCase();
        }
      }
      const lastTurn = events.filter((e) => e && e.type === "human_turn").pop();
      const ended = events.some(
        (e) =>
          e &&
          e.type === "system" &&
          /游戏结束|游戏已终止|异常终止/.test(String(e.content || ""))
      );
      humanRequest.value = ended ? null : lastTurn || null;

      processHistoricalFeed(evt.events);
      return;
    }

    processFeedEvent(evt);
    if (evt.type === "agent_message" || evt.type === "conference_message") {
      upsertBubbleFromMessage(evt);
    }
    if (evt.type === "agent_typing") {
      handleAgentTyping(evt);
    }
  };

  const client = new ReadOnlyClient(onEvent);
  clientRef.value = client;

  // 任意用户交互都尝试唤醒音频，避免浏览器自动播放策略导致无声
  const resumeAudio = () => {
    try {
      audio.resume();
    } catch {
      // ignore
    }
  };
  window.addEventListener("pointerdown", resumeAudio);
  window.addEventListener("keydown", resumeAudio);
  audioGestureCleanup = () => {
    window.removeEventListener("pointerdown", resumeAudio);
    window.removeEventListener("keydown", resumeAudio);
  };

  addSystemMessage("等待游戏开始…");
  client.connect();
});

onBeforeUnmount(() => {
  if (statusTimer) {
    clearInterval(statusTimer);
    statusTimer = null;
  }

  const timers = bubbleTimersRef.value || {};
  Object.keys(timers).forEach((k) => clearTimeout(timers[k]));
  bubbleTimersRef.value = {};

  if (clientRef.value) {
    try {
      clientRef.value.disconnect();
    } catch {
      // ignore
    }
  }
  clientRef.value = null;

  try {
    audio.dispose();
  } catch {
    // ignore
  }
  if (audioGestureCleanup) {
    audioGestureCleanup();
    audioGestureCleanup = null;
  }
});
</script>
