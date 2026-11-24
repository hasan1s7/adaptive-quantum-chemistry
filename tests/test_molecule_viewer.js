/* Run: node tests/test_molecule_viewer.js. No browser, CDN, or node packages required.
 * Exercises display math and interaction/resource wiring. This is not a visual
 * browser-rendering test; the integrated lab also receives browser inspection.
 */
'use strict';
const assert = require('node:assert/strict');
const viewer = require('../aqc/web/molecule-viewer.js');

const source = {atoms: [
  {element: 'C', x: 4, y: 0, z: 0}, {element: 'O', x: 5.2, y: 0, z: 0},
  {element: 'H', x: 3, y: 0, z: 0}
]};
const original = JSON.stringify(source), geometry = viewer.normalizeGeometry(source);
assert.equal(JSON.stringify(source), original, 'original coordinates must remain unchanged');
assert.equal(geometry.bonds.length, 2);
assert.equal(geometry.bondsInferred, true);
assert(Math.abs(geometry.centered[1][0] - geometry.centered[0][0] - 1.2) < 1e-12);
const rotation = viewer.axisQuaternion([0, 1, 0], Math.PI / 2);
const rotated = viewer.rotateVector(rotation, [1, 0, 0]);
assert(Math.abs(rotated[0]) < 1e-12 && Math.abs(rotated[2] + 1) < 1e-12);
let repeated = [0, 0, 0, 1];
for (let i = 0; i < 1000; i++) repeated = viewer.quaternionMultiply(rotation, repeated);
assert(Math.abs(Math.hypot(...repeated) - 1) < 1e-12);
const front = viewer.projectPoint([1, 0, 0], [0, 0, 0, 1], [0, 0], 10, 800, 400);
const turned = viewer.projectPoint([1, 0, 0], rotation, [0, 0], 10, 800, 400);
assert(front.x > 400 && Math.abs(turned.x - 400) < 1e-10 && turned.z < front.z);
assert.throws(() => viewer.normalizeGeometry({atoms: [{element: 'C', x: NaN, y: 0, z: 0}]}), /coordinate/);
assert.throws(() => viewer.normalizeGeometry({...source, units: 'bohr'}), /ångströms/);
assert.throws(() => viewer.normalizeGeometry({...source, bonds: [{a: 0, b: 9}]}), /indices/);
assert.equal(viewer.normalizeGeometry({...source, bonds: []}).bondsInferred, false);

function harness(renderer) {
  const draws = [], frames = new Map(); let frameNumber = 0;
  const gl = new Proxy({
    VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4,
    ARRAY_BUFFER: 5, STATIC_DRAW: 6, COLOR_BUFFER_BIT: 8, DEPTH_BUFFER_BIT: 16,
    DEPTH_TEST: 17, LEQUAL: 18, CULL_FACE: 19, FLOAT: 20, TRIANGLES: 21, LINES: 22,
    createShader: () => ({}), createProgram: () => ({}), createBuffer: () => ({}),
    getShaderParameter: () => true, getProgramParameter: () => true,
    getAttribLocation: (_, name) => ['aPosition', 'aNormal', 'aColor'].indexOf(name),
    getUniformLocation: (_, name) => name,
    bufferData: (_, data) => {assert(data instanceof Float32Array); assert(data.every(Number.isFinite));},
    drawArrays: (mode, start, count) => draws.push({mode, start, count}),
    uniformMatrix4fv: (_, transpose, matrix) => {assert.equal(transpose, false); assert(matrix.every(Number.isFinite));}
  }, {get: (object, key) => key in object ? object[key] : () => {}});
  const ctx = new Proxy({createRadialGradient: () => ({addColorStop() {}})},
    {get: (object, key) => key in object ? object[key] : () => {}});
  class Node {
    constructor(tag) {this.tag = tag; this.style = {}; this.children = []; this.listeners = {}; this.attributes = {}; this.rect = {width: 600, height: 370, left: 0, top: 0};}
    appendChild(child) {this.children.push(child); child.parent = this; return child;}
    replaceChild(next, old) {this.children[this.children.indexOf(old)] = next; next.parent = this;}
    remove() {if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);}
    setAttribute(key, value) {this.attributes[key] = value;}
    addEventListener(key, fn) {(this.listeners[key] ||= []).push(fn);}
    removeEventListener(key, fn) {this.listeners[key] = (this.listeners[key] || []).filter(value => value !== fn);}
    dispatchEvent(event) {for (const fn of this.listeners[event.type] || []) fn(event);}
    getBoundingClientRect() {return this.rect;}
    querySelector(selector) {this.selectors ||= {}; return this.selectors[selector] ||= new Node('svg-child');}
    cloneNode() {const node = new Node(this.tag); node.style = {...this.style}; return node;}
    getContext(type) {return type.includes('webgl') ? (renderer === 'webgl' ? gl : null) : ctx;}
    focus() {this.focused = true;}
    setPointerCapture() {}
    releasePointerCapture() {}
  }
  const document = new Node('document'); document.createElement = tag => new Node(tag); document.hidden = false;
  global.document = document;
  global.getComputedStyle = () => ({position: 'relative'});
  global.devicePixelRatio = 2;
  global.requestAnimationFrame = callback => {frames.set(++frameNumber, callback); return frameNumber;};
  global.cancelAnimationFrame = id => frames.delete(id);
  global.ResizeObserver = class {constructor(callback) {this.callback = callback;} observe() {} disconnect() {}};
  global.CustomEvent = class {constructor(type, values) {this.type = type; Object.assign(this, values);}};
  const container = new Node('container'), externalOverlay = new Node('existing-loading-overlay');
  container.appendChild(externalOverlay);
  const api = viewer.create(container, {background: '#09131f'});
  const canvas = container.children[1].children[0];
  function event(type, values = {}) {canvas.dispatchEvent({type, preventDefault() {}, pointerId: 1, pointerType: 'mouse',
    button: 0, clientX: 100, clientY: 100, shiftKey: false, deltaMode: 0, ...values});}
  function frame(time) {const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback(time));}
  return {api, canvas, container, externalOverlay, event, frame, draws, gl};
}

