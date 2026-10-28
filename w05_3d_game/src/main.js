
import * as THREE from 'three';
import { Sound } from './audio.js';

/* ------------------------------------------------------------------ *
 *  错层 SEAM — 可玩原型
 *  机制：两条轨道分别长在立方体相邻的两个面上。
 *        把它们在共用的那条棱上对到同一高度，轨道就接上了。
 *  判定：只比较一个标量（高度差），不做任何屏幕空间几何匹配。
 * ------------------------------------------------------------------ */

const H = 1.2;                 // 立方体半边长
const SEAM_TOL = 0.085;        // 对齐容差（一维）

const canvas = document.getElementById('stage');
const overlay = document.getElementById('overlay');
const audioPanel = document.getElementById('audio-panel');
const progressEl = document.getElementById('progress');
const objectiveEl = document.getElementById('objective');
const narrationEl = document.getElementById('narration');
const hintEl = document.getElementById('hint');
const toastEl = document.getElementById('toast');

const sound = new Sound();

/* ---------- 渲染器 / 场景 ---------- */
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x06070a);
scene.fog = new THREE.FogExp2(0x06070a, 0.055);

const camera = new THREE.PerspectiveCamera(33, 1, 0.1, 120);

/* ---------- 相机：受限轨道，围绕盒子看那个棱 ---------- */
const CAM_R = 7.4;
const orbit = { theta: Math.PI / 4, phi: 1.22 };
const orbitTarget = { theta: Math.PI / 4, phi: 1.22 };
const LIMIT = { thetaMin: Math.PI / 4 - 0.36, thetaMax: Math.PI / 4 + 0.36, phiMin: 1.08, phiMax: 1.36 };
const focus = new THREE.Vector3(0, 0.02, 0);

function placeCamera() {
  const sp = Math.sin(orbit.phi), cp = Math.cos(orbit.phi);
  camera.position.set(
    focus.x + CAM_R * sp * Math.sin(orbit.theta),
    focus.y + CAM_R * cp,
    focus.z + CAM_R * sp * Math.cos(orbit.theta)
  );
  camera.lookAt(focus);
}

/* ---------- 灯光 ---------- */
scene.add(new THREE.AmbientLight(0x28344c, 0.62));
scene.add(new THREE.HemisphereLight(0x18202c, 0x0a0806, 0.35));

const key = new THREE.SpotLight(0xffcf9a, 145, 30, 0.33, 0.86, 1.0);
key.position.set(3.4, 6.8, 3.2);
key.target.position.set(0, 0.1, 0);
key.castShadow = true;
key.shadow.mapSize.set(1536, 1536);
key.shadow.bias = -0.0012;
key.shadow.camera.near = 1;
key.shadow.camera.far = 22;
scene.add(key, key.target);

const rim = new THREE.PointLight(0x3d6ea8, 16, 16, 1.0);
rim.position.set(-4.2, 1.4, -3.8);
scene.add(rim);

const fill = new THREE.PointLight(0x8a5220, 7, 12, 1.2);
fill.position.set(0.6, -0.9, 4.6);
scene.add(fill);

/* ---------- 展台 ---------- */
const plinth = new THREE.Mesh(
  new THREE.CylinderGeometry(2.5, 2.65, 0.14, 64),
  new THREE.MeshStandardMaterial({ color: 0x0c0f14, roughness: 0.94, metalness: 0.08 })
);
plinth.position.y = -1.28;
plinth.receiveShadow = true;
scene.add(plinth);

/* ---------- 立方体 ---------- */
const cube = new THREE.Group();
scene.add(cube);

const body = new THREE.Mesh(
  new THREE.BoxGeometry(H * 2, H * 2, H * 2),
  new THREE.MeshStandardMaterial({ color: 0x1c232e, roughness: 0.78, metalness: 0.14 })
);
body.castShadow = true;
body.receiveShadow = true;
cube.add(body);

const edges = new THREE.LineSegments(
  new THREE.EdgesGeometry(new THREE.BoxGeometry(H * 2, H * 2, H * 2)),
  new THREE.LineBasicMaterial({ color: 0x33405a, transparent: true, opacity: 0.55 })
);
cube.add(edges);

