<template>
  <div v-if="request" class="human-panel">
    <div class="human-panel__inner">
      <div class="human-panel__head">
        <span class="human-panel__title">轮到你了（{{ seatLabel }}）</span>
        <span v-if="roleText" class="human-panel__role">你的身份：{{ roleText }}</span>
      </div>

      <div v-if="request.prompt" class="human-panel__prompt">{{ request.prompt }}</div>

      <!-- 发言输入（文字 + 语音） -->
      <div v-if="spec.needsSpeech" class="human-panel__field">
        <label class="human-panel__label">你的发言</label>
        <div class="human-panel__speech-row">
          <textarea
            v-model="speech"
            class="human-panel__textarea"
            rows="2"
            placeholder="输入你的发言…（也可点右侧麦克风语音输入）"
          />
          <button
            type="button"
            class="human-panel__mic"
            :class="{ 'is-recording': recording }"
            :title="micSupported ? (recording ? '点击停止' : '点击语音输入') : '当前浏览器不支持语音识别'"
            :disabled="!micSupported"
            @click="toggleMic"
          >
            {{ recording ? "● 录音中" : "🎤 语音" }}
          </button>
        </div>
        <input
          v-model="behavior"
          class="human-panel__input"
          placeholder="（可选）你的表现/动作，例如：皱眉环视全场"
        />
      </div>

      <!-- 选择类字段（投票/查验/目标） -->
      <div
        v-for="field in choiceFields"
        :key="field.field"
        class="human-panel__field"
      >
        <label class="human-panel__label">{{ field.label }}</label>
        <div class="human-panel__options">
          <button
            v-for="opt in playerOptions(field)"
            :key="opt"
            type="button"
            class="human-panel__opt"
            :class="{ 'is-active': choices[field.field] === opt }"
            @click="choices[field.field] = opt"
          >
            {{ displayName(opt) }}
          </button>
          <button
            v-if="hasAbstain(field)"
            type="button"
            class="human-panel__opt human-panel__opt--abstain"
            :class="{ 'is-active': choices[field.field] === ABSTAIN }"
            @click="choices[field.field] = ABSTAIN"
          >
            弃权 / 不选
          </button>
        </div>
      </div>

      <!-- 布尔类字段（是否用药/开枪/达成一致） -->
      <div
        v-for="field in boolFields"
        :key="field.field"
        class="human-panel__field"
      >
        <label class="human-panel__label">{{ field.label }}</label>
        <div class="human-panel__options">
          <button
            type="button"
            class="human-panel__opt"
            :class="{ 'is-active': bools[field.field] === true }"
            @click="bools[field.field] = true"
          >
            是
          </button>
          <button
            type="button"
            class="human-panel__opt"
            :class="{ 'is-active': bools[field.field] === false }"
            @click="bools[field.field] = false"
          >
            否
          </button>
        </div>
      </div>

      <div class="human-panel__foot">
        <span v-if="error" class="human-panel__error">{{ error }}</span>
        <button type="button" class="human-panel__submit" @click="submit">
          提交
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";

const ABSTAIN = "__abstain__";

const props = defineProps({
  request: { type: Object, default: null }, // { requestId, prompt, agentName, spec }
  roleText: { type: String, default: "" },
  onSubmit: { type: Function, default: null },
});

const speech = ref("");
const behavior = ref("");
const choices = reactive({});
const bools = reactive({});
const error = ref("");

const spec = computed(() => props.request?.spec || { needsSpeech: false, fields: [] });
const seatLabel = computed(() => {
  const n = String(props.request?.agentName || "");
  const m = n.match(/(\d+)/);
  return m ? `${m[1]}号` : n;
});

const choiceFields = computed(() => (spec.value.fields || []).filter((f) => f.kind === "choice"));
const boolFields = computed(() => (spec.value.fields || []).filter((f) => f.kind === "bool"));

const isAbstainToken = (o) => o === "abstain" || o === "弃权";
const playerOptions = (field) => (field.options || []).filter((o) => !isAbstainToken(o));
const hasAbstain = (field) => field.nullable || (field.options || []).some(isAbstainToken);

const displayName = (name) => {
  const m = String(name || "").match(/(\d+)/);
  return m ? `${m[1]}号` : name;
};

