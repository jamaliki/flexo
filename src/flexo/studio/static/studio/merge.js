// Three-way merge of JSON documents: the page's copy of flexo/studio/merge.py.
// merge3(base, ours, theirs) keeps what either side changed from base. Lists merge item
// by item, each item known by what it was (a slide edited by one side and moved by the
// other is the edited slide, moved); words merge line by line, then word by word; where
// both changed one thing differently, theirs wins.

export function merge3(base, ours, theirs) {
  if (same(ours, theirs) || same(base, theirs)) return ours;
  if (same(base, ours)) return theirs;
  if (isMap(ours) && isMap(theirs)) return mergeMaps(isMap(base) ? base : {}, ours, theirs);
  if (Array.isArray(ours) && Array.isArray(theirs)) return mergeItems(Array.isArray(base) ? base : [], ours, theirs);
  if (typeof ours === "string" && typeof theirs === "string" && typeof base === "string") return mergeText(base, ours, theirs);
  return theirs;
}

const MISSING = Symbol("missing");
const isMap = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const lines = (text) => text.match(/[^\n]*\n|[^\n]+$/g) || [];
const WORDS = /[\p{L}\p{N}_]+|\s+|[^\p{L}\p{N}_\s]/gu;
const WORDS_ONLY = /[\p{L}\p{N}_]+/gu;

// Two edits of words: line by line, and lines both changed word by word, so two people
// typing in one field keep both their words. A single word (a name, a colour) is not
// taken apart: where both changed it, theirs wins.
export function mergeText(base, ours, theirs) {
  if (ours === theirs || base === theirs) return ours;
  if (base === ours) return theirs;
  if (base.includes("\n") || ours.includes("\n") || theirs.includes("\n")) return diff3(lines(base), lines(ours), lines(theirs), linesChunk).join("");
  return mergeWords(base, ours, theirs);
}

function mergeWords(base, ours, theirs) {
  if (![base, ours, theirs].some((text) => /\s/.test(text))) return theirs;
  const words = (text) => text.match(WORDS) || [];
  return diff3(words(base), words(ours), words(theirs), wordsChunk).join("");
}

const linesChunk = (base, ours, theirs) => (base.length ? [mergeWords(base.join(""), ours.join(""), theirs.join(""))] : [...ours, ...theirs]);
const wordsChunk = (base, ours, theirs) => (base.length ? [...theirs] : [...ours, ...theirs]);

function mergeMaps(base, ours, theirs) {
  const result = {};
  const keys = [...Object.keys(ours), ...Object.keys(theirs).filter((key) => !(key in ours))];
  for (const key of keys) {
    const was = key in base ? base[key] : MISSING;
    const mine = key in ours ? ours[key] : MISSING;
    const other = key in theirs ? theirs[key] : MISSING;
    if (mine !== MISSING && other !== MISSING) result[key] = merge3(was === MISSING ? null : was, mine, other);
    else if (mine !== MISSING) { if (was === MISSING) result[key] = mine; }
    else if (was === MISSING || !same(was, other)) result[key] = other;
  }
  return result;
}

export function mergeLists(base, ours, theirs) {
  return diff3(base, ours, theirs, chunk);
}

