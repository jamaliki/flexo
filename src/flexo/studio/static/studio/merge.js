// Three-way merge of JSON documents: the page's copy of flexo/studio/merge.py.
// merge3(base, ours, theirs) keeps what either side changed from base. Lists merge item
// by item, each item known by what it was (a slide edited by one side and moved by the
// other is the edited slide, moved); words merge line by line, then word by word; where
// both changed one thing differently, theirs wins -- but words one side wrote anew while
// the other typed in them are kept whole, with the other's words after them.
//
// `notes`, an array, if given, is told what was settled for someone: { kept: side, item },
// an item the other side removed kept for `side` ("ours" or "theirs"), who edited it;
// { rewritten: side, words, typed }, words `side` wrote anew, kept whole, and the other's
// `typed` after them.
//
// replay(base, target, now) makes a change again (or takes it back: `target` what it was
// before) on the document as it is now, which wins every conflict (see replay).

export function merge3(base, ours, theirs, notes = null) {
  if (same(ours, theirs) || same(base, theirs)) return ours;
  if (same(base, ours)) return theirs;
  if (isMap(ours) && isMap(theirs)) {
    // Made again, a figure's change is made whole or not at all: a shape put between two
    // others is not taken back from under the label someone has since given it, leaving it
    // stranded with the lines it was put in by gone -- the figure stays as they have it.
    const missed = replaying?.length;
    const [followedBase, followedOurs, followedTheirs] = followed(isMap(base) ? base : {}, ours, theirs);
    const merged = mergeMaps(followedBase, followedOurs, followedTheirs, notes);
    return replaying && replaying.length > missed && (Array.isArray(theirs.nodes) || Array.isArray(theirs.edges)) ? theirs : merged;
  }
  if (Array.isArray(ours) && Array.isArray(theirs)) return mergeItems(Array.isArray(base) ? base : [], ours, theirs, notes);
  if (typeof ours === "string" && typeof theirs === "string" && typeof base === "string") return mergeText(base, ours, theirs, notes);
  replaying?.push({ changed: theirs });
  return theirs;
}

// -- a change made again on the document as it is now --
// replay(base, target, now): the change from `base` to `target` (an undo's, or a redo's)
// made on `now` -- merged as merge3 merges, but `now` wins every conflict, as no one's work is
// undone by someone else's undo: words others wrote since stay, letter by letter, in among
// the change's own (replayText); an item someone has removed since stays removed, and a
// setting or an item they have changed since stays as they have it; items are known by what
// they were wherever they have moved, changed too (follows). [document, lost]: `lost`, what
// of the change could not be made, for its person to be told ({ changed }, { removed },
// { kept }, { words }).
let replaying = null;
export function replay(base, target, now) {
  const outer = replaying;
  replaying = [];
  try {
    const document = merge3(base, target, now);
    return [document, replaying];
  } finally {
    replaying = outer;
  }
}

const MISSING = Symbol("missing");
const isMap = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const lines = (text) => text.match(/[^\n]*\n|[^\n]+$/g) || [];
const WORDS = /[\p{L}\p{N}_]+|\s+|[^\p{L}\p{N}_\s]/gu;
const WORDS_ONLY = /[\p{L}\p{N}_]+/gu;

// Two edits of words: line by line, and lines both changed word by word, so two people
// typing in one field keep both their words. A single word (a name, a colour) is not
// taken apart: where both changed it, theirs wins.
export function mergeText(base, ours, theirs, notes = null) {
  if (ours === theirs || base === theirs) return ours;
  if (base === ours) return theirs;
  if (replaying) {
    // Words over several lines -- a file's (a figure's) -- are made again whole or not at all:
    // part of a change taken back from lines others have changed would leave them half made.
    const missed = replaying.length;
    const replayed = replayText(base, ours, theirs);
    if (replayed !== null && replaying.length > missed && base.includes("\n")) return theirs;
    if (replayed !== null) return replayed;
  }
  if (base.includes("\n") || ours.includes("\n") || theirs.includes("\n")) {
    return diff3(lines(base), lines(ours), lines(theirs), (...chunk) => linesChunk(...chunk, notes)).join("");
  }
  return mergeWords(base, ours, theirs, notes);
}

