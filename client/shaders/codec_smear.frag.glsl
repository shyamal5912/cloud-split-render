// Fullscreen pass used by the "standard streaming" pane.
// Simulates video-codec smear: blur grows with camera angular speed.
uniform sampler2D tFrame;
uniform vec2 uTexel;
uniform float uMotion;   // radians/sec of camera rotation
uniform float uBlock;    // macroblock size in pixels when moving fast
varying vec2 vUv;

void main() {
  float amount = clamp(uMotion * 2.2, 0.0, 6.0);
  vec2 uv = vUv;
  if (amount > 2.5) {
    // crude macroblocking: snap to a coarse grid under fast motion
    vec2 cell = uTexel * uBlock;
    uv = (floor(uv / cell) + 0.5) * cell;
  }
  vec4 c = vec4(0.0);
  float total = 0.0;
  for (int i = -3; i <= 3; i++) {
    for (int j = -3; j <= 3; j++) {
      float w = exp(-float(i * i + j * j) / 6.0);
      c += texture2D(tFrame, uv + vec2(float(i), float(j)) * uTexel * amount * 0.5) * w;
      total += w;
    }
  }
  gl_FragColor = c / total;
}
