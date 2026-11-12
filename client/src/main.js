import * as THREE from 'three';
import { CameraRig, applyPose } from './camera.js';

const $ = (id) => document.getElementById(id);
const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setScissorTest(true);

const load = (u) => fetch(new URL(u, import.meta.url)).then((r) => r.text());
const [vert, frag, smear] = await Promise.all([
  load('../shaders/lit_proxy.vert.glsl'),
  load('../shaders/lit_proxy.frag.glsl'),
  load('../shaders/codec_smear.frag.glsl'),
]);

// ---- scene: procedural block city -------------------------------------------------
function mulberry32(a) {
  return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const rand = mulberry32(7);

const lightUniforms = {
  uLightPos: { value: [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()] },
  uLightCol: { value: [new THREE.Vector3(1, 0.4, 0.2), new THREE.Vector3(0.2, 0.6, 1), new THREE.Vector3(0.8, 1, 0.3)] },
  uSun: { value: new THREE.Vector3(0.4, 1, 0.3) },
};
const material = new THREE.ShaderMaterial({ vertexShader: vert, fragmentShader: frag, uniforms: lightUniforms });

const geo = new THREE.BoxGeometry(1, 1, 1);
const group = new THREE.Group();
const cells = [];
for (let x = -9; x <= 9; x++) for (let z = -14; z <= 3; z++) {
  if (x % 3 === 0 || z % 3 === 0) continue;
  cells.push({ x: x * 4, z: z * 4, h: 2 + rand() * 14, c: new THREE.Color().setHSL(rand() * 0.15 + 0.55, 0.25, 0.3 + rand() * 0.3) });
}
const merged = new THREE.BufferGeometry();
const pos = [], nor = [], col = [];
const tmp = geo.toNonIndexed();
for (const c of cells) {
  const p = tmp.attributes.position, n = tmp.attributes.normal;
  for (let i = 0; i < p.count; i++) {
    pos.push((p.getX(i)) * 3 + c.x, (p.getY(i) + 0.5) * c.h, p.getZ(i) * 3 + c.z);
    nor.push(n.getX(i), n.getY(i), n.getZ(i));
    col.push(c.c.r, c.c.g, c.c.b);
  }
}
merged.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
merged.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
merged.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
const city = new THREE.Mesh(merged, material);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(400, 400).rotateX(-Math.PI / 2), material);
ground.geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Array(12).fill(0.18), 3));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1020);
scene.add(city, ground);

// proxy wireframe overlay: what the client really renders locally
const wire = new THREE.LineSegments(new THREE.WireframeGeometry(merged),
  new THREE.LineBasicMaterial({ color: 0x3fb950, transparent: true, opacity: 0.18 }));
const wireScene = new THREE.Scene();
wireScene.add(wire);

const camL = new THREE.PerspectiveCamera(70, 1, 0.1, 500);
const camR = new THREE.PerspectiveCamera(70, 1, 0.1, 500);
const rig = new CameraRig(canvas);

// ---- streaming pane render target + post pass --------------------------------------
const rtL = new THREE.WebGLRenderTarget(2, 2);
const post = new THREE.ShaderMaterial({
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }',
  fragmentShader: smear,
  uniforms: { tFrame: { value: rtL.texture }, uTexel: { value: new THREE.Vector2() }, uMotion: { value: 0 }, uBlock: { value: 10 } },
  depthTest: false,
});
const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), post);
const quadScene = new THREE.Scene(); quadScene.add(quad);
const quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

// ---- server light history ----------------------------------------------------------
function serverLights(t) {
  const s = t / 1000;
  return [
    new THREE.Vector3(Math.sin(s * 0.9) * 30, 5, -20 + Math.cos(s * 0.9) * 20),
    new THREE.Vector3(Math.cos(s * 0.6) * 36, 8, -30 + Math.sin(s * 0.7) * 24),
    new THREE.Vector3(Math.sin(s * 1.3 + 2) * 20, 4, -10 + Math.sin(s * 0.5) * 30),
  ];
}
const setLights = (t) => serverLights(t).forEach((v, i) => lightUniforms.uLightPos.value[i].copy(v));

// ---- UI state ----------------------------------------------------------------------
const slider = $('rtt'), rttOut = $('rttOut');
let rtt = +slider.value;
slider.addEventListener('input', () => { rtt = +slider.value; rttOut.textContent = rtt; });
rttOut.textContent = rtt;

let size = { w: 0, h: 0 };
function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  size = { w, h };
  const half = Math.floor(w / 2 * renderer.getPixelRatio());
  rtL.setSize(half, Math.floor(h * renderer.getPixelRatio()));
  post.uniforms.uTexel.value.set(1 / half, 1 / (h * renderer.getPixelRatio()));
  camL.aspect = camR.aspect = (w / 2) / h;
  camL.updateProjectionMatrix(); camR.updateProjectionMatrix();
}
addEventListener('resize', resize); resize();

// ---- loop --------------------------------------------------------------------------
let prev = performance.now(), fpsL = 60, fpsR = 60, lastLeftDraw = 0, held = 0;
const pctl = (n) => n.toFixed(0);

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min((now - prev) / 1000, 0.1); prev = now;
  rig.update(dt, now);

  const { w, h } = size, half = w / 2;
  const r = renderer.getPixelRatio();

  // LEFT: whole frame comes from the server, so it uses an RTT-old pose, drops frames
  // more often as RTT grows, and passes through the codec-smear shader.
  const dropChance = Math.min(0.02 + rtt / 150 * 0.28, 0.35);
  const dropped = Math.random() < dropChance;
  const leftPeriod = 1000 / 60;
  if (!dropped && now - lastLeftDraw >= leftPeriod * 0.9) {
    const pose = rig.poseAt(now, rtt + 12 + 8 + 7); // encode + decode + scanout
    applyPose(camL, pose);
    setLights(now - rtt);
    renderer.setRenderTarget(rtL);
    renderer.setViewport(0, 0, half, h); renderer.setScissor(0, 0, half, h);
    renderer.render(scene, camL);
    renderer.setRenderTarget(null);
    fpsL += (1000 / Math.max(now - lastLeftDraw, 1) - fpsL) * 0.1;
    lastLeftDraw = now; held = 0;
  } else held++;
  post.uniforms.uMotion.value = rig.angularSpeed;
  renderer.setViewport(0, 0, half, h); renderer.setScissor(0, 0, half, h);
  renderer.autoClear = true;
  renderer.render(quadScene, quadCam);

  // RIGHT: camera and proxy geometry are current; only lighting is RTT-old.
  applyPose(camR, rig.poseAt(now, 0));
  setLights(now - rtt - 11.5);
  renderer.setViewport(half, 0, half, h); renderer.setScissor(half, 0, half, h);
  renderer.render(scene, camR);
  renderer.autoClear = false;
  renderer.render(wireScene, camR);
  renderer.autoClear = true;
  fpsR += (1 / dt - fpsR) * 0.1;

  $('latL').textContent = pctl(3.5 + rtt + 12 + 8 + 14);
  $('latR').textContent = pctl(1 + 1.4 + 6.15 + 4.2);
  $('ageR').textContent = pctl(rtt + 11.5);
  $('fpsL').textContent = pctl(Math.min(fpsL, 60) * (1 - dropChance * 0.5));
  $('fpsR').textContent = pctl(Math.min(fpsR, 60));
}
requestAnimationFrame(frame);
