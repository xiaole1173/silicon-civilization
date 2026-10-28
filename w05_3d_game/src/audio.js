// 极简程序化音效：零音频文件、零版权风险
export class Sound {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.muted = false;
    this.volume = 0.7;
    this.guide = null;
  }

  // 必须在用户手势里调用（浏览器 autoplay 策略）
  async init() {
    if (this.ctx) { await this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    this.master = this.ctx.createGain();
    this.master.gain.value = this.muted ? 0 : this.volume;
    this.master.connect(this.ctx.destination);
    this.noise = this._noiseBuffer();
    this._startDrone();
    this._makeGuide();
  }

  _noiseBuffer() {
    const n = this.ctx.sampleRate * 0.5;
    const buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  // 房间的嗡鸣：两个轻微失谐的低频正弦
  _startDrone() {
    const g = this.ctx.createGain();
    g.gain.value = 0.0;
    g.gain.linearRampToValueAtTime(0.05, this.ctx.currentTime + 4);
    g.connect(this.master);
    [55, 55.4, 82.5].forEach((f, i) => {
      const o = this.ctx.createOscillator();
      o.type = 'sine';
      o.frequency.value = f;
      const og = this.ctx.createGain();
      og.gain.value = i === 2 ? 0.35 : 0.6;
      o.connect(og).connect(g);
      o.start();
    });
    // 极慢的音量起伏，制造"活着"的感觉
    const lfo = this.ctx.createOscillator();
    lfo.frequency.value = 0.06;
    const lg = this.ctx.createGain();
    lg.gain.value = 0.02;
    lfo.connect(lg).connect(g.gain);
    lfo.start();
  }

  // 对齐引导音：高度差越小，音越高、越响
  _makeGuide() {
    const o = this.ctx.createOscillator();
    o.type = 'sine';
    o.frequency.value = 220;
    const g = this.ctx.createGain();
    g.gain.value = 0;
    o.connect(g).connect(this.master);
    o.start();
    this.guide = { osc: o, gain: g };
  }

  setGuide(diff) {
    if (!this.guide || !this.ctx) return;
    const t = this.ctx.currentTime;
    const near = Math.max(0, 1 - diff / 0.5);
    const level = near > 0.02 ? Math.pow(near, 2) * 0.055 : 0;
    this.guide.gain.gain.setTargetAtTime(level, t, 0.05);
    this.guide.osc.frequency.setTargetAtTime(196 + near * 220, t, 0.05);
  }

  _burst(freq, q, dur, gain) {
    if (!this.ctx) return;
    const s = this.ctx.createBufferSource();
    s.buffer = this.noise;
    const f = this.ctx.createBiquadFilter();
    f.type = 'bandpass';
    f.frequency.value = freq;
    f.Q.value = q;
    const g = this.ctx.createGain();
    const t = this.ctx.currentTime;
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f).connect(g).connect(this.master);
    s.start(t);
    s.stop(t + dur + 0.02);
  }

  _tone(freq, dur, gain, type) {
    if (!this.ctx) return;
    const o = this.ctx.createOscillator();
    o.type = type || 'sine';
    o.frequency.value = freq;
    const g = this.ctx.createGain();
    const t = this.ctx.currentTime;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.master);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  rotate() { this._burst(900, 2.2, 0.09, 0.16); }
  grab() { this._burst(1600, 3.0, 0.05, 0.07); }
  click() { this._burst(2400, 4.0, 0.06, 0.22); this._tone(180, 0.12, 0.09, 'triangle'); }
  arrive() { this._tone(523.25, 1.1, 0.07, 'triangle'); this._tone(784, 1.4, 0.045, 'sine'); }
  dread() { this._tone(48, 2.4, 0.16, 'sine'); this._burst(220, 1.2, 0.9, 0.05); }
  denied() { this._burst(320, 1.4, 0.16, 0.1); this._tone(110, 0.18, 0.07, 'sine'); }

  setVolume(v) {
    this.volume = v;
    if (this.master && !this.muted) this.master.gain.value = v;
  }
  setMuted(m) {
    this.muted = m;
    if (this.master) this.master.gain.value = m ? 0 : this.volume;
  }
}