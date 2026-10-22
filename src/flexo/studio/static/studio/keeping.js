// What a cache of drawings parsed into the page keeps: every one in use (on screen), and of
// the rest the newest, up to a count and a total size. A slide edited key by key is drawn
// anew at each key, and a large slide's every drawing kept (its pictures, its molecules, a
// picture's whole data in it) would hold hundreds of megabytes for nothing.

// The keys to let go of `entries` ([key, value] pairs, oldest first): those not `inUse`, past
// the newest `most` of them or past `budget` of `size` in all.
export function overflow(entries, { inUse = () => false, size = () => 0, most = 120, budget = 24e6 } = {}) {
  const gone = [];
  let count = 0, total = 0;
  for (let n = entries.length - 1; n >= 0; n -= 1) {
    const [key, value] = entries[n];
    if (inUse(value)) continue;
    count += 1;
    total += Number(size(value)) || 0;
    if (count > most || total > budget) gone.push(key);
  }
  return gone;
}
