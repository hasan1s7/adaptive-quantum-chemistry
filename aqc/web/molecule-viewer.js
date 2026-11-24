/* Offline coordinate viewer. Display geometry only; never an acquisition feature. */
(function (global) {
  'use strict';

  const ELEMENTS = {
    H: {color: [0.91, 0.95, 0.98], covalent: 0.31, vdw: 1.20, ball: 0.20},
    C: {color: [0.43, 0.66, 0.76], covalent: 0.76, vdw: 1.70, ball: 0.34},
    N: {color: [0.30, 0.48, 0.98], covalent: 0.71, vdw: 1.55, ball: 0.33},
    O: {color: [1.00, 0.34, 0.40], covalent: 0.66, vdw: 1.52, ball: 0.32},
    F: {color: [0.43, 0.86, 0.64], covalent: 0.57, vdw: 1.47, ball: 0.30},
    P: {color: [1.00, 0.63, 0.33], covalent: 1.07, vdw: 1.80, ball: 0.41},
    S: {color: [1.00, 0.83, 0.31], covalent: 1.05, vdw: 1.80, ball: 0.40},
    Cl: {color: [0.32, 0.80, 0.51], covalent: 1.02, vdw: 1.75, ball: 0.40},
    Br: {color: [0.73, 0.40, 0.30], covalent: 1.20, vdw: 1.85, ball: 0.44},
    I: {color: [0.65, 0.45, 0.85], covalent: 1.39, vdw: 1.98, ball: 0.48},
    B: {color: [0.90, 0.68, 0.58], covalent: 0.85, vdw: 1.92, ball: 0.34},
    Si: {color: [0.79, 0.66, 0.49], covalent: 1.11, vdw: 2.10, ball: 0.42},
    Na: {color: [0.66, 0.51, 0.90], covalent: 1.66, vdw: 2.27, ball: 0.47},
    Mg: {color: [0.54, 0.89, 0.59], covalent: 1.41, vdw: 1.73, ball: 0.43},
    Ca: {color: [0.56, 0.85, 0.52], covalent: 1.76, vdw: 2.31, ball: 0.48},
    Fe: {color: [0.85, 0.46, 0.33], covalent: 1.32, vdw: 2.00, ball: 0.44},
    Zn: {color: [0.69, 0.73, 0.78], covalent: 1.22, vdw: 2.10, ball: 0.44}
  };
  const UNKNOWN = {color: [0.76, 0.63, 0.88], covalent: 0.77, vdw: 1.80, ball: 0.36};
  const FOV = Math.PI / 4;
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const subtract = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const multiply = (a, scalar) => [a[0] * scalar, a[1] * scalar, a[2] * scalar];
  const length = a => Math.hypot(a[0], a[1], a[2]);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const normalize = a => multiply(a, 1 / (length(a) || 1));
  const isHydrogen = element => element === 'H' || element === 'D' || element === 'T';
  const elementInfo = element => ELEMENTS[isHydrogen(element) ? 'H' : element] || UNKNOWN;

  function quaternionMultiply(a, b) {
    const [ax, ay, az, aw] = a, [bx, by, bz, bw] = b;
    const q = [aw * bx + ax * bw + ay * bz - az * by,
      aw * by - ax * bz + ay * bw + az * bx,
      aw * bz + ax * by - ay * bx + az * bw,
      aw * bw - ax * bx - ay * by - az * bz];
    const norm = Math.hypot(...q) || 1;
    return q.map(v => v / norm);
  }
  function axisQuaternion(axis, angle) {
    const unit = normalize(axis), s = Math.sin(angle / 2);
    return [unit[0] * s, unit[1] * s, unit[2] * s, Math.cos(angle / 2)];
  }
  function rotateVector(q, v) {
    const u = [q[0], q[1], q[2]], uv = cross(u, v), uuv = cross(u, uv);
    return add(v, add(multiply(uv, 2 * q[3]), multiply(uuv, 2)));
  }
  function modelViewMatrix(q, pan, distance) {
    const [x, y, z, w] = q;
    return new Float32Array([
      1 - 2 * y * y - 2 * z * z, 2 * x * y + 2 * z * w, 2 * x * z - 2 * y * w, 0,
      2 * x * y - 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z + 2 * x * w, 0,
      2 * x * z + 2 * y * w, 2 * y * z - 2 * x * w, 1 - 2 * x * x - 2 * y * y, 0,
      pan[0], pan[1], -distance, 1
    ]);
  }
  function perspectiveMatrix(aspect, near, far) {
    const f = 1 / Math.tan(FOV / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0,
      0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  }
  function projectPoint(point, quaternion, pan, distance, width, height) {
    const view = rotateVector(quaternion, point);
    view[0] += pan[0]; view[1] += pan[1]; view[2] -= distance;
    if (view[2] >= -0.001) return null;
    const scale = height / (2 * Math.tan(FOV / 2) * -view[2]);
    return {x: width / 2 + view[0] * scale, y: height / 2 - view[1] * scale,
      z: view[2], scale, view};
  }

  function inferDisplayBonds(atoms) {
    const bonds = [];
    for (let a = 0; a < atoms.length; a++) {
      const first = atoms[a], ra = elementInfo(first.element).covalent;
      for (let b = a + 1; b < atoms.length; b++) {
        const second = atoms[b], rb = elementInfo(second.element).covalent;
        const distance = Math.hypot(first.x - second.x, first.y - second.y, first.z - second.z);
        // A display heuristic only. No bond orders, chemistry, or features are inferred.
        if (distance > 0.4 && distance <= 1.2 * (ra + rb) + 1e-9) bonds.push({a, b, order: 1});
      }
    }
    return bonds;
  }

  function normalizeGeometry(input) {
    if (!input || typeof input !== 'object') throw new TypeError('Geometry must contain actual atomic coordinates.');
    const suppliedAtoms = input.atoms || (Array.isArray(input.symbols) && Array.isArray(input.coordinates_angstrom)
      ? input.symbols.map((element, i) => ({element, x: input.coordinates_angstrom[i]?.[0],
        y: input.coordinates_angstrom[i]?.[1], z: input.coordinates_angstrom[i]?.[2]})) : null);
    if (!Array.isArray(suppliedAtoms) || !suppliedAtoms.length) throw new TypeError('Geometry has no atoms.');
    if (suppliedAtoms.length > 3000) throw new RangeError('This local viewer supports at most 3,000 atoms.');
    const atoms = suppliedAtoms.map((atom, index) => {
      const symbol = String(atom.element || atom.symbol || '').trim();
      if (!/^[A-Za-z]{1,2}$/.test(symbol)) throw new TypeError('Invalid element at atom ' + (index + 1));
      const element = symbol[0].toUpperCase() + symbol.slice(1).toLowerCase();
      const coordinates = [atom.x, atom.y, atom.z];
      if (!coordinates.every(value => typeof value === 'number' && Number.isFinite(value))) {
        throw new TypeError('Nonfinite or absent coordinate at atom ' + (index + 1));
      }
      return {element, x: coordinates[0], y: coordinates[1], z: coordinates[2], index};
    });
    const units = String(input.units || 'angstrom').toLowerCase();
    if (!['angstrom', 'angstroms', 'å', 'a'].includes(units)) throw new TypeError('Viewer coordinates must be in ångströms.');
    const bondsInferred = !Array.isArray(input.bonds);
    const bonds = bondsInferred ? inferDisplayBonds(atoms) : input.bonds.map((bond, index) => {
      if (!Number.isInteger(bond.a) || !Number.isInteger(bond.b) || bond.a === bond.b ||
          bond.a < 0 || bond.b < 0 || bond.a >= atoms.length || bond.b >= atoms.length) {
        throw new TypeError('Invalid atom indices in display bond ' + (index + 1));
      }
      return {a: bond.a, b: bond.b, order: bond.order === 2 || bond.order === 3 ? bond.order : 1};
    });
    const center = [0, 0, 0];
    for (const atom of atoms) {center[0] += atom.x; center[1] += atom.y; center[2] += atom.z;}
    for (let axis = 0; axis < 3; axis++) center[axis] /= atoms.length;
    const centered = atoms.map(atom => subtract([atom.x, atom.y, atom.z], center));
    const radius = Math.max(1, ...centered.map((point, i) => length(point) + elementInfo(atoms[i].element).vdw));
    return {atoms, bonds, center, centered, radius, bondsInferred, units: 'angstrom'};
  }

  const VERTEX_SHADER = `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    attribute vec3 aColor;
    uniform mat4 uProjection;
    uniform mat4 uModelView;
    varying vec3 vNormal;
    varying vec3 vColor;
    varying vec3 vViewPosition;
    void main() {
      vec4 view = uModelView * vec4(aPosition, 1.0);
      vViewPosition = view.xyz;
      vNormal = mat3(uModelView) * aNormal;
      vColor = aColor;
      gl_Position = uProjection * view;
    }`;
  const FRAGMENT_SHADER = `
    precision mediump float;
    varying vec3 vNormal;
    varying vec3 vColor;
    varying vec3 vViewPosition;
    uniform float uUnlit;
    void main() {
      vec3 n = normalize(vNormal);
      vec3 light = normalize(vec3(0.35, 0.60, 1.0));
      vec3 eye = normalize(-vViewPosition);
      float diffuse = max(dot(n, light), 0.0);
      float highlight = pow(max(dot(n, normalize(light + eye)), 0.0), 42.0);
      vec3 shaded = vColor * (0.31 + 0.69 * diffuse) + vec3(0.30 * highlight);
      gl_FragColor = vec4(mix(shaded, vColor, uUnlit), 1.0);
    }`;

  function createGL(gl) {
    function shader(type, source) {
      const object = gl.createShader(type);
      gl.shaderSource(object, source); gl.compileShader(object);
      if (!gl.getShaderParameter(object, gl.COMPILE_STATUS)) {
        const message = gl.getShaderInfoLog(object); gl.deleteShader(object); throw new Error(message);
      }
      return object;
    }
    const vertex = shader(gl.VERTEX_SHADER, VERTEX_SHADER), fragment = shader(gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    const program = gl.createProgram();
    gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
    gl.deleteShader(vertex); gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    return {gl, program, mesh: gl.createBuffer(), lines: gl.createBuffer(), meshCount: 0, lineCount: 0,
      attributes: ['aPosition', 'aNormal', 'aColor'].map(name => gl.getAttribLocation(program, name)),
      projection: gl.getUniformLocation(program, 'uProjection'), modelView: gl.getUniformLocation(program, 'uModelView'),
      unlit: gl.getUniformLocation(program, 'uUnlit')};
  }
  function vertex(target, position, normal, color) {target.push(...position, ...normal, ...color);}
  function sphere(target, center, radius, color) {
    const rings = 9, segments = 14;
    const normal = (theta, phi) => [Math.sin(theta) * Math.cos(phi), Math.cos(theta), Math.sin(theta) * Math.sin(phi)];
    for (let ring = 0; ring < rings; ring++) {
      const theta0 = ring * Math.PI / rings, theta1 = (ring + 1) * Math.PI / rings;
      for (let segment = 0; segment < segments; segment++) {
        const phi0 = segment * 2 * Math.PI / segments, phi1 = (segment + 1) * 2 * Math.PI / segments;
        const a = normal(theta0, phi0), b = normal(theta1, phi0), c = normal(theta1, phi1), d = normal(theta0, phi1);
        for (const n of [a, b, c, a, c, d]) vertex(target, add(center, multiply(n, radius)), n, color);
      }
    }
  }
  function perpendicular(direction) {
    return normalize(cross(direction, Math.abs(direction[1]) < .9 ? [0, 1, 0] : [1, 0, 0]));
  }
  function cylinder(target, start, end, radius, color) {
    const direction = normalize(subtract(end, start)), u = perpendicular(direction), v = cross(direction, u);
    const side = angle => add(multiply(u, Math.cos(angle)), multiply(v, Math.sin(angle)));
    for (let i = 0; i < 9; i++) {
      const n0 = side(i * Math.PI * 2 / 9), n1 = side((i + 1) * Math.PI * 2 / 9);
      const a = add(start, multiply(n0, radius)), b = add(end, multiply(n0, radius));
      const c = add(end, multiply(n1, radius)), d = add(start, multiply(n1, radius));
      for (const [point, normal] of [[a, n0], [b, n0], [c, n1], [a, n0], [c, n1], [d, n1]]) vertex(target, point, normal, color);
    }
  }
  function colorCSS(color, factor = 1) {return 'rgb(' + color.map(v => Math.round(clamp(v * factor, 0, 1) * 255)).join(',') + ')';}
  function backgroundRGB(value) {
    const hex = String(value || '#09131f').replace('#', '');
    if (!/^[a-f0-9]{6}$/i.test(hex)) return [9 / 255, 19 / 255, 31 / 255];
    return [0, 2, 4].map(start => parseInt(hex.slice(start, start + 2), 16) / 255);
  }

  function create(container, options = {}) {
    if (typeof container === 'string') container = document.querySelector(container);
    if (!container || typeof container.appendChild !== 'function') throw new TypeError('A viewer container is required.');
    if (global.getComputedStyle && global.getComputedStyle(container).position === 'static') container.style.position = 'relative';
    const wrapper = document.createElement('div');
    wrapper.className = 'aqc-molecule-viewer';
    Object.assign(wrapper.style, {position: 'absolute', inset: '0', overflow: 'hidden', borderRadius: 'inherit', background: options.background || '#09131f'});
    const canvas = document.createElement('canvas');
    Object.assign(canvas.style, {display: 'block', width: '100%', height: '100%', touchAction: 'none', cursor: 'grab', outlineOffset: '-4px'});
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', options.ariaLabel || 'Interactive molecular geometry. Drag to rotate, Shift drag to pan, scroll or pinch to zoom. Arrow keys rotate; plus and minus zoom; R resets.');
    wrapper.appendChild(canvas);
    const status = document.createElement('div');
    Object.assign(status.style, {position: 'absolute', right: '12px', bottom: '12px', maxWidth: 'calc(100% - 105px)',
      padding: '5px 9px', border: '1px solid rgba(178,208,231,.20)', borderRadius: '7px', background: 'rgba(5,13,23,.72)',
      color: '#b9d1df', font: '14px/1.4 system-ui,sans-serif', pointerEvents: 'none', textAlign: 'right'});
    wrapper.appendChild(status);
    const empty = document.createElement('div');
    Object.assign(empty.style, {position: 'absolute', inset: '0', display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '30px', color: '#a8c2d5', textAlign: 'center', font: '16px/1.5 system-ui,sans-serif', pointerEvents: 'none'});
    empty.textContent = 'Select a conformer to inspect its actual coordinates.';
    wrapper.appendChild(empty);
    const tooltip = document.createElement('div');
    Object.assign(tooltip.style, {position: 'absolute', display: 'none', padding: '8px 11px', color: '#edf7fc',
      background: 'rgba(8,24,39,.94)', border: '1px solid #47617a', borderRadius: '7px', font: '14px/1.5 system-ui,sans-serif',
      whiteSpace: 'pre-line', pointerEvents: 'none', maxWidth: '230px'});
    wrapper.appendChild(tooltip);
    const axis = document.createElement('div');
    Object.assign(axis.style, {position: 'absolute', bottom: '7px', left: '6px', width: '75px', height: '75px', pointerEvents: 'none'});
    axis.innerHTML = '<svg viewBox="0 0 75 75" width="75" height="75" aria-hidden="true">' +
      ['#f48d8d', '#8bddad', '#94bbff'].map((color, i) => '<line data-axis="' + i + '" x1="36" y1="37" stroke="' + color + '" stroke-width="2"/>' +
        '<text data-axis-label="' + i + '" fill="' + color + '" font-family="system-ui,sans-serif" font-size="14" text-anchor="middle">' + 'XYZ'[i] + '</text>').join('') + '</svg>';
    wrapper.appendChild(axis);
    container.appendChild(wrapper); // Keep the lab's own loading overlay and controls.

    const initialRotation = quaternionMultiply(axisQuaternion([1, 0, 0], -.22), axisQuaternion([0, 1, 0], .40));
    let geometry = null, metadata = {}, width = 1, height = 1, dpr = 1;
    let quaternion = initialRotation.slice(), pan = [0, 0], baseDistance = 10, distance = 10;
    let style = 'ball-stick', hydrogens = options.hydrogens !== false, autoRotate = Boolean(options.autoRotate);
    let renderer = 'canvas2d', glState = null, context2d = null, destroyed = false, contextLost = false;
    let request = null, previousFrame = null, dirty = true, meshDirty = true;
    const pointers = new Map(), listeners = [];
    const background = backgroundRGB(options.background);

    function listen(target, event, handler, settings) {target.addEventListener(event, handler, settings); listeners.push([target, event, handler, settings]);}
    function reportError(error) {if (typeof options.onError === 'function') options.onError(error);}
    try {
      const gl = canvas.getContext('webgl', {alpha: false, antialias: true, depth: true, powerPreference: 'low-power'}) ||
        canvas.getContext('experimental-webgl', {alpha: false, antialias: true, depth: true});
      if (gl) {glState = createGL(gl); renderer = 'webgl';}
    } catch (error) {reportError(error);}
    let activeCanvas = canvas;
    if (!glState) {
      // A canvas that already acquired a failed WebGL context cannot acquire 2D.
      context2d = canvas.getContext('2d');
      if (!context2d) {
        activeCanvas = canvas.cloneNode(false);
        wrapper.replaceChild(activeCanvas, canvas);
        context2d = activeCanvas.getContext('2d');
      }
      if (!context2d) {wrapper.remove(); throw new Error('Neither WebGL nor Canvas 2D is available.');}
    }

    function visibleAtom(atom) {return hydrogens || !isHydrogen(atom.element);}
    function atomRadius(atom) {const info = elementInfo(atom.element); return style === 'spacefill' ? info.vdw : style === 'wireframe' ? .10 : info.ball;}
    function getState() {
      return {renderer, contextLost, atomCount: geometry?.atoms.length || 0, bondCount: geometry?.bonds.length || 0,
        visibleAtomCount: geometry ? geometry.atoms.filter(visibleAtom).length : 0,
        visibleBondCount: geometry && style !== 'spacefill' ? geometry.bonds.filter(b => visibleAtom(geometry.atoms[b.a]) && visibleAtom(geometry.atoms[b.b])).length : 0,
        bondsInferred: Boolean(geometry?.bondsInferred || metadata.bonds_inferred),
        bondsAreDisplayOnly: true, units: 'angstrom', molecule_id: metadata.molecule_id ?? null,
        candidate_id: metadata.candidate_id ?? null, label: metadata.label ?? '',
        rotation: quaternion.slice(), pan: pan.slice(), zoom: baseDistance / distance,
        style, hydrogens, autoRotate, width, height, pixelRatio: dpr, destroyed};
    }
    function emit() {
      const state = getState();
      for (const callback of new Set([options.onStateChange, options.onChange])) {
        if (typeof callback === 'function') {try {callback(state);} catch (error) {reportError(error);}}
      }
      if (typeof global.CustomEvent === 'function') container.dispatchEvent(new CustomEvent('aqc-viewer-change', {detail: state, bubbles: true}));
    }
    function updateStatus() {
      const mode = renderer === 'webgl' ? 'WebGL · true 3D' : 'Projected 3D · Canvas fallback';
      status.textContent = contextLost ? 'Graphics context interrupted · restoring…' : mode + (geometry && (geometry.bondsInferred || metadata.bonds_inferred) ? ' · display-only inferred bonds' : '');
      status.title = 'Coordinates are the saved conformer coordinates in ångströms. Display bonds are not quantum calculations or acquisition features.';
    }
    function invalidate(rebuild = false) {
      if (destroyed) return;
      dirty = true; meshDirty = meshDirty || rebuild;
      if (request === null) request = global.requestAnimationFrame(frame);
    }
    function fitDistance() {
      const narrowHalfAngle = Math.atan(Math.tan(FOV / 2) * Math.min(1, width / height));
      return (geometry?.radius || 1) / Math.sin(narrowHalfAngle) * 1.12;
    }
    function resize() {
      if (destroyed) return;
      const rect = wrapper.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      const nextDpr = clamp(global.devicePixelRatio || 1, 1, options.maxPixelRatio || 2);
      const nextWidth = Math.max(1, rect.width), nextHeight = Math.max(1, rect.height);
      if (nextWidth !== width || nextHeight !== height || dpr !== nextDpr) {
        const currentZoom = baseDistance / distance;
        width = nextWidth; height = nextHeight; dpr = nextDpr;
        activeCanvas.width = Math.max(1, Math.round(width * dpr));
        activeCanvas.height = Math.max(1, Math.round(height * dpr));
        if (geometry) {baseDistance = fitDistance(); distance = baseDistance / currentZoom;}
        invalidate();
      }
    }
    function rebuildMesh() {
      if (!glState || contextLost) return;
      const mesh = [], lines = [];
      if (geometry) {
        for (let i = 0; i < geometry.atoms.length; i++) {
          const atom = geometry.atoms[i];
          if (visibleAtom(atom)) sphere(mesh, geometry.centered[i], atomRadius(atom), elementInfo(atom.element).color);
        }
        if (style !== 'spacefill') for (const bond of geometry.bonds) {
          const first = geometry.atoms[bond.a], second = geometry.atoms[bond.b];
          if (!visibleAtom(first) || !visibleAtom(second)) continue;
          const a = geometry.centered[bond.a], b = geometry.centered[bond.b];
          const normal = perpendicular(normalize(subtract(b, a)));
          const offsets = bond.order === 3 ? [-.15, 0, .15] : bond.order === 2 ? [-.10, .10] : [0];
          for (const offset of offsets) {
            const aa = add(a, multiply(normal, offset)), bb = add(b, multiply(normal, offset)), middle = multiply(add(aa, bb), .5);
            for (const [start, end, color] of [[aa, middle, elementInfo(first.element).color], [middle, bb, elementInfo(second.element).color]]) {
              if (style === 'wireframe') {vertex(lines, start, [0, 0, 1], color); vertex(lines, end, [0, 0, 1], color);}
              else cylinder(mesh, start, end, .075, color);
            }
          }
        }
      }
      const gl = glState.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, glState.mesh); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(mesh), gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, glState.lines); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lines), gl.STATIC_DRAW);
      glState.meshCount = mesh.length / 9; glState.lineCount = lines.length / 9;
      meshDirty = false;
    }
    function drawWebGL() {
      if (!glState || contextLost) return;
      if (meshDirty) rebuildMesh();
      const gl = glState.gl;
      gl.viewport(0, 0, activeCanvas.width, activeCanvas.height);
      gl.clearColor(...background, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.disable(gl.CULL_FACE);
      gl.useProgram(glState.program);
      const radius = geometry?.radius || 1, near = Math.max(.01, distance - radius * 2.5), far = distance + radius * 4 + 5;
      gl.uniformMatrix4fv(glState.projection, false, perspectiveMatrix(width / height, near, far));
      gl.uniformMatrix4fv(glState.modelView, false, modelViewMatrix(quaternion, pan, distance));
      function draw(buffer, count, primitive, unlit) {
        if (!count) return;
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        glState.attributes.forEach((location, index) => {
          gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 36, index * 12);
        });
        gl.uniform1f(glState.unlit, unlit); gl.drawArrays(primitive, 0, count);
      }
      draw(glState.mesh, glState.meshCount, gl.TRIANGLES, 0);
      draw(glState.lines, glState.lineCount, gl.LINES, 1);
    }
    function drawCanvas() {
      const ctx = context2d;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = colorCSS(background); ctx.fillRect(0, 0, width, height);
      if (!geometry) return;
      const projected = geometry.centered.map(point => projectPoint(point, quaternion, pan, distance, width, height));
      const objects = [];
      if (style !== 'spacefill') for (const bond of geometry.bonds) {
        const first = geometry.atoms[bond.a], second = geometry.atoms[bond.b], a = projected[bond.a], b = projected[bond.b];
        if (!a || !b || !visibleAtom(first) || !visibleAtom(second)) continue;
        objects.push({type: 'bond', a, b, first, second, order: bond.order, z: (a.z + b.z) / 2});
      }
      for (let i = 0; i < geometry.atoms.length; i++) if (visibleAtom(geometry.atoms[i]) && projected[i]) {
        objects.push({type: 'atom', atom: geometry.atoms[i], position: projected[i], z: projected[i].z});
      }
      objects.sort((a, b) => a.z - b.z);
      for (const object of objects) {
        if (object.type === 'bond') {
          const {a, b, first, second} = object, dx = b.x - a.x, dy = b.y - a.y;
          const norm = Math.hypot(dx, dy) || 1, offsets = object.order === 3 ? [-3, 0, 3] : object.order === 2 ? [-2, 2] : [0];
          for (const offset of offsets) {
            const ox = -dy / norm * offset, oy = dx / norm * offset;
            ctx.lineWidth = style === 'wireframe' ? 1.4 : Math.max(1.5, .15 * (a.scale + b.scale) / 2);
            ctx.lineCap = 'round';
            for (const [start, end, color] of [[a, {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}, elementInfo(first.element).color],
              [{x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}, b, elementInfo(second.element).color]]) {
              ctx.strokeStyle = colorCSS(color); ctx.beginPath(); ctx.moveTo(start.x + ox, start.y + oy); ctx.lineTo(end.x + ox, end.y + oy); ctx.stroke();
            }
          }
        } else {
          const {atom, position: p} = object, radius = Math.max(1, atomRadius(atom) * p.scale), color = elementInfo(atom.element).color;
          if (p.x + radius < 0 || p.y + radius < 0 || p.x - radius > width || p.y - radius > height) continue;
          const gradient = ctx.createRadialGradient(p.x - radius * .32, p.y - radius * .35, radius * .02, p.x, p.y, radius);
          gradient.addColorStop(0, colorCSS(color.map(v => v * .65 + .35)));
          gradient.addColorStop(.4, colorCSS(color)); gradient.addColorStop(1, colorCSS(color, .38));
          ctx.fillStyle = gradient; ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2); ctx.fill();
        }
      }
    }
    function drawAxes() {
      [[1, 0, 0], [0, 1, 0], [0, 0, 1]].forEach((vector, index) => {
        const point = rotateVector(quaternion, vector), x = 36 + point[0] * 23, y = 37 - point[1] * 23;
        const line = axis.querySelector('[data-axis="' + index + '"]'), label = axis.querySelector('[data-axis-label="' + index + '"]');
        line.setAttribute('x2', x); line.setAttribute('y2', y); line.setAttribute('opacity', point[2] < -.2 ? '.55' : '1');
        label.setAttribute('x', 36 + point[0] * 30); label.setAttribute('y', 42 - point[1] * 30);
      });
    }
    function frame(time) {
      request = null;
      if (destroyed) return;
      const elapsed = previousFrame === null ? 0 : Math.min(.05, (time - previousFrame) / 1000);
      previousFrame = time;
      if (autoRotate && pointers.size === 0 && geometry && !document.hidden) {
        quaternion = quaternionMultiply(axisQuaternion([0, 1, 0], elapsed * .38), quaternion); dirty = true;
      }
      if (dirty) {if (glState) drawWebGL(); else drawCanvas(); drawAxes(); dirty = false;}
      if (autoRotate && geometry && !document.hidden && !contextLost) request = global.requestAnimationFrame(frame);
      else previousFrame = null;
    }
    function orbit(dx, dy) {
      quaternion = quaternionMultiply(axisQuaternion([1, 0, 0], dy * .008),
        quaternionMultiply(axisQuaternion([0, 1, 0], dx * .008), quaternion));
    }
    function panPixels(dx, dy) {
      const units = 2 * distance * Math.tan(FOV / 2) / Math.max(1, height);
      pan[0] += dx * units; pan[1] -= dy * units;
    }
    function zoomBy(factor) {distance = clamp(distance * factor, baseDistance * .15, baseDistance * 8);}
    function hover(event) {
      if (!geometry || event.pointerType === 'touch') return;
      const rect = activeCanvas.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
      let hit = null;
      for (let i = 0; i < geometry.atoms.length; i++) {
        const atom = geometry.atoms[i]; if (!visibleAtom(atom)) continue;
        const projected = projectPoint(geometry.centered[i], quaternion, pan, distance, width, height);
        if (projected && Math.hypot(projected.x - x, projected.y - y) <= Math.max(7, atomRadius(atom) * projected.scale)
            && (!hit || projected.z > hit.z)) hit = {atom, z: projected.z};
      }
      if (!hit) {tooltip.style.display = 'none'; return;}
      const atom = hit.atom;
      tooltip.textContent = atom.element + ' · atom ' + (atom.index + 1) + '\n' +
        [atom.x, atom.y, atom.z].map(v => v.toFixed(3)).join(', ') + ' Å';
      tooltip.style.display = 'block'; tooltip.style.left = clamp(x + 15, 5, Math.max(5, width - 230)) + 'px';
      tooltip.style.top = clamp(y + 15, 5, Math.max(5, height - 80)) + 'px';
    }
    function onPointerDown(event) {
      if (event.button > 2) return;
      event.preventDefault(); activeCanvas.focus({preventScroll: true});
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY, pan: event.shiftKey || event.button !== 0});
      try {activeCanvas.setPointerCapture(event.pointerId);} catch (_) { /* Browser may cancel an ended touch. */ }
      activeCanvas.style.cursor = 'grabbing'; tooltip.style.display = 'none';
    }
    function onPointerMove(event) {
      if (!pointers.has(event.pointerId)) {hover(event); return;}
      event.preventDefault();
      const old = pointers.get(event.pointerId), before = [...pointers.values()];
      pointers.set(event.pointerId, {...old, x: event.clientX, y: event.clientY});
      const after = [...pointers.values()];
      if (after.length >= 2) {
        const oldDistance = Math.hypot(before[0].x - before[1].x, before[0].y - before[1].y);
        const newDistance = Math.hypot(after[0].x - after[1].x, after[0].y - after[1].y);
        if (oldDistance > 2 && newDistance > 2) zoomBy(oldDistance / newDistance);
        panPixels((after[0].x + after[1].x - before[0].x - before[1].x) / 2,
          (after[0].y + after[1].y - before[0].y - before[1].y) / 2);
      } else if (old.pan || event.shiftKey) panPixels(event.clientX - old.x, event.clientY - old.y);
      else orbit(event.clientX - old.x, event.clientY - old.y);
      invalidate(); emit();
    }
    function onPointerEnd(event) {
      pointers.delete(event.pointerId);
      if (!pointers.size) activeCanvas.style.cursor = 'grab';
      try {activeCanvas.releasePointerCapture(event.pointerId);} catch (_) { /* Already released. */ }
      invalidate();
    }
    function resetView() {
      quaternion = initialRotation.slice(); pan = [0, 0]; distance = baseDistance;
      invalidate(); emit(); return api;
    }
    function setStyle(value) {
      const normalized = ({ballstick: 'ball-stick', 'ball-and-stick': 'ball-stick', 'space-filling': 'spacefill'}[value] || value);
      if (!['ball-stick', 'wireframe', 'spacefill'].includes(normalized)) throw new TypeError('Unknown display style: ' + value);
      style = normalized; invalidate(true); emit(); return api;
    }
    function setHydrogens(value) {hydrogens = Boolean(value); invalidate(true); emit(); return api;}
    function setAutoRotate(value) {autoRotate = Boolean(value); previousFrame = null; invalidate(); emit(); return api;}
    function setGeometry(input, details = {}) {
      if (destroyed) throw new Error('Viewer has been destroyed.');
      if (input === null) {
        geometry = null; metadata = {}; empty.style.display = 'flex'; tooltip.style.display = 'none';
        updateStatus(); invalidate(true); emit(); return api;
      }
      const next = normalizeGeometry(input), previousZoom = baseDistance / distance;
      const sameMolecule = geometry && details.molecule_id && details.molecule_id === metadata.molecule_id;
      geometry = next; metadata = {...details};
      baseDistance = fitDistance();
      if (sameMolecule) distance = baseDistance / previousZoom;
      else {distance = baseDistance; quaternion = initialRotation.slice(); pan = [0, 0];}
      empty.style.display = 'none'; tooltip.style.display = 'none'; updateStatus();
      resize(); invalidate(true); emit(); return api;
    }
    function destroy() {
      if (destroyed) return;
      destroyed = true;
      if (request !== null) global.cancelAnimationFrame(request);
      if (observer) observer.disconnect();
      for (const [target, event, handler, settings] of listeners) target.removeEventListener(event, handler, settings);
      if (glState && !contextLost) {glState.gl.deleteBuffer(glState.mesh); glState.gl.deleteBuffer(glState.lines); glState.gl.deleteProgram(glState.program);}
      pointers.clear(); wrapper.remove();
    }

    listen(activeCanvas, 'pointerdown', onPointerDown);
    listen(activeCanvas, 'pointermove', onPointerMove);
    listen(activeCanvas, 'pointerup', onPointerEnd);
    listen(activeCanvas, 'pointercancel', onPointerEnd);
    listen(activeCanvas, 'pointerleave', () => {tooltip.style.display = 'none';});
    listen(activeCanvas, 'contextmenu', event => event.preventDefault());
    listen(activeCanvas, 'wheel', event => {
      event.preventDefault(); const delta = event.deltaY * (event.deltaMode === 1 ? 20 : event.deltaMode === 2 ? height : 1);
      zoomBy(Math.exp(clamp(delta, -500, 500) * .0014)); invalidate(); emit();
    }, {passive: false});
    listen(activeCanvas, 'dblclick', event => {event.preventDefault(); resetView();});
    listen(activeCanvas, 'keydown', event => {
      const arrows = {ArrowLeft: [-15, 0], ArrowRight: [15, 0], ArrowUp: [0, -15], ArrowDown: [0, 15]};
      if (arrows[event.key]) {const delta = arrows[event.key]; if (event.shiftKey) panPixels(...delta); else orbit(...delta);}
      else if (event.key === '+' || event.key === '=') zoomBy(.86);
      else if (event.key === '-' || event.key === '_') zoomBy(1 / .86);
      else if (event.key.toLowerCase() === 'r' || event.key === 'Home') {event.preventDefault(); resetView(); return;}
      else if (event.key.toLowerCase() === 'h') {event.preventDefault(); setHydrogens(!hydrogens); return;}
      else if (event.key.toLowerCase() === 'a' || event.key === ' ') {event.preventDefault(); setAutoRotate(!autoRotate); return;}
      else if (['1', '2', '3'].includes(event.key)) {event.preventDefault(); setStyle(['ball-stick', 'wireframe', 'spacefill'][Number(event.key) - 1]); return;}
      else return;
      event.preventDefault(); invalidate(); emit();
    });
    listen(document, 'visibilitychange', () => {previousFrame = null; invalidate();});
    if (glState) {
      listen(activeCanvas, 'webglcontextlost', event => {event.preventDefault(); contextLost = true; updateStatus(); emit();});
      listen(activeCanvas, 'webglcontextrestored', () => {
        try {glState = createGL(glState.gl); contextLost = false; updateStatus(); invalidate(true); emit();}
        catch (error) {reportError(error); status.textContent = 'Graphics restore failed · reload this local dashboard';}
      });
    }
    const observer = typeof global.ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
    if (observer) observer.observe(wrapper); else listen(global, 'resize', resize);
    const api = {setGeometry, resetView, setStyle, setHydrogens, setAutoRotate, resize, destroy, getState};
    updateStatus(); resize();
    if (options.style) setStyle(options.style);
    invalidate(); emit();
    return api;
  }

  const publicAPI = Object.freeze({version: '1.0.0', create});
  global.AQCMoleculeViewer = publicAPI;
  if (typeof module === 'object' && module.exports) {
    module.exports = {create, normalizeGeometry, inferDisplayBonds, quaternionMultiply, axisQuaternion,
      rotateVector, modelViewMatrix, perspectiveMatrix, projectPoint};
  }
})(typeof window !== 'undefined' ? window : globalThis);
