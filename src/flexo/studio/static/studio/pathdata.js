// SVG path data, as a `path` shape writes its outline (flexo.pathdata, here in the page): read,
// every command absolute and relative, what is wrong said in words (the same words), written back
// as absolute moves, lines, cubics and closes to a hundredth of a point. A test reads both on the
// same paths and keeps them the same.
//
// A drawing may hold hundreds of paths of thousands of points, and a drag moves them all at
// once, a frame at a time: so what is read is kept -- by its words, and by the shape it was read
// for -- and a path moved (or stretched) is not written out again on each frame. Its shape says
// its outline as it always does (`d`), but those words are written only when they are first
// read; until then its points are what it was read as, moved, found when first wanted, and its
// box is the one it was read in, moved. What is found from a path (its outline flattened, where
// a line meets it) is found once, and kept with it.

export const LIMIT = 100000;
export const MOST = 100000;
export const EXAMPLE = '"M 10 10 L 60 10 L 60 40 Z"';

const TAKES = { M: 2, L: 2, H: 1, V: 1, C: 6, S: 4, Q: 4, T: 2, A: 7 };
const SAYS = { M: "x y", L: "x y", H: "x", V: "y", C: "x1 y1 x2 y2 x y", S: "x2 y2 x y", Q: "x1 y1 x y", T: "x y", A: "rx ry turn large-arc sweep x y" };
const NUMBER = /^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;
const COMMANDS = new Set("MmLlHhVvCcSsQqTtAaZz");

export class PathError extends Error {}

// Python's repr of a string, near enough for what is said of one: 'text'.
const quoted = (text) => (text.includes("'") && !text.includes('"') ? `"${text}"` : `'${text.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`);
const begun = (data) => { const text = data.split(/\s+/).filter(Boolean).join(" "); return quoted(text.length <= 16 ? text : `${text.slice(0, 15)}…`); };
const grouped = (count) => String(count).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
// A number as Python's `:g` says it: six figures, an exponent when it is large.
function said(value) {
  if (value === Infinity) return "inf";
  const exponent = Math.floor(Math.log10(Math.abs(value)));
  if (exponent < -4 || exponent >= 6) {
    const [digits, power] = value.toExponential(5).split("e");
    const n = Number(power);
    return `${digits.replace(/\.?0+$/, "")}e${n < 0 ? "-" : "+"}${String(Math.abs(n)).padStart(2, "0")}`;
  }
  return String(Number(value.toPrecision(6)));
}

// -- reading --

const separator = (code) => code === 32 || code === 44 || (code >= 9 && code <= 13);
const digit = (code) => code >= 48 && code <= 57;
// Where a number starting at `at` ends (as flexo.pathdata's pattern reads one), or `at`.
function numberEnd(data, at) {
  let n = at, code = data.charCodeAt(n);
  if (code === 43 || code === 45) code = data.charCodeAt(++n);
  if (digit(code)) {
    while (digit(data.charCodeAt(n))) n += 1;
    if (data.charCodeAt(n) === 46) { n += 1; while (digit(data.charCodeAt(n))) n += 1; }
  } else if (code === 46 && digit(data.charCodeAt(n + 1))) {
    n += 1;
    while (digit(data.charCodeAt(n))) n += 1;
  } else return at;
  code = data.charCodeAt(n);
  if (code === 101 || code === 69) {
    let m = n + 1;
    const sign = data.charCodeAt(m);
    if (sign === 43 || sign === 45) m += 1;
    if (digit(data.charCodeAt(m))) { while (digit(data.charCodeAt(m))) m += 1; n = m; }
  }
  return n;
}