// Two edits of a list of items, merged by the items' identities: each side's items are
// paired with the items of base they were.
export function mergeItems(base, ours, theirs) {
  const toOurs = pairsOf(base, ours), toTheirs = pairsOf(base, theirs);
  const fromOurs = new Map([...toOurs].map(([i, j]) => [j, i]));
  const fromTheirs = new Map([...toTheirs].map(([i, k]) => [k, i]));
  // Items both sides added alike are one item.
  const twins = new Map(), added = new Map();
  ours.forEach((item, j) => { if (!fromOurs.has(j)) { const k = key(item); if (!added.has(k)) added.set(k, []); added.get(k).push(j); } });
  theirs.forEach((item, k) => { if (!fromTheirs.has(k) && added.get(key(item))?.length) twins.set(k, added.get(key(item)).shift()); });
  const seqOurs = ours.map((_, j) => (fromOurs.has(j) ? `b:${fromOurs.get(j)}` : `o:${j}`));
  const seqTheirs = theirs.map((_, k) => (fromTheirs.has(k) ? `b:${fromTheirs.get(k)}` : twins.has(k) ? `o:${twins.get(k)}` : `t:${k}`));
  const content = new Map();
  base.forEach((was, i) => {
    const j = toOurs.get(i), k = toTheirs.get(i);
    if (j !== undefined && k !== undefined) content.set(`b:${i}`, merge3(was, ours[j], theirs[k]));
    else if (j !== undefined && !same(ours[j], was)) content.set(`b:${i}`, ours[j]);  // removed by them, edited by us: kept, edited
    else if (k !== undefined && !same(theirs[k], was)) content.set(`b:${i}`, theirs[k]);
  });
  for (const id of seqOurs) if (id.startsWith("o:")) content.set(id, ours[Number(id.slice(2))]);
  for (const id of seqTheirs) if (id.startsWith("t:")) content.set(id, theirs[Number(id.slice(2))]);
  // The order: the side that moved items has its order (theirs, if both did); the other
  // side's items not in it go after the item they followed there, after the first side's
  // own additions at that place.
  const moved = (seq) => {
    const kept = seq.filter((id) => id.startsWith("b:")).map((id) => Number(id.slice(2)));
    return kept.some((value, n) => n > 0 && value < kept[n - 1]);
  };
  const [first, second] = moved(seqTheirs) ? [seqTheirs, seqOurs] : [seqOurs, seqTheirs];
  const order = first.filter((id) => content.has(id));
  const placed = new Set(order);
  const own = new Set(first.filter((id) => !id.startsWith("b:")));
  let previous = null;
  for (const id of second) {
    if (placed.has(id)) { previous = id; continue; }
    if (!content.has(id)) continue;
    let at = previous !== null ? order.indexOf(previous) + 1 : 0;
    while (at < order.length && own.has(order[at])) at++;
    order.splice(at, 0, id);
    placed.add(id);
    previous = id;
  }
  return order.map((id) => content.get(id));
}

// How alike an item must be to an item of base to be taken for it (see alike).
const ALIKE = 0.4;
const movable = (item) => typeof item === "string" || (item !== null && typeof item === "object");

// Which item of side each item of base became: the same item where it is in order (a
// longest common subsequence), or moved; else, between items kept, the most alike of
// the items changed; else, as many changed as there were, each in turn.
function pairsOf(base, side) {
  const keysBase = base.map(key), keysSide = side.map(key);
  const pairs = matches(keysBase, keysSide);
  const anchors = [...pairs].sort((a, b) => a[0] - b[0]);
  const used = new Set(pairs.values());
  // Moved: the same item elsewhere (a word, a slide), never a number or a flag.
  const free = new Map();
  side.forEach((item, j) => { if (!used.has(j) && movable(item)) { if (!free.has(keysSide[j])) free.set(keysSide[j], []); free.get(keysSide[j]).push(j); } });
  base.forEach((item, i) => {
    if (!pairs.has(i) && movable(item) && free.get(keysBase[i])?.length) { const j = free.get(keysBase[i]).shift(); pairs.set(i, j); used.add(j); }
  });
  // Changed: between two items kept in order, the most alike first, then the rest in turn.
  const bounds = [[-1, -1], ...anchors, [base.length, side.length]];
  for (let n = 0; n + 1 < bounds.length; n++) {
    const [lowB, lowS] = bounds[n], [highB, highS] = bounds[n + 1];
    let gone = [], come = [];
    for (let i = lowB + 1; i < highB; i++) if (!pairs.has(i)) gone.push(i);
    for (let j = lowS + 1; j < highS; j++) if (!used.has(j)) come.push(j);
    if (!gone.length || !come.length) continue;
    const scored = [];
    for (const i of gone) for (const j of come) {
      const score = alike(base[i], side[j]);
      if (score >= ALIKE) scored.push([-score, Math.abs((i - lowB) / (highB - lowB) - (j - lowS) / (highS - lowS)), i, j]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3]);
    for (const [, , i, j] of scored) if (!pairs.has(i) && !used.has(j)) { pairs.set(i, j); used.add(j); }
    gone = gone.filter((i) => !pairs.has(i));
    come = come.filter((j) => !used.has(j));
    if (gone.length === come.length) gone.forEach((i, m) => { if (kin(base[i], side[come[m]])) { pairs.set(i, come[m]); used.add(come[m]); } });
  }
  return pairs;
}