function mergeWords(base, ours, theirs, notes = null) {
  if (![base, ours, theirs].some((text) => /\s/.test(text))) {
    replaying?.push({ changed: theirs });
    return theirs;
  }
  const words = [base, ours, theirs].map((text) => text.match(WORDS) || []);
  // Words one side wrote anew while the other typed in them would be held together only by
  // the spaces and a stray word they share, and come out a jumble of both: they are kept
  // whole, and the other's own words after them, in one piece. (Both written anew, the
  // newer stands, as for any words changed both ways.)
  for (const [side, other, name] of [[words[2], words[1], "theirs"], [words[1], words[2], "ours"]]) {
    if (!rewritten(words[0], side) || rewritten(words[0], other)) continue;
    const kept = side.join(""), [typed, onto] = typedIn(words[0], other);
    // Within a line's end, and run on from the word they were typed onto, if the kept words
    // end with it (the typing kept before, typed on).
    const body = kept.replace(/\n+$/, ""), end = kept.slice(body.length);
    if (!typed.trim()) return body + (/\s$/.test(body) ? "" : typed) + end;
    const joined = !body || /\s$/.test(body) || (onto && body.endsWith(onto));
    const merged = body + (joined || CLOSING.test(typed) ? "" : " ") + typed + end;
    notes?.push({ rewritten: name, words: merged, typed: typed.trim() });
    return merged;
  }
  return diff3(...words, wordsChunk, true).join("");
}

const CLOSING = /^[.,;:!?)\]}\u201d\u2019]/;
const LETTER = /[\p{L}\p{N}_]/u;
const isWord = (token) => /^[\p{L}\p{N}_]+$/u.test(token);

// Whether `side` is words written anew over `base`: fewer than half of base's words kept,
// and words of its own.
function rewritten(base, side) {
  const was = base.filter(isWord), now = side.filter(isWord);
  const kept = matches(was, now).size;
  return kept * 2 < was.length && now.length > kept;
}

// What `side` has that `base` has not, in one piece: the words put in each place (the
// letters typed into a word of base's, where they run into it, its space not typed yet),
// and the space typed after the last, for the words to go on after it; and the letters of
// the word the first was typed onto, if it ran on from one. ([typed, onto])
function typedIn(base, side) {
  const runs = [];  // each, and the words of `side` before it
  let b = 0, s = 0;
  for (const [i, j] of [...[...matches(base, side)].sort((x, y) => x[0] - y[0]), [base.length, side.length]]) {
    const was = [...base.slice(b, i).join("")], now = [...side.slice(s, j).join("")];
    let [start, end] = ends(was, now);
    if (start + end < was.length) [start, end] = [0, 0];
    const run = now.slice(start, now.length - end).join("");
    if (run) runs.push([run, side.slice(0, s).join("") + now.slice(0, start).join("")]);
    b = i + 1; s = j + 1;
  }
  if (!runs.length) return ["", ""];
  const words = runs.map(([run]) => run.trim()).filter(Boolean).join(" ");
  const [first, before] = runs.find(([run]) => run.trim()) || runs[0];
  const onto = /^\s/.test(first) ? "" : /\S*$/.exec(before)[0];
  return [words + /\s*$/.exec(runs[runs.length - 1][0])[0], onto];
}

// How many letters `was` and `now` (arrays of them) have alike at their start, and then at
// their end.
function ends(was, now) {
  let start = 0;
  while (start < was.length && start < now.length && was[start] === now[start]) start++;
  let end = 0;
  while (end < was.length - start && end < now.length - start && was[was.length - 1 - end] === now[now.length - 1 - end]) end++;
  return [start, end];
}