// Each command and number: what it is (a command's letter; "" a number), where it starts and ends.
function tokens(data) {
  const kinds = [], starts = [], ends = [], count = data.length;
  let at = 0;
  while (at < count) {
    const code = data.charCodeAt(at), letter = data[at];
    if (COMMANDS.has(letter)) { kinds.push(letter); starts.push(at); ends.push(at + 1); at += 1; continue; }
    const end = numberEnd(data, at);
    if (end > at) { kinds.push(""); starts.push(at); ends.push(end); at = end; continue; }
    if (separator(code)) { at += 1; while (at < count && separator(data.charCodeAt(at))) at += 1; continue; }
    throw new PathError(`${quoted(String.fromCodePoint(data.codePointAt(at)))} at character ${at + 1} is not a path command or a number: `
      + "the commands are M, L, H, V, C, S, Q, T, A and Z (in lower case, relative).");
  }
  return { kinds, starts, ends };
}

// An elliptical arc as cubics, a quarter turn at most each (SVG's own reading of one: radii too
// small for its ends grown until they reach), each pushed to `kinds` and `values`.
function arc(start, rx, ry, turn, large, sweep, end, kinds, values) {
  if (start[0] === end[0] && start[1] === end[1]) return;
  rx = Math.abs(rx); ry = Math.abs(ry);
  if (rx === 0 || ry === 0) { kinds.push("L"); values.push(end[0], end[1]); return; }
  const phi = (((turn % 360) + 360) % 360) * Math.PI / 180;
  const cos = Math.cos(phi), sin = Math.sin(phi);
  const hx = (start[0] - end[0]) / 2, hy = (start[1] - end[1]) / 2;
  const x1 = cos * hx + sin * hy, y1 = -sin * hx + cos * hy;
  const reach = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry);
  if (reach > 1) { const grow = Math.sqrt(reach); rx *= grow; ry *= grow; }
  const above = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
  const below = rx * rx * y1 * y1 + ry * ry * x1 * x1;
  let share = below > 0 ? Math.sqrt(Math.max(0, above / below)) : 0;
  if (large === sweep) share = -share;
  const cx1 = share * rx * y1 / ry, cy1 = -share * ry * x1 / rx;
  const cx = cos * cx1 - sin * cy1 + (start[0] + end[0]) / 2, cy = sin * cx1 + cos * cy1 + (start[1] + end[1]) / 2;
  const ux = (x1 - cx1) / rx, uy = (y1 - cy1) / ry, vx = (-x1 - cx1) / rx, vy = (-y1 - cy1) / ry;
  const theta = Math.atan2(uy, ux);
  let delta = Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  if (!sweep && delta > 0) delta -= 2 * Math.PI;
  else if (sweep && delta < 0) delta += 2 * Math.PI;
  const pieces = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 2) - 1e-9));
  const step = delta / pieces, k = 4 / 3 * Math.tan(step / 4);
  const at = (u, v) => [cx + cos * rx * u - sin * ry * v, cy + sin * rx * u + cos * ry * v];
  for (let piece = 0; piece < pieces; piece += 1) {
    const a = theta + piece * step, b = a + step;
    const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
    const last = piece === pieces - 1 ? end : at(cb, sb);
    kinds.push("C");
    values.push(...at(ca - k * sa, sa + k * ca), ...at(cb + k * sb, sb - k * cb), last[0], last[1]);
  }
}