/* 两个面上各一块内凹的"房间"背板 */
function facePanel(face) {
  const panel = new THREE.Mesh(
    new THREE.PlaneGeometry(H * 2 - 0.16, H * 2 - 0.16),
    new THREE.MeshStandardMaterial({ color: 0x161b22, roughness: 1, metalness: 0 })
  );
  if (face === 'z') { panel.position.set(0, 0, H + 0.004); }
  else { panel.position.set(H + 0.004, 0, 0); panel.rotation.y = Math.PI / 2; }
  panel.receiveShadow = true;
  cube.add(panel);
}
facePanel('z');
facePanel('x');

// 每个面一圈细边框 + 一块外挑的搁板，用来把"平面"读成"房间"
const bezelMat = new THREE.MeshStandardMaterial({ color: 0x2b323e, roughness: 0.55, metalness: 0.55 });
const ledgeMat = new THREE.MeshStandardMaterial({ color: 0x1a1f28, roughness: 0.9, metalness: 0.15 });

function faceFurniture(face) {
  const g = new THREE.Group();
  const span = H * 2 - 0.1;
  const t = 0.045;
  const bars = [
    [0, span / 2 - t / 2, span, t],
    [0, -span / 2 + t / 2, span, t]
  ];
  for (const [x, y, w, h] of bars) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(w, h, t), bezelMat);
    bar.position.set(x, y, 0);
    g.add(bar);
  }
  for (const x of [-span / 2 + t / 2, span / 2 - t / 2]) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(t, span, t), bezelMat);
    bar.position.set(x, 0, 0);
    g.add(bar);
  }
  const ledge = new THREE.Mesh(new THREE.BoxGeometry(span, 0.07, 0.42), ledgeMat);
  ledge.position.set(0, -span / 2 + 0.02, 0.2);
  ledge.castShadow = true;
  ledge.receiveShadow = true;
  g.add(ledge);

  if (face === 'z') g.position.set(0, 0, H + 0.03);
  else { g.position.set(H + 0.03, 0, 0); g.rotation.y = Math.PI / 2; }
  cube.add(g);
}
faceFurniture('z');
faceFurniture('x');

/* ---------- 两条轨道 ---------- */
const railMat = new THREE.MeshStandardMaterial({ color: 0x241a10, roughness: 0.5, metalness: 0.55 });
const glowMat = new THREE.MeshBasicMaterial({ color: 0xb8742e });

function makeRail(dir) {
  const g = new THREE.Group();
  const long = H * 2 - 0.1;

  const rail = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.075, long), railMat);
  if (dir === 'z') { rail.position.set(0, 0, 0.1); rail.geometry = new THREE.BoxGeometry(long, 0.075, 0.11); }
  else { rail.position.set(0.1, 0, 0); rail.geometry = new THREE.BoxGeometry(0.11, 0.075, long); }
  rail.castShadow = true;
  g.add(rail);

  // 轨道上沿一条发光的细线，让"对齐"看得见
  const strip = new THREE.Mesh(
    new THREE.BoxGeometry(dir === 'z' ? long : 0.115, 0.012, dir === 'z' ? 0.115 : long),
    glowMat
  );
  strip.position.copy(rail.position);
  strip.position.y += 0.042;
  g.add(strip);

  // 拾取用的不可见加粗体积
  const grab = new THREE.Mesh(
    new THREE.BoxGeometry(dir === 'z' ? long : 0.5, 0.42, dir === 'z' ? 0.5 : long),
    new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
  );
  grab.position.copy(rail.position);
  g.add(grab);

  return { group: g, grab, dir };
}

const railA = makeRail('z');   // 长在 +Z 面（画面右侧偏左）
railA.group.position.set(0, 0.30, H + 0.055);
cube.add(railA.group);

const railB = makeRail('x');   // 长在 +X 面（画面右侧）
railB.group.position.set(H + 0.055, -0.22, 0);
cube.add(railB.group);

const heights = { a: 0.30, b: -0.22 };

/* ---------- 光球 ---------- */
const orb = new THREE.Mesh(
  new THREE.SphereGeometry(0.078, 24, 16),
  new THREE.MeshBasicMaterial({ color: 0xffc06a })
);
const orbLight = new THREE.PointLight(0xffb060, 2.2, 3.2, 2);
orb.add(orbLight);
orb.position.set(-1.0, heights.a + 0.1, H + 0.055);
cube.add(orb);

