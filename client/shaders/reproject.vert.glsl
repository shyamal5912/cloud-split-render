// Depth-based forward warp. A grid of vertices, one per server pixel, is
// unprojected with the server camera's depth and re-projected with the
// client's current camera. Stretched triangles across depth edges are flagged
// so the fragment shader can discard them (disocclusions).
uniform sampler2D tDepth;
uniform mat4 uStaleInvVP;   // inverse(view-projection) of the camera the server used
uniform mat4 uCurVP;        // view-projection of the client's current camera
uniform vec2 uTexel;
uniform vec2 uNearFar;
uniform float uEdge;        // relative depth jump treated as an edge
varying vec2 vUv;
varying float vBad;

float lin(float d) {
  float z = d * 2.0 - 1.0;
  return 2.0 * uNearFar.x * uNearFar.y / (uNearFar.y + uNearFar.x - z * (uNearFar.y - uNearFar.x));
}

void main() {
  vUv = uv;
  float d = texture2D(tDepth, uv).r;
  float z = lin(d);
  float zn = lin(texture2D(tDepth, uv + vec2(uTexel.x, 0.0)).r);
  float zs = lin(texture2D(tDepth, uv - vec2(uTexel.x, 0.0)).r);
  float zu = lin(texture2D(tDepth, uv + vec2(0.0, uTexel.y)).r);
  float zd = lin(texture2D(tDepth, uv - vec2(0.0, uTexel.y)).r);
  float jump = max(max(abs(zn - z), abs(zs - z)), max(abs(zu - z), abs(zd - z))) / z;
  vBad = jump > uEdge ? 1.0 : 0.0;

  vec4 clip = vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
  vec4 w = uStaleInvVP * clip;
  w /= w.w;
  gl_Position = uCurVP * w;
}