// Where in `was` (an array of letters) letters were typed in one place to make `now`, and
// what they were ([at, typed]; null if it was not so).
function insertion(was, now) {
  const [start, end] = ends(was, now);
  if (start + end < was.length || now.length === was.length) return null;
  return [start, now.slice(start, now.length - end).join("")];
}

// What was typed into `was` in one place to make `now` (null if it was not so), with the
// spaces about it that `was` had: the words round it may go.
function inserted(wasText, nowText) {
  const was = [...wasText];
  const found = insertion(was, [...nowText]);
  if (!found) return null;
  const [start, typed] = found;
  const lead = /^\s/.test(typed) ? "" : /^\s*/.exec(was.slice(0, start).join(""))[0];
  const tail = /\s$/.test(typed) ? "" : /\s*$/.exec(was.slice(start).join(""))[0];
  return lead + typed + tail;
}

const linesChunk = (base, ours, theirs, notes) => (base.length ? [mergeWords(base.join(""), ours.join(""), theirs.join(""), notes)] : [...ours, ...theirs]);
function wordsChunk(base, ours, theirs) {
  if (!base.length) {
    // Words both put at one place (two people typing on at the same end): ours, then theirs,
    // never run together into one word.
    const joins = ours.length && theirs.length && endsWord(ours) && startsWord(theirs);
    return joins ? [...ours, " ", ...theirs] : [...ours, ...theirs];
  }
  // Words one side took away while the other typed among them: they go, and the typing stays.
  for (const [gone, typing] of [[ours, theirs], [theirs, ours]]) {
    const typed = gone.length ? null : inserted(base.join(""), typing.join(""));
    if (typed !== null) return [typed];
  }
  const merged = letters([...base.join("")], [...ours.join("")], [...theirs.join("")]);
  if (merged === null) replaying?.push({ changed: theirs.join("") });
  return merged !== null ? [merged] : [...theirs];
}

// Two changes to the same words (arrays of letters), each run of letters they changed in a
// place of its own (one typing on just after what the other took away; two typing at one
// place; one making a word bold, at its ends, while the other types in it), all made, letter
// by letter; null where two overlap. At one place, letters that run on from the word before
// go first (someone typing on in it), then the other's (ours first, if both or neither do).
function letters(was, ours, theirs) {
  const spaced = (edit) => (/^\s/.test(edit[2]) ? 1 : 0);
  const edits = [...runsOf(was, ours), ...runsOf(was, theirs)].sort((a, b) => a[0] - b[0] || a[1] - b[1] || spaced(a) - spaced(b));
  let merged = "", at = 0, typed = null;
  for (const [start, end, put] of edits) {
    if (start < at) return null;
    // Two starting words at one place: they never run together into one (two typing on in
    // one word -- "m" made "m4" and "mc" -- keep its letters together).
    const fresh = start === 0 || !LETTER.test(was[start - 1]);
    const both = typed === start && start === end && fresh && put && endsWord([...merged]) && startsWord([...put]);
    merged += was.slice(at, start).join("") + (both ? " " : "") + put;
    typed = start === end ? start : null;
    at = end;
  }
  return merged + was.slice(at).join("");
}

// Whether words (tokens, or letters) end, or start, with a word's letter -- a mark put among
// them (the page's caret, a private letter) passed over.
const PRIVATE = /^[\ue000-\uf8ff]$/u;
function endsWord(tokens) {
  for (let n = tokens.length - 1; n >= 0; n--) if (!PRIVATE.test(tokens[n])) return LETTER.test(tokens[n].at(-1) ?? "");
  return false;
}
function startsWord(tokens) {
  for (const token of tokens) if (!PRIVATE.test(token)) return LETTER.test(token[0] ?? "");
  return false;
}