// `data` read: its segments' letters (M, L, C or Z, one each) and their numbers, in pairs.
export function read(data) {
  data = String(data);
  const list = tokens(data), types = list.kinds, starts = list.starts, ends = list.ends, count = types.length;
  const text = (index) => data.slice(starts[index], ends[index]);
  if (!count) throw new PathError(`d is empty: a path needs a move and a line at least, such as ${EXAMPLE}.`);
  if (types[0] !== "M" && types[0] !== "m") throw new PathError(`a path starts with M (a move to its first point), such as ${EXAMPLE}, not ${begun(data)}.`);
  const kinds = [], values = [];
  const last = () => kinds[kinds.length - 1];
  let here = [0, 0], start = [0, 0], cubic = null, quad = null, command = "", named = "", at = 0, index = 0, repeated = false;
  // An arc's flag, read off the front of the next number ("0110" is two flags and 10).
  const flag = (which) => {
    if (index >= count || types[index]) throw new PathError(`${named} at character ${at + 1} needs 7 numbers (${SAYS.A}), but its ${which} flag is missing.`);
    const word = text(index);
    if (word[0] !== "0" && word[0] !== "1") throw new PathError(`the arc at character ${at + 1} has a ${which} flag of ${quoted(word)}: a flag is 0 or 1.`);
    const rest = word.slice(1);
    if (!rest) { index += 1; return word[0] === "1"; }
    if (!NUMBER.test(rest)) throw new PathError(`${quoted(rest)} at character ${starts[index] + 2} is not a number.`);
    starts[index] += 1;
    return word[0] === "1";
  };
  while (index < count) {
    if (types[index]) {
      command = types[index]; at = starts[index]; named = command; index += 1; repeated = false;
      if (command === "Z" || command === "z") {
        if (kinds.length && last() !== "Z") kinds.push("Z");
        here = start; cubic = null; quad = null;
        if (index < count && !types[index]) throw new PathError(`${quoted(text(index))} at character ${starts[index] + 1} follows Z, which takes no numbers: a command (L, C ...) comes before them.`);
        continue;
      }
    }
    const upper = command.toUpperCase(), relative = command !== upper;
    const ox = relative ? here[0] : 0, oy = relative ? here[1] : 0;
    const got = [];
    let large = false, sweep = false;
    if (upper === "A") {
      for (let n = 0; n < 3 && index < count && !types[index]; n += 1) { got.push(Number(text(index))); index += 1; }
      if (got.length < 3) throw new PathError(`${named} at character ${at + 1} needs 7 numbers (${SAYS.A})${repeated ? " at a time: some are left over." : ", but some are missing."}`);
      large = flag("large-arc");
      sweep = flag("sweep");
      for (let n = 0; n < 2; n += 1) {
        if (index >= count || types[index]) throw new PathError(`${named} at character ${at + 1} needs 7 numbers (${SAYS.A}), but its end is missing.`);
        got.push(Number(text(index))); index += 1;
      }
    } else {
      const takes = TAKES[upper];
      while (got.length < takes) {
        if (index >= count || types[index]) {
          const have = got.length;
          const has = repeated ? `${have} ${have === 1 ? "is" : "are"} left over` : `it has ${have || "none"}`;
          throw new PathError(`${named} at character ${at + 1} needs ${takes} numbers (${SAYS[named.toUpperCase()]})${repeated ? " at a time" : ""}, but ${has}.`);
        }
        got.push(Number(text(index))); index += 1;
      }
    }
    repeated = true;
    if (upper === "M") {
      const x = ox + got[0], y = oy + got[1];
      if (kinds.length && last() === "M") { values[values.length - 2] = x; values[values.length - 1] = y; }
      else { kinds.push("M"); values.push(x, y); }
      here = start = [x, y]; cubic = null; quad = null;
      command = relative ? "l" : "L";
      continue;
    }
    if (last() === "Z") { kinds.push("M"); values.push(start[0], start[1]); }
    if (upper === "L" || upper === "H" || upper === "V") {
      const point = upper === "L" ? [ox + got[0], oy + got[1]]
        : upper === "H" ? [(relative ? here[0] : 0) + got[0], here[1]] : [here[0], (relative ? here[1] : 0) + got[0]];
      kinds.push("L"); values.push(point[0], point[1]);
      here = point; cubic = null; quad = null;
    } else if (upper === "C" || upper === "S") {
      const first = upper === "C" ? [ox + got[0], oy + got[1]] : cubic ? [2 * here[0] - cubic[0], 2 * here[1] - cubic[1]] : here;
      const rest = upper === "C" ? 2 : 0;
      const second = [ox + got[rest], oy + got[rest + 1]], end = [ox + got[rest + 2], oy + got[rest + 3]];
      kinds.push("C"); values.push(first[0], first[1], second[0], second[1], end[0], end[1]);
      here = end; cubic = second; quad = null;
    } else if (upper === "Q" || upper === "T") {
      const control = upper === "Q" ? [ox + got[0], oy + got[1]] : quad ? [2 * here[0] - quad[0], 2 * here[1] - quad[1]] : here;
      const end = upper === "Q" ? [ox + got[2], oy + got[3]] : [ox + got[0], oy + got[1]];
      kinds.push("C");
      values.push(here[0] + 2 / 3 * (control[0] - here[0]), here[1] + 2 / 3 * (control[1] - here[1]),
        end[0] + 2 / 3 * (control[0] - end[0]), end[1] + 2 / 3 * (control[1] - end[1]), end[0], end[1]);
      here = end; cubic = null; quad = control;
    } else {
      const end = [ox + got[3], oy + got[4]];
      arc(here, got[0], got[1], got[2], large, sweep, end, kinds, values);
      here = end; cubic = null; quad = null;
    }
  }
  if (kinds.length && last() === "M") { kinds.pop(); values.length -= 2; }
  if (!kinds.some((kind) => kind === "L" || kind === "C")) throw new PathError(`d only moves: a path needs a line or a curve after its M, such as ${EXAMPLE}.`);
  if (kinds.length > MOST) throw new PathError(`d has ${grouped(kinds.length)} pieces: a path has ${grouped(MOST)} at most.`);
  let far = 0;
  for (const value of values) { const size = Math.abs(value); if (!(size <= far)) far = size; }
  if (!(far <= LIMIT)) throw new PathError(`d has a point ${said(far)} points from the page: a point must be on it, or near it.`);
  return { kinds: kinds.join(""), values };
}