// Where each item of `before` is in `after` (its index, or -1 if it is gone): paired as
// a merge pairs them, then, for one moved and changed at once (a paragraph moved while
// someone typed in it), the most alike of those left, wherever it went.
export function follows(before, after) {
  const pairs = pairsOf(before, after);
  const used = new Set(pairs.values());
  const scored = [];
  before.forEach((item, i) => {
    if (pairs.has(i)) return;
    after.forEach((other, j) => {
      if (used.has(j)) return;
      const score = alike(item, other);
      if (score >= ALIKE) scored.push([score, i, j]);
    });
  });
  scored.sort((a, b) => b[0] - a[0] || a[1] - b[1] || a[2] - b[2]);
  for (const [, i, j] of scored) if (!pairs.has(i) && !used.has(j)) { pairs.set(i, j); used.add(j); }
  return before.map((_, i) => (pairs.has(i) ? pairs.get(i) : -1));
}

const kindOf = (item) => (typeof item === "boolean" ? "flag" : typeof item === "number" ? "number" : typeof item === "string" ? "str"
  : item === null || item === undefined ? "none" : Array.isArray(item) ? "list" : "dict");

// Whether one item could have become the other: of one kind, and a mapping with a key of
// the other's (with an id, the same id).
function kin(first, second) {
  if (kindOf(first) !== kindOf(second)) return false;
  if (isMap(first)) {
    if (Object.hasOwn(first, "id") && Object.hasOwn(second, "id")) return same(first.id, second.id);
    const keys = Object.keys(first);
    return keys.some((k) => Object.hasOwn(second, k)) || !keys.length || !Object.keys(second).length;
  }
  return true;
}

