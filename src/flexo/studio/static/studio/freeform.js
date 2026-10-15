// Shapes drawn where they are put -- lines, arrows, boxes, callouts, braces and measures --
// as flexo.freeform draws them, here in the page: an editor draws a shape as it is dragged,
// sized or bent with this, and what it draws is what the slide (or figure) saves and draws.
// A test runs both on the same shapes and keeps them the same, number for number.
//
// Nothing here touches the page: a shape is a mapping (as written in its document), its
// geometry plain numbers, its drawing SVG markup -- so the same code draws an icon, a preview
// on a slide, and the test's shapes in Node.

export const LINES = ["line", "arrow", "double-arrow", "curved-arrow", "elbow", "arc", "brace", "bracket", "dimension", "scale-bar"];
export const TRACED = ["polyline", "pen"];
export const BOXED = [
  "rectangle", "rounded-rectangle", "ellipse", "triangle", "right-triangle", "diamond", "polygon", "star",
  "parallelogram", "trapezoid", "arrow-right", "arrow-left", "arrow-up", "arrow-down", "arrow-left-right",
  "chevron", "plus", "cross", "check", "cloud", "bubble", "highlight", "ring", "inset",
];
export const KINDS = [...LINES, ...TRACED, ...BOXED, "text"];

export const SECTIONS = [
  ["Lines", ["line", "arrow", "double-arrow", "curved-arrow", "elbow", "arc", "polyline", "pen"]],
  ["Shapes", ["rectangle", "rounded-rectangle", "ellipse", "triangle", "right-triangle", "diamond", "parallelogram",
    "trapezoid", "polygon", "star", "plus", "cross", "check", "cloud"]],
  ["Arrows & Callouts", ["arrow-right", "arrow-left", "arrow-up", "arrow-down", "arrow-left-right", "chevron", "bubble"]],
  ["Brackets & Measures", ["brace", "bracket", "dimension", "scale-bar"]],
  ["Highlights", ["highlight", "ring"]],
  ["Text", ["text"]],
];

export const LABELS = {
  line: "Line", arrow: "Arrow", "double-arrow": "Double Arrow", "curved-arrow": "Curved Arrow",
  elbow: "Elbow Connector", arc: "Arc", polyline: "Polyline", pen: "Pen", rectangle: "Rectangle",
  "rounded-rectangle": "Rounded Rectangle", ellipse: "Oval", triangle: "Triangle",
  "right-triangle": "Right Triangle", diamond: "Diamond", polygon: "Polygon", star: "Star",
  parallelogram: "Parallelogram", trapezoid: "Trapezoid", "arrow-right": "Right Arrow",
  "arrow-left": "Left Arrow", "arrow-up": "Up Arrow", "arrow-down": "Down Arrow",
  "arrow-left-right": "Left-Right Arrow", chevron: "Chevron", plus: "Plus", cross: "Cross",
  check: "Check Mark", cloud: "Cloud", bubble: "Speech Bubble", brace: "Brace", bracket: "Bracket",
  dimension: "Dimension Line", "scale-bar": "Scale Bar", highlight: "Highlight", ring: "Highlight Ring",
  text: "Text Box", inset: "Zoom Inset", group: "Group",
};

export const HEADS = ["none", "triangle", "open", "stealth", "dot", "circle", "bar", "diamond"];
export const DASHES = ["solid", "dashed", "dotted"];

const LINE = { fill: "none", line: "accent", line_width: 2, cap: "round", join: "round" };
const CLOSED = { fill: "accent-fill", line: "accent", line_width: 1.5, cap: "butt", join: "miter" };
const SOLID = { fill: "accent", line: "none", line_width: 1.5, cap: "butt", join: "miter" };
const MEASURE = { fill: "none", line: "ink", line_width: 1.5, cap: "butt", join: "miter" };

export const STYLES = {
  line: LINE,
  arrow: { ...LINE, end: "triangle" },
  "double-arrow": { ...LINE, start: "triangle", end: "triangle" },
  "curved-arrow": { ...LINE, end: "triangle" },
  elbow: { ...LINE, end: "triangle", join: "miter" },
  arc: LINE,
  polyline: LINE,
  pen: LINE,
  ...Object.fromEntries(BOXED.map((kind) => [kind, CLOSED])),
  check: SOLID,
  cross: SOLID,
  highlight: { fill: "accent", fill_opacity: 0.25, line: "none", line_width: 1.5, cap: "butt", join: "miter" },
  ring: { fill: "none", line: "accent", line_width: 3, cap: "butt", join: "miter" },
  brace: { ...MEASURE, cap: "round", join: "round" },
  bracket: MEASURE,
  dimension: { ...MEASURE, line_width: 1.25, start: "bar", end: "bar" },
  "scale-bar": { ...MEASURE, line_width: 4 },
  text: { fill: "none", line: "none", line_width: 1.5, cap: "butt", join: "miter" },
  // A zoom inset (insets.js): on the page, outlined, its label at its top left.
  inset: { fill: "paper", line: "accent", line_width: 1.5, cap: "butt", join: "miter", align: "start", valign: "top", bold: true, padding: 4 },
};

export const PARAMETERS = {
  "curved-arrow": { bend: 0.25, lean: 0 },
  arc: { bend: 0.3 },
  elbow: { elbow: 0.5, route: "across" },
  brace: { depth: 16, curl: 0.5, tip: 0.5 },
  bracket: { depth: 12, curl: 0 },
  rectangle: { corner: 0 },
  "rounded-rectangle": { corner: 12 },
  highlight: { corner: 3 },
  triangle: { apex: 0.5 },
  polygon: { sides: 6 },
  star: { tips: 5, ratio: 0.38 },
  parallelogram: { slant: 0.25 },
  trapezoid: { inset: 0.25 },
  ...Object.fromEntries(["arrow-right", "arrow-left", "arrow-up", "arrow-down", "arrow-left-right"].map((kind) => [kind, { shaft: 0.5, head: 0.5 }])),
  chevron: { point: 0.5 },
  plus: { arm: 0.25 },
  cross: { arm: 0.2 },
  bubble: { body: "rounded", corner: 10 },
  polyline: { closed: false },
  pen: { closed: false },
};

export const SIZES = {
  ...Object.fromEntries(BOXED.map((kind) => [kind, [160, 100]])),
  ellipse: [120, 120], ring: [140, 100], polygon: [120, 120], star: [120, 120],
  diamond: [120, 120], triangle: [120, 104], "right-triangle": [120, 104],
  plus: [100, 100], cross: [100, 100], check: [100, 80], chevron: [100, 80],
  "arrow-up": [80, 140], "arrow-down": [80, 140], highlight: [200, 40], cloud: [180, 120],
  text: [240, 40], inset: [200, 150],
  ...Object.fromEntries(LINES.map((kind) => [kind, [160, 0]])),
  brace: [0, 160], bracket: [0, 160],
  ...Object.fromEntries(TRACED.map((kind) => [kind, [160, 0]])),
};

// How a kind is placed: from one point to another, through points, in a box, words, or a group.
export function family(kind) {
  if (LINES.includes(kind)) return "line";
  if (TRACED.includes(kind)) return "points";
  if (kind === "text") return "text";
  if (kind === "group") return "group";
  return "box";
}
export const isClosed = (spec) => BOXED.includes(spec?.kind) || (TRACED.includes(spec?.kind) && Boolean(spec.closed));

