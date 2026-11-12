uniform sampler2D tColor;
varying vec2 vUv;
varying float vBad;

void main() {
  if (vBad > 0.01) discard;   // leave a hole; the fill pass shows through
  gl_FragColor = texture2D(tColor, vUv);
}
