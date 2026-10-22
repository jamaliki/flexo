// An answer carrying a drawing, framed (flexo.studio.framing): its JSON on a line of its own,
// each page's SVG after it as it is -- not escaped into JSON and read back out of it, at every
// key typed on a slide drawing a protein. Asked for by what a page accepts (`ACCEPT`); any
// other answer is JSON.

export const ACCEPT = "application/x-flexo-framed";
const words = new TextDecoder();

// The answer as JSON would have given it: each SVG put back where `framed` says it was.
export async function answered(response) {
  if (!(response.headers.get("Content-Type") || "").startsWith(ACCEPT)) return response.json();
  const bytes = new Uint8Array(await response.arrayBuffer());
  const end = bytes.indexOf(10);
  const answer = JSON.parse(words.decode(bytes.subarray(0, end)));
  for (const [path, start, length] of answer.framed || []) {
    let holder = answer;
    for (const key of path.slice(0, -1)) holder = holder[key];
    holder[path[path.length - 1]] = words.decode(bytes.subarray(end + 1 + start, end + 1 + start + length));
  }
  delete answer.framed;
  return answer;
}