// `data` as segments: ["M", x, y], ["L", x, y], ["C", x1, y1, x2, y2, x, y], ["Z"].
export const parse = (data) => { const found = read(data); return segmentsOf(found.kinds, found.values); };

function segmentsOf(kinds, values) {
  const out = new Array(kinds.length);
  let at = 0;
  for (let n = 0; n < kinds.length; n += 1) {
    const kind = kinds[n];
    if (kind === "Z") out[n] = ["Z"];
    else if (kind === "C") { out[n] = ["C", values[at], values[at + 1], values[at + 2], values[at + 3], values[at + 4], values[at + 5]]; at += 6; }
    else { out[n] = [kind, values[at], values[at + 1]]; at += 2; }
  }
  return out;
}

// -- what is read, kept --

// Path data as read: its letters and numbers, the box round what they draw ([x, y, w, h]),
// whether its first piece and its last are open, its segments (made when first wanted), and
// what is found from it, kept with it (`kept`). One moved is the one it was moved from, its
// numbers moved only when they are wanted. (`rounded`: its numbers are to a hundredth, as its
// words say them.)
class Read {
  constructor(kinds, values, box, { error = null, opens = null, rounded = false, source = null } = {}) {
    this.kinds = kinds; this.box = box; this.error = error; this.rounded = rounded;
    this.numbers = values; this.source = source; this.made = null; this.words_ = null; this.found = new Map();
    if (opens) this.opens = opens;
    else {
      const second = kinds.indexOf("M", 1), first = second < 0 ? kinds.length - 1 : second - 1;
      this.opens = kinds.length ? [kinds[first] !== "Z", kinds[kinds.length - 1] !== "Z"] : [false, false];
    }
  }
  get values() { if (!this.numbers) { this.numbers = this.source(); this.source = null; } return this.numbers; }
  get segments() { if (!this.made) this.made = segmentsOf(this.kinds, this.values); return this.made; }
  kept(key, make) { if (!this.found.has(key)) this.found.set(key, make()); return this.found.get(key); }
  // Its words, as a shape writes them: kept by them too, where its numbers are as they say.
  words() {
    if (this.words_ === null) {
      this.words_ = wordsOf(this.kinds, this.values);
      if (this.rounded && !this.error && !byWords.has(this.words_)) keep(this.words_, this);
    }
    return this.words_;
  }
}
const fresh = (kinds, values, options = {}) => {
  const [left, top, right, bottom] = extentOf(kinds, values);
  return new Read(kinds, values, [left, top, right - left, bottom - top], options);
};

