// Copy Style and Paste Style (⌥⌘C, ⌥⌘V), as Keynote's and Inkscape's: how one thing is drawn
// -- its fill, line, width, dash, arrowheads, shadow, opacity and words' look -- put on others.
// A shape's style goes on shapes (on a slide, over a figure); a figure's part's -- its tone,
// its own colours, its outline, its words' weight, slant and size -- on parts (a shape's,
// a group's, a line's, as each takes it); and either goes on the other where it maps: a theme's
// accent is a part's tone (accent2 its second), a colour of one's own the other's own colour,
// a dash an outline's style. What is copied stays to be pasted, in this window and others.
//
// Nothing here touches the page: a style is plain values, and pasting one makes the values
// written (a shape's, a part's), for its editor to write in one step.

import * as F from "./freeform.js";

// What of a shape is its style (its kind's own settings and its words are not).
export const SHAPE_STYLE = ["fill", "fill_opacity", "line", "line_width", "dash", "cap", "join", "start", "end", "head_size", "shadow", "opacity",
  "font", "font_size", "bold", "italic", "colour", "align", "valign", "padding"];
// A zoom inset's pieces, from one inset to another.
const INSET_STYLE = ["frame_line", "frame_width", "frame_dash", "connector_line", "connector_width", "connector_dash"];
const FILLED = new Set(["fill", "fill_opacity"]);
const HEADED = new Set(["start", "end", "head_size"]);

const STORE = "flexo.style";
let copied = null;

// What was copied, here or in another window of the studio.
export function copiedStyle() {
  if (copied) return copied;
  try { const kept = JSON.parse(localStorage.getItem(STORE) || "null"); if (kept && (kept.from === "shape" || kept.from === "part")) copied = kept; } catch { /* none */ }
  return copied;
}
export function keepStyle(style) {
  copied = style;
  try { localStorage.setItem(STORE, JSON.stringify(style)); } catch { /* this window's alone */ }
  return style;
}
// What a style is called in a command's hint: "Arrow", "Shape Encoder".
export const styleName = (style) => style?.name || (style?.from === "part" ? "Shape" : "Shape");

// -- taken --

// A shape's style: every setting of it as it is drawn (its kind's defaults where it says none).
export function shapeStyle(spec, name = "") {
  const normal = F.normalised(spec?.kind === "group" ? (spec.shapes || []).find((child) => child.kind !== "group") || spec : spec);
  const values = {};
  for (const key of SHAPE_STYLE) if (normal[key] !== undefined) values[key] = normal[key];
  if (normal.kind === "inset") for (const key of INSET_STYLE) if (normal[key] !== undefined && normal[key] !== null) values[key] = normal[key];
  return { from: "shape", kind: normal.kind, closed: F.isClosed(normal) || normal.kind === "text", values, name: name || F.LABELS[normal.kind] || "Shape" };
}

// A figure's part's style (`type`: node, group, edge or net; `item` as its file has it).
export function partStyle(item, type, name = "") {
  const props = item?.properties || {}, paint = item?.paint || {};
  const values = type === "group"
    ? { fill: paint.fill ?? null, stroke: paint.stroke ?? null, text: paint.label ?? null, line: item?.line ?? null }
    : type === "edge" || type === "net"
      ? { tone: item?.tone ?? null, line: item?.line ?? null }
      : { tone: props.tone ?? null, fill: props["paint-fill"] ?? null, stroke: props["paint-stroke"] ?? null, text: props["paint-label"] ?? null,
        line: item?.line ?? null, shadow: item?.shadow ?? null, bold: props.bold ?? null, italic: props.italic ?? null, size: props.size ?? null, align: props.align ?? null };
  return { from: "part", type, values, name: name || "Shape" };
}

// -- given --

const hex = (value) => (typeof value === "string" && /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(value.trim()) ? value.trim() : null);
// The tone a theme colour's name is (accent2, accent2-fill: "2"), "neutral" for its grey; else none.
function toneOf(value) {
  const found = /^accent(\d*)(-fill)?$/.exec(String(value ?? ""));
  if (found) return found[1] || "1";
  return value === "grey" || value === "gray" ? "neutral" : null;
}
const accent = (tone, fill = false) => `accent${tone === "1" ? "" : tone}${fill ? "-fill" : ""}`;
const points = (size) => { const found = /^\s*([\d.]+)\s*(pt)?\s*$/.exec(String(size ?? "")); return found ? Number(found[1]) : null; };
const ALIGN_PART = { start: "left", middle: null, end: "right" };
const ALIGN_SHAPE = { left: "start", center: "middle", centre: "middle", right: "end" };

// A shape with `style` pasted on it: each setting its kind takes, those its kind has of itself
// unsaid (a group's shapes each given it).
export function onShape(spec, style) {
  if (!spec || !style) return spec;
  if (spec.kind === "group") return { ...spec, shapes: (spec.shapes || []).map((child) => onShape(child, style)) };
  const values = style.from === "part" ? shapeValues(style, spec) : style.values;
  const closed = F.isClosed(spec) || spec.kind === "text";
  const out = { ...spec }, defaults = F.defaults(spec.kind);
  const keys = [...SHAPE_STYLE, ...(spec.kind === "inset" && style.kind === "inset" ? INSET_STYLE : [])];
  for (const key of keys) {
    if (!(key in values)) continue;
    // (A fill goes on what is closed; arrowheads from a line onto a line alone.)
    if ((!closed && FILLED.has(key)) || ((closed || style.closed) && HEADED.has(key))) continue;
    const value = values[key];
    // (Said only where it is not what its kind is anyway.)
    if (value === null || value === undefined || JSON.stringify(value) === JSON.stringify(defaults[key])) delete out[key];
    else out[key] = value;
  }
  return out;
}

