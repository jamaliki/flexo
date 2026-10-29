// The studio's colour picker: a popover by a colour's well, wherever a colour is chosen -- a
// shape's fill, outline and words, an object's words, a slide's background, a figure's parts'
// own colours, a gradient's ends, a theme's colours, a structure's chains, a table's cells.
//
// In it, from the top: the colour's saturation and brightness as a plane, its hue and (where
// the thing has one) its opacity as sliders, the eyedropper beside them; its code (any way a
// colour is written: hexcolour.js); the colours the document in front draws ("On This Slide",
// "In This Figure"), the most used first; and those applied last.
//
// The eyedropper (eyedropper.js) takes a colour from anywhere on the screen. One of the page's
// own -- a shape, a part, words -- is taken as drawn, exactly, and one the screen shows a
// step off a colour the document has is that colour (colourmatch.js): a theme's colour by
// its name, where the control takes the theme's colours (an outline taken from an accent's
// line is "accent", and follows the theme), else by its code.
//
// Each choice is one step in the history: a swatch, a code, a colour taken, a drag across the
// plane or along a slider from press to release -- drawn as it goes (`live`), one step once
// let go.
//
// The system's own picker (an <input type="color">), wherever a panel has one, opens this one
// instead: its value set and its input and change events sent, as the system's would send them.

import { h, icon, popover, closeMenu, roving } from "./ui.js";
import { hexField, shownHex, recentColours, rememberColour, stepHistory } from "./hexcolour.js";
import { joinSteps } from "./mixing.js";
import { hsvOf, hexOfHsv, paintHex, usedColours, candidatesFor, matchSample, valueFor } from "./colourmatch.js";
import { canPick, pickFromScreen, drawnAt } from "./eyedropper.js";

const GREY = "#888888";
const RECENT_SHOWN = 8;
const clamp = (value, low = 0, high = 1) => Math.min(high, Math.max(low, value));

// What the document in front draws, for the picker's row of its colours: its editor's word
// (colourkey.js's `source`): { title ("On This Slide"), root (its drawing), skip (colours left
// out: its paper, its words' own ink), theme (its theme's colours) }; null where it draws
// nothing.
export function colourSource() {
  try { return globalThis.flexoStudio?.active?.colourSource?.() || null; } catch { return null; }
}

// The colours the document in front draws, the most used first, those a control offers by
// name (`offered`) left out: { title, colours } (none: no title).
export function drawnColours(offered = [], source = colourSource()) {
  if (!source?.root) return { title: null, colours: [] };
  const skip = [...(source.skip || []), ...(offered || []).map((item) => item?.colour)].filter(Boolean);
  return { title: source.title || "In This Document", colours: usedColours(source.root, { skip }) };
}

// A colour taken from the screen ({ hex, at }, pickFromScreen), as a control offering
// `offered` is to take it: what the page drew there, exactly, if it was the page's (by its
// name, where the control has it), else the colour seen put back to the nearest the document
// has, within a screen's rounding. { value, hex }.
export function sampledValue(sample, { offered = [], source = colourSource(), used = null } = {}) {
  if (!sample?.hex) return null;
  if (sample.at && source?.root) {
    const drawn = drawnAt(source.root, sample.at.x, sample.at.y, sample.hex);
    if (drawn) return { value: valueFor(drawn.hex, offered), hex: drawn.hex };
  }
  const everything = used ?? (source?.root ? usedColours(source.root, { limit: 200 }) : []);
  const found = matchSample(sample.hex, candidatesFor({ offered, used: everything, theme: source?.theme || [], recent: recentColours() }));
  return found ? { value: found.value, hex: found.hex } : null;
}

