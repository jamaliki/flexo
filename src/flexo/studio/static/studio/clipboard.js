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
// - in the Mac app, whenever a picture of any kind is pasted, or nothing the page reads as
//   words: the drawing the app finds on the clipboard, first -- so the PNG of it Inkscape
//   puts beside it (which is all the web view hands the page) never wins;
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
  const ask = Boolean(app?.clipboard_drawing) && (files.some(pictured) || (!words.trim() && !data?.getData?.("text/html")));
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