// The runs of letters a change put in place of others, `was` to `now` (arrays of letters):
// [start, end, put] in order. Letters kept between two runs, no more of them than either run
// changed, are part of them: a word written anew is one run, not the letters it happens to
// share with the old.
function runsOf(was, now, pairs = [...matches(was, now)].sort((a, b) => a[0] - b[0])) {
  const runs = [];
  let i = 0, j = 0;
  for (const [a, b] of [...pairs, [was.length, now.length]]) {
    if (a > i || b > j) runs.push([i, a, now.slice(j, b).join("")]);
    i = a + 1;
    j = b + 1;
  }
  const size = ([start, end, put]) => Math.max(end - start, [...put].length);
  for (let n = 0; n + 1 < runs.length;) {
    const [first, second] = [runs[n], runs[n + 1]], between = second[0] - first[1];
    if (between > size(first) || between > size(second)) { n += 1; continue; }
    runs.splice(n, 2, [first[0], second[1], first[2] + was.slice(first[1], second[0]).join("") + second[2]]);
    n = Math.max(0, n - 1);
  }
  return runs;
}

// The change from `base` to `target` (words) made on `now`, letter by letter: the letters it
// took away go where they still are, the letters it put in go where their place still is,
// and the letters others typed since -- in among its own, too -- stay. Where it took words
// away, the spaces about them are not left doubled (nor at the start, or the end, unless
// `target` has them there). Letters put back where all about them has gone since are not (see
// replay). Null where there is nothing to follow (`base` empty, or the texts too far apart).
function replayText(base, target, now) {
  if (!base) return null;
  const was = [...base], to = [...target], at = [...now];
  const toTarget = lettersKept(was, to), toNow = lettersKept(was, at);
  if (!toTarget || !toNow) return null;
  // Where each letter is now (-1: gone), its own letters among others' written anew since --
  // a few letters they happen to share -- taken as gone with the rest (runsOf).
  const where = new Int32Array(was.length).fill(-1);
  let from = 0, into = 0;
  for (const [start, end, words] of [...runsOf(was, at, toNow), [was.length, was.length, ""]]) {
    while (from < start) where[from++] = into++;
    from = end;
    into += [...words].length;
  }
  const mapped = new Set(where.filter((k) => k >= 0));
  const gone = new Uint8Array(at.length), put = new Map();
  for (const [start, end, words] of runsOf(was, to, toTarget)) {
    // Words it puts back in place of letters others have changed since (a word it retyped,
    // retyped again by another): not spliced into theirs -- theirs stand, and that is said.
    if (words && end > start) {
      let intact = where[start] >= 0;
      for (let i = start + 1; i < end && intact; i++) intact = where[i] === where[i - 1] + 1;
      // (Nor where others have typed onto it, making it a word of theirs: "drafted", made
      // "redrafted", is not undone to "rewritten".)
      const theirs = (k) => k >= 0 && k < at.length && !mapped.has(k) && LETTER.test(at[k]);
      if (intact && ((LETTER.test(was[start]) && theirs(where[start] - 1)) || (LETTER.test(was[end - 1]) && theirs(where[end - 1] + 1)))) intact = false;
      if (!intact) { replaying?.push({ changed: words }); continue; }
    }
    // Lines it put in that others have since typed among (a figure's file: a shape's lines,
    // its label typed in by another): not taken out from about their letters, left as lines
    // of nothing whole -- they stay, and that is said.
    if (!words && was.slice(start, end).includes("\n")) {
      const own = [];
      for (let i = start; i < end; i++) if (where[i] >= 0) own.push(where[i]);
      let among = false;
      for (let n = 1; n < own.length && !among; n++) for (let k = own[n - 1] + 1; k < own[n] && !among; k++) among = !mapped.has(k);
      if (among) { replaying?.push({ changed: was.slice(start, end).join("") }); continue; }
    }
    for (let i = start; i < end; i++) if (where[i] >= 0) gone[where[i]] = 1;
    if (!words) continue;
    let place = -1;
    for (let i = start; i < end && place < 0; i++) place = where[i];
    if (place < 0) {
      const before = start > 0 && where[start - 1] >= 0, after = end < was.length && where[end] >= 0;
      if (!before && !after) { replaying?.push({ words }); continue; }
      let i = start - 1;
      while (i >= 0 && where[i] < 0) i -= 1;
      place = i >= 0 ? where[i] + 1 : 0;
    }
    if (!put.has(place)) put.set(place, []);
    put.get(place).push(words);
  }
  // A space taken away between two words that stay is left there, whosever it was: words
  // others typed after it (a space both typed at one place is one, kept with either's typing)
  // are not run into the words before them.
  let merged = "", cut = false, gap = "";
  const space = /[ \t]/;
  for (let k = 0; k <= at.length; k++) {
    for (const words of put.get(k) || []) { merged += words; cut = false; gap = ""; }
    if (k === at.length) break;
    if (gone[k]) { cut = true; if (space.test(at[k]) && !gap) gap = at[k]; continue; }
    if (cut && space.test(at[k]) && (!merged ? !space.test(to[0] ?? "") : space.test(merged.at(-1)))) continue;
    if (cut && gap && !/\s/.test(at[k]) && !CLOSING.test(at[k]) && merged && !/\s/.test(merged.at(-1))) merged += gap;
    merged += at[k];
    cut = false;
    gap = "";
  }
  return cut && !space.test(to.at(-1) ?? "") ? merged.replace(/[ \t]+$/, "") : merged;
}