const byWords = new Map();
const KEPT = 4096;
function keep(data, entry) {
  byWords.delete(data);
  byWords.set(data, entry);
  while (byWords.size > KEPT) byWords.delete(byWords.keys().next().value);
}

// `data` read and kept by its words. Written wrong, it is what was read before the mistake
// (nothing), its `error` saying what is wrong: the page draws what it can.
export function parsed(data) {
  data = String(data ?? "");
  const found = byWords.get(data);
  if (found) { byWords.delete(data); byWords.set(data, found); return found; }
  let entry;
  try { const { kinds, values } = read(data); entry = fresh(kinds, values); }
  catch (error) { if (!(error instanceof PathError)) throw error; entry = new Read("", [], [0, 0, 0, 0], { error: error.message }); }
  keep(data, entry);
  return entry;
}
// What is wrong with `data`, if anything, in the words flexo.pathdata says it in.
export const problem = (data) => parsed(data).error;

// A path shape's outline as read: kept with the shape where it was moved here (its words not
// yet written), else by the shape, else by its words.
const bySpec = new WeakMap();
export const heldBy = (spec) => Object.getOwnPropertyDescriptor(spec, "d")?.get?.entry || null;
export function parsedOf(spec) {
  const held = heldBy(spec);
  if (held) return held;
  const found = bySpec.get(spec);
  if (found && found.data === spec.d) return found.entry;
  const entry = parsed(spec.d);
  bySpec.set(spec, { data: spec.d, entry });
  return entry;
}
// `target`'s outline (`d`) given as `entry`'s, its words written only when first read.
export function lazily(target, entry) {
  let words = null;
  const get = () => (words ??= entry.words());
  get.entry = entry;
  Object.defineProperty(target, "d", {
    get, enumerable: true, configurable: true,
    set(value) { Object.defineProperty(target, "d", { value, writable: true, enumerable: true, configurable: true }); },
  });
  return target;
}
// A copy of `spec` -- its keys in their order -- its outline `entry`'s.
export function withOutline(spec, entry) {
  const made = {};
  for (const key of Object.keys(spec)) { if (key === "d") lazily(made, entry); else made[key] = spec[key]; }
  if (!("d" in made)) lazily(made, entry);
  return made;
}

// -- writing --

const hundredths = (value) => Math.round(value * 100);
// A number of hundredths as the words of what it is: 1234 "12.34", 1230 "12.3", -5 "-0.05".
function figure(k) {
  if (k === 0) return "0";
  const sign = k < 0 ? "-" : "", size = Math.abs(k), whole = Math.floor(size / 100), part = size % 100;
  if (!part) return `${sign}${whole}`;
  return `${sign}${whole}.${part < 10 ? `0${part}` : part % 10 ? part : part / 10}`;
}
function wordsOf(kinds, values) {
  const words = new Array(kinds.length + values.length);
  let at = 0, w = 0;
  for (let n = 0; n < kinds.length; n += 1) {
    const kind = kinds[n], takes = kind === "C" ? 6 : kind === "Z" ? 0 : 2;
    words[w++] = kind;
    for (let m = 0; m < takes; m += 1) words[w++] = figure(hundredths(values[at++]));
  }
  return words.join(" ");
}

// Segments as path data: absolute moves, lines, cubics and closes, to a hundredth.
export function written(segments) {
  return segments.map(([kind, ...values]) => [kind, ...values.map((value) => figure(hundredths(value)))].join(" ")).join(" ");
}
const rounded = (value) => hundredths(value) / 100;