/* ---------- 远处的灯 + 人形剪影 ---------- */
const lamp = new THREE.Mesh(
  new THREE.BoxGeometry(0.09, 0.09, 0.09),
  new THREE.MeshBasicMaterial({ color: 0x161a20 })
);
lamp.position.set(H + 0.03, 0.55, -0.98);
cube.add(lamp);

const lampLight = new THREE.PointLight(0xffbe78, 0, 5.5, 2);
lampLight.position.copy(lamp.position);
cube.add(lampLight);

const figure = new THREE.Group();
const figMat = new THREE.MeshStandardMaterial({ color: 0x05070b, roughness: 1, metalness: 0 });
const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.085, 0.62, 12), figMat);
torso.position.y = 0.31;
const head = new THREE.Mesh(new THREE.SphereGeometry(0.105, 16, 12), figMat);
head.position.y = 0.70;
figure.add(torso, head);
figure.position.set(H + 0.02, -1.19, -0.92);
figure.rotation.y = -Math.PI / 2;
cube.add(figure);

/* ---------- 尘埃 ---------- */
const dustGeo = new THREE.BufferGeometry();
const dustN = 420;
const dustPos = new Float32Array(dustN * 3);
for (let i = 0; i < dustN; i++) {
  dustPos[i * 3] = (Math.random() - 0.5) * 7;
  dustPos[i * 3 + 1] = (Math.random() - 0.5) * 5;
  dustPos[i * 3 + 2] = (Math.random() - 0.5) * 7;
}
dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
  color: 0x9fb2cc, size: 0.017, transparent: true, opacity: 0.42, sizeAttenuation: true, depthWrite: false
}));
scene.add(dust);

/* ---------- 状态机 ---------- */
const state = {
  solved: false,
  phase: 'idle',      // idle | travelling | revealed
  demo: false,
  dragging: null,     // 'orbit' | 'a' | 'b'
  pointerId: null,
  last: { x: 0, y: 0 },
  orbitStart: { theta: 0, phi: 0 }
};

const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();
const trackPlane = new THREE.Plane();

function setNdc(ev) {
  const r = canvas.getBoundingClientRect();
  ndc.x = ((ev.clientX - r.left) / r.width) * 2 - 1;
  ndc.y = -((ev.clientY - r.top) / r.height) * 2 + 1;
}

function pickRail(ev) {
  setNdc(ev);
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObjects([railA.grab, railB.grab], false);
  if (!hits.length) return null;
  return hits[0].object === railA.grab ? 'a' : 'b';
}

// 把屏幕位移投到该面上的世界坐标，直接取 y —— 只有一维，永远稳定
function heightFromPointer(ev, which) {
  setNdc(ev);
  raycaster.setFromCamera(ndc, camera);
  const facePoint = new THREE.Vector3(0, 0, which === 'a' ? H : 0)
    .applyMatrix4(cube.matrixWorld);
  if (which === 'b') facePoint.set(H, 0, 0).applyMatrix4(cube.matrixWorld);
  const normal = new THREE.Vector3(which === 'a' ? 0 : 1, 0, which === 'a' ? 1 : 0)
    .transformDirection(cube.matrixWorld).normalize();
  trackPlane.setFromNormalAndCoplanarPoint(normal, facePoint);
  const hit = raycaster.ray.intersectPlane(trackPlane, new THREE.Vector3());
  if (!hit) return null;
  return THREE.MathUtils.clamp(hit.y, -0.92, 0.92);
}

function applyHeight(which, y) {
  if (y === null) return;
  heights[which] = y;
  if (which === 'a') railA.group.position.y = y;
  else railB.group.position.y = y;
  syncOrbToRail();
  updateGuide();
  checkAlignment();
}

function syncOrbToRail() {
  if (state.solved) return;
  orb.position.set(-1.0, heights.a + 0.1, H + 0.055);
}

function updateGuide() {
  const diff = Math.abs(heights.a - heights.b);
  sound.setGuide(diff);
}

function checkAlignment() {
  if (state.solved) return;
  if (Math.abs(heights.a - heights.b) > SEAM_TOL) return;
  state.solved = true;
  state.phase = 'travelling';
  sound.setGuide(9);
  sound.click();
  toast('咔。');
  hideHint();
  runOrb();
}

/* ---------- 光球穿过拐角 ---------- */
let orbT = 0;
const ORB_TIME = 2.6;
const pathPts = [];

