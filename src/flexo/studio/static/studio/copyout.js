// Copied out: what is copied in the studio put on the clipboard as the drawing it is too, for
// other apps -- Keynote, PowerPoint, Word, Google Slides, Inkscape -- to paste as a drawing,
// beside what the studio itself pastes from (its own copy, and its words).
//
// The editor that copies says what is copied: the drawing of the page it is on (its SVG, as
// the studio drew it) and the ids in it of what is copied -- none, all of it. In the Mac app
// the app puts the drawing on the clipboard itself, in every form other apps paste (its
// `copy_drawing`): Office's own shapes, a PDF, an SVG, a picture, each drawn only when an app
// asks for it. A browser is given what a web page may put there: the words, a picture of
// it, and its SVG where the browser takes one (drawn by the studio: /api/copy). A browser
// that takes none of it keeps what the copy put there, as before.

// The copy made last in this studio: its words, and Flexo's own copy. A browser's clipboard,
// written with a picture, keeps only words of Flexo's own: a paste whose words are these is
// this copy (any of the studio's documents, in any of its tabs: kept for them too).
let last = null;
const KEY = "flexo-studio-copied";

function remember(text, clip) {
  last = text && clip ? { text, clip } : null;
  try {
    if (last) localStorage.setItem(KEY, JSON.stringify(last)); else localStorage.removeItem(KEY);
  } catch { /* a private window, or a copy too large to keep: this page's alone */ }
}

// Flexo's own copy a paste (its clipboardData, `data`) brings, when the clipboard keeps only
// its words: the copy made last in the studio, if they are its words; else null.
export function copiedHere(data) {
  const words = data?.getData?.("text/plain") || "";
  if (!words) return null;
  if (last?.text === words) return last.clip;
  try {
    const kept = JSON.parse(localStorage.getItem(KEY) || "null");
    return kept?.text === words ? kept.clip : null;
  } catch { return null; }
}

// What is copied (`clip`, Flexo's own copy, and `text`, its words), put on the clipboard as
// a drawing too: `svg` the drawing of its page, `keep` the ids in it of what is copied (none:
// the whole page), `title` its name. `wrote` is what put the copy on the clipboard, when it
// is not done yet (words written by the page itself): the drawing goes there after it. Never
// fails, never waits: a copy that cannot be drawn is the copy it was.
export function copyOut(studio, { svg, keep = [], text = "", clip = null, title = "" } = {}, wrote = null) {
  remember(text, clip);
  const app = globalThis.pywebview?.api;
  // (A copy that is no one drawing -- several slides -- is still Flexo's own on the Mac's
  // clipboard, for a window of another folder to paste: the app puts that alone there.)
  if (!svg && !(clip && app?.copy_drawing)) return;
  if (app?.copy_drawing) {
    // After the web view has written the copy (the copy event's, done as it ends): the app
    // adds the drawing to it.
    Promise.resolve(wrote).catch(() => {}).then(() => new Promise((done) => setTimeout(done, 0)))
      .then(() => app.copy_drawing({ svg, keep, text, clip: clip ? JSON.stringify(clip) : null, title }))
      .catch(() => {});
    return;
  }
  const Item = globalThis.ClipboardItem;
  if (!Item || !navigator.clipboard?.write) return;
  try {
    // (Asked for at once, as the copy is made: a browser writes only while the person acts.)
    const made = studio.api("/api/copy", { svg, keep, title });
    const parts = {
      "text/plain": new Blob([text], { type: "text/plain" }),
      "image/png": made.then((drawn) => new Blob([bytesOf(drawn.png)], { type: "image/png" })),
    };
    const supports = (type) => { try { return Boolean(Item.supports?.(type)); } catch { return false; } };
    const svgType = supports("image/svg+xml") ? "image/svg+xml" : supports("web image/svg+xml") ? "web image/svg+xml" : null;
    if (svgType) parts[svgType] = made.then((drawn) => new Blob([drawn.svg], { type: "image/svg+xml" }));
    const after = Promise.resolve(wrote).catch(() => {});
    // (A browser that writes only some of these, or none, keeps the copy as it was.)
    after.then(() => navigator.clipboard.write([new Item(parts)])).catch(() => {});
    made.catch(() => {});
  } catch { /* no clipboard to write to here */ }
}

const bytesOf = (base64) => Uint8Array.from(atob(base64), (letter) => letter.charCodeAt(0));
