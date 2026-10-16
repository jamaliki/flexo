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

// A GIF a drawing names by the studio's address for it (flexo.studio.pictures), shown still:
// the frame its picture names for paper (data-flexo-still, from 1), or `frame` -- a slide's
// thumbnail, or a picture paused. Every other picture is left as it is.
const GIF_LINK = /^\/api\/picture\?(?:[^#]*&)?path=[^&#]*\.gif(?:[&#]|$)/i;
export function stillHref(href, frame = 1) {
  const link = String(href || "");
  if (!GIF_LINK.test(link)) return link;
  return `${link.replace(/&still=\d*/g, "")}&still=${Math.max(1, Math.round(Number(frame)) || 1)}`;
}
export function stillGifs(root, frame = null) {
  for (const image of root?.querySelectorAll?.("image") || []) {
    const href = image.getAttribute("href") || "";
    const still = stillHref(href, frame ?? (Number(image.getAttribute("data-flexo-still")) || 1));
    if (still !== href) image.setAttribute("href", still);
  }
  return root;
}