export function defaults(kind) {
  const style = { fill: "none", fill_opacity: 1, line: "accent", line_width: 2, dash: "solid", cap: "butt", join: "miter",
    start: "none", end: "none", head_size: 1, shadow: false, opacity: 1, rotate: 0, flip: null, text: "", font_size: null,
    bold: false, italic: false, colour: null, font: null, padding: 5 };
  const boxed = BOXED.includes(kind) || kind === "text";
  const words = boxed ? { align: kind === "text" ? "start" : "middle", valign: kind === "text" ? "top" : "middle" } : { align: "middle", valign: "middle" };
  return { ...style, ...words, ...(STYLES[kind] || {}), ...(PARAMETERS[kind] || {}) };
}

export function normalised(spec) {
  const kind = String(spec.kind);
  if (kind === "group") return { opacity: 1, ...spec, shapes: (spec.shapes || []).map(normalised) };
  const made = { ...defaults(kind), ...Object.fromEntries(Object.entries(spec).filter(([, value]) => value !== null && value !== undefined)) };
  if (kind === "bubble" && (made.tail === null || made.tail === undefined) && made.at && made.size) {
    const [x, y] = made.at, [w, h] = made.size;
    made.tail = [x + w * 0.25, y + h + h * 0.45];
  }
  return made;
}

// A theme colour by the name a person gives it, as the palette role it paints.
const ALIASES = { muted: "muted-ink", paper: "canvas", grey: "block-fill", gray: "block-fill" };
export function roleOf(name) {
  const found = /^accent(\d*)(-fill)?$/.exec(name);
  if (found) return `tone-${found[1] || 1}-${found[2] ? "fill" : "stroke"}`;
  return ALIASES[name] || name;
}
// A colour as written, painted from `roles` (palette role: colour); null for none.
export function paintOf(value, roles = {}) {
  if (value === null || value === undefined || value === "none") return null;
  const text = String(value);
  if (text.startsWith("#")) return text;
  return roles[roleOf(text)] || roles[text] || "#888888";
}

// -- geometry -------------------------------------------------------------------------------

const KAPPA = 0.5522847498307936;
const CLOUD_START = [0.03171, 0.66922];
const CLOUD = [
  [0.00644, 0.62621, -0.00453, 0.56924, 0.00171, 0.51343],
  [0.00796, 0.45763, 0.03078, 0.40863, 0.06412, 0.37944],
  [0.06241, 0.29946, 0.09012, 0.2242, 0.13688, 0.18187],
  [0.18364, 0.13955, 0.24237, 0.13655, 0.29106, 0.17401],
  [0.32083, 0.06679, 0.39316, -0.00249, 0.47275, 0.0],
  [0.55233, 0.00249, 0.62255, 0.07623, 0.6491, 0.18521],
  [0.69516, 0.12126, 0.76276, 0.10246, 0.82183, 0.13718],
  [0.88089, 0.1719, 0.92046, 0.25368, 0.92292, 0.34616],
  [0.9691, 0.37704, 0.99904, 0.44355, 1.0, 0.51736],
  [1.00096, 0.59117, 0.97277, 0.65927, 0.92743, 0.69266],
  [0.92897, 0.77426, 0.89287, 0.84734, 0.83916, 0.87137],
  [0.78544, 0.8954, 0.72728, 0.86449, 0.69694, 0.79579],
  [0.69566, 0.86579, 0.66877, 0.92949, 0.62639, 0.96289],
  [0.584, 0.99629, 0.53257, 0.99432, 0.49146, 0.95771],
  [0.45036, 0.92111, 0.42582, 0.85543, 0.42709, 0.78543],
  [0.43313, 0.89162, 0.37875, 0.98481, 0.30563, 0.99358],
  [0.23251, 1.00235, 0.16834, 0.92338, 0.1623, 0.81719],
  [0.09931, 0.82272, 0.04334, 0.7593, 0.03171, 0.66922],
];

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const unit = (dx, dy) => { const length = Math.hypot(dx, dy); return length > 1e-12 ? [dx / length, dy / length] : [1, 0]; };
const mod = (value, by) => ((value % by) + by) % by;

function roundedBox(x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  if (r <= 1e-9) return [["M", x, y], ["L", x + w, y], ["L", x + w, y + h], ["L", x, y + h], ["Z"]];
  const k = r * (1 - KAPPA);
  return [
    ["M", x + r, y], ["L", x + w - r, y], ["C", x + w - k, y, x + w, y + k, x + w, y + r],
    ["L", x + w, y + h - r], ["C", x + w, y + h - k, x + w - k, y + h, x + w - r, y + h],
    ["L", x + r, y + h], ["C", x + k, y + h, x, y + h - k, x, y + h - r],
    ["L", x, y + r], ["C", x, y + k, x + k, y, x + r, y], ["Z"],
  ];
}

function ellipse(cx, cy, rx, ry) {
  const kx = rx * KAPPA, ky = ry * KAPPA;
  return [
    ["M", cx + rx, cy], ["C", cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry],
    ["C", cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy],
    ["C", cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry],
    ["C", cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy], ["Z"],
  ];
}

const polygon = (points) => [["M", ...points[0]], ...points.slice(1).map((point) => ["L", ...point]), ["Z"]];

function fitted(points, x, y, w, h) {
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  const left = Math.min(...xs), top = Math.min(...ys);
  const across = (Math.max(...xs) - left) || 1, down = (Math.max(...ys) - top) || 1;
  return points.map(([px, py]) => [x + (px - left) / across * w, y + (py - top) / down * h]);
}

function arcCubics(cx, cy, rx, ry, start, sweep) {
  const pieces = Math.max(1, Math.ceil(Math.abs(sweep) / (Math.PI / 2) - 1e-9));
  const step = sweep / pieces, k = 4 / 3 * Math.tan(step / 4);
  const out = [];
  let angle = start;
  for (let n = 0; n < pieces; n += 1) {
    const a = angle, b = angle + step;
    out.push(["C",
      cx + rx * (Math.cos(a) - k * Math.sin(a)), cy + ry * (Math.sin(a) + k * Math.cos(a)),
      cx + rx * (Math.cos(b) + k * Math.sin(b)), cy + ry * (Math.sin(b) - k * Math.cos(b)),
      cx + rx * Math.cos(b), cy + ry * Math.sin(b)]);
    angle = b;
  }
  return out;
}

export function turned(point, centre, degrees) {
  if (!degrees) return [Number(point[0]), Number(point[1])];
  const angle = degrees * Math.PI / 180, cos = Math.cos(angle), sin = Math.sin(angle);
  const dx = point[0] - centre[0], dy = point[1] - centre[1];
  return [centre[0] + cos * dx - sin * dy, centre[1] + sin * dx + cos * dy];
}
export const unturned = (point, centre, degrees) => turned(point, centre, -degrees);

