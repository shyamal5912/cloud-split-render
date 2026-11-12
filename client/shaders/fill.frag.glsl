// Cheap disocclusion fill: the server frame at a coarse mip level, drawn
// behind the warped geometry so holes show blurred nearby colour, not black.
uniform sampler2D tColor;
uniform float uLod;
varying vec2 vUv;

void main() {
  gl_FragColor = texture2DLodEXT(tColor, vUv, uLod);
}
