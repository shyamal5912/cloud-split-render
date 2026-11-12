varying vec3 vWorld;
varying vec3 vNormal;
varying vec3 vColor;
attribute vec3 color;

void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vWorld = w.xyz;
  vNormal = normalize(mat3(modelMatrix) * normal);
  vColor = color;
  gl_Position = projectionMatrix * viewMatrix * w;
}