function buildPath() {
  const ya = heights.a + 0.1;
  const yb = heights.b + 0.1;
  const zf = H + 0.055;
  const xf = H + 0.055;
  pathPts.length = 0;
  pathPts.push(
    new THREE.Vector3(-1.0, ya, zf),
    new THREE.Vector3(1.16, ya, zf),
    new THREE.Vector3(xf, ya, 1.16),
    new THREE.Vector3(xf, yb, 1.16),
    new THREE.Vector3(xf, yb, -0.86)
  );
}

function runOrb() {
  buildPath();
  orbT = 0;
}

function stepOrb(dt) {
  if (state.phase !== 'travelling') return;
  orbT += dt;
  const t = Math.min(orbT / ORB_TIME, 1);
  const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

  // 沿折线插值
  const segs = pathPts.length - 1;
  const f = eased * segs;
  const i = Math.min(Math.floor(f), segs - 1);
  const local = f - i;
  orb.position.lerpVectors(pathPts[i], pathPts[i + 1], local);
  orbLight.intensity = 2.2 + Math.sin(orbT * 22) * 0.5;

  if (t >= 1) reveal();
}

/* ---------- 揭示 ---------- */
let revealT = 0;

function reveal() {
  state.phase = 'revealed';
  revealT = 0;
  sound.arrive();
  progressEl.innerHTML = '1 <small>/ 1</small>';
  objectiveEl.classList.add('done');
  setTimeout(() => {
    narration('走廊的另一头，站着一个人。<br>它没有动，但你已经走到这里了。');
    sound.dread();
  }, 900);
}

function stepReveal(dt) {
  if (state.phase !== 'revealed') return;
  revealT += dt;
  // 灯闪两下才稳定，稳定三秒后熄灭 —— 人形还留在暗处
  let target = 0;
  if (revealT < 0.16) target = 0.4;
  else if (revealT < 0.30) target = 2.4;
  else if (revealT < 0.42) target = 0.6;
  else if (revealT < 3.6) target = 3.4;
  else target = 0;

  lampLight.intensity += (target - lampLight.intensity) * Math.min(dt * 14, 1);
  lamp.material.color.setHex(lampLight.intensity > 0.4 ? 0xffd8a0 : 0x161a20);
}

/* ---------- 输入 ---------- */
canvas.addEventListener('pointerdown', (ev) => {
  if (isBlocking()) return;
  sound.init();
  const hit = pickRail(ev);
  if (hit) {
    state.dragging = hit;
    state.pointerId = ev.pointerId;
    state.last = { x: ev.clientX, y: ev.clientY };
    canvas.setPointerCapture(ev.pointerId);
    sound.grab();
    hideHint();
  } else {
    state.dragging = 'orbit';
    state.pointerId = ev.pointerId;
    state.last = { x: ev.clientX, y: ev.clientY };
    state.orbitStart = { theta: orbitTarget.theta, phi: orbitTarget.phi };
    canvas.setPointerCapture(ev.pointerId);
  }
});

canvas.addEventListener('pointermove', (ev) => {
  if (!state.dragging || ev.pointerId !== state.pointerId) return;
  if (state.dragging === 'orbit') {
    const dx = (ev.clientX - state.last.x) / canvas.clientWidth;
    const dy = (ev.clientY - state.last.y) / canvas.clientHeight;
    orbitTarget.theta = THREE.MathUtils.clamp(
      state.orbitStart.theta + dx * 2.4, LIMIT.thetaMin, LIMIT.thetaMax);
    orbitTarget.phi = THREE.MathUtils.clamp(
      state.orbitStart.phi - dy * 2.0, LIMIT.phiMin, LIMIT.phiMax);
  } else {
    const y = heightFromPointer(ev, state.dragging);
    applyHeight(state.dragging, y);
  }
});

function endDrag(ev) {
  if (state.pointerId === null) return;
  if (ev && ev.pointerId !== state.pointerId) return;
  state.dragging = null;
  state.pointerId = null;
  sound.setGuide(9);
}
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);
canvas.addEventListener('pointerleave', endDrag);

/* ---------- 观看演示：把 B 轨推到 A 轨的高度 ---------- */
let auto = null;