// The letters of `first` kept in `second` (arrays), in order, as few changes apart as can be
// (Myers's diff): [[i, j], ...]; null if they are too far apart to be worth following.
function lettersKept(first, second, most = 2000) {
  let start = 0;
  while (start < first.length && start < second.length && first[start] === second[start]) start += 1;
  let end = 0;
  while (end < first.length - start && end < second.length - start && first[first.length - 1 - end] === second[second.length - 1 - end]) end += 1;
  const a = first.slice(start, first.length - end), b = second.slice(start, second.length - end);
  const n = a.length, m = b.length, trace = [];
  let found = -1;
  for (let d = 0; d <= n + m && found < 0; d += 1) {
    if (d > most) return null;
    const v = new Int32Array(2 * d + 1), was = trace[d - 1];
    for (let k = -d; k <= d; k += 2) {
      const down = k === -d || (k !== d && was[k - 1 + d - 1] < was[k + 1 + d - 1]);
      let x = d === 0 ? 0 : down ? was[k + 1 + d - 1] : was[k - 1 + d - 1] + 1, y = x - k;
      while (x < n && y < m && a[x] === b[y]) { x += 1; y += 1; }
      v[k + d] = x;
      if (x >= n && y >= m) { found = d; break; }
    }
    trace.push(v);
  }
  const pairs = [];
  for (let i = 0; i < end; i += 1) pairs.push([first.length - 1 - i, second.length - 1 - i]);
  let x = n, y = m;
  for (let d = found; d > 0; d -= 1) {
    const was = trace[d - 1], k = x - y;
    const down = k === -d || (k !== d && was[k - 1 + d - 1] < was[k + 1 + d - 1]);
    const from = down ? k + 1 : k - 1, fromX = was[from + d - 1];
    const snake = down ? fromX : fromX + 1;
    while (x > snake) { x -= 1; y -= 1; pairs.push([start + x, start + y]); }
    x = fromX;
    y = fromX - from;
  }
  while (x > 0) { x -= 1; y -= 1; pairs.push([start + x, start + y]); }
  for (let i = start - 1; i >= 0; i -= 1) pairs.push([i, i]);
  return pairs.reverse();
}