for (const renderer of ['canvas2d', 'webgl']) {
  const h = harness(renderer), api = h.api;
  api.setGeometry(source, {molecule_id: 'unit-test-molecule', candidate_id: 'conformer-a'});
  h.frame(0);
  assert.equal(api.getState().renderer, renderer);
  assert.equal(api.getState().atomCount, 3);
  assert.equal(api.getState().bondCount, 2);
  assert.equal(h.canvas.width, 1200);
  assert.equal(h.canvas.height, 740);
  const before = api.getState().rotation;
  h.event('pointerdown'); h.event('pointermove', {clientX: 160, clientY: 120}); h.event('pointerup');
  assert.notDeepEqual(api.getState().rotation, before, 'pointer drag must orbit');
  h.event('pointerdown', {shiftKey: true}); h.event('pointermove', {clientX: 125, shiftKey: true}); h.event('pointerup');
  assert.notEqual(api.getState().pan[0], 0, 'Shift drag must pan');
  const zoom = api.getState().zoom;
  h.event('wheel', {deltaY: -100}); assert(api.getState().zoom > zoom, 'wheel must zoom');
  const keyboardRotation = api.getState().rotation;
  h.event('keydown', {key: 'ArrowRight'}); assert.notDeepEqual(api.getState().rotation, keyboardRotation);
  api.setHydrogens(false); assert.equal(api.getState().visibleAtomCount, 2);
  assert.equal(api.getState().visibleBondCount, 1);
  api.setStyle('wireframe'); h.frame(16);
  if (renderer === 'webgl') assert(h.draws.some(draw => draw.mode === h.gl.LINES && draw.count > 0));
  api.setStyle('spacefill'); h.frame(32);
  assert.equal(api.getState().visibleBondCount, 0);
  if (renderer === 'webgl') assert(h.draws.some(draw => draw.mode === h.gl.TRIANGLES && draw.count > 0));
  const sameMoleculeRotation = api.getState().rotation, sameMoleculeZoom = api.getState().zoom;
  const next = {atoms: source.atoms.map((atom, index) => ({...atom, z: index * .2}))};
  api.setGeometry(next, {molecule_id: 'unit-test-molecule', candidate_id: 'conformer-b'});
  assert.deepEqual(api.getState().rotation, sameMoleculeRotation, 'conformer changes preserve orbit');
  assert(Math.abs(api.getState().zoom - sameMoleculeZoom) < 1e-12);
  api.setAutoRotate(true); h.frame(64); const autoStart = api.getState().rotation; h.frame(96);
  assert.notDeepEqual(api.getState().rotation, autoStart, 'auto-rotation must advance');
  api.setAutoRotate(false); api.resetView();
  assert.equal(api.getState().zoom, 1); assert.deepEqual(api.getState().pan, [0, 0]);
  api.setGeometry(null); h.frame(112); assert.equal(api.getState().atomCount, 0);
  api.destroy(); assert.equal(api.getState().destroyed, true);
  assert.deepEqual(h.container.children, [h.externalOverlay], 'destroy must preserve external UI');
}
console.log('Molecule viewer smoke checks passed: data/math + Canvas/WebGL resources + orbit/pan/zoom/keyboard/styles/hydrogens/auto-rotation/conformer switching/cleanup.');
