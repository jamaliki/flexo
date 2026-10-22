// A drawing on the clipboard, pasted as the drawing it is. An app that copies a drawing --
// Inkscape, Affinity -- puts it there as SVG and as a picture of it besides, and a web view
// hands a page only the picture: pasted, the drawing would be a PNG, its lines and words
// pixels. The Mac app reads the SVG for the page (its `clipboard_drawing`), and words that
// are a whole SVG drawing (its markup, copied as words), and an SVG file pasted, are one too.

// The pictures a web view makes of what an app copied (named "image.png", "image.tiff").
const PICTURE = /\.(png|jpe?g|tiff?|gif|webp|heic|bmp)$/i;
// A whole SVG drawing: its <svg> after what may come before it (a declaration, comments, a
// doctype), to its end.
const SVG = /^\s*(?:<\?xml[^>]*\?>\s*)?(?:(?:<!--[\s\S]*?-->|<!DOCTYPE[^>[]*(?:\[[\s\S]*?\])?[^>]*>)\s*)*<svg[\s>][\s\S]*<\/svg>\s*$/i;

// Words that are a whole SVG drawing: the drawing, else null.
export const svgOfWords = (words) => (SVG.test(String(words ?? "")) ? String(words).trim() : null);

// The types a drawing's SVG is handed over as, besides words: the web's own, and the ones
// Inkscape writes (as a web view that hands them over names them).
const SVG_TYPES = ["image/svg+xml", "image/x-inkscape-svg", "org.inkscape.svg", "public.svg-image"];
// A file that is an SVG drawing, by its type or its name; and one that is a picture of some kind.
const svgNamed = (file) => /^image\/svg\+xml\b/i.test(file?.type || "") || /\.svg$/i.test(file?.name || "");
const pictured = (file) => svgNamed(file) || PICTURE.test(file?.name || "") || /^image\//i.test(file?.type || "");

// What a paste (its clipboardData, `data`) brings as a drawing: a promise of it as an SVG
// file (null if there is none after all) -- or null at once when it can bring none, so that
// words and files are pasted as they were, with nothing waited for. However the drawing
// comes, it is the drawing, never a picture of it (Paste as Picture is for that):
// - words that are a whole SVG drawing, or its SVG under a type of its own (image/svg+xml,
//   Inkscape's);
// - in the Mac app, whenever a picture of any kind is pasted, or no words: the drawing the
//   app finds on the clipboard, first -- so the picture of it Inkscape puts beside it (all
//   the web view hands the page: a JPEG, a PNG, and its canvas HTML) never wins;
// - a file pasted that is an SVG (one copied in the Finder; one a web view hands over): read.
// Words or a file named as the web view names a picture pasted ("image.svg"), for the folder
// it is saved in; a file pasted keeps its own name.
export function pastedDrawing(data) {
  const words = data?.getData?.("text/plain") || "";
  const drawn = svgOfWords(words);
  if (drawn) return Promise.resolve(svgFile(drawn));
  for (const type of SVG_TYPES) {
    let given = null;
    try { given = svgOfWords(data?.getData?.(type)); } catch { /* a type the page may not read */ }
    if (given) return Promise.resolve(svgFile(given));
  }
  const app = globalThis.pywebview?.api;
  const files = [...(data?.files || [])];
  const file = files.find(svgNamed);
  // (No words: an HTML of no words beside them -- Inkscape's "Inkscape Output", a canvas
  // script -- is no reason not to ask.)
  const ask = Boolean(app?.clipboard_drawing) && (files.some(pictured) || !words.trim());
  if (!ask && !file) return null;
  return (async () => {
    if (ask) {
      try {
        const svg = await app.clipboard_drawing();
        if (svg) return svgFile(svg);
      } catch { /* the app's clipboard unread: the file's, below */ }
    }
    return file ? drawingOfFile(file) : null;
  })();
}
const svgFile = (svg, name = "image.svg") => new File([svg], name, { type: "image/svg+xml" });

// A file pasted that says it is an SVG, as the drawing it holds (null if it holds none).
async function drawingOfFile(file) {
  let words = "";
  try { words = await file.text(); } catch { return null; }
  return /<svg[\s>]/i.test(words) ? svgFile(words, /\.svg$/i.test(file.name || "") ? file.name : "image.svg") : null;
}

// Flexo's own copy a paste brings from a studio window of another folder (another page,
// which the web view does not give what that one copied, only its words and the picture the
// Mac app put beside them): in the Mac app, a promise of that copy (null if the clipboard's
// drawing is not Flexo's) -- or null at once, where the paste brings no picture alone.
// Pasted, it is what it is, never that picture.
export function pastedOwn(data) {
  const app = globalThis.pywebview?.api;
  const files = [...(data?.files || [])];
  if (!app?.clipboard_own || !files.length || !files.every(pictured)) return null;
  return Promise.resolve(app.clipboard_own()).then((words) => {
    try { return words ? JSON.parse(words) : null; } catch { return null; }
  }, () => null);
}

// Flexo's own copy a paste of words alone brings from a window of another folder: several
// slides copied there are no one drawing, so the Mac app puts Flexo's own copy on the
// clipboard beside their words alone (no picture), and the web view hands this page only the
// words. In the Mac app, a promise of that copy (null if the clipboard holds none of Flexo's);
// null at once in a browser, or where the paste brings files. The paste's data is gone once
// anything is waited for: what it holds is kept first (`heldData`).
export function pastedOwnWords(data) {
  const app = globalThis.pywebview?.api;
  if (!app?.clipboard_own || [...(data?.files || [])].length) return null;
  return Promise.resolve(app.clipboard_own()).then((words) => {
    try { return words ? JSON.parse(words) : null; } catch { return null; }
  }, () => null);
}

// Flexo's own copy a paste of a picture alone brings, in a browser, from a studio of another
// folder: copied there, the picture of it was put on the clipboard with Flexo's own copy in a
// web format of its own (copyout.js), which a paste's data does not hand over -- read from the
// clipboard (the browser may ask the person, once). A promise of it (null if there is none, or
// the clipboard is not to be read); null at once in the Mac app, or where the paste brings
// anything but pictures -- or no drawing beside them, as the studio puts its copy's there
// (so a screenshot pasted never has the browser ask).
export function pastedOwnWeb(data) {
  const files = [...(data?.files || [])];
  if (globalThis.pywebview?.api || !files.length || !files.every(pictured) || !navigator.clipboard?.read) return null;
  if (![...(data?.types || [])].includes("image/svg+xml")) return null;
  return (async () => {
    try {
      for (const item of await navigator.clipboard.read()) {
        if (!item.types.includes(OWN_WEB)) continue;
        return JSON.parse(await (await item.getType(OWN_WEB)).text());
      }
    } catch { /* not to be read, or not Flexo's */ }
    return null;
  })();
}
const OWN_WEB = "web application/x-flexo-clip";

// What a paste's data (its clipboardData) holds, kept to be read after it is waited on --
// when the web view has emptied it: each of its types' words, and its files.
export function heldData(data) {
  const kept = {};
  for (const type of [...(data?.types || []), "text/plain", "text/html", ...SVG_TYPES]) {
    if (type === "Files" || type in kept) continue;
    try { kept[type] = data?.getData?.(type) || ""; } catch { kept[type] = ""; }
  }
  const files = [...(data?.files || [])];
  return { files, types: [...(data?.types || [])], getData: (type) => kept[type] ?? "" };
}

// A GIF pasted, as the GIF it is -- every frame, to play -- never the still picture a copy
// hands the page instead: a browser's Copy Image puts a GIF on the clipboard as a PNG of its
// first frame (its address in the HTML beside it), and the web view hands Safari's GIF on as
// "image.png". A promise of the GIF as a file (null if there is none after all) -- or null at
// once where the paste brings no picture alone, or brings a GIF already, named as one (copied
// in the Finder). Where it is found: the picture handed over, if its bytes are a GIF's; in
// the Mac app, the GIF on the clipboard (its `clipboard_gif`: Safari's, Preview's, a .gif
// copied in the Finder); else the picture the copied HTML shows, if the page may fetch it.
// Asked for as the paste comes, before anything is waited for: its clipboard goes after.
const GIF = /\.gif$/i;
const gifBytes = (bytes) => bytes.length > 5 && String.fromCharCode(...bytes.slice(0, 4)) === "GIF8";
export function pastedGif(data) {
  const files = [...(data?.files || [])];
  if (!files.length || !files.every(pictured) || files.some((file) => GIF.test(file.name || "") || /^image\/gif\b/i.test(file.type || ""))) return null;
  const app = globalThis.pywebview?.api;
  const html = files.length === 1 ? data?.getData?.("text/html") || "" : "";
  const shown = [...html.matchAll(/<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/gi)].map((found) => found[1].replace(/&amp;/g, "&"));
  const source = shown.length === 1 && (/^data:image\/gif[;,]/i.test(shown[0]) || /^https?:[^?#]*\.gif(?:[?#]|$)/i.test(shown[0])) ? shown[0] : null;
  const asked = files.length === 1 && app?.clipboard_gif ? Promise.resolve(app.clipboard_gif()).catch(() => null) : null;
  const named = (name, fallback = "image.gif") => (GIF.test(name || "") ? name : fallback);
  return (async () => {
    // (Handed over as itself under a PNG's name: only named again.)
    if (files.length === 1) {
      const bytes = new Uint8Array(await files[0].arrayBuffer().catch(() => new ArrayBuffer(0)));
      if (gifBytes(bytes)) return new File([bytes], named(files[0].name?.replace(/\.\w+$/, ".gif")), { type: "image/gif" });
    }
    const given = await asked;
    if (given?.data) return new File([Uint8Array.from(atob(given.data), (c) => c.charCodeAt(0))], named(given.name), { type: "image/gif" });
    if (!source) return null;
    try {
      const reply = await fetch(source, { credentials: "omit", signal: AbortSignal.timeout?.(4000) });
      const bytes = reply.ok ? new Uint8Array(await reply.arrayBuffer()) : null;
      if (!bytes || !gifBytes(bytes)) return null;
      return new File([bytes], source.startsWith("data:") ? "image.gif" : named(decodeURIComponent(new URL(source).pathname.split("/").pop() || "")), { type: "image/gif" });
    } catch { return null; }
  })();
}