// What is read moved by dx, dy: the same, its box moved now and its numbers when wanted.
export function shifted(entry, dx, dy) {
  if (entry.error) return entry;
  const [x, y, w, h] = entry.box;
  return new Read(entry.kinds, null, [x + dx, y + dy, w, h], { opens: entry.opens, rounded: true, source: () => {
    const from = entry.values, out = new Array(from.length);
    for (let n = 0; n < from.length; n += 2) { out[n] = rounded(from[n] + dx); out[n + 1] = rounded(from[n + 1] + dy); }
    return out;
  } });
}
// What is read with every point mapped (its curves' controls too: for a map that moves,
// stretches, turns or mirrors).
export function remapped(entry, map) {
  if (entry.error) return entry;
  const from = entry.values, out = new Array(from.length);
  for (let n = 0; n < from.length; n += 2) { const [x, y] = map([from[n], from[n + 1]]); out[n] = rounded(x); out[n + 1] = rounded(y); }
  return fresh(entry.kinds, out, { opens: entry.opens, rounded: true });
}
// Segments as what is read, to a hundredth: a path drawn or edited here, its words written only
// when they are first read.
export function readOf(segments) {
  let kinds = "";
  const values = [];
  for (const segment of segments) { kinds += segment[0]; for (let n = 1; n < segment.length; n += 1) values.push(rounded(segment[n])); }
  return fresh(kinds, values, { rounded: true });
}
export const normalised = (data) => remapped(parsed(data), (point) => point).words();
export const moved = (data, dx, dy) => shifted(parsed(data), dx, dy).words();
export const mapped = (data, map) => remapped(parsed(data), map).words();
// `data` stretched to fill `box` ([x, y, w, h]), as a polyline's points are round parts.
export function fitted(data, [x, y, w, h]) {
  const [left, top, across, down] = parsed(data).box;
  return mapped(data, ([px, py]) => [x + (px - left) / (across || 1) * w, y + (py - top) / (down || 1) * h]);
}

// -- geometry --

function roots(a, b, c) {
  let found;
  if (Math.abs(a) < 1e-12) {
    if (Math.abs(b) < 1e-12) return [];
    found = [-c / b];
  } else {
    const under = b * b - 4 * a * c;
    if (under < 0) return [];
    const root = Math.sqrt(under);
    found = [(-b + root) / (2 * a), (-b - root) / (2 * a)];
  }
  return found.filter((t) => t > 0 && t < 1);
}