// 每次轮到新的一步，重置本地输入状态
watch(
  () => props.request?.requestId,
  () => {
    speech.value = "";
    behavior.value = "";
    error.value = "";
    Object.keys(choices).forEach((k) => delete choices[k]);
    Object.keys(bools).forEach((k) => delete bools[k]);
    for (const f of boolFields.value) {
      bools[f.field] = false; // 布尔默认否
    }
  },
  { immediate: true }
);

const submit = () => {
  error.value = "";
  // 校验必选的选择项
  for (const f of choiceFields.value) {
    const required = !hasAbstain(f);
    if (required && !choices[f.field]) {
      error.value = `请先${f.label}`;
      return;
    }
  }

  const data = {
    speech: speech.value || "",
    behavior: behavior.value || "",
    thought: "",
  };
  for (const f of choiceFields.value) {
    const v = choices[f.field];
    data[f.field] = !v || v === ABSTAIN ? null : v;
  }
  for (const f of boolFields.value) {
    data[f.field] = bools[f.field] === true;
  }

  if (props.onSubmit && props.request?.requestId) {
    props.onSubmit(props.request.requestId, data);
  }
};

// ---------- 语音输入：浏览器原生 Web Speech API ----------
const recording = ref(false);
const SpeechRecognition =
  typeof window !== "undefined"
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;
const micSupported = !!SpeechRecognition;
let recognition = null;

const toggleMic = () => {
  if (!micSupported) return;
  if (recording.value) {
    try {
      recognition && recognition.stop();
    } catch {
      // ignore
    }
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = false;
  recognition.continuous = false;
  recognition.onresult = (ev) => {
    let text = "";
    for (let i = 0; i < ev.results.length; i++) {
      text += ev.results[i][0].transcript;
    }
    speech.value = (speech.value ? speech.value + " " : "") + text;
  };
  recognition.onerror = () => {
    recording.value = false;
  };
  recognition.onend = () => {
    recording.value = false;
  };
  try {
    recognition.start();
    recording.value = true;
  } catch {
    recording.value = false;
  }
};
</script>

<style scoped>
.human-panel {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 50;
  display: flex;
  justify-content: center;
  padding: 12px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.12), transparent);
  pointer-events: none;
}
.human-panel__inner {
  pointer-events: auto;
  width: 100%;
  max-width: 880px;
  background: #ffffff;
  border: 2px solid #4338ca;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(67, 56, 202, 0.25);
  padding: 14px 16px;
}
.human-panel__head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.human-panel__title {
  font-weight: 800;
  color: #4338ca;
  font-size: 14px;
}
.human-panel__role {
  font-size: 12px;
  font-weight: 700;
  color: #111827;
  background: #eef2ff;
  border-radius: 4px;
  padding: 2px 8px;
}
.human-panel__prompt {
  font-size: 12px;
  color: #374151;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
.human-panel__field {
  margin-bottom: 10px;
}
.human-panel__label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: #111827;
  margin-bottom: 6px;
}
.human-panel__speech-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
.human-panel__textarea {
  flex: 1;
  resize: vertical;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 8px;
  font-size: 13px;
  font-family: inherit;
}
.human-panel__input {
  width: 100%;
  margin-top: 6px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  font-family: inherit;
}
.human-panel__mic {
  flex: 0 0 auto;
  border: 1px solid #4338ca;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 6px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.human-panel__mic:disabled {
  border-color: #e5e7eb;
  background: #f3f4f6;
  color: #9ca3af;
  cursor: not-allowed;
}
.human-panel__mic.is-recording {
  background: #fee2e2;
  border-color: #dc2626;
  color: #dc2626;
}
.human-panel__options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.human-panel__opt {
  border: 1px solid #d1d5db;
  background: #ffffff;
  color: #111827;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.human-panel__opt.is-active {
  background: #4338ca;
  border-color: #4338ca;
  color: #ffffff;
}
.human-panel__opt--abstain {
  border-style: dashed;
}
.human-panel__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 4px;
}
.human-panel__error {
  color: #dc2626;
  font-size: 12px;
  font-weight: 700;
}
.human-panel__submit {
  border: 1px solid #4338ca;
  background: #4338ca;
  color: #ffffff;
  border-radius: 6px;
  padding: 8px 22px;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}
</style>