function callout(spec, x, y, w, h) {
  const tail = spec.tail || [x + w * 0.25, y + h * 1.45];
  const [tx, ty] = unturned(tail, [x + w / 2, y + h / 2], Number(spec.rotate || 0));
  const cx = x + w / 2, cy = y + h / 2, dx = tx - cx, dy = ty - cy;
  if (spec.body === "oval") {
    const rx = w / 2, ry = h / 2, angle = Math.atan2(dy * w, dx * h);
    const start = angle + 11 * Math.PI / 180, end = angle - 11 * Math.PI / 180;
    const sweep = mod(end - start, 2 * Math.PI);
    return [["M", cx + rx * Math.cos(start), cy + ry * Math.sin(start)], ...arcCubics(cx, cy, rx, ry, start, sweep), ["L", tx, ty], ["Z"]];
  }
  const vertical = Math.abs(dy) - Math.abs(dx * h / Math.max(w, 1e-9)) > 0;
  const x1 = x + w * (dx > 0 ? 7 : 2) / 12, x2 = x + w * (dx > 0 ? 10 : 5) / 12;
  const y1 = y + h * (dy > 0 ? 7 : 2) / 12, y2 = y + h * (dy > 0 ? 10 : 5) / 12;
  const top = vertical && dy <= 0 ? [tx, ty] : [x1, y];
  const bottom = vertical && dy > 0 ? [tx, ty] : [x1, y + h];
  const left = !vertical && dx <= 0 ? [tx, ty] : [x, y1];
  const right = !vertical && dx > 0 ? [tx, ty] : [x + w, y1];
  const r = spec.body === "rectangle" ? 0 : Math.max(0, Math.min(Number(spec.corner || 0), w / 2, h / 2));
  const k = r * (1 - KAPPA);
  const out = [["M", x, y + r]];
  if (r) out.push(["C", x, y + k, x + k, y, x + r, y]);
  out.push(["L", x1, y], ["L", ...top], ["L", x2, y], ["L", x + w - r, y]);
  if (r) out.push(["C", x + w - k, y, x + w, y + k, x + w, y + r]);
  out.push(["L", x + w, y1], ["L", ...right], ["L", x + w, y2], ["L", x + w, y + h - r]);
  if (r) out.push(["C", x + w, y + h - k, x + w - k, y + h, x + w - r, y + h]);
  out.push(["L", x2, y + h], ["L", ...bottom], ["L", x1, y + h], ["L", x + r, y + h]);
  if (r) out.push(["C", x + k, y + h, x, y + h - k, x, y + h - r]);
  out.push(["L", x, y2], ["L", ...left], ["L", x, y1], ["Z"]);
  return out;
}

function closedOutline(spec, x, y, w, h) {
  const kind = spec.kind, ss = Math.min(w, h), cx = x + w / 2, cy = y + h / 2;
  if (["rectangle", "rounded-rectangle", "highlight", "inset"].includes(kind)) return roundedBox(x, y, w, h, Number(spec.corner || 0));
  if (kind === "ellipse" || kind === "ring") return ellipse(cx, cy, w / 2, h / 2);
  if (kind === "triangle") return polygon([[x, y + h], [x + w * Number(spec.apex), y], [x + w, y + h]]);
  if (kind === "right-triangle") return polygon([[x, y], [x + w, y + h], [x, y + h]]);
  if (kind === "diamond") return polygon([[cx, y], [x + w, cy], [cx, y + h], [x, cy]]);
  if (kind === "polygon") {
    const n = Number(spec.sides);
    const points = Array.from({ length: n }, (_, k) => [Math.cos(-Math.PI / 2 + 2 * Math.PI * k / n), Math.sin(-Math.PI / 2 + 2 * Math.PI * k / n)]);
    return polygon(fitted(points, x, y, w, h));
  }
  if (kind === "star") {
    const n = Number(spec.tips), ratio = Number(spec.ratio);
    const points = Array.from({ length: 2 * n }, (_, k) => {
      const angle = -Math.PI / 2 + Math.PI * k / n, radius = k % 2 === 0 ? 1 : ratio;
      return [radius * Math.cos(angle), radius * Math.sin(angle)];
    });
    const outer = points.filter((_, k) => k % 2 === 0), xs = outer.map((p) => p[0]), ys = outer.map((p) => p[1]);
    const left = Math.min(...xs), top = Math.min(...ys), across = (Math.max(...xs) - left) || 1, down = (Math.max(...ys) - top) || 1;
    return polygon(points.map(([px, py]) => [x + (px - left) / across * w, y + (py - top) / down * h]));
  }
  if (kind === "parallelogram") {
    const slant = Math.min(ss * Number(spec.slant), w);
    return polygon([[x, y + h], [x + slant, y], [x + w, y], [x + w - slant, y + h]]);
  }
  if (kind === "trapezoid") {
    const inset = Math.min(ss * Number(spec.inset), w / 2);
    return polygon([[x, y + h], [x + inset, y], [x + w - inset, y], [x + w, y + h]]);
  }
  if (kind === "arrow-right" || kind === "arrow-left") {
    const head = Math.min(ss * Number(spec.head), w), half = h * Number(spec.shaft) / 2;
    let points = [[x, cy - half], [x + w - head, cy - half], [x + w - head, y], [x + w, cy], [x + w - head, y + h], [x + w - head, cy + half], [x, cy + half]];
    if (kind === "arrow-left") points = points.map(([px, py]) => [2 * cx - px, py]);
    return polygon(points);
  }
  if (kind === "arrow-up" || kind === "arrow-down") {
    const head = Math.min(ss * Number(spec.head), h), half = w * Number(spec.shaft) / 2;
    let points = [[x, y + head], [cx, y], [x + w, y + head], [cx + half, y + head], [cx + half, y + h], [cx - half, y + h], [cx - half, y + head]];
    if (kind === "arrow-down") points = points.map(([px, py]) => [px, 2 * cy - py]);
    return polygon(points);
  }
  if (kind === "arrow-left-right") {
    const head = Math.min(ss * Number(spec.head), w / 2), half = h * Number(spec.shaft) / 2;
    return polygon([[x, cy], [x + head, y], [x + head, cy - half], [x + w - head, cy - half], [x + w - head, y], [x + w, cy],
      [x + w - head, y + h], [x + w - head, cy + half], [x + head, cy + half], [x + head, y + h]]);
  }
  if (kind === "chevron") {
    const point = Math.min(ss * Number(spec.point), w);
    return polygon([[x, y], [x + w - point, y], [x + w, cy], [x + w - point, y + h], [x, y + h], [x + point, cy]]);
  }
  if (kind === "plus") {
    const arm = ss * Number(spec.arm);
    return polygon([[x, y + arm], [x + arm, y + arm], [x + arm, y], [x + w - arm, y], [x + w - arm, y + arm], [x + w, y + arm],
      [x + w, y + h - arm], [x + w - arm, y + h - arm], [x + w - arm, y + h], [x + arm, y + h], [x + arm, y + h - arm], [x, y + h - arm]]);
  }
  if (kind === "cross") {
    const k = Number(spec.arm);
    const points = [[0, k], [k, 0], [0.5, 0.5 - k], [1 - k, 0], [1, k], [0.5 + k, 0.5], [1, 1 - k], [1 - k, 1], [0.5, 0.5 + k], [k, 1], [0, 1 - k], [0.5 - k, 0.5]];
    return polygon(points.map(([u, v]) => [x + u * w, y + v * h]));
  }
  if (kind === "check") {
    const points = [[0, 0.58], [0.13, 0.44], [0.37, 0.68], [0.87, 0.02], [1, 0.16], [0.37, 1]];
    return polygon(points.map(([u, v]) => [x + u * w, y + v * h]));
  }
  if (kind === "cloud") {
    return [["M", x + CLOUD_START[0] * w, y + CLOUD_START[1] * h],
      ...CLOUD.map((cubic) => ["C", ...cubic.map((value, index) => (index % 2 === 0 ? x + value * w : y + value * h))]), ["Z"]];
  }
  if (kind === "bubble") return callout(spec, x, y, w, h);
  throw new Error(`Not a closed shape: ${kind}`);
}

