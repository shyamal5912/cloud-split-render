// Camera input + pose history. The hybrid pane uses the live pose; the
// streaming pane reads the pose from `rtt` milliseconds ago, which is what a
// player on a video stream effectively sees.
import * as THREE from 'three';

export class CameraRig {
  constructor(dom) {
    this.pos = new THREE.Vector3(0, 6, 28);
    this.yaw = 0;
    this.pitch = -0.15;
    this.keys = new Set();
    this.drag = false;
    this.history = []; // {t, pos, yaw, pitch}
    this.autoOrbit = true;
    this.angularSpeed = 0;
    this._last = { yaw: 0, pitch: 0, t: performance.now() };

    dom.addEventListener('pointerdown', (e) => { this.drag = true; this.autoOrbit = false; dom.setPointerCapture(e.pointerId); });
    dom.addEventListener('pointerup', () => { this.drag = false; });
    dom.addEventListener('pointermove', (e) => {
      if (!this.drag) return;
      this.yaw -= e.movementX * 0.005;
      this.pitch = Math.max(-1.2, Math.min(1.2, this.pitch - e.movementY * 0.005));
    });
    addEventListener('keydown', (e) => { this.keys.add(e.code); this.autoOrbit = false; });
    addEventListener('keyup', (e) => this.keys.delete(e.code));
  }

  update(dt, now) {
    if (this.autoOrbit) {
      // Whip-pan: sweeps quickly so lag is visible without any input.
      this.yaw = Math.sin(now / 1100) * 1.1;
      this.pitch = -0.15 + Math.sin(now / 1700) * 0.08;
    }
    const f = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    const r = new THREE.Vector3(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
    const v = 14 * dt;
    if (this.keys.has('KeyW')) this.pos.addScaledVector(f, v);
    if (this.keys.has('KeyS')) this.pos.addScaledVector(f, -v);
    if (this.keys.has('KeyD')) this.pos.addScaledVector(r, v);
    if (this.keys.has('KeyA')) this.pos.addScaledVector(r, -v);

    const d = Math.hypot(this.yaw - this._last.yaw, this.pitch - this._last.pitch);
    const elapsed = Math.max((now - this._last.t) / 1000, 1e-3);
    this.angularSpeed += (d / elapsed - this.angularSpeed) * 0.2;
    this._last = { yaw: this.yaw, pitch: this.pitch, t: now };

    this.history.push({ t: now, pos: this.pos.clone(), yaw: this.yaw, pitch: this.pitch });
    while (this.history.length > 2 && this.history[1].t < now - 400) this.history.shift();
  }

  /** Pose as it was `ageMs` ago, linearly interpolated from history. */
  poseAt(now, ageMs) {
    const target = now - ageMs;
    const h = this.history;
    if (h.length === 0 || target <= h[0].t) return h[0];
    for (let i = h.length - 1; i > 0; i--) {
      if (h[i - 1].t <= target) {
        const a = h[i - 1], b = h[i];
        const k = (target - a.t) / Math.max(b.t - a.t, 1e-3);
        return {
          pos: a.pos.clone().lerp(b.pos, k),
          yaw: a.yaw + (b.yaw - a.yaw) * k,
          pitch: a.pitch + (b.pitch - a.pitch) * k,
        };
      }
    }
    return h[h.length - 1];
  }
}

export function applyPose(camera, pose) {
  camera.position.copy(pose.pos);
  camera.rotation.set(pose.pitch, pose.yaw, 0, 'YXZ');
}
