// Drawings put in the page: what each needs to stay itself beside the others.

// A drawing put in the page beside others -- another tab's slide, the slide presented --
// is given markers, gradients and clips of its own: its url(#…) must not find another
// drawing's of the same name, which, hidden, draws nothing (its arrowheads vanished).
const RESOURCES = "marker, linearGradient, radialGradient, clipPath, mask, pattern, filter, symbol";
let drawings = 0;
export function ownResources(svg) {
  if (!svg) return svg;
  const tag = `~${(drawings += 1).toString(36)}`;
  const renamed = new Map();
  for (const node of svg.querySelectorAll(RESOURCES)) if (node.id) { renamed.set(node.id, node.id + tag); node.id += tag; }
  if (!renamed.size) return svg;
  const swap = (text) => text.replace(/url\(\s*(['"]?)#([^)'"]+)\1\s*\)/g, (whole, quote, id) => (renamed.has(id) ? `url(#${renamed.get(id)})` : whole));
  for (const node of svg.querySelectorAll("*")) {
    for (const attr of [...node.attributes]) {
      if (attr.value.includes("url(")) attr.value = swap(attr.value);
      else if (attr.localName === "href" && attr.value.startsWith("#") && renamed.has(attr.value.slice(1))) attr.value = `#${renamed.get(attr.value.slice(1))}`;
    }
    if (node.localName === "style" && node.textContent.includes("url(")) node.textContent = swap(node.textContent);
  }
  return svg;
}