function area(spec, x, y, w, h) {
  const kind = spec.kind, ss = Math.min(w, h);
  if (["rectangle", "rounded-rectangle", "highlight"].includes(kind) || (kind === "bubble" && spec.body !== "oval")) {
    const corner = kind === "bubble" && spec.body === "rectangle" ? 0 : Math.max(0, Math.min(Number(spec.corner || 0), w / 2, h / 2));
    const inset = corner * 0.29289;
    return [x + inset, y + inset, w - 2 * inset, h - 2 * inset];
  }
  if (["ellipse", "ring", "bubble"].includes(kind)) return [x + w * 0.14645, y + h * 0.14645, w * 0.7071, h * 0.7071];
  if (kind === "triangle") { const apex = Number(spec.apex); return [x + w * apex / 2, y + h / 2, w / 2, h / 2]; }
  if (kind === "right-triangle") return [x + w / 12, y + h * 7 / 12, w / 2, h / 3];
  if (kind === "diamond" || kind === "cross") return [x + w / 4, y + h / 4, w / 2, h / 2];
  if (kind === "parallelogram") {
    const share = Number(spec.slant) * ss / Math.max(w, 1e-9), inset = (1 + 5 * share) / 12;
    return [x + w * inset, y + h * inset, w * (1 - 2 * inset), h * (1 - 2 * inset)];
  }
  if (kind === "trapezoid") {
    const share = Number(spec.inset) * ss / Math.max(w / 2, 1e-9);
    return [x + w / 3 * share, y + h / 3 * share, w - 2 * w / 3 * share, h - h / 3 * share];
  }
  if (kind === "polygon" || kind === "star") {
    const inner = kind === "polygon" ? Math.cos(Math.PI / Number(spec.sides)) : Number(spec.ratio);
    const half = 0.5 * inner * 0.8;
    return [x + w * (0.5 - half), y + h * (0.5 - half), w * 2 * half, h * 2 * half];
  }
  if (kind === "arrow-right" || kind === "arrow-left") {
    const head = Math.min(ss * Number(spec.head), w), half = h * Number(spec.shaft) / 2;
    const reach = w - head + half * head / Math.max(h / 2, 1e-9);
    return [kind === "arrow-right" ? x : x + w - reach, y + h / 2 - half, reach, 2 * half];
  }
  if (kind === "arrow-up" || kind === "arrow-down") {
    const head = Math.min(ss * Number(spec.head), h), half = w * Number(spec.shaft) / 2;
    const reach = h - head + half * head / Math.max(w / 2, 1e-9);
    return [x + w / 2 - half, kind === "arrow-up" ? y + h - reach : y, 2 * half, reach];
  }
  if (kind === "arrow-left-right") {
    const head = Math.min(ss * Number(spec.head), w / 2), half = h * Number(spec.shaft) / 2;
    const inner = head - half * head / Math.max(h / 2, 1e-9);
    return [x + inner, y + h / 2 - half, w - 2 * inner, 2 * half];
  }
  if (kind === "chevron") { const point = Math.min(ss * Number(spec.point), w); return [x + point, y, Math.max(w - 2 * point, 0), h]; }
  if (kind === "plus") { const arm = ss * Number(spec.arm); return [x, y + arm, w, h - 2 * arm]; }
  if (kind === "cloud") return [x + w * 2977 / 21600, y + h * 3262 / 21600, w * (17087 - 2977) / 21600, h * (17337 - 3262) / 21600];
  return [x, y, w, h];
}

function flipped(segments, flip, cx, cy) {
  if (!flip) return segments;
  const sx = flip === "horizontal" || flip === "both" ? -1 : 1, sy = flip === "vertical" || flip === "both" ? -1 : 1;
  return segments.map(([kind, ...values]) => [kind, ...values.map((value, index) => (index % 2 === 0 ? cx + sx * (value - cx) : cy + sy * (value - cy)))]);
}

function cubicAt(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return [u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]];
}
function split(p0, p1, p2, p3, t) {
  const mix = (a, b) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  const a = mix(p0, p1), b = mix(p1, p2), c = mix(p2, p3), d = mix(a, b), e = mix(b, c), f = mix(d, e);
  return [[p0, a, d, f], [f, e, c, p3]];
}

function endsOf(segments) {
  const flat = [];
  for (const segment of segments) {
    if (segment[0] === "M" || segment[0] === "L") flat.push([segment[1], segment[2]]);
    else if (segment[0] === "C") flat.push([segment[1], segment[2]], [segment[3], segment[4]], [segment[5], segment[6]]);
  }
  const start = flat[0], end = flat[flat.length - 1];
  const after = flat.slice(1).find((p) => dist(p, start) > 1e-6) || [start[0] + 1, start[1]];
  const before = [...flat.slice(0, -1)].reverse().find((p) => dist(p, end) > 1e-6) || [end[0] - 1, end[1]];
  return [start, unit(start[0] - after[0], start[1] - after[1]), end, unit(end[0] - before[0], end[1] - before[1])];
}

export function headSize(spec) {
  const width = Number(spec.line_width || 0), length = Number(spec.head_size || 1) * (4 + 3 * width);
  return [length, length * 0.85];
}

function head(kind, end, tip, way, spec) {
  const [length, width] = headSize(spec), line = Number(spec.line_width || 0);
  const [ux, uy] = way, px = -uy, py = ux, [tx, ty] = tip, scale = Number(spec.head_size || 1);
  const at = (along, across) => [tx + ux * along + px * across, ty + uy * along + py * across];
  const angle = Math.atan2(uy, ux) * 180 / Math.PI;
  const made = (segments, filled, stroked) => ({ end, kind, segments, filled, stroked, tip, angle });
  if (kind === "triangle") return [made(polygon([tip, at(-length, width / 2), at(-length, -width / 2)]), true, false), length * 0.8];
  if (kind === "stealth") return [made(polygon([tip, at(-length, width * 0.53), at(-length * 0.65, 0), at(-length, -width * 0.53)]), true, false), length * 0.6];
  if (kind === "open") return [made([["M", ...at(-length, width / 2)], ["L", ...tip], ["L", ...at(-length, -width / 2)]], false, true), 0];
  if (kind === "dot" || kind === "circle") {
    const radius = scale * (1.5 + 1.2 * line);
    return [made(ellipse(tx, ty, radius, radius), kind === "dot", kind === "circle"), kind === "circle" ? radius : 0];
  }
  if (kind === "bar") {
    const reach = scale * (6 + 3 * line) / 2;
    return [made([["M", ...at(0, reach)], ["L", ...at(0, -reach)]], false, true), 0];
  }
  return [made(polygon([at(length / 2, 0), at(0, width / 2), at(-length / 2, 0), at(0, -width / 2)]), true, false), 0];
}

