// A shape's fill as a gradient (flexo.gradients): its colours running across its box at an
// angle, or out from a point in it -- drawn here as the page draws it, and chosen in the
// shapes' inspector (gradientFields).
//
//   { gradient: "linear", angle: 90, stops: [[0, "accent"], [1, "#ffffff"]] }
//   { gradient: "radial", centre: [0.5, 0.5], radius: 0.5, stops: [[0, "paper"], [1, "accent"]] }

export const isGradient = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value) && "gradient" in value;

// Where a linear gradient starts and ends in a box [x, y, w, h]: through its middle at its
// angle, from the corner it starts at to the opposite one.
export function linearEnds(fill, [x, y, w, h]) {
  const angle = (Number(fill.angle || 0) * Math.PI) / 180, ux = Math.cos(angle), uy = Math.sin(angle);
  const half = (Math.abs(w * ux) + Math.abs(h * uy)) / 2, cx = x + w / 2, cy = y + h / 2;
  return [cx - ux * half, cy - uy * half, cx + ux * half, cy + uy * half];
}

export function radii(fill) {
  const radius = fill.radius ?? 0.5;
  return Array.isArray(radius) ? [Number(radius[0]), Number(radius[1])] : [Number(radius), Number(radius)];
}

export function radialFrame(fill, [x, y, w, h]) {
  const [u, v] = fill.centre || [0.5, 0.5], [rx, ry] = radii(fill);
  return [x + Number(u) * w, y + Number(v) * h, rx * w, ry * h];
}

const hex = (rgb) => `#${rgb.map((value) => Math.max(0, Math.min(255, Math.round(value * 255))).toString(16).padStart(2, "0")).join("")}`;
const rgb = (colour) => {
  let text = String(colour || "#888888").replace(/^#/, "");
  if (text.length === 3) text = [...text].map((ch) => ch + ch).join("");
  return [0, 2, 4].map((at) => (parseInt(text.slice(at, at + 2), 16) || 0) / 255);
};

// Its colour half way along: what one colour stands in for it (a swatch, words read on it).
export function middle(fill, paint) {
  const stops = (fill.stops || []).map((stop) => [Number(stop[0]), paint(stop[1]) || "#888888"]);
  for (let n = 1; n < stops.length; n += 1) {
    const [a, ca] = stops[n - 1], [b, cb] = stops[n];
    if (a <= 0.5 && 0.5 <= b) {
      const share = b - a < 1e-12 ? 0 : (0.5 - a) / (b - a), one = rgb(ca), other = rgb(cb);
      return hex(one.map((value, k) => value + (other[k] - value) * share));
    }
  }
  return stops.length ? (stops[stops.length - 1][0] < 0.5 ? stops[stops.length - 1][1] : stops[0][1]) : "#888888";
}

const escape = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
let made = 0;

// The gradient as SVG markup for a box, and the url that fills with it.
export function markup(fill, box, paint, id = "") {
  const name = `${id || "shape"}.fill~${(made += 1).toString(36)}`;
  const stops = (fill.stops || []).map((stop) => `<stop offset="${Number(stop[0])}" stop-color="${escape(paint(stop[1]) || "#888888")}"${stop.length > 2 && Number(stop[2]) < 1 ? ` stop-opacity="${Number(stop[2])}"` : ""}/>`).join("");
  if (fill.gradient === "radial") {
    const [cx, cy, rx, ry] = radialFrame(fill, box);
    const stretch = Math.abs(rx - ry) > 1e-9 && rx > 0 ? ` gradientTransform="translate(${cx} ${cy}) scale(1 ${ry / rx}) translate(${-cx} ${-cy})"` : "";
    return { defs: `<radialGradient id="${escape(name)}" gradientUnits="userSpaceOnUse" cx="${cx}" cy="${cy}" r="${Math.max(rx, 1e-6)}"${stretch}>${stops}</radialGradient>`, url: `url(#${name})` };
  }
  const [x1, y1, x2, y2] = linearEnds(fill, box);
  return { defs: `<linearGradient id="${escape(name)}" gradientUnits="userSpaceOnUse" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stops}</linearGradient>`, url: `url(#${name})` };
}

// The inspector's fill as a gradient: Solid or Gradient, and for a gradient its kind, its
// angle (or its centre), and its two ends' colours -- or, written with more stops, those
// kept as they are. `set(fill, label)` changes it; `swatches(value, onChange)` is the
// inspector's own colour row.
export function gradientFields({ value, ui, h, swatches, set }) {
  const on = isGradient(value);
  const fields = [];
  const solid = (fill) => (isGradient(fill) ? fill.stops?.[0]?.[1] ?? "accent-fill" : fill && fill !== "none" ? fill : "accent-fill");
  fields.push(ui.field("Fill Type", ui.segmented({ value: on ? value.gradient : "solid", key: "shape.fill_type",
    options: [{ value: "solid", label: "Colour" }, { value: "linear", label: "Linear" }, { value: "radial", label: "Radial" }],
    onChange: (kind) => {
      if (kind === "solid") { set(solid(value), "Change Fill"); return; }
      const stops = on ? value.stops : [[0, solid(value)], [1, "paper"]];
      set(kind === "linear" ? { gradient: "linear", angle: on && value.gradient === "linear" ? value.angle ?? 0 : 90, stops } : { gradient: "radial", centre: [0.5, 0.5], radius: 0.5, stops }, "Change Fill");
    } })));
  if (!on) return fields;
  const ends = [value.stops[0], value.stops[value.stops.length - 1]];
  const stopsWith = (index, colour) => value.stops.map((stop, n) => (n === (index ? value.stops.length - 1 : 0) ? [stop[0], colour, ...stop.slice(2)] : stop));
  fields.push(h("div.row", {},
    ui.field("From", swatches(ends[0][1], (colour) => set({ ...value, stops: stopsWith(0, colour ?? "paper") }, "Change Gradient"), "shape.gradient_from")),
    ui.field("To", swatches(ends[1][1], (colour) => set({ ...value, stops: stopsWith(1, colour ?? "paper") }, "Change Gradient"), "shape.gradient_to"))));
  if (value.gradient === "linear") {
    fields.push(ui.field("Angle", ui.number({ value: Number(value.angle ?? 0), min: 0, max: 359, step: 15, unit: "°", key: "shape.gradient_angle",
      onChange: (angle) => set({ ...value, angle: ((Number(angle || 0) % 360) + 360) % 360 }, "Change Gradient") })));
  } else {
    const [rx] = radii(value);
    fields.push(ui.field("Radius", ui.number({ value: Math.round(rx * 100), min: 5, max: 200, step: 5, unit: "%", key: "shape.gradient_radius",
      onChange: (share) => set({ ...value, radius: Math.max(0.05, Number(share || 50) / 100) }, "Change Gradient") })));
  }
  if (value.stops.length > 2) fields.push(h("div.hint", {}, `${value.stops.length} colours: the ends are chosen here, the rest kept.`));
  return fields;
}
