// The work an author has left in a document: the word TODO, in capitals, as a word of its
// own -- "TODO", "TODO: check the rates", "TODO — a figure" -- anywhere in its words (a
// deck's slides and notes, a figure's labels). "todo" and "Todo" are words, not work left;
// nor is "TODOs". Found by the studio's one engine (finding.js) with Match Case and Whole
// Words, as the find bar finds them; read in Node as in the studio.
//
// A document's fields (finding.js's) are read again after each change, but each field's words
// are read, and looked through, once for each value it has had: a field unchanged since is a
// lookup, so a deck of many slides, typed in, has only the words that changed looked at.

import { findIn, patternOf, wordsOf } from "./finding.js";

export const TODO = "TODO";
// The find bar's options that find them, and only them.
export const TODO_FINDS = { matchCase: true, wholeWords: true };
const PATTERN = patternOf(TODO, TODO_FINDS);

// Where TODO is in words as they read (finding.js's wordsOf): [[start, end], ...].
export const todosIn = (text) => findIn(text, PATTERN, TODO_FINDS);

// "1 TODO", "3 TODOs".
export const todosSaid = (count) => `${count} ${count === 1 ? "TODO" : "TODOs"}`;

// A document's TODOs, kept up to date as it changes. `find(fields)` answers { fields, matches }:
// the fields with their words read (`words`, as finding.js's wordIndex reads them, for marking
// them where they are drawn), and every TODO in them as finding.js's search finds a match --
// { field, index, start, end }, in the fields' order and then each field's.
export function todoIndex() {
  let known = new Map();
  return {
    find(fields) {
      if (known.size > 20000) known = new Map();
      const read = [], matches = [];
      fields.forEach((field) => {
        const key = field.kind === "runs" ? `r\u0000${JSON.stringify(field.value)}` : `${field.kind}\u0000${field.value}`;
        let seen = known.get(key);
        if (!seen) {
          const words = wordsOf(field.value, field.kind);
          seen = { words, ranges: todosIn(words.text) };
          known.set(key, seen);
        }
        const own = { ...field, words: seen.words };
        const index = read.push(own) - 1;
        for (const [start, end] of seen.ranges) matches.push({ field: own, index, start, end });
      });
      return { fields: read, matches };
    },
  };
}

// The one after `at` (a match, or where one was: { index, start }) going `way` (1 or -1)
// through `matches`, round from the last to the first: the first (or last) with none.
export function stepFrom(matches, at, way = 1) {
  if (!matches.length) return null;
  if (!at) return way > 0 ? matches[0] : matches[matches.length - 1];
  const after = (match) => match.index > at.index || (match.index === at.index && match.start > at.start);
  const before = (match) => match.index < at.index || (match.index === at.index && match.start < at.start);
  if (way > 0) return matches.find(after) || matches[0];
  return [...matches].reverse().find(before) || matches[matches.length - 1];
}