function lastPoint(segments) {
  for (const segment of [...segments].reverse()) {
    if (segment[0] === "M" || segment[0] === "L") return [segment[1], segment[2]];
    if (segment[0] === "C") return [segment[5], segment[6]];
  }
  return [0, 0];
}

function cutAt(p0, p1, p2, p3, distance, fromEnd) {
  const anchor = fromEnd ? p3 : p0;
  let [low, high] = fromEnd ? [0.5, 1] : [0, 0.5];
  for (let n = 0; n < 40; n += 1) {
    const middle = (low + high) / 2, far = dist(cubicAt(p0, p1, p2, p3, middle), anchor);
    if (fromEnd) [low, high] = far < distance ? [low, middle] : [middle, high];
    else [low, high] = far < distance ? [middle, high] : [low, middle];
  }
  return (low + high) / 2;
}

function trimmed(segments, start, end) {
  const out = [...segments];
  if (end > 1e-9) {
    const last = out[out.length - 1], before = lastPoint(out.slice(0, -1));
    if (last[0] === "L") {
      const point = [last[1], last[2]], cut = Math.min(end, dist(before, point) * 0.9), [ux, uy] = unit(point[0] - before[0], point[1] - before[1]);
      out[out.length - 1] = ["L", point[0] - ux * cut, point[1] - uy * cut];
    } else if (last[0] === "C") {
      const p0 = before, p1 = [last[1], last[2]], p2 = [last[3], last[4]], p3 = [last[5], last[6]];
      const [[, b, c, d]] = split(p0, p1, p2, p3, cutAt(p0, p1, p2, p3, end, true));
      out[out.length - 1] = ["C", ...b, ...c, ...d];
    }
  }
  if (start > 1e-9 && out.length > 1) {
    const first = [out[0][1], out[0][2]], next = out[1];
    if (next[0] === "L") {
      const point = [next[1], next[2]], cut = Math.min(start, dist(first, point) * 0.9), [ux, uy] = unit(point[0] - first[0], point[1] - first[1]);
      out[0] = ["M", first[0] + ux * cut, first[1] + uy * cut];
    } else if (next[0] === "C") {
      const p0 = first, p1 = [next[1], next[2]], p2 = [next[3], next[4]], p3 = [next[5], next[6]];
      const [, [a, b, c, d]] = split(p0, p1, p2, p3, cutAt(p0, p1, p2, p3, start, false));
      out[0] = ["M", ...a];
      out[1] = ["C", ...b, ...c, ...d];
    }
  }
  return out;
}

export const pointOf = (value) => (value && !Array.isArray(value) && typeof value === "object" ? (value.at ? [Number(value.at[0]), Number(value.at[1])] : [0, 0]) : [Number(value[0]), Number(value[1])]);

function beside(point, normal, gap) {
  const [nx, ny] = normal, x = point[0] + nx * gap, y = point[1] + ny * gap;
  if (Math.abs(nx) >= Math.abs(ny) * 1.2) return { x, y, align: nx > 0 ? "start" : "end", valign: "middle", angle: 0 };
  return { x, y, align: "middle", valign: ny > 0 ? "top" : "bottom", angle: 0 };
}

function headReach(spec, end) {
  const kind = spec[end] || "none";
  if (kind === "bar") return Number(spec.head_size || 1) * (6 + 3 * Number(spec.line_width || 0)) / 2;
  if (kind === "none") return Number(spec.line_width || 0) / 2;
  return headSize(spec)[1] / 2;
}

function braceQuarter(at, centre, ru, rv, from, to) {
  const local = arcCubics(centre[0], centre[1], ru, rv ? Math.abs(rv) : 0, from, to - from);
  const sign = rv >= 0 ? 1 : -1;
  return local.map(([, ...values]) => {
    const mapped = [];
    for (let index = 0; index < 6; index += 2) mapped.push(...at(values[index], centre[1] + (values[index + 1] - centre[1]) * sign));
    return ["C", ...mapped];
  });
}

function linePath(spec, a, b) {
  const kind = spec.kind, length = dist(a, b);
  const [ux, uy] = unit(b[0] - a[0], b[1] - a[1]), nx = uy, ny = -ux;
  const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const gap = Number(spec.line_width || 0) / 2 + 4;
  if (kind === "curved-arrow") {
    const bend = Number(spec.bend || 0), lean = Number(spec.lean || 0);
    const through = [mid[0] + (nx * bend + ux * lean) * length, mid[1] + (ny * bend + uy * lean) * length];
    const control = [2 * through[0] - mid[0], 2 * through[1] - mid[1]];
    const c1 = [a[0] + 2 / 3 * (control[0] - a[0]), a[1] + 2 / 3 * (control[1] - a[1])];
    const c2 = [b[0] + 2 / 3 * (control[0] - b[0]), b[1] + 2 / 3 * (control[1] - b[1])];
    const side = bend >= 0 ? 1 : -1;
    return [[["M", ...a], ["C", ...c1, ...c2, ...b]], beside(through, [nx * side, ny * side], gap), null];
  }
  if (kind === "arc") {
    const sagitta = Number(spec.bend || 0) * length;
    if (Math.abs(sagitta) < 1e-6 || length < 1e-9) return [[["M", ...a], ["L", ...b]], beside(mid, [nx, ny], gap), null];
    const radius = (length * length / 4 + sagitta * sagitta) / (2 * Math.abs(sagitta));
    const t = sagitta - Math.sign(sagitta) * radius;
    const cx = mid[0] + nx * t, cy = mid[1] + ny * t, top = [mid[0] + nx * sagitta, mid[1] + ny * sagitta];
    const a0 = Math.atan2(a[1] - cy, a[0] - cx), a1 = Math.atan2(b[1] - cy, b[0] - cx), am = Math.atan2(top[1] - cy, top[0] - cx);
    const forward = mod(a1 - a0, 2 * Math.PI);
    const sweep = mod(am - a0, 2 * Math.PI) < forward ? forward : -mod(a0 - a1, 2 * Math.PI);
    const side = sagitta >= 0 ? 1 : -1;
    return [[["M", ...a], ...arcCubics(cx, cy, radius, radius, a0, sweep)], beside(top, [nx * side, ny * side], gap), null];
  }
  if (kind === "elbow") {
    const share = spec.elbow === undefined ? 0.5 : Number(spec.elbow);
    let corners;
    if (spec.route === "down") { const ym = a[1] + share * (b[1] - a[1]); corners = [a, [a[0], ym], [b[0], ym], b]; }
    else { const xm = a[0] + share * (b[0] - a[0]); corners = [a, [xm, a[1]], [xm, b[1]], b]; }
    const middle = [(corners[1][0] + corners[2][0]) / 2, (corners[1][1] + corners[2][1]) / 2];
    const way = unit(corners[2][0] - corners[1][0], corners[2][1] - corners[1][1]);
    return [[["M", ...corners[0]], ...corners.slice(1).map((point) => ["L", ...point])], beside(middle, [way[1], -way[0]], gap), null];
  }
  if (kind === "brace" || kind === "bracket") {
    const depth = Number(spec.depth || 0), reach = Math.abs(depth), sign = depth >= 0 ? 1 : -1;
    const at = (u, v) => [a[0] + ux * u + nx * v, a[1] + uy * u + ny * v];
    if (kind === "bracket") {
      const curl = Math.min(Number(spec.curl || 0) * reach, length / 2), out = [["M", ...at(0, 0)]];
      if (curl > 1e-9) out.push(["C", ...at(0, depth * KAPPA), ...at(curl * (1 - KAPPA), depth), ...at(curl, depth)]);
      else out.push(["L", ...at(0, depth)]);
      out.push(["L", ...at(length - curl, depth)]);
      if (curl > 1e-9) out.push(["C", ...at(length - curl * (1 - KAPPA), depth), ...at(length, depth * KAPPA), ...at(length, 0)]);
      else out.push(["L", ...at(length, 0)]);
      const tip = at(length / 2, depth);
      return [out, beside(tip, [nx * sign, ny * sign], gap + 2), tip];
    }
    const tipAt = (spec.tip === undefined ? 0.5 : Number(spec.tip)) * length;
    const curl = Math.min(Number(spec.curl || 0) * reach, tipAt / 2, (length - tipAt) / 2), midV = depth / 2;
    const out = [["M", ...at(0, 0)],
      ...braceQuarter(at, [curl, 0], curl, midV, Math.PI, Math.PI / 2),
      ["L", ...at(tipAt - curl, midV)],
      ...braceQuarter(at, [tipAt - curl, depth], curl, midV, -Math.PI / 2, 0),
      ...braceQuarter(at, [tipAt + curl, depth], curl, midV, Math.PI, 1.5 * Math.PI),
      ["L", ...at(length - curl, midV)],
      ...braceQuarter(at, [length - curl, 0], curl, midV, Math.PI / 2, 0)];
    const tip = at(tipAt, depth);
    return [out, beside(tip, [nx * sign, ny * sign], gap + 2), tip];
  }
  if (kind === "dimension" || kind === "scale-bar") {
    const angle = Math.atan2(uy, ux) * 180 / Math.PI, upright = angle > 90 || angle <= -90 ? angle + 180 : angle;
    const side = kind === "dimension" ? 1 : -1, width = Number(spec.line_width || 0);
    const heads = Math.max(headReach(spec, "start"), headReach(spec, "end"));
    const away = (kind === "dimension" ? heads : width / 2) + 3;
    const point = [mid[0] + nx * side * away, mid[1] + ny * side * away];
    const turn = upright * Math.PI / 180, localY = -(nx * side) * Math.sin(turn) + (ny * side) * Math.cos(turn);
    return [[["M", ...a], ["L", ...b]], { x: point[0], y: point[1], align: "middle", valign: localY < 0 ? "bottom" : "top", angle: upright }, null];
  }
  return [[["M", ...a], ["L", ...b]], beside(mid, [nx, ny], gap), null];
}