// A colour light enough that a mark on it is drawn dark; one near black, ringed clearly.
function lightness(hex) {
  const rgb = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
  if (!rgb) return null;
  const [r, g, b] = rgb.slice(1).map((part) => parseInt(part, 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export const light = (hex) => (lightness(hex) ?? 0) > 0.6;
const dark = (hex) => (lightness(hex) ?? 1) < 0.2;

// The session in front: its history, for a drag made one step.
const session = () => globalThis.flexoStudio?.active || null;

// The picker by `anchor` (the well that opened it). `value`: the colour now (a code, the name
// of one of `offered`, null for none, undefined where those chosen differ); `offered`: the
// theme's colours the control has by name ([{ value, colour, title }]); `opacity`: the thing's
// opacity now (0-1), for an Opacity slider -- left out, there is none; `onChange(value, how)`:
// a colour chosen (`how.alpha`, its opacity where it has one, `how.live` while a drag goes on);
// `onDone()`: each choice done; `title`: what it colours. The popover.
export function openColourPicker(anchor, { value, offered = [], opacity, onChange, onDone, title = "Colour" } = {}) {
  const named = (offered || []).find((item) => item && item.value === value);
  let hex = paintHex(named ? named.colour : value) || GREY;
  let hsv = hsvOf(hex);
  let alpha = opacity === undefined || opacity === null ? null : clamp(Number(opacity));
  // What is chosen now: a code, or one of the theme's by name.
  let chosen = named ? named.value : paintHex(value) ? hex : null;

  const plane = h("div.cp-plane", { tabIndex: 0, role: "slider", "aria-label": "Saturation and Brightness" }, h("span.cp-knob"));
  const hue = h("input.cp-hue", { type: "range", min: 0, max: 360, step: 1, "aria-label": "Hue" });
  const fade = alpha === null ? null : h("input.cp-alpha", { type: "range", min: 0, max: 100, step: 1, "aria-label": "Opacity" });
  const percent = alpha === null ? null : h("span.cp-percent");
  const dropper = canPick() ? h("button.cp-dropper", { type: "button", title: "Pick a Colour from the Screen", "aria-label": "Pick a Colour from the Screen" }, icon("eyedropper")) : null;
  const chip = h("span.cp-chip", { "aria-hidden": "true" }, h("span"));
  const field = hexField({ value: chosen && !named ? hex : null, placeholder: named ? named.title || "Theme" : value === undefined ? "Mixed" : "None", leaving: false, title,
    apply: (code, given) => take(code, { alpha: given }) });
  field.removeAttribute("title");

  // The colours drawn, and those applied last: a click is that colour.
  const drawn = drawnColours(offered);
  const swatches = [];
  const row = (label, colours) => {
    if (!colours.length) return null;
    const list = h("div.cp-swatches", { role: "radiogroup", "aria-label": label });
    for (const colour of colours) {
      const button = h(`button.swatch${light(colour) ? ".light" : ""}${dark(colour) ? ".dark" : ""}`, { type: "button", role: "radio", title: shownHex(colour), "aria-label": `${label}: ${shownHex(colour)}`,
        style: { background: colour }, onclick: () => { take(colour); closeMenu(); } });
      button.dataset.colour = colour;
      swatches.push(button);
      list.append(button);
    }
    roving(list, () => [...list.children]);
    return h("div.cp-section", {}, h("div.cp-title", {}, label), list);
  };
  const recent = recentColours().filter((colour) => !drawn.colours.includes(colour)).slice(0, RECENT_SHOWN);

  const node = popover(anchor, [
    plane,
    h("div.cp-row", {}, dropper, h("div.cp-sliders", {}, hue, fade ? h("div.cp-fade", {}, fade, percent) : null)),
    h("div.cp-row.cp-code", {}, chip, field),
    row(drawn.title, drawn.colours),
    row("Recent", recent),
  ], { className: "colour-picker" });
  node.setAttribute("aria-label", title);

  // -- shown --
  const paint = () => {
    plane.style.setProperty("--cp-hue", hexOfHsv({ h: hsv.h, s: 1, v: 1 }));
    plane.style.setProperty("--cp-x", `${hsv.s * 100}%`);
    plane.style.setProperty("--cp-y", `${(1 - hsv.v) * 100}%`);
    plane.setAttribute("aria-valuetext", `Saturation ${Math.round(hsv.s * 100)}%, Brightness ${Math.round(hsv.v * 100)}%`);
    hue.value = String(Math.round(hsv.h));
    node.style.setProperty("--cp-colour", hex);
    chip.firstChild.style.background = hex;
    chip.firstChild.style.opacity = alpha === null ? "" : String(alpha);
    if (fade) { fade.value = String(Math.round(alpha * 100)); percent.textContent = `${Math.round(alpha * 100)}%`; }
    for (const swatch of swatches) {
      const on = chosen !== null && swatch.dataset.colour === hex;
      swatch.classList.toggle("on", on);
      swatch.setAttribute("aria-checked", String(on));
    }
  };

  // -- told --
  // (Its opacity told once it is changed here: a colour chosen leaves several things' own be.)
  let faded = false;
  const how = (extra = {}) => ({ alpha: faded ? alpha : null, ...extra });
  const send = (extra = {}) => {
    try { onChange?.(chosen ?? hex, how(extra)); } catch (error) { console.error(error); }
  };
  const done = () => {
    if (paintHex(chosen)) rememberColour(chosen);
    try { onDone?.(); } catch (error) { console.error(error); }
  };
  // A choice made at once: one step of its own.
  const once = (extra = {}) => { stepHistory(); send(extra); stepHistory(); done(); };
  // A drag: drawn as it goes, at most once a frame; one step from press to release.
  let dragging = false, from = -1, frame = 0;
  const begin = () => {
    if (dragging) return;
    dragging = true;
    stepHistory();
    from = session()?.past?.length ?? -1;
  };
  const step = () => {
    if (!dragging || frame) return;
    frame = requestAnimationFrame(() => { frame = 0; if (dragging) send({ live: true }); });
  };
  const end = () => {
    if (!dragging) return;
    dragging = false;
    if (frame) { cancelAnimationFrame(frame); frame = 0; }
    send();
    const now = session();
    if (now && from >= 0 && (now.past?.length ?? 0) - from > 1) joinSteps(now, from);
    stepHistory();
    done();
  };

  // `code` (a colour's code, or one of the theme's by name) taken, one step.
  const take = (code, { alpha: given = null } = {}) => {
    const item = (offered || []).find((each) => each && each.value === code);
    const next = paintHex(item ? item.colour : code);
    if (!next) return;
    if (given !== null && given !== undefined && alpha !== null) { alpha = clamp(given); faded = true; }
    hex = next;
    const read = hsvOf(hex);
    // (A grey keeps the hue it had: the plane does not turn red under it.)
    hsv = read.s && read.v ? read : { ...read, h: hsv.h };
    chosen = item ? item.value : hex;
    paint();
    field.show(item ? null : hex);
    // (An alpha written after a code, #1f77b4cc, where the picker has no Opacity: told too.)
    once(given !== null && given !== undefined && fade === null ? { alpha: given } : {});
  };
  const moved = () => {
    hex = hexOfHsv(hsv);
    chosen = hex;
    paint();
    field.show(hex);
  };

  // -- the plane --
  const at = (event) => {
    const box = plane.getBoundingClientRect();
    if (!box.width || !box.height) return;
    hsv = { ...hsv, s: clamp((event.clientX - box.left) / box.width), v: 1 - clamp((event.clientY - box.top) / box.height) };
    moved();
  };
  plane.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    plane.focus({ preventScroll: true });
    plane.setPointerCapture?.(event.pointerId);
    begin();
    at(event);
    step();
  });
  plane.addEventListener("pointermove", (event) => {
    if (!dragging || !plane.hasPointerCapture?.(event.pointerId)) return;
    at(event);
    step();
  });
  plane.addEventListener("pointerup", (event) => { if (dragging) { at(event); end(); } });
  plane.addEventListener("lostpointercapture", end);
  plane.addEventListener("keydown", (event) => {
    const by = event.shiftKey ? 0.1 : 0.01;
    const moves = { ArrowLeft: ["s", -by], ArrowRight: ["s", by], ArrowUp: ["v", by], ArrowDown: ["v", -by] }[event.key];
    if (!moves) return;
    event.preventDefault();
    event.stopPropagation();
    hsv = { ...hsv, [moves[0]]: clamp(hsv[moves[0]] + moves[1]) };
    moved();
    once();
  });

  // -- the sliders --
  for (const slider of [hue, fade].filter(Boolean)) {
    slider.addEventListener("input", () => {
      begin();
      if (slider === hue) { hsv = { ...hsv, h: Number(hue.value) }; moved(); }
      else { alpha = Number(fade.value) / 100; faded = true; paint(); }
      step();
    });
    slider.addEventListener("change", end);
    // (The arrows are the slider's, not the popover's way from control to control.)
    slider.addEventListener("keydown", (event) => { if (event.key.startsWith("Arrow") || event.key === "Home" || event.key === "End" || event.key.startsWith("Page")) event.stopPropagation(); });
  }

  // -- the eyedropper --
  dropper?.addEventListener("click", async () => {
    const sample = await pickFromScreen({ hide: node });
    if (!sample || !node.isConnected) return;
    const found = sampledValue(sample, { offered });
    if (!found) return;
    take(found.value);
    dropper.focus({ preventScroll: true });
  });

  // Return in the code's field: taken (hexField), and the picker closed.
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing && !field.classList.contains("invalid") && field.value.trim()) setTimeout(() => { if (!field.classList.contains("invalid")) closeMenu(); }, 0);
  });

  paint();
  // The keys in the code's field: a colour's code typed or pasted at once.
  field.focus({ preventScroll: true });
  field.select();
  return node;
}

// The system's own picker, wherever a panel has one: this one opened instead, by the well (or,
// hidden, by what holds it), its value set and its events sent as the system's would be.
function openForInput(input) {
  let anchor = input;
  while (anchor && anchor !== document.body && !anchor.getBoundingClientRect().width) anchor = anchor.parentElement;
  const label = input.getAttribute("aria-label") || input.title || "Colour";
  openColourPicker(anchor || input, {
    value: input.value, title: label,
    onChange: (hex) => {
      const code = paintHex(hex);
      if (!code || !input.isConnected) return;
      input.value = code;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    },
    onDone: () => { if (input.isConnected) input.dispatchEvent(new Event("change", { bubbles: true })); },
  });
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("click", (event) => {
    const input = event.target?.closest?.("input[type=color]");
    if (!input || input.disabled || event.defaultPrevented) return;
    event.preventDefault();
    openForInput(input);
  }, true);
}
