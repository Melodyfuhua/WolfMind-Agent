/**
 * 氛围音 / 背景音乐管理器。
 *
 * 文件优先：优先播放 frontend/public/audio/ 下的 mp3（Vite 以 / 根路径提供）：
 *   - day.mp3        白天背景音乐（循环）
 *   - night.mp3      夜晚背景音乐（循环）
 *   - wolf_kill.mp3  狼人刀人音效（一次性）
 *   - hunter_shot.mp3 猎人开枪音效（一次性）
 * 若某个文件缺失或加载失败，自动回退到 Web Audio 合成音，保证不会变哑。
 *
 * 接口：
 *   - init()                  在用户交互（点击）里调用，创建/唤醒音频上下文。
 *   - setPhase('day'|'night'|'none')  背景音乐随昼夜切换（交叉淡入淡出）。
 *   - playWolfKill() / playHunterShot()  一次性音效。
 *   - setMuted(bool) / resume() / blip()。
 */

const FILES = {
  day: "/audio/day.mp3",
  night: "/audio/night.mp3",
  wolf_kill: "/audio/wolf_kill.mp3",
  hunter_shot: "/audio/hunter_shot.mp3",
};

export class AudioManager {
  constructor() {
    this.muted = false;
    this.baseVolume = 0.6;
    this.phase = null;

    // 合成兜底用的 Web Audio
    this.ctx = null;
    this.master = null;
    this.synthNodes = null;

    // 文件循环播放用的 HTMLAudioElement
    this.loopEls = {};
    this.curLoop = null;
    this._fadeTimer = null;
  }