function smooth(points, isClosed) {
  const count = points.length;
  if (count < 3) return [["M", ...points[0]], ...points.slice(1).map((point) => ["L", ...point]), ...(isClosed ? [["Z"]] : [])];
  const out = [["M", ...points[0]]], last = isClosed ? count : count - 1;
  for (let index = 0; index < last; index += 1) {
    const p0 = isClosed || index > 0 ? points[mod(index - 1, count)] : points[index];
    const p1 = points[index], p2 = points[(index + 1) % count];
    const p3 = isClosed || index + 2 < count ? points[(index + 2) % count] : p2;
    out.push(["C", p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6, p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, ...p2]);
  }
  if (isClosed) out.push(["Z"]);
  return out;
}

function halfWay(points) {
  const lengths = points.slice(1).map((q, n) => dist(points[n], q));
  let total = lengths.reduce((sum, length) => sum + length, 0) / 2;
  for (let n = 0; n < lengths.length; n += 1) {
    const p = points[n], q = points[n + 1], length = lengths[n];
    if (total <= length && length > 0) {
      const t = total / length, [ux, uy] = unit(q[0] - p[0], q[1] - p[1]);
      return [[p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t], [uy, -ux]];
    }
    total -= length;
  }
  return [points[points.length - 1], [0, -1]];
}

function headed(spec, segments) {
  const [start, startWay, end, endWay] = endsOf(segments), heads = [], cuts = [0, 0];
  [["start", start, startWay], ["end", end, endWay]].forEach(([name, tip, way], index) => {
    const kind = spec[name] || "none";
    if (kind === "none") return;
    const [made, cut] = head(kind, name, tip, way, spec);
    heads.push(made);
    cuts[index] = cut;
  });
  return [heads, cuts[0] || cuts[1] ? trimmed(segments, cuts[0], cuts[1]) : segments];
}

// A shape as drawn: its outline (a box's unturned, about its centre by `turn`), its heads,
// and where its words go -- inside it (`area`), or beside it (`label`). `ends`: a line's
// ends where it is glued; `size`: a text box's, as its words make it.
export function geometry(spec, ends = null, size = null) {
  spec = normalised(spec);
  const kind = spec.kind, form = family(kind);
  if (form === "group") {
    const boxes = spec.shapes.map((child) => bounds(child));
    const left = Math.min(...boxes.map((b) => b[0])), top = Math.min(...boxes.map((b) => b[1]));
    const right = Math.max(...boxes.map((b) => b[2])), bottom = Math.max(...boxes.map((b) => b[3]));
    return { segments: [], closed: false, box: [left, top, right - left, bottom - top], turn: 0, heads: [], area: null, label: null, ends: null };
  }
  if (form === "box" || form === "text") {
    const [x, y] = spec.at.map(Number);
    const [w, h] = form === "text" ? (size || [Number(spec.width || SIZES.text[0]), SIZES.text[1]]) : spec.size.map(Number);
    // (A zoom inset shows what it magnifies as it is: never turned, nor mirrored.)
    const cx = x + w / 2, cy = y + h / 2, turn = kind === "inset" ? 0 : Number(spec.rotate || 0);
    let segments, room;
    if (form === "text") { segments = roundedBox(x, y, w, h, 0); room = [x, y, w, h]; }
    else {
      segments = closedOutline(spec, x, y, w, h);
      room = area(spec, x, y, w, h);
      if (kind !== "bubble" && kind !== "inset") {
        segments = flipped(segments, spec.flip, cx, cy);
        const corners = flipped([["M", room[0], room[1]], ["L", room[0] + room[2], room[1] + room[3]]], spec.flip, cx, cy);
        const xs = [corners[0][1], corners[1][1]], ys = [corners[0][2], corners[1][2]];
        room = [Math.min(...xs), Math.min(...ys), Math.abs(xs[1] - xs[0]), Math.abs(ys[1] - ys[0])];
      }
    }
    return { segments, closed: true, box: [x, y, w, h], turn, heads: [], area: room, label: null, ends: null };
  }
  if (form === "points") {
    const points = spec.points.map((p) => [Number(p[0]), Number(p[1])]), isClosed = Boolean(spec.closed);
    let segments = kind === "pen" ? smooth(points, isClosed) : [["M", ...points[0]], ...points.slice(1).map((point) => ["L", ...point]), ...(isClosed ? [["Z"]] : [])];
    const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
    const box = [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
    if (isClosed) return { segments, closed: true, box, turn: 0, heads: [], area: box, label: null, ends: null };
    const [middle, normal] = halfWay(points);
    const label = beside(middle, normal, Number(spec.line_width || 0) / 2 + 4);
    let heads;
    [heads, segments] = headed(spec, segments);
    return { segments, closed: false, box, turn: 0, heads, area: null, label, ends: [points[0], points[points.length - 1]] };
  }
  const [a, b] = ends || [pointOf(spec.from), pointOf(spec.to)];
  let [segments, label] = linePath(spec, a, b);
  let heads = [];
  if (kind !== "brace" && kind !== "bracket") [heads, segments] = headed(spec, segments);
  const xs = segments.flatMap(([, ...values]) => values.filter((_, n) => n % 2 === 0));
  const ys = segments.flatMap(([, ...values]) => values.filter((_, n) => n % 2 === 1));
  const box = xs.length ? [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)] : [a[0], a[1], 0, 0];
  return { segments, closed: false, box, turn: 0, heads, area: null, label, ends: [a, b] };
}