function startAutoDemo() {
  if (state.solved) return;
  overlay.classList.add('hide');
  audioPanel.style.opacity = '0';
  state.demo = true;
  auto = { t: 0, from: heights.b, to: heights.a };
  toast('自动演示');
}

function stepAuto(dt) {
  if (!auto) return;
  auto.t += dt;
  const k = Math.min(auto.t / 2.0, 1);
  const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
  applyHeight('b', auto.from + (auto.to - auto.from) * e);
  if (k >= 1) auto = null;
}

/* ---------- UI ---------- */
let toastTimer = null;
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 1800);
}

let hintHidden = false;
function hideHint() {
  if (hintHidden) return;
  hintHidden = true;
  hintEl.classList.add('fade');
}

let narTimer = null;
function narration(html) {
  narrationEl.innerHTML = html;
  narrationEl.classList.add('show');
  clearTimeout(narTimer);
  narTimer = setTimeout(() => narrationEl.classList.remove('show'), 7000);
}

function isBlocking() {
  return !overlay.classList.contains('hide');
}

document.getElementById('start').addEventListener('click', () => {
  sound.init();
  overlay.classList.add('hide');
  hideHint();
  setTimeout(() => hideHint(), 9000);
});

document.getElementById('watch').addEventListener('click', () => {
  sound.init();
  startAutoDemo();
});

const muteBtn = document.getElementById('mute');
muteBtn.addEventListener('click', () => {
  sound.init();
  const next = !sound.muted;
  sound.setMuted(next);
  muteBtn.textContent = next ? '声音 关' : '声音 开';
});

const vol = document.getElementById('volume');
vol.addEventListener('input', () => {
  sound.setVolume(Number(vol.value) / 100);
});

addEventListener('keydown', (ev) => {
  if (ev.key === 'm' || ev.key === 'M') {
    const next = !sound.muted;
    sound.setMuted(next);
    muteBtn.textContent = next ? '声音 关' : '声音 开';
  }
  if (ev.key === 'r' || ev.key === 'R') location.reload();
});

/* ---------- 尺寸 ---------- */
function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();

/* ---------- 主循环 ---------- */
const clock = new THREE.Clock();
let elapsed = 0;

function frame() {
  const dt = Math.min(clock.getDelta(), 0.05);
  elapsed += dt;

  // 相机阻尼
  orbit.theta += (orbitTarget.theta - orbit.theta) * Math.min(dt * 6, 1);
  orbit.phi += (orbitTarget.phi - orbit.phi) * Math.min(dt * 6, 1);
  // 极轻微的呼吸感
  const breathe = Math.sin(elapsed * 0.5) * 0.012;
  placeCamera();
  camera.position.y += breathe;

  stepAuto(dt);
  stepOrb(dt);
  stepReveal(dt);

  dust.rotation.y += dt * 0.014;
  dust.position.y = Math.sin(elapsed * 0.25) * 0.06;

  if (state.phase === 'revealed') {
    figure.rotation.y = -Math.PI / 2 + Math.sin(elapsed * 0.16) * 0.02;
  }

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

/* 极小的自检：确认状态与几何一致 */
window.__seam = {
  state, heights, railA, railB, cube, camera,
  align() { applyHeight('b', heights.a); },
  get aligned() { return Math.abs(heights.a - heights.b) <= SEAM_TOL; }
};

/* ---------- 由 URL 参数驱动的自动运行（用于录制/截图/自查） ---------- */
const params = new URLSearchParams(location.search);
const autoParam = params.get('auto');
if (autoParam) {
  overlay.style.transition = 'none';
  hintEl.style.transition = 'none';
  overlay.classList.add('hide');
  audioPanel.style.opacity = '0';
  hideHint();

  // 无头截图环境里 CSS transition / setTimeout 不一定推进，这里直接落状态
  if (autoParam === 'demo') {
    state.demo = true;
    applyHeight('b', heights.a);
  } else if (autoParam === 'aligned') {
    applyHeight('b', heights.a);
  } else if (autoParam === 'revealed') {
    applyHeight('b', heights.a);
    reveal();
    revealT = 1.2;
  } else if (autoParam === 'trace') {
    // 关掉动画依赖，同步把光球走完全程，用于无头环境自查
    applyHeight('b', heights.a);
    for (let i = 0; i < 40; i++) stepOrb(0.1);
  }
}

placeCamera();
requestAnimationFrame(frame);
