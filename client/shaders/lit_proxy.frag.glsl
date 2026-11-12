// Lighting for the proxy geometry. The light positions come from the server
// and are therefore RTT-old on the hybrid pane; geometry and camera are current.
uniform vec3 uLightPos[3];
uniform vec3 uLightCol[3];
uniform vec3 uSun;
varying vec3 vWorld;
varying vec3 vNormal;
varying vec3 vColor;

void main() {
  vec3 n = normalize(vNormal);
  vec3 lit = vColor * (0.12 + 0.55 * max(dot(n, normalize(uSun)), 0.0));
  for (int i = 0; i < 3; i++) {
    vec3 d = uLightPos[i] - vWorld;
    float att = 1.0 / (1.0 + 0.02 * dot(d, d));
    lit += vColor * uLightCol[i] * max(dot(n, normalize(d)), 0.0) * att * 2.0;
  }
  // simple filmic curve
  lit = lit / (lit + vec3(0.8));
  gl_FragColor = vec4(pow(lit, vec3(1.0 / 2.2)), 1.0);
}