export const centreOf = (made) => [made.box[0] + made.box[2] / 2, made.box[1] + made.box[3] / 2];

// The corners of a shape's frame, turned as it is.
export function corners(made) {
  const [x, y, w, h] = made.box, centre = centreOf(made);
  return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]].map((point) => turned(point, centre, made.turn));
}

// left, top, right, bottom of what a shape draws, turned as it is.
export function bounds(spec, made = null) {
  made ||= geometry(spec);
  const points = [];
  for (const segments of [made.segments, ...made.heads.map((one) => one.segments)]) {
    for (const [, ...values] of segments) for (let n = 0; n < values.length; n += 2) points.push([values[n], values[n + 1]]);
  }
  const placed = made.turn ? points.map((point) => turned(point, centreOf(made), made.turn)) : points;
  if (!placed.length) { const [x, y, w, h] = made.box; return [x, y, x + w, y + h]; }
  return [Math.min(...placed.map((p) => p[0])), Math.min(...placed.map((p) => p[1])), Math.max(...placed.map((p) => p[0])), Math.max(...placed.map((p) => p[1]))];
}

// A path as points, its curves cut into `steps` each.
export function flattened(segments, steps = 8) {
  const out = [];
  let here = [0, 0];
  for (const segment of segments) {
    if (segment[0] === "M" || segment[0] === "L") { here = [segment[1], segment[2]]; out.push(here); }
    else if (segment[0] === "C") {
      const p1 = [segment[1], segment[2]], p2 = [segment[3], segment[4]], p3 = [segment[5], segment[6]];
      for (let step = 1; step <= steps; step += 1) out.push(cubicAt(here, p1, p2, p3, step / steps));
      here = p3;
    }
  }
  return out;
}

export function pathData(segments) {
  const number = (value) => { const text = (Math.abs(value) < 5e-8 ? 0 : value).toFixed(5).replace(/0+$/, "").replace(/\.$/, ""); return text === "-0" ? "0" : text || "0"; };
  return segments.map(([kind, ...values]) => [kind, ...values.map(number)].join(" ")).join(" ");
}

// -- what a line's end is glued to -------------------------------------------------------------

// A shape as something a line is glued to: its box, its turn, its outline on the page.
export function targetOf(spec, made = null) {
  made ||= geometry(spec);
  const centre = centreOf(made);
  return { box: made.box, turn: made.turn, outline: made.closed ? flattened(made.segments).map((point) => turned(point, centre, made.turn)) : null };
}

export function sites(target) {
  const [x, y, w, h] = target.box, centre = [x + w / 2, y + h / 2];
  const places = { top: [x + w / 2, y], right: [x + w, y + h / 2], bottom: [x + w / 2, y + h], left: [x, y + h / 2], centre };
  return Object.fromEntries(Object.entries(places).map(([side, point]) => [side, turned(point, centre, target.turn || 0)]));
}

export function facing(target, other) {
  const [x, y, w, h] = target.box, centre = [x + w / 2, y + h / 2];
  const local = unturned(other, centre, target.turn || 0), dx = local[0] - centre[0], dy = local[1] - centre[1];
  if (Math.abs(dx) * Math.max(h, 1e-9) >= Math.abs(dy) * Math.max(w, 1e-9)) return dx >= 0 ? "right" : "left";
  return dy >= 0 ? "bottom" : "top";
}

function met(outline, inside, outside) {
  let best = null;
  const [ax, ay] = inside, [bx, by] = outside;
  outline.forEach(([cx, cy], n) => {
    const [dx, dy] = outline[(n + 1) % outline.length];
    const denominator = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx);
    if (Math.abs(denominator) < 1e-12) return;
    const t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denominator;
    const u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denominator;
    if (t >= 0 && t <= 1 && u >= 0 && u <= 1 && (!best || t > best[0])) best = [t, [ax + (bx - ax) * t, ay + (by - ay) * t]];
  });
  return best ? best[1] : null;
}

// Where a line's ends are: each written point, or the place on what it is glued to that
// `find(end)` gives as a target (null, gone: where it was, its `at`).
export function glued(spec, find) {
  const ends = [spec.from, spec.to];
  const targets = ends.map((end) => (end && !Array.isArray(end) && typeof end === "object" ? find(end) : null));
  const points = ends.map((end, n) => (targets[n] ? sites(targets[n]).centre : isEnd(end) && !end.at ? null : pointOf(end)));
  // (An end glued to what is not there, with no place of its own kept: at the other end.)
  for (const n of [0, 1]) if (!points[n]) points[n] = points[1 - n] || [0, 0];
  for (let round = 0; round < 2; round += 1) {
    ends.forEach((end, n) => {
      const target = targets[n];
      if (!target) return;
      const other = points[1 - n], side = end.side || facing(target, other);
      if (side === "centre") {
        const centre = sites(target).centre, [x, y, w, h] = target.box;
        const outline = target.outline || [[x, y], [x + w, y], [x + w, y + h], [x, y + h]].map((p) => turned(p, centre, target.turn || 0));
        points[n] = met(outline, centre, other) || centre;
      } else points[n] = sites(target)[side];
    });
  }
  return points;
}

// -- drawing ---------------------------------------------------------------------------------

export function dashArray(spec) {
  const dash = spec.dash || "solid";
  if (dash === "solid") return [];
  const width = Math.max(Number(spec.line_width || 0), 0.1);
  let [on, off] = dash === "dashed" ? [4, 3] : [1, 2];
  if (spec.cap === "round" || spec.cap === "square") { on = Math.max(on - 1, 0); off += 1; }
  return [on * width, off * width];
}

const escape = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