function mergeMaps(base, ours, theirs, notes = null) {
  if (replaying) [base, ours] = reworded(base, ours, theirs);
  const result = {};
  const keys = [...Object.keys(ours), ...Object.keys(theirs).filter((key) => !(key in ours))];
  for (const key of keys) {
    const was = key in base ? base[key] : MISSING;
    const mine = key in ours ? ours[key] : MISSING;
    const other = key in theirs ? theirs[key] : MISSING;
    // (Made again, words both wrote in a field the change had none in are both kept.)
    const written = replaying && was === MISSING && typeof mine === "string" && typeof other === "string";
    if (mine !== MISSING && other !== MISSING) result[key] = written ? mergeText("", mine, other, notes) : merge3(was === MISSING ? null : was, mine, other, notes);
    else if (mine !== MISSING) {
      if (was === MISSING) result[key] = mine;
      else if (!same(mine, was)) replaying?.push({ removed: was });
    } else if (was === MISSING || !same(was, other)) {
      // Made again, a change that took away a field another has written in since leaves
      // their words in it (its own taken out), or, not words, it as they have it.
      const left = replaying && was !== MISSING ? keptOf(was, other) : other;
      if (left !== MISSING) result[key] = left;
    }
  }
  return result;
}

// Made again on words made a list since (a paragraph made a list, its lines items): the change
// is made on them as they now are, line for line -- `base` and `target` (the change) given the
// words as the list's, the old's taken out. [base, target]
function reworded(base, target, now) {
  const words = (value) => Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string");
  const gone = Object.keys(base).filter((key) => typeof base[key] === "string" && typeof target[key] === "string" && !(key in now));
  const come = Object.keys(now).filter((key) => !(key in base) && !(key in target) && words(now[key]));
  if (gone.length !== 1 || come.length !== 1) return [base, target];
  const [was, into] = [gone[0], come[0]];
  const made = replayText(base[was], target[was], now[into].join("\n"));
  if (made === null) return [base, target];
  const { [was]: _old, ...restBase } = base, { [was]: _gone, ...restTarget } = target;
  return [{ ...restBase, [into]: now[into] }, { ...restTarget, [into]: made.split("\n") }];
}

// What stays of `now`, which someone changed since a change being made again took it (`was`)
// away: words, those others wrote in it, the change's own taken out (none: MISSING); else
// all of it, as they have it.
function keptOf(was, now) {
  if (typeof was === "string" && typeof now === "string") {
    const left = replayText(was, "", now);
    if (left !== null) return left.trim() ? left : MISSING;
  }
  replaying.push({ kept: now });
  return now;
}

export function mergeLists(base, ours, theirs) {
  return diff3(base, ours, theirs, chunk);
}

