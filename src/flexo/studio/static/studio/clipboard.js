// A drawing on the clipboard, pasted as the drawing it is. An app that copies a drawing --
// Inkscape, Affinity -- puts it there as SVG and as a picture of it besides, and a web view
// hands a page only the picture: pasted, the drawing would be a PNG, its lines and words
// pixels. The Mac app reads the SVG for the page (its `clipboard_drawing`), and words that
// are a whole SVG drawing (its markup, copied as words) are one too.

// The pictures a web view makes of what an app copied (named "image.png", "image.tiff").
const PICTURE = /\.(png|jpe?g|tiff?|gif|webp|heic|bmp)$/i;
// A whole SVG drawing: its <svg> after what may come before it (a declaration, comments, a
// doctype), to its end.
const SVG = /^\s*(?:<\?xml[^>]*\?>\s*)?(?:(?:<!--[\s\S]*?-->|<!DOCTYPE[^>[]*(?:\[[\s\S]*?\])?[^>]*>)\s*)*<svg[\s>][\s\S]*<\/svg>\s*$/i;

// Words that are a whole SVG drawing: the drawing, else null.
export const svgOfWords = (words) => (SVG.test(String(words ?? "")) ? String(words).trim() : null);

// What a paste (its clipboardData, `data`) brings as a drawing: a promise of it as an SVG
// file (null if there is none after all) -- or null at once when it can bring none, so that
// words and files are pasted as they were, with nothing waited for. Words that are a drawing
// are one; and in the Mac app, with a picture alone on the clipboard as the page sees it (or
// nothing the page reads), the drawing the app finds beside it. The file is named as the web
// view names a picture pasted ("image.png"), for the folder it is saved in.
export function pastedDrawing(data) {
  const words = data?.getData?.("text/plain") || "";
  const drawn = svgOfWords(words);
  if (drawn) return Promise.resolve(svgFile(drawn));
  const app = globalThis.pywebview?.api;
  const files = [...(data?.files || [])];
  const alone = files.length ? files.every((file) => PICTURE.test(file.name)) : !words.trim() && !data?.getData?.("text/html");
  if (!app?.clipboard_drawing || !alone) return null;
  return Promise.resolve(app.clipboard_drawing()).then((svg) => (svg ? svgFile(svg) : null), () => null);
}
const svgFile = (svg) => new File([svg], "image.svg", { type: "image/svg+xml" });