// A part's style as a shape's settings: its tone the theme's accent (a tint in it, its
// outline the accent), its own colours its fill and line, its outline's dash, its words.
function shapeValues(style, spec) {
  const v = style.values, out = {};
  const closed = F.isClosed(spec) || spec.kind === "text";
  if (v.tone !== null && v.tone !== undefined && /^\d+$|^neutral$/.test(String(v.tone))) {
    const tone = String(v.tone);
    if (tone === "neutral") { out.fill = "grey"; out.line = "muted"; } else { out.fill = accent(tone, true); out.line = accent(tone); }
    if (!closed) delete out.fill;
  } else { out.fill = null; out.line = null; }
  if (hex(v.fill)) out.fill = hex(v.fill);
  if (hex(v.stroke)) out.line = hex(v.stroke);
  if ("text" in v) out.colour = hex(v.text);
  if ("line" in v) out.dash = v.line || "solid";
  if ("shadow" in v) out.shadow = Boolean(v.shadow);
  if ("bold" in v) out.bold = Boolean(v.bold);
  if ("italic" in v) out.italic = Boolean(v.italic);
  if ("size" in v) out.font_size = points(v.size);
  if ("align" in v) out.align = ALIGN_SHAPE[String(v.align || "center").toLowerCase()] || null;
  return out;
}

// The values written on a part of `type` (node, group, edge, net) with `style` pasted on it,
// as the figure's update takes them (null: said no more). `roles` paints a theme's colour
// for a part that takes only colours of its own (a group).
export function partValues(style, type, roles = {}) {
  if (!style) return {};
  const v = style.from === "part" ? partFrom(style) : fromShape(style.values, roles);
  if (type === "group") return { "paint.fill": v.fill ?? v.toneFill ?? null, "paint.stroke": v.stroke ?? v.toneStroke ?? null, "paint.label": v.text ?? null, line: v.line ?? null };
  if (type === "edge" || type === "net") return { tone: v.lineTone ?? v.tone ?? null, line: v.line ?? null };
  return {
    "properties.tone": v.tone ?? null, "properties.paint-fill": v.fill ?? null, "properties.paint-stroke": v.stroke ?? null, "properties.paint-label": v.text ?? null,
    line: v.line ?? null, shadow: v.shadow ? true : null, "properties.bold": v.bold ? true : null, "properties.italic": v.italic ? true : null,
    "properties.size": v.size ?? null, "properties.align": v.align ?? null,
  };
}
// A part's style, as plain values: its tone, its own colours, its outline, its words.
function partFrom(style) {
  const v = style.values;
  return { tone: v.tone ?? null, lineTone: v.tone ?? null, fill: hex(v.fill), stroke: hex(v.stroke), text: hex(v.text), line: v.line && v.line !== "solid" ? v.line : null,
    shadow: Boolean(v.shadow), bold: Boolean(v.bold), italic: Boolean(v.italic), size: v.size ?? null, align: v.align && !/^cent(er|re)$/.test(String(v.align)) ? v.align : null };
}
// A shape's style, as a part's: a theme's accent its tone, colours of its own its own colours.
function fromShape(values, roles) {
  const tone = toneOf(values.fill) ?? toneOf(values.line);
  const paint = (value) => hex(value) ?? (value && value !== "none" ? F.paintOf(value, roles) || null : null);
  return {
    tone, lineTone: toneOf(values.line) ?? tone,
    fill: hex(values.fill), stroke: hex(values.line), text: hex(values.colour),
    toneFill: values.fill && values.fill !== "none" ? paint(values.fill) : null, toneStroke: values.line && values.line !== "none" ? paint(values.line) : null,
    line: values.dash && values.dash !== "solid" ? values.dash : null,
    shadow: Boolean(values.shadow), bold: Boolean(values.bold), italic: Boolean(values.italic),
    size: Number.isFinite(values.font_size) && values.font_size ? values.font_size : null,
    align: ALIGN_PART[values.align] ?? null,
  };
}

// -- a figure's parts --

// The parts chosen in a figure (parts.js), each as its update names it, with its file's own.
export function chosenParts(figure) {
  const root = figure.model?.root;
  return (figure.selected || []).map((id) => {
    if (figure.nodeOf?.(id)) return { type: "node", id, item: figure.nodeOf(id) };
    if (figure.groupOf?.(id) && id !== root) return { type: "group", id, item: figure.groupOf(id) };
    if (figure.edgeOf?.(id)) return { type: "edge", id, item: figure.edgeOf(id) };
    if (figure.netOf?.(id)) return { type: "net", id, item: figure.netOf(id) };
    return null;
  }).filter(Boolean);
}
// Copy Style of the one part chosen.
export function copyPartStyle(figure) {
  const picks = chosenParts(figure);
  if (picks.length !== 1) return null;
  const [one] = picks;
  return keepStyle(partStyle(one.item, one.type, figure.nameOf?.(one.id) || one.id));
}
// Paste Style on the parts chosen: one step, each given what its kind takes.
export function pastePartStyle(figure, roles = {}) {
  const style = copiedStyle(), picks = chosenParts(figure);
  if (!style || !picks.length) return false;
  figure.act({ do: "update", targets: picks.map(({ type, id }) => ({ type, id, values: partValues(style, type, roles) })) }, { label: "Paste Style", select: false });
  return true;
}