// A shape as SVG markup: its outline and heads painted with `roles` (palette role: colour),
// turned as it is -- a preview while it is drawn, an icon. Its words are not drawn here.
export function svg(spec, made = null, roles = {}, { id = "" } = {}) {
  spec = normalised(spec);
  made ||= geometry(spec);
  const fill = made.closed ? paintOf(spec.fill, roles) : null;
  const width = Number(spec.line_width || 0), stroke = width > 0 ? paintOf(spec.line, roles) : null;
  const [cx, cy] = centreOf(made);
  const attributes = [`fill="${escape(fill || "none")}"`];
  if (fill && Number(spec.fill_opacity ?? 1) < 1) attributes.push(`fill-opacity="${Number(spec.fill_opacity)}"`);
  if (stroke) {
    attributes.push(`stroke="${escape(stroke)}"`, `stroke-width="${width}"`, `stroke-linecap="${spec.cap || "butt"}"`, `stroke-linejoin="${spec.join || "miter"}"`);
    const dashes = dashArray(spec);
    if (dashes.length) attributes.push(`stroke-dasharray="${dashes.join(" ")}"`);
  }
  const parts = [];
  if (made.segments.length && (fill || stroke)) parts.push(`<path d="${pathData(made.segments)}" ${attributes.join(" ")}/>`);
  for (const one of stroke ? made.heads : []) {
    parts.push(`<path d="${pathData(one.segments)}" fill="${one.filled ? escape(stroke) : "none"}"${one.stroked ? ` stroke="${escape(stroke)}" stroke-width="${width}" stroke-linecap="${one.kind === "open" ? "round" : "butt"}" stroke-linejoin="round"` : ""}/>`);
  }
  const turn = made.turn ? ` transform="rotate(${made.turn} ${cx} ${cy})"` : "";
  const fade = Number(spec.opacity ?? 1) < 1 ? ` opacity="${Number(spec.opacity)}"` : "";
  return `<g${id ? ` id="${escape(id)}"` : ""}${turn}${fade}>${parts.join("")}</g>`;
}

// -- moving, sizing, turning (as an editor does) ---------------------------------------------

const isEnd = (end) => end && !Array.isArray(end) && typeof end === "object";

// A shape moved by dx, dy: its box, points and tail; a glued end stays glued (its `at` moved).
export function moved(spec, dx, dy) {
  const made = { ...spec };
  if (made.kind === "group") { made.shapes = (made.shapes || []).map((child) => moved(child, dx, dy)); return made; }
  for (const key of ["at", "tail"]) if (Array.isArray(made[key])) made[key] = [made[key][0] + dx, made[key][1] + dy];
  for (const key of ["from", "to"]) {
    const end = made[key];
    if (isEnd(end)) { if (end.at) made[key] = { ...end, at: [end.at[0] + dx, end.at[1] + dy] }; }
    else if (Array.isArray(end)) made[key] = [end[0] + dx, end[1] + dy];
  }
  if (Array.isArray(made.points)) made.points = made.points.map(([x, y]) => [x + dx, y + dy]);
  return made;
}

// A shape's points mapped by `map` ([x, y] to [x, y]): every point it is placed by -- its box
// (by its corners: for a map that only stretches and moves), its ends, points and tail.
export function mapped(spec, map, { box = true } = {}) {
  const made = { ...spec };
  if (made.kind === "group") { made.shapes = (made.shapes || []).map((child) => mapped(child, map, { box })); return made; }
  if (box && Array.isArray(made.at)) {
    const a = map(made.at), size = made.size || (made.width ? [made.width, 0] : null);
    if (size) {
      const b = map([made.at[0] + size[0], made.at[1] + size[1]]);
      made.at = [Math.min(a[0], b[0]), Math.min(a[1], b[1])];
      if (made.size) made.size = [Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])];
      else if (made.width) made.width = Math.abs(b[0] - a[0]);
    } else made.at = a;
  }
  if (Array.isArray(made.tail)) made.tail = map(made.tail);
  for (const key of ["from", "to"]) {
    const end = made[key];
    if (isEnd(end)) { if (end.at) made[key] = { ...end, at: map(end.at) }; }
    else if (Array.isArray(end)) made[key] = map(end);
  }
  if (Array.isArray(made.points)) made.points = made.points.map((point) => map(point));
  return made;
}

// A shape turned by `degrees` about `pivot`: a box turned about its own middle and moved with
// it; a line's points turned.
export function turnedAbout(spec, degrees, pivot) {
  if (spec.kind === "group") return { ...spec, shapes: (spec.shapes || []).map((child) => turnedAbout(child, degrees, pivot)) };
  const form = family(spec.kind);
  if (form === "box" || form === "text") {
    const made = geometry(spec), centre = centreOf(made), now = turned(centre, pivot, degrees);
    const shifted = moved(spec, now[0] - centre[0], now[1] - centre[1]);
    const angle = mod(Number(spec.rotate || 0) + degrees, 360);
    // (A bubble's tail is where it points, on the page: turned about the pivot too.)
    if (Array.isArray(spec.tail)) shifted.tail = turned(spec.tail, pivot, degrees);
    return { ...shifted, rotate: Math.abs(angle) < 1e-9 || Math.abs(angle - 360) < 1e-9 ? 0 : Math.round(angle * 1000) / 1000 };
  }
  return mapped(spec, (point) => turned(point, pivot, degrees));
}

// Points closer than `tolerance` to the line through their neighbours dropped (Ramer,
// Douglas and Peucker's): a hand-drawn line as few points as keep its shape.
export function simplified(points, tolerance = 1.5) {
  if (points.length < 3) return points;
  const keep = new Array(points.length).fill(false);
  keep[0] = keep[points.length - 1] = true;
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop();
    const [ax, ay] = points[first], [bx, by] = points[last], length = Math.hypot(bx - ax, by - ay) || 1;
    let far = -1, at = -1;
    for (let n = first + 1; n < last; n += 1) {
      const [px, py] = points[n], away = Math.abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length;
      if (away > far) { far = away; at = n; }
    }
    if (far > tolerance) { keep[at] = true; stack.push([first, at], [at, last]); }
  }
  return points.filter((_, n) => keep[n]);
}

// Whether `point` is on the shape, within `slack` of its outline (or inside it, closed and
// filled, or a box of words).
export function hits(spec, made, point, slack) {
  const centre = centreOf(made), local = made.turn ? unturned(point, centre, made.turn) : point;
  spec = normalised(spec);
  if (spec.kind === "text") {
    const [x, y, w, h] = made.box;
    return local[0] >= x - slack && local[0] <= x + w + slack && local[1] >= y - slack && local[1] <= y + h + slack;
  }
  const outline = flattened(made.segments);
  if (made.closed && outline.length > 2 && inside(outline, local)) return true;
  const reach = slack + Number(spec.line_width || 0) / 2;
  for (let n = 1; n < outline.length; n += 1) if (segmentDistance(local, outline[n - 1], outline[n]) <= reach) return true;
  if (made.closed && outline.length > 2 && segmentDistance(local, outline[outline.length - 1], outline[0]) <= reach) return true;
  for (const one of made.heads) {
    const points = flattened(one.segments);
    if (one.filled && inside(points, local)) return true;
    for (let n = 1; n < points.length; n += 1) if (segmentDistance(local, points[n - 1], points[n]) <= reach) return true;
  }
  return false;
}

export function inside(polygonPoints, [px, py]) {
  let within = false;
  for (let n = 0, m = polygonPoints.length - 1; n < polygonPoints.length; m = n, n += 1) {
    const [xi, yi] = polygonPoints[n], [xj, yj] = polygonPoints[m];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi || 1e-12) + xi) within = !within;
  }
  return within;
}

export function segmentDistance([px, py], [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / length)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}
