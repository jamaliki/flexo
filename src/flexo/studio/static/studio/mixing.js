// One choice of two kinds, as Keynote's is: a slide's objects and its shapes, a figure's parts
// and the shapes drawn over it -- the sums alone, for mixed.js (where the person meets them),
// read in Node as they are in the studio.
//
// - What a choice of both is called: "2 Objects, 3 Shapes" in the inspector, and in a
//   command's or a step's name "Delete 2 Objects and 3 Shapes".
// - Flexo's own copy of both: each kind's copy, as each copies alone, in one ({ what: "mixed",
//   clips }), its words theirs.
// - One step in the history of the several each kind made: undone, they are undone together.
// - One taken out of or put into a choice by ⇧-click, as each kind's own is.

// "1 Object", "3 Shapes", "2 Drawn Shapes".
export const counted = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

// The choice, as the inspector names it: `own` of the page's things (`words[0]`, "Object") and
// `shapes` shapes (`words[1]`).
export function mixedName(own, shapes, words = ["Object", "Shape"]) {
  return [own ? counted(own, words[0]) : "", shapes ? counted(shapes, words[1]) : ""].filter(Boolean).join(", ");
}

// A command or a step done to it: "Delete 2 Objects and 3 Shapes".
export function mixedLabel(verb, own, shapes, words = ["Object", "Shape"]) {
  return `${verb} ${[own ? counted(own, words[0]) : "", shapes ? counted(shapes, words[1]) : ""].filter(Boolean).join(" and ")}`;
}

// Flexo's own copy of both: the copies each kind made of its own (none: nothing).
export function mixedClip(clips, label) {
  const each = (clips || []).filter(Boolean);
  if (!each.length) return null;
  if (each.length === 1) return each[0];
  return { what: "mixed", clips: each, label };
}

// The copies in a copy, a copy of both or of one kind: [clip, ...].
export const clipsOf = (clip) => (clip?.what === "mixed" ? (Array.isArray(clip.clips) ? clip.clips.filter((one) => one && typeof one === "object") : []) : clip ? [clip] : []);

// The steps the studio's history (`studio.past`) took from `from` on, made one, named `label`:
// undone, all of it is undone. Each kept as its own part where another's change came between
// two (session.js's parts: undone, those alone are taken back). A step made elsewhere (a
// figure's own file, `apply`) among them: one step made elsewhere too, which puts each back
// where it was made -- the files first, then the document (session.js's travelPart) -- so a
// figure's parts kept in a file of their own, deleted with the slide's shapes, come back
// with them by one ⌘Z. (A studio that cannot: they are left as they are.) The step, else null.
export function joinSteps(studio, from, label = null) {
  const past = studio?.past;
  if (!Array.isArray(past) || from < 0 || from >= past.length) return null;
  const steps = past.slice(from);
  if (steps.length === 1) {
    if (label) Object.assign(steps[0], { label, said: null });
    return steps[0];
  }
  if (steps.some((step) => step.apply)) {
    if (typeof studio.travelPart !== "function") return null;
    const files = steps.filter((step) => step.apply), own = steps.filter((step) => !step.apply);
    const told = (step) => { try { return studio.said?.(step) || {}; } catch { return {}; } };
    const placed = steps.map(told).find((said) => said.place !== undefined || said.where !== undefined) || {};
    const last = steps[steps.length - 1];
    const joined = {
      label: label || last.label || null, at: last.at, place: placed.place, where: placed.where,
      before: steps[0].before, after: last.after, steps,
      // (Undone, the last made first: each file put back, then the document's changes taken
      // back; made again, in the order they were made.)
      apply(target) {
        const order = (list) => (target === "before" ? [...list].reverse() : list);
        return order(files).reduce((done, step) => done.then(() => step.apply(target)), Promise.resolve())
          .then(() => { for (const step of order(own)) studio.travelPart(step, target); });
      },
    };
    past.splice(from, steps.length, joined);
    studio.step?.();
    return joined;
  }
  const parts = steps.flatMap((step) => step.parts || [{ before: step.before, after: step.after }]);
  const apart = parts.some((part, n) => n > 0 && part.before !== parts[n - 1].after);
  const joined = { before: parts[0].before, after: parts[parts.length - 1].after, at: steps[steps.length - 1].at, label: label || steps[steps.length - 1].label || null,
    ...(apart ? { parts } : {}) };
  past.splice(from, steps.length, joined);
  studio.step?.();
  return joined;
}

// A choice with `item` taken out (it was in it) or put in at its end; `same(a, b)` says two
// are one.
export function toggled(list, item, same = (a, b) => a === b) {
  const at = list.findIndex((one) => same(one, item));
  return at >= 0 ? list.filter((_, n) => n !== at) : [...list, item];
}

// A choice's key, to know it again: the same things chosen, in any order.
export const choiceKey = (picks) => (picks || []).map((pick) => JSON.stringify(pick)).sort().join("\n");