  init() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) {
        this.ctx = new AC();
        this.master = this.ctx.createGain();
        this.master.gain.value = this.muted ? 0 : this.baseVolume;
        this.master.connect(this.ctx.destination);
      }
    }
    this.resume();
  }

  resume() {
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume().catch(() => {});
    }
    if (this.curLoop && this.curLoop.paused && !this.muted) {
      this.curLoop.play().catch(() => {});
    }
  }

  setMuted(muted) {
    this.muted = muted;
    if (this.master && this.ctx) {
      this.master.gain.setTargetAtTime(
        muted ? 0 : this.baseVolume,
        this.ctx.currentTime,
        0.05
      );
    }
    if (this.curLoop) {
      if (muted) {
        this.curLoop.pause();
      } else {
        this.curLoop.volume = this.baseVolume;
        this.curLoop.play().catch(() => {});
      }
    }
  }

  // ---------- 背景音乐（昼夜） ----------
  setPhase(phase) {
    if (this.phase === phase) return;
    this.phase = phase;

    this._stopSynthPhase();
    this._fadeOutCurrentLoop();

    if (phase === "none") return;

    const el = this._getLoopEl(phase);
    if (!el) {
      this._synthPhase(phase);
      return;
    }

    try {
      el.currentTime = 0;
    } catch {
      /* ignore */
    }
    el.volume = 0;
    const p = el.play();
    if (p && typeof p.then === "function") {
      p.then(() => {
        this.curLoop = el;
        if (!this.muted) this._fadeLoopTo(el, this.baseVolume, 800);
      }).catch(() => {
        // 文件不可用或被浏览器拦截 → 合成兜底
        this._synthPhase(phase);
      });
    } else {
      this.curLoop = el;
      if (!this.muted) this._fadeLoopTo(el, this.baseVolume, 800);
    }
  }

  _getLoopEl(name) {
    if (this.loopEls[name]) {
      return this.loopEls[name]._broken ? null : this.loopEls[name];
    }
    const el = new Audio(FILES[name]);
    el.loop = true;
    el.preload = "auto";
    el.volume = 0;
    el.addEventListener("error", () => {
      el._broken = true;
    });
    this.loopEls[name] = el;
    return el;
  }

  _fadeOutCurrentLoop() {
    const el = this.curLoop;
    this.curLoop = null;
    if (!el) return;
    this._fadeLoopTo(el, 0, 500, () => {
      try {
        el.pause();
      } catch {
        /* ignore */
      }
    });
  }

  _fadeLoopTo(el, target, ms, done) {
    if (this._fadeTimer) {
      clearInterval(this._fadeTimer);
      this._fadeTimer = null;
    }
    const start = el.volume;
    const steps = Math.max(1, Math.round(ms / 40));
    let i = 0;
    const timer = setInterval(() => {
      i += 1;
      const v = start + (target - start) * (i / steps);
      try {
        el.volume = Math.min(1, Math.max(0, v));
      } catch {
        /* ignore */
      }
      if (i >= steps) {
        clearInterval(timer);
        if (done) done();
      }
    }, 40);
    this._fadeTimer = timer;
  }

  // ---------- 一次性音效 ----------
  playWolfKill() {
    this._oneShot("wolf_kill", () => this._synthWolfKill());
  }

  playHunterShot() {
    this._oneShot("hunter_shot", () => this._synthHunterShot());
  }

  _oneShot(name, fallback) {
    if (this.muted) return;
    const el = new Audio(FILES[name]);
    el.volume = this.baseVolume;
    let usedFallback = false;
    el.addEventListener("error", () => {
      if (!usedFallback) {
        usedFallback = true;
        this.init();
        fallback();
      }
    });
    const p = el.play();
    if (p && typeof p.catch === "function") {
      p.catch(() => {
        if (!usedFallback) {
          usedFallback = true;
          this.init();
          fallback();
        }
      });
    }
  }

  blip() {
    this.init();
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const g = this.ctx.createGain();
    g.gain.value = 0.0001;
    g.connect(this.master);
    const o = this.ctx.createOscillator();
    o.type = "triangle";
    o.frequency.setValueAtTime(523.25, t);
    o.frequency.setValueAtTime(659.25, t + 0.12);
    o.connect(g);
    g.gain.exponentialRampToValueAtTime(0.4, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
    o.start(t);
    o.stop(t + 0.32);
  }

  dispose() {
    this._stopSynthPhase(0.1);
    this._fadeOutCurrentLoop();
    this.phase = null;
  }

  // ---------- 以下为合成兜底（无文件时使用） ----------
  _stopSynthPhase(fade = 0.6) {
    if (!this.synthNodes || !this.ctx) return;
    const t = this.ctx.currentTime;
    const { gain, nodes } = this.synthNodes;
    try {
      gain.gain.setTargetAtTime(0, t, fade / 3);
    } catch {
      /* ignore */
    }
    nodes.forEach((n) => {
      try {
        n.stop(t + fade + 0.2);
      } catch {
        /* ignore */
      }
    });
    this.synthNodes = null;
  }

  _synthPhase(phase) {
    this.init();
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const gain = this.ctx.createGain();
    gain.gain.value = 0;
    gain.connect(this.master);
    const nodes = [];

    if (phase === "day") {
      [261.63, 329.63, 392.0].forEach((f) => {
        const o = this.ctx.createOscillator();
        o.type = "triangle";
        o.frequency.value = f;
        const g = this.ctx.createGain();
        g.gain.value = 0.16;
        o.connect(g);
        g.connect(gain);
        o.start();
        nodes.push(o);
      });
      gain.gain.setTargetAtTime(0.22, t, 0.8);
    } else if (phase === "night") {
      [
        { f: 110, type: "sine", g: 0.28 },
        { f: 164.81, type: "sine", g: 0.2 },
        { f: 220, type: "triangle", g: 0.08 },
      ].forEach(({ f, type, g: gv }) => {
        const o = this.ctx.createOscillator();
        o.type = type;
        o.frequency.value = f;
        const g = this.ctx.createGain();
        g.gain.value = gv;
        o.connect(g);
        g.connect(gain);
        o.start();
        nodes.push(o);
      });
      gain.gain.setTargetAtTime(0.3, t, 1.0);
    }

    this.synthNodes = { gain, nodes };
  }

  _synthWolfKill() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const g = this.ctx.createGain();
    g.gain.value = 0.0001;
    g.connect(this.master);
    [330, 349].forEach((startF) => {
      const o = this.ctx.createOscillator();
      o.type = "sawtooth";
      o.frequency.setValueAtTime(startF, t);
      o.frequency.exponentialRampToValueAtTime(startF * 0.33, t + 0.7);
      o.connect(g);
      o.start(t);
      o.stop(t + 1.05);
    });
    g.gain.exponentialRampToValueAtTime(0.32, t + 0.03);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.0);
  }

  _synthHunterShot() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const dur = 0.45;
    const buffer = this.ctx.createBuffer(
      1,
      Math.floor(this.ctx.sampleRate * dur),
      this.ctx.sampleRate
    );
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / data.length, 2);
    }
    const noise = this.ctx.createBufferSource();
    noise.buffer = buffer;
    const hp = this.ctx.createBiquadFilter();
    hp.type = "highpass";
    hp.frequency.value = 600;
    const ng = this.ctx.createGain();
    ng.gain.value = 0.5;
    noise.connect(hp);
    hp.connect(ng);
    ng.connect(this.master);
    noise.start(t);
    const o = this.ctx.createOscillator();
    o.type = "sine";
    o.frequency.setValueAtTime(160, t);
    o.frequency.exponentialRampToValueAtTime(45, t + 0.25);
    const og = this.ctx.createGain();
    og.gain.setValueAtTime(0.6, t);
    og.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
    o.connect(og);
    og.connect(this.master);
    o.start(t);
    o.stop(t + 0.45);
  }
}