// left, top, right, bottom of what is drawn by `kinds` and `values` -- a curve's own reach, not
// its controls' -- turned `turn` degrees about `centre`.
function extentOf(kinds, values, turn = 0, centre = [0, 0]) {
  const angle = turn * Math.PI / 180, cos = turn ? Math.cos(angle) : 1, sin = turn ? Math.sin(angle) : 0, ox = centre[0], oy = centre[1];
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity, hx = 0, hy = 0, at = 0;
  const reach = (p0, p1, p2, p3, low, high) => {
    let lo = low, hi = high;
    for (const t of roots(p3 - 3 * p2 + 3 * p1 - p0, 2 * (p0 - 2 * p1 + p2), p1 - p0)) {
      const u = 1 - t, value = u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3;
      if (value < lo) lo = value;
      if (value > hi) hi = value;
    }
    return [lo, hi];
  };
  for (let n = 0; n < kinds.length; n += 1) {
    const kind = kinds[n];
    if (kind === "Z") continue;
    const takes = kind === "C" ? 6 : 2;
    let ex = values[at + takes - 2], ey = values[at + takes - 1];
    if (turn) { const dx = ex - ox, dy = ey - oy; ex = ox + cos * dx - sin * dy; ey = oy + sin * dx + cos * dy; }
    if (ex < left) left = ex;
    if (ex > right) right = ex;
    if (ey < top) top = ey;
    if (ey > bottom) bottom = ey;
    if (kind === "C") {
      let ax = values[at], ay = values[at + 1], bx = values[at + 2], by = values[at + 3];
      if (turn) {
        let dx = ax - ox, dy = ay - oy; ax = ox + cos * dx - sin * dy; ay = oy + sin * dx + cos * dy;
        dx = bx - ox; dy = by - oy; bx = ox + cos * dx - sin * dy; by = oy + sin * dx + cos * dy;
      }
      if (!(left <= Math.min(ax, bx) && Math.max(ax, bx) <= right)) [left, right] = reach(hx, ax, bx, ex, left, right);
      if (!(top <= Math.min(ay, by) && Math.max(ay, by) <= bottom)) [top, bottom] = reach(hy, ay, by, ey, top, bottom);
    }
    hx = ex; hy = ey; at += takes;
  }
  return left > right ? [0, 0, 0, 0] : [left, top, right, bottom];
}
// left, top, right, bottom of what segments draw (their curves' own reach), turned as they are.
export function extent(segments, turn = 0, centre = [0, 0]) {
  let kinds = "";
  const values = [];
  for (const segment of segments) { kinds += segment[0]; for (let n = 1; n < segment.length; n += 1) values.push(segment[n]); }
  return extentOf(kinds, values, turn, centre);
}

function steps(p0, p1, p2, p3) {
  let reach = 0;
  for (const [a, b] of [[p0, p1], [p1, p2], [p2, p3]]) { const dx = b[0] - a[0], dy = b[1] - a[1]; reach += Math.sqrt(dx * dx + dy * dy); }
  return Math.max(1, Math.min(24, Math.ceil(Math.sqrt(reach) - 1e-9)));
}

// Each piece of a path as points along it (its curves cut into lines), and whether it is closed.
export function rings(segments) {
  const out = [];
  let points = [], here = [0, 0];
  for (const segment of segments) {
    const kind = segment[0];
    if (kind === "M") { if (points.length > 1) out.push([points, false]); here = [segment[1], segment[2]]; points = [here]; }
    else if (kind === "L") { here = [segment[1], segment[2]]; points.push(here); }
    else if (kind === "C") {
      const p1 = [segment[1], segment[2]], p2 = [segment[3], segment[4]], p3 = [segment[5], segment[6]], n = steps(here, p1, p2, p3);
      for (let step = 1; step < n; step += 1) {
        const t = step / n, u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
        points.push([a * here[0] + b * p1[0] + c * p2[0] + d * p3[0], a * here[1] + b * p1[1] + c * p2[1] + d * p3[1]]);
      }
      points.push(p3); here = p3;
    } else { out.push([points, true]); points = []; }
  }
  if (points.length > 1) out.push([points, false]);
  return out;
}

// Where the line from `inside` to `outside` last crosses any of `outlines` (each closed).
export function crossing(outlines, inside, outside) {
  let best = -1;
  const [ax, ay] = inside, [bx, by] = outside, ex = bx - ax, ey = by - ay;
  for (const outline of outlines) {
    if (outline.length < 2) continue;
    let [cx, cy] = outline[outline.length - 1];
    for (const [dx, dy] of outline) {
      const fx = dx - cx, fy = dy - cy, below = ex * fy - ey * fx;
      if (Math.abs(below) >= 1e-12) {
        const t = ((cx - ax) * fy - (cy - ay) * fx) / below, u = ((cx - ax) * ey - (cy - ay) * ex) / below;
        if (t >= 0 && t <= 1 && u >= 0 && u <= 1 && t > best) best = t;
      }
      cx = dx; cy = dy;
    }
  }
  return best < 0 ? null : [ax + ex * best, ay + ey * best];
}

