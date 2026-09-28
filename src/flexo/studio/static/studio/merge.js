// Three-way merge of JSON documents: the page's copy of flexo/studio/merge.py.
// merge3(base, ours, theirs) keeps what either side changed from base; where both
// changed one thing differently, theirs wins.

export function merge3(base, ours, theirs) {
  if (same(ours, theirs) || same(base, theirs)) return ours;
  if (same(base, ours)) return theirs;
  if (isMap(ours) && isMap(theirs)) return mergeMaps(isMap(base) ? base : {}, ours, theirs);
  if (Array.isArray(ours) && Array.isArray(theirs)) return mergeLists(Array.isArray(base) ? base : [], ours, theirs);
  if (typeof ours === "string" && typeof theirs === "string" && typeof base === "string"
      && (base.includes("\n") || ours.includes("\n") || theirs.includes("\n"))) {
    return mergeLists(lines(base), lines(ours), lines(theirs)).join("");
  }
  return theirs;
}

const MISSING = Symbol("missing");
const isMap = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const lines = (text) => text.match(/[^\n]*\n|[^\n]+$/g) || [];

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
  const keysBase = base.map(key);
  const toOurs = matches(keysBase, ours.map(key));
  const toTheirs = matches(keysBase, theirs.map(key));
  const anchors = [];
  for (let i = 0; i < base.length; i++) if (toOurs.has(i) && toTheirs.has(i)) anchors.push([i, toOurs.get(i), toTheirs.get(i)]);
  anchors.push([base.length, ours.length, theirs.length]);
  const result = [];
  let b = 0, o = 0, t = 0;
  for (const [ab, ao, at] of anchors) {
    result.push(...chunk(base.slice(b, ab), ours.slice(o, ao), theirs.slice(t, at)));
    if (ab < base.length) result.push(ours[ao]);
    b = ab + 1; o = ao + 1; t = at + 1;
  }
  return result;
}

function chunk(base, ours, theirs) {
  if (same(ours, base)) return [...theirs];
  if (same(theirs, base) || same(ours, theirs)) return [...ours];
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

export function same(first, second) {
  if (first === second) return true;
  if (typeof first !== typeof second) return false;
  if (typeof first !== "object" || first === null || second === null) return false;
  return stable(first) === stable(second);
}