// Two edits of a list of items, merged by the items' identities: each side's items are
// paired with the items of base they were.
export function mergeItems(base, ours, theirs, notes = null) {
  // (Made again, items moved and changed at once are still known: follows; and an object
  // made another kind where it was -- a paragraph made a list -- is still itself: reworded.)
  const pairs = replaying ? (before, after) => {
    const found = new Map(follows(before, after).map((j, i) => [i, j]).filter(([, j]) => j >= 0));
    const used = new Set(found.values());
    before.forEach((item, i) => { if (!found.has(i) && isMap(item) && isMap(after[i]) && !used.has(i) && !kin(item, after[i])) { found.set(i, i); used.add(i); } });
    return found;
  } : pairsOf;
  const toOurs = pairs(base, ours), toTheirs = pairs(base, theirs);
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
    if (j !== undefined && k !== undefined) content.set(`b:${i}`, merge3(was, ours[j], theirs[k], notes));
    else if (j !== undefined && !same(ours[j], was)) {
      // Removed by them, edited by us: kept, edited -- but not made again, removed since.
      if (replaying) { replaying.push({ removed: was }); return; }
      content.set(`b:${i}`, ours[j]);
      notes?.push({ kept: "ours", item: ours[j] });
    } else if (k !== undefined && !same(theirs[k], was)) {
      const left = replaying ? keptOf(was, theirs[k]) : theirs[k];
      if (left === MISSING) return;
      content.set(`b:${i}`, left);
      notes?.push({ kept: "theirs", item: left });
    }
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
  // Moved and changed at once (a slide moved and retitled while typed in): of the mappings
  // left, the most alike, wherever it went -- one mapping, not one gone and another new.
  const gone = base.map((_, i) => i).filter((i) => !pairs.has(i) && isMap(base[i]));
  const come = side.map((_, j) => j).filter((j) => !used.has(j) && isMap(side[j]));
  const scored = [];
  for (const i of gone) for (const j of come) {
    if (!kin(base[i], side[j])) continue;
    const score = alike(base[i], side[j]);
    if (score >= MOVED) scored.push([-score, i, j]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  for (const [, i, j] of scored) if (!pairs.has(i) && !used.has(j)) { pairs.set(i, j); used.add(j); }
  return pairs;
}

// How alike a mapping moved and changed at once must be to the one it was (see pairsOf).
const MOVED = 0.6;

// A mapping's lists (a slide's body and sides, each of its columns), by where they are:
// [[key], list] or [[key, index], list] for a list of lists.
function pools(value) {
  const found = [];
  for (const [key, item] of Object.entries(value)) {
    if (Array.isArray(item) && item.length && item.every((inner) => Array.isArray(inner))) item.forEach((inner, index) => found.push([[key, index], inner]));
    else if (Array.isArray(item)) found.push([[key], item]);
  }
  return found;
}
const poolName = (pool) => pool.join("\u0000");

// Whether one mapping could be the other moved to another list: of one kind, with at least
// half their keys alike (a paragraph and a paragraph, not a shape and a line).
function movableTo(first, second) {
  if (!isMap(first) || !isMap(second) || !kin(first, second)) return false;
  const keys = new Set([...Object.keys(first), ...Object.keys(second)]);
  const shared = Object.keys(first).filter((key) => Object.hasOwn(second, key)).length;
  return keys.size > 0 && shared * 2 >= keys.size;
}

// Items one side moved to another of a mapping's lists while the other side kept (and edited)
// them where they were -- a paragraph put in the next column, a slide's body set out in two
// columns: moved for the other side too (and in base), so the merge has each where it went,
// with both sides' edits, never left behind as a copy in the list it left. (merge.py's
// _followed.)
function followed(base, ours, theirs) {
  [base, ours] = followMoves(base, theirs, ours);
  [base, theirs] = followMoves(base, ours, theirs);
  return [base, ours, theirs];
}

function followMoves(base, side, other) {
  const listsB = new Map(pools(base).map(([pool, items]) => [poolName(pool), [pool, items]]));
  const listsS = new Map(pools(side).map(([pool, items]) => [poolName(pool), [pool, items]]));
  const listsO = new Map(pools(other).map(([pool, items]) => [poolName(pool), [pool, items]]));
  if (new Set([...listsB.keys(), ...listsS.keys()]).size < 2) return [base, other];
  const kept = new Map([...listsB].map(([name, [, items]]) => [name, listsS.has(name) ? pairsOf(items, listsS.get(name)[1]) : new Map()]));
  const gone = [], come = [];
  for (const [name, [, items]] of listsB) items.forEach((item, i) => { if (!kept.get(name).has(i) && isMap(item)) gone.push([name, i]); });
  for (const [name, [, items]] of listsS) {
    const used = new Set(kept.get(name)?.values() || []);
    items.forEach((item, j) => { if (!used.has(j) && isMap(item)) come.push([name, j]); });
  }
  const scored = [];
  gone.forEach(([from, i], n) => come.forEach(([to, j], m) => {
    const was = listsB.get(from)[1][i], now = listsS.get(to)[1][j];
    if (from === to || !movableTo(was, now)) return;
    const score = alike(was, now);
    if (score >= ALIKE) scored.push([-score, n, m]);
  }));
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  const moves = [], takenGone = new Set(), takenCome = new Set();
  for (const [, n, m] of scored) {
    if (takenGone.has(n) || takenCome.has(m)) continue;
    takenGone.add(n); takenCome.add(m);
    moves.push([...gone[n], ...come[m]]);
  }
  if (!moves.length) return [base, other];
  // Each moved where it went, in the order the side has there: after the item it follows
  // there that was in that list already (else first).
  const order = [...listsS.keys()];
  moves.sort((a, b) => order.indexOf(a[2]) - order.indexOf(b[2]) || a[3] - b[3]);
  const goneB = new Map(), goneO = new Map(), addedB = new Map(), addedO = new Map();
  const add = (map, name, entry) => { if (!map.has(name)) map.set(name, []); map.get(name).push(entry); };
  const drop = (map, name, index) => { if (!map.has(name)) map.set(name, new Set()); map.get(name).add(index); };
  for (const [from, i, to, j] of moves) {
    const back = new Map([...(kept.get(to) || new Map())].map(([b, k]) => [k, b]));
    let after = -1;
    for (let k = 0; k < j; k++) if (back.has(k)) after = Math.max(after, back.get(k));
    drop(goneB, from, i);
    add(addedB, to, [after + 0.5, listsB.get(from)[1][i]]);
    const theirsNow = listsO.has(from) ? pairsOf(listsB.get(from)[1], listsO.get(from)[1]) : new Map();
    if (!theirsNow.has(i)) continue;  // the other side took it away: it is not theirs to move
    drop(goneO, from, theirsNow.get(i));
    const inOther = pairsOf(listsB.get(to)?.[1] || [], listsO.get(to)?.[1] || []);
    const place = after >= 0 && inOther.has(after) ? inOther.get(after) : -1;
    add(addedO, to, [place + 0.5, listsO.get(from)[1][theirsNow.get(i)]]);
  }
  const poolOf = new Map([...listsB, ...listsS, ...listsO].map(([name, [pool]]) => [name, pool]));
  return [repooled(base, listsB, goneB, addedB, poolOf), repooled(other, listsO, goneO, addedO, poolOf)];
}

// `value` with the items of its lists `gone` taken out and those `added` put in (each at its
// place, a fraction past the index of the item it follows).
function repooled(value, lists, gone, added, poolOf) {
  const result = { ...value };
  for (const name of [...lists.keys(), ...[...added.keys()].filter((key) => !lists.has(key))]) {
    const pool = poolOf.get(name), items = lists.get(name)?.[1] || [];
    const left = gone.get(name) || new Set();
    const placed = items.map((item, n) => [n, item]).filter(([n]) => !left.has(n)).concat(added.get(name) || []);
    const made = placed.sort((a, b) => a[0] - b[0]).map(([, item]) => item);
    if (pool.length === 1) result[pool[0]] = made;
    else {
      const outer = (result[pool[0]] || []).map((inner) => [...inner]);
      while (outer.length <= pool[1]) outer.push([]);
      outer[pool[1]] = made;
      result[pool[0]] = outer;
    }
  }
  return result;
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
// What both put at one place alike is put there once -- but, with `spaces`, not a space both
// typed there: two people starting words at one place, each their own.
function diff3(base, ours, theirs, both, spaces = false) {
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
    const twin = same(mine, other) && !(spaces && !was.length && mine.length && !mine.join("").trim());
    if (same(mine, was)) result.push(...other);
    else if (same(other, was) || twin) result.push(...mine);
    else result.push(...both(was, mine, other));
    if (ab < base.length) result.push(ours[ao]);
    b = ab + 1; o = ao + 1; t = at + 1;
  }
  return result;
}

function chunk(base, ours, theirs) {
  if (!base.length) return [...ours, ...theirs];
  if (base.length === ours.length && ours.length === theirs.length) return base.map((was, i) => merge3(was, ours[i], theirs[i]));
  replaying?.push({ changed: theirs });
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