// How alike two items are, from 0 to 1: words by the letters they share at their ends
// and the words they share; mappings by their values, key by key (with an id, by it
// alone); lists by their items, place by place.
function alike(first, second) {
  if (same(first, second)) return 1;
  if (!kin(first, second)) return 0;
  if (typeof first === "string") {
    if (!first || !second) return 0.5;
    const a = [...first], b = [...second];
    const most = Math.min(a.length, b.length);
    let start = 0;
    while (start < most && a[start] === b[start]) start++;
    let end = 0;
    while (end < most - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
    const ends = (start + end) / ((a.length + b.length) / 2);
    const wordsA = new Set(first.toLowerCase().match(WORDS_ONLY) || []), wordsB = new Set(second.toLowerCase().match(WORDS_ONLY) || []);
    const union = new Set([...wordsA, ...wordsB]);
    const shared = union.size ? [...wordsA].filter((word) => wordsB.has(word)).length / union.size : 0;
    return Math.max(ends, shared);
  }
  if (isMap(first)) {
    if (Object.hasOwn(first, "id") && Object.hasOwn(second, "id")) return 1;
    const keys = [...new Set([...Object.keys(first), ...Object.keys(second)])].sort();  // in one order, as the server adds them
    let total = 0;
    for (const k of keys) {
      if (Object.hasOwn(first, k) && Object.hasOwn(second, k)) total += same(first[k], second[k]) ? 1 : 0.25 + 0.75 * alike(first[k], second[k]);
    }
    return total / keys.length;
  }
  if (Array.isArray(first)) {
    const longest = Math.max(first.length, second.length);
    if (!longest) return 1;
    let total = 0;
    for (let n = 0; n < Math.min(first.length, second.length); n++) total += same(first[n], second[n]) ? 1 : 0.5 * alike(first[n], second[n]);
    return total / longest;
  }
  return 0;
}

// The items of base both sides kept hold the merge together; between them, the side
// that changed something has it, and `both` settles what both sides changed.
function diff3(base, ours, theirs, both) {
  const keysBase = base.map(key);
  const toOurs = matches(keysBase, ours.map(key));
  const toTheirs = matches(keysBase, theirs.map(key));
  const anchors = [];
  for (let i = 0; i < base.length; i++) if (toOurs.has(i) && toTheirs.has(i)) anchors.push([i, toOurs.get(i), toTheirs.get(i)]);
  anchors.push([base.length, ours.length, theirs.length]);
  const result = [];
  let b = 0, o = 0, t = 0;
  for (const [ab, ao, at] of anchors) {
    const was = base.slice(b, ab), mine = ours.slice(o, ao), other = theirs.slice(t, at);
    if (same(mine, was)) result.push(...other);
    else if (same(other, was) || same(mine, other)) result.push(...mine);
    else result.push(...both(was, mine, other));
    if (ab < base.length) result.push(ours[ao]);
    b = ab + 1; o = ao + 1; t = at + 1;
  }
  return result;
}

function chunk(base, ours, theirs) {
  if (!base.length) return [...ours, ...theirs];
  if (base.length === ours.length && ours.length === theirs.length) return base.map((was, i) => merge3(was, ours[i], theirs[i]));
  return [...theirs];
}

function matches(first, second) {
  let start = 0;
  while (start < first.length && start < second.length && first[start] === second[start]) start++;
  let endA = first.length, endB = second.length;
  while (endA > start && endB > start && first[endA - 1] === second[endB - 1]) { endA--; endB--; }
  const matched = new Map();
  for (let i = 0; i < start; i++) matched.set(i, i);
  const a = first.slice(start, endA), b = second.slice(start, endB);
  if (a.length && b.length) {
    const rows = a.length, cols = b.length;
    const table = Array.from({ length: rows + 1 }, () => new Int32Array(cols + 1));
    for (let i = rows - 1; i >= 0; i--) for (let j = cols - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
    let i = 0, j = 0;
    while (i < rows && j < cols) {
      if (a[i] === b[j]) { matched.set(start + i, start + j); i++; j++; }
      else if (table[i + 1][j] >= table[i][j + 1]) i++;
      else j++;
    }
  }
  for (let offset = 0; offset < first.length - endA; offset++) matched.set(endA + offset, endB + offset);
  return matched;
}

function key(item) {
  return typeof item === "string" ? item : stable(item);
}

// JSON with sorted keys, so equal documents compare equal whatever their key order.
export function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (isMap(value)) return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${stable(value[k])}`).join(",")}}`;
  return JSON.stringify(value === undefined ? null : value);
}

// Whether two documents are equal, as ``stable`` would find them, without writing
// either out: it stops at the first difference and allocates nothing, so it can
// run on every keystroke.
export function same(first, second) {
  if (first === second) return true;
  if (first === undefined) first = null;
  if (second === undefined) second = null;
  if (first === second) return true;
  if (typeof first !== "object" || typeof second !== "object" || first === null || second === null) return false;
  const list = Array.isArray(first);
  if (list !== Array.isArray(second)) return false;
  if (list) {
    if (first.length !== second.length) return false;
    for (let index = 0; index < first.length; index++) if (!same(first[index], second[index])) return false;
    return true;
  }
  const keys = Object.keys(first);
  if (keys.length !== Object.keys(second).length) return false;
  for (const key of keys) if (!Object.hasOwn(second, key) || !same(first[key], second[key])) return false;
  return true;
}