// The point on any of `outlines` (each closed) nearest `point`.
export function nearest(outlines, [px, py]) {
  let best = null;
  for (const outline of outlines) {
    if (!outline.length) continue;
    let [ax, ay] = outline[outline.length - 1];
    for (const [bx, by] of outline) {
      const dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy;
      const t = length ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / length)) : 0;
      const qx = ax + dx * t, qy = ay + dy * t, far = (px - qx) * (px - qx) + (py - qy) * (py - qy);
      if (!best || far < best[0]) best = [far, [qx, qy]];
      ax = bx; ay = by;
    }
  }
  return best ? best[1] : null;
}

// How far `point` is from any of `outlines` (each closed, or open where `closed` says so).
export function distance(outlines, [px, py], closed = null) {
  let best = Infinity;
  outlines.forEach((outline, n) => {
    const shut = closed ? closed[n] : true;
    for (let m = shut ? 0 : 1; m < outline.length; m += 1) {
      const [ax, ay] = outline[m === 0 ? outline.length - 1 : m - 1], [bx, by] = outline[m];
      const dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy;
      const t = length ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / length)) : 0;
      const far = Math.hypot(px - (ax + dx * t), py - (ay + dy * t));
      if (far < best) best = far;
    }
  });
  return best;
}

// Whether `point` is in what `outlines` (each closed) fill, by the fill `rule`.
export function inside(outlines, [px, py], rule = "nonzero") {
  let winding = 0;
  for (const outline of outlines) {
    if (outline.length < 3) continue;
    let [ax, ay] = outline[outline.length - 1];
    for (const [bx, by] of outline) {
      if ((ay > py) !== (by > py) && px < (bx - ax) * (py - ay) / (by - ay) + ax) winding += by > ay ? 1 : -1;
      ax = bx; ay = by;
    }
  }
  return rule === "evenodd" ? Math.abs(winding) % 2 === 1 : winding !== 0;
}

// A path placed on its page -- mirrored and turned about its box's middle -- as what a line is
// glued to: its rings on the page (`rings()`), and where a line meets it on each side
// (`sites()`): on its outline, level with its middle (or straight above, below it).
export function outline(entry, flip, turn) {
  flip = flip || null; turn = Number(turn || 0);
  const [x, y, w, h] = entry.box, cx = x + w / 2, cy = y + h / 2;
  const turned = ([px, py]) => {
    if (!turn) return [px, py];
    const angle = turn * Math.PI / 180, cos = Math.cos(angle), sin = Math.sin(angle), dx = px - cx, dy = py - cy;
    return [cx + cos * dx - sin * dy, cy + sin * dx + cos * dy];
  };
  const local = () => entry.kept(`local ${flip}`, () => {
    const plain = entry.kept("rings", () => rings(entry.segments));
    if (!flip) return plain.map(([points]) => points);
    const sx = flip === "horizontal" || flip === "both" ? -1 : 1, sy = flip === "vertical" || flip === "both" ? -1 : 1;
    return plain.map(([points]) => points.map(([px, py]) => [cx + sx * (px - cx), cy + sy * (py - cy)]));
  });
  return {
    box: entry.box, centre: [cx, cy], flip, turn, entry, local,
    rings: () => entry.kept(`rings ${flip} ${turn}`, () => (turn ? local().map((ring) => ring.map(turned)) : local())),
    sites: () => entry.kept(`sites ${flip} ${turn}`, () => {
      const places = { top: [cx, y], right: [x + w, cy], bottom: [cx, y + h], left: [x, cy] }, found = {};
      for (const [side, [px, py]] of Object.entries(places)) {
        const far = [cx + (px - cx) * 1.01, cy + (py - cy) * 1.01];
        const met = far[0] !== cx || far[1] !== cy ? crossing(local(), [cx, cy], far) : null;
        found[side] = turned(met || nearest(local(), [px, py]) || [px, py]);
      }
      found.centre = [cx, cy];
      return found;
    }),
  };
}
